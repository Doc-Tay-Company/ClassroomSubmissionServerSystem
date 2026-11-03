"""Isolated Java and Python STDIO grading runner."""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from decimal import Decimal, InvalidOperation, localcontext
import math
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import sys
import time
from typing import Mapping, Sequence

from .grading import grade_stdio, sum_configured_points
from .java_runner import (
    DEFAULT_JAVA_COMPILE_LIMITS,
    ProcessStatus,
    RunWorkspace,
    _is_java_identifier,
    compile_java_in_workspace,
    java_heap_limit_mb,
    minimal_environment,
    run_process,
)
from .windows_job import DEFAULT_JOB_LIMITS, JobLimits


DEFAULT_TEST_TIMEOUT_SECONDS = 2.0
DEFAULT_COMPILE_TIMEOUT_SECONDS = 20.0
DEFAULT_MAX_OUTPUT_BYTES = 64 * 1024
MAX_SOURCE_BYTES = 1024 * 1024
MAX_TEST_DATA_BYTES = 1024 * 1024
MAX_TOTAL_TEST_DATA_BYTES = 16 * 1024 * 1024
_MAX_FLOAT_TOKEN_DIGITS = 1000
_MAX_FLOAT_TOKEN_EXPONENT = 1000
_FLOAT_COMPARISON_PRECISION = 6000
_FLOAT_TOKEN_PATTERN = re.compile(
    r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z"
)
_NUMERIC_PREFIX_PATTERN = re.compile(r"^[+-]?(?:[0-9]|\.[0-9])")
_VALID_COMPARE_MODES = frozenset({"exact", "normalized", "tokens", "float_tolerance"})
_INFRASTRUCTURE_CATEGORIES = frozenset(
    {"INVALID_REQUEST", "JDK_NOT_FOUND", "JUDGE_INFRA_ERROR", "PROTOCOL_ERROR"}
)


@dataclass(frozen=True)
class _TestCase:
    test_id: str
    stdin: bytes
    expected_stdout: str
    is_visible: bool
    points: Decimal
    compare_mode: str
    abs_tolerance: Decimal | None
    rel_tolerance: Decimal | None


@dataclass(frozen=True)
class OutputComparison:
    """One deterministic output comparison; it does not calculate score."""

    passed: bool
    expected: str
    actual: str
    reason: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class CompilationResult:
    """Compiler result shared by Java javac and Python syntax compilation."""

    status: str
    success: bool
    verdict: str | None
    exit_code: int | None
    duration_ms: int
    stdout: str
    stderr: str
    error: str | None = None
    error_category: str | None = None
    expected_class_file: str | None = None
    expected_class_file_exists: bool | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class StdioTestResult:
    id: str
    verdict: str
    passed: bool
    points: int | float
    points_earned: int | float
    is_visible: bool
    expected_stdout: str
    actual_stdout: str
    stderr: str
    duration_ms: int
    error: str | None = None
    error_category: str | None = None
    exit_code: int | None = None
    stdout_truncated: bool = False
    stderr_truncated: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class StdioResult:
    verdict: str
    score: int | float
    total_points: int | float
    tests: list[StdioTestResult]
    run_id: str | None
    duration_ms: int
    compile_result: CompilationResult | None = None
    error: str | None = None
    error_category: str | None = None

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "score": self.score,
            "total_points": self.total_points,
            "tests": [test.to_dict() for test in self.tests],
            "run_id": self.run_id,
            "duration_ms": self.duration_ms,
            "compile_result": self.compile_result.to_dict() if self.compile_result else None,
            "error": self.error,
            "error_category": self.error_category,
        }


def _number(value, field: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ValueError(f"{field} must be a finite non-negative number")
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f"{field} must be a finite non-negative number") from exc
    if not number.is_finite() or number < 0:
        raise ValueError(f"{field} must be a finite non-negative number")
    if len(number.as_tuple().digits) > 1000 or abs(number.as_tuple().exponent) > 1000:
        raise ValueError(f"{field} exceeds the supported numeric range")
    try:
        if not math.isfinite(float(number)):
            raise ValueError(f"{field} exceeds the supported numeric range")
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"{field} exceeds the supported numeric range") from exc
    return number


def _plain_number(value: Decimal) -> int | float:
    if value == value.to_integral_value():
        return int(value)
    return float(value)


def _positive_seconds(value, field: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
    ):
        raise ValueError(f"{field} must be a positive finite number")
    return float(value)


def _safe_single_file(value: str, suffix: str, field: str) -> str:
    if not isinstance(value, str) or not value or "\0" in value:
        raise ValueError(f"{field} must be a safe {suffix} filename")
    posix = PurePosixPath(value.replace("\\", "/"))
    windows = PureWindowsPath(value)
    if (
        posix.is_absolute()
        or windows.is_absolute()
        or windows.drive
        or len(posix.parts) != 1
        or posix.parts[0] in {".", ".."}
        or posix.suffix.casefold() != suffix
    ):
        raise ValueError(f"{field} must be a safe {suffix} filename")
    return value


def _java_target(
    target_class: str | None,
    target_package: str | None,
    target_file: str | None,
) -> tuple[str, Path]:
    if not isinstance(target_class, str) or not target_class:
        raise ValueError("target_class is required for Java STDIO")
    if target_package is not None and not isinstance(target_package, str):
        raise ValueError("target_package must be a string")

    if "." in target_class:
        declared_package, _, simple_name = target_class.rpartition(".")
        if target_package and target_package != declared_package:
            raise ValueError("target_class and target_package specify different packages")
        package = target_package or declared_package
    else:
        simple_name = target_class
        package = target_package or ""

    if not _is_java_identifier(simple_name):
        raise ValueError("target_class must be a valid Java class name")
    if package and not all(_is_java_identifier(part) for part in package.split(".")):
        raise ValueError("target_package must be a valid Java package name")
    filename = f"{simple_name}.java"
    if target_file is not None:
        supplied_file = _safe_single_file(target_file, ".java", "target_file")
        if supplied_file != filename:
            raise ValueError("target_file must match the target class name")

    source_path = Path(*package.split("."), filename) if package else Path(filename)
    binary_name = f"{package}.{simple_name}" if package else simple_name
    return binary_name, source_path


def _validate_tests(tests: Sequence[Mapping]) -> tuple[list[_TestCase], Decimal]:
    if isinstance(tests, (str, bytes, bytearray)) or not isinstance(tests, Sequence):
        raise ValueError("tests must be an array of test objects")
    if not tests:
        raise ValueError("at least one test is required")

    normalized: list[_TestCase] = []
    identifiers: set[str] = set()
    total_data_bytes = 0
    for index, test in enumerate(tests):
        if not isinstance(test, Mapping):
            raise ValueError(f"test at index {index} must be an object")
        test_id = test.get("id")
        if not isinstance(test_id, str) or not test_id.strip() or test_id in identifiers:
            raise ValueError(f"test at index {index} must have a unique non-empty id")
        identifiers.add(test_id)

        stdin = test.get("stdin")
        expected = test.get("expected_stdout")
        if not isinstance(stdin, str) or not isinstance(expected, str):
            raise ValueError(f"test '{test_id}' stdin and expected_stdout must be strings")
        try:
            input_bytes = stdin.encode("utf-8")
            expected_bytes = expected.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise ValueError(f"test '{test_id}' data must be valid UTF-8") from exc
        if len(input_bytes) > MAX_TEST_DATA_BYTES or len(expected_bytes) > MAX_TEST_DATA_BYTES:
            raise ValueError(f"test '{test_id}' data exceeds the per-field size limit")
        total_data_bytes += len(input_bytes) + len(expected_bytes)
        if total_data_bytes > MAX_TOTAL_TEST_DATA_BYTES:
            raise ValueError("combined test input and expected output exceeds the size limit")

        is_visible = test.get("is_visible")
        if not isinstance(is_visible, bool):
            raise ValueError(f"test '{test_id}' is_visible must be a boolean")
        points = _number(test.get("points"), f"test '{test_id}' points")
        compare_mode = test.get("compare_mode", "normalized")
        if not isinstance(compare_mode, str) or compare_mode not in _VALID_COMPARE_MODES:
            raise ValueError(f"test '{test_id}' has an unsupported compare_mode")
        unset = object()
        abs_value = test.get("abs_tolerance", unset)
        rel_value = test.get("rel_tolerance", unset)
        legacy_tolerance = test.get("tolerance", unset)
        if legacy_tolerance is not unset:
            if abs_value is not unset:
                raise ValueError(
                    f"test '{test_id}' cannot combine tolerance with abs_tolerance"
                )
            abs_value = legacy_tolerance
        abs_tolerance = (
            None
            if abs_value is unset
            else _number(abs_value, f"test '{test_id}' abs_tolerance")
        )
        rel_tolerance = (
            None
            if rel_value is unset
            else _number(rel_value, f"test '{test_id}' rel_tolerance")
        )
        if compare_mode == "float_tolerance" and abs_tolerance is None and rel_tolerance is None:
            raise ValueError(
                f"test '{test_id}' float_tolerance requires abs_tolerance and/or rel_tolerance"
            )
        normalized.append(
            _TestCase(
                test_id=test_id,
                stdin=input_bytes,
                expected_stdout=expected,
                is_visible=is_visible,
                points=points,
                compare_mode=compare_mode,
                abs_tolerance=abs_tolerance,
                rel_tolerance=rel_tolerance,
            )
        )
    total_points = sum_configured_points(
        [{"id": test.test_id, "points": test.points} for test in normalized],
        item_name="test",
    )
    return normalized, total_points


def _normalize_crlf(value: str) -> str:
    return value.replace("\r\n", "\n")


def _normalized_lines(value: str) -> list[str]:
    """Keep leading/internal whitespace, trim line tails, then drop final blank lines."""
    lines = [line.rstrip() for line in _normalize_crlf(value).split("\n")]
    while lines and not lines[-1]:
        lines.pop()
    return lines


def _float_token(token: str) -> tuple[str, Decimal | None]:
    """Classify finite decimal tokens, literal labels, and malformed numeric tokens."""
    try:
        value = Decimal(token)
    except InvalidOperation:
        if _NUMERIC_PREFIX_PATTERN.match(token):
            return "malformed", None
        return "text", None

    if (
        not value.is_finite()
        or not _FLOAT_TOKEN_PATTERN.fullmatch(token)
        or len(value.as_tuple().digits) > _MAX_FLOAT_TOKEN_DIGITS
        or abs(value.as_tuple().exponent) > _MAX_FLOAT_TOKEN_EXPONENT
    ):
        return "malformed", None
    return "number", value


def compare_outputs(
    expected: str,
    actual: str,
    compare_mode: str,
    *,
    abs_tolerance=None,
    rel_tolerance=None,
) -> OutputComparison:
    """Compare output under the selected mode and return details without scoring.

    `exact` converts CRLF to LF only. `normalized` also removes trailing whitespace
    from each line and all final blank lines; leading whitespace, internal spaces,
    and internal blank lines remain significant. Float tolerances must be supplied
    explicitly; the allowed error is the larger of absolute tolerance and relative
    tolerance times the larger absolute operand. Identical literal label tokens are
    allowed, but malformed numeric-looking and non-finite tokens fail.
    """
    if not isinstance(expected, str) or not isinstance(actual, str):
        return OutputComparison(False, str(expected), str(actual), "Expected and actual output must be strings.")

    def failed(reason: str) -> OutputComparison:
        return OutputComparison(False, expected, actual, reason)

    if compare_mode == "exact":
        passed = _normalize_crlf(expected) == _normalize_crlf(actual)
        return OutputComparison(
            passed,
            expected,
            actual,
            None if passed else "Outputs differ after CRLF-to-LF conversion.",
        )
    if compare_mode == "normalized":
        passed = _normalized_lines(expected) == _normalized_lines(actual)
        return OutputComparison(
            passed,
            expected,
            actual,
            None
            if passed
            else "Outputs differ after trimming line endings and final blank lines.",
        )
    if compare_mode == "tokens":
        passed = _normalize_crlf(expected).split() == _normalize_crlf(actual).split()
        return OutputComparison(
            passed,
            expected,
            actual,
            None if passed else "Whitespace-separated token sequences differ.",
        )
    if compare_mode != "float_tolerance":
        return failed(f"Unsupported compare_mode: {compare_mode!r}.")

    try:
        abs_error = None if abs_tolerance is None else _number(abs_tolerance, "abs_tolerance")
        rel_error = None if rel_tolerance is None else _number(rel_tolerance, "rel_tolerance")
    except (TypeError, ValueError) as exc:
        return failed(str(exc))
    if abs_error is None and rel_error is None:
        return failed("float_tolerance requires abs_tolerance and/or rel_tolerance.")

    expected_tokens = _normalize_crlf(expected).split()
    actual_tokens = _normalize_crlf(actual).split()
    if len(expected_tokens) != len(actual_tokens):
        return failed("Whitespace-separated token counts differ.")

    for index, (expected_token, actual_token) in enumerate(
        zip(expected_tokens, actual_tokens), start=1
    ):
        expected_kind, expected_number = _float_token(expected_token)
        actual_kind, actual_number = _float_token(actual_token)
        if expected_kind == "malformed" or actual_kind == "malformed":
            return failed(f"Token {index} is malformed or outside the supported numeric range.")
        if expected_kind == actual_kind == "text":
            if expected_token != actual_token:
                return failed(f"Literal token {index} differs.")
            continue
        if expected_kind != "number" or actual_kind != "number":
            return failed(f"Token {index} mixes numeric and non-numeric values.")

        with localcontext() as context:
            context.prec = _FLOAT_COMPARISON_PRECISION
            difference = abs(expected_number - actual_number)
            allowed_error = abs_error or Decimal(0)
            if rel_error is not None:
                relative_error = rel_error * max(abs(expected_number), abs(actual_number))
                allowed_error = max(allowed_error, relative_error)
        if difference > allowed_error:
            return failed(f"Numeric token {index} exceeds the configured tolerance.")

    return OutputComparison(True, expected, actual)


def outputs_match(
    expected: str,
    actual: str,
    compare_mode: str,
    tolerance=None,
    *,
    abs_tolerance=None,
    rel_tolerance=None,
) -> bool:
    """Compatibility boolean wrapper; `tolerance` is an explicit absolute value."""
    if tolerance is not None:
        if abs_tolerance is not None:
            return False
        abs_tolerance = tolerance
    return compare_outputs(
        expected,
        actual,
        compare_mode,
        abs_tolerance=abs_tolerance,
        rel_tolerance=rel_tolerance,
    ).passed


def _failure_for_process(result, max_output_bytes: int) -> tuple[str, str | None, str | None]:
    if result.status == ProcessStatus.TIMEOUT:
        return "TLE", None, result.error or "Process exceeded its time limit."
    if result.status == ProcessStatus.MEMORY_LIMIT:
        return "MLE", None, result.error or "Process exceeded its memory limit."
    if result.status == ProcessStatus.OUTPUT_LIMIT:
        return "OLE", None, result.error or f"Process output exceeded {max_output_bytes} bytes."
    if result.status == ProcessStatus.START_ERROR:
        category = result.error_category
        if category not in _INFRASTRUCTURE_CATEGORIES:
            category = "JUDGE_INFRA_ERROR"
        return category, category, result.error or "Could not start or clean up the process."
    if result.exit_code is None:
        return "JUDGE_INFRA_ERROR", "JUDGE_INFRA_ERROR", "Process exit code was unavailable."
    if result.exit_code != 0:
        detail = result.stderr.strip() or f"Process exited with code {result.exit_code}."
        return "RE", None, detail
    return "", None, None


def _test_result(
    test: _TestCase,
    *,
    verdict: str,
    actual_stdout: str = "",
    stderr: str = "",
    duration_ms: int = 0,
    error: str | None = None,
    error_category: str | None = None,
    exit_code: int | None = None,
    stdout_truncated: bool = False,
    stderr_truncated: bool = False,
) -> StdioTestResult:
    passed = verdict == "AC"
    return StdioTestResult(
        id=test.test_id,
        verdict=verdict,
        passed=passed,
        points=_plain_number(test.points),
        points_earned=0,
        is_visible=test.is_visible,
        expected_stdout=test.expected_stdout,
        actual_stdout=actual_stdout,
        stderr=stderr,
        duration_ms=duration_ms,
        error=error,
        error_category=error_category,
        exit_code=exit_code,
        stdout_truncated=stdout_truncated,
        stderr_truncated=stderr_truncated,
    )


def _compilation_summary(result) -> CompilationResult:
    return CompilationResult(
        status=result.status.value,
        success=result.success,
        verdict=result.verdict,
        exit_code=result.exit_code,
        duration_ms=result.duration_ms,
        stdout=result.stdout,
        stderr=result.stderr,
        error=result.error,
        error_category=result.error_category,
        expected_class_file=result.expected_class_file,
        expected_class_file_exists=result.expected_class_file_exists,
    )


def _compile_failure_verdict(status: ProcessStatus, exit_code: int | None, error_category: str | None):
    if status == ProcessStatus.EXITED:
        if exit_code == 0:
            return None, None
        if exit_code is not None:
            return "CE", None
        return "JUDGE_INFRA_ERROR", "JUDGE_INFRA_ERROR"
    if status == ProcessStatus.TIMEOUT:
        return "TLE", None
    if status == ProcessStatus.MEMORY_LIMIT:
        return "MLE", None
    if status == ProcessStatus.OUTPUT_LIMIT:
        return "OLE", None
    category = error_category if error_category in _INFRASTRUCTURE_CATEGORIES else "JUDGE_INFRA_ERROR"
    return category, category


def _overall_verdict(tests: Sequence[StdioTestResult]) -> str:
    for test in tests:
        if test.error_category in _INFRASTRUCTURE_CATEGORIES:
            return test.error_category
    for verdict in ("TLE", "MLE", "OLE", "RE", "WA"):
        if any(test.verdict == verdict for test in tests):
            return verdict
    return "AC"


def _invalid_result(error: str, started: float) -> StdioResult:
    return StdioResult(
        verdict="INVALID_REQUEST",
        score=0,
        total_points=0,
        tests=[],
        run_id=None,
        duration_ms=max(0, int((time.monotonic() - started) * 1000)),
        error=error,
        error_category="INVALID_REQUEST",
    )


def _python_executable(configured: str | Path | None) -> str:
    candidate = Path(sys.executable if configured is None else configured).expanduser()
    if not candidate.is_absolute():
        raise OSError("Python executable must be an absolute path; py.exe is not supported.")
    resolved = candidate.resolve(strict=True)
    if not resolved.is_file():
        raise OSError("Configured Python executable is not a file.")
    return str(resolved)


def _java_runtime_environment(source: Mapping[str, str], jdk) -> dict[str, str]:
    result = minimal_environment(source)
    original_path = result.get("PATH", "")
    jdk_bin = str(Path(jdk.java).parent)
    result["PATH"] = jdk_bin + (os.pathsep + original_path if original_path else "")
    result["JAVA_HOME"] = jdk.home
    return result


def run_stdio(
    source_code: str,
    language: str,
    tests: Sequence[Mapping],
    *,
    target_class: str | None = None,
    target_package: str | None = None,
    target_file: str | None = None,
    timeout_seconds: float = DEFAULT_TEST_TIMEOUT_SECONDS,
    compile_timeout_seconds: float = DEFAULT_COMPILE_TIMEOUT_SECONDS,
    max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
    visible_only: bool = False,
    python_executable: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    workspace_parent: str | Path | None = None,
    job_limits: JobLimits | None = None,
) -> StdioResult:
    """Compile once when required, then run each STDIO test in its own Job Object.

    `float_tolerance` requires explicit `abs_tolerance` and/or `rel_tolerance`
    values on the test. The legacy `tolerance` field remains an explicit absolute
    tolerance alias.
    """
    started = time.monotonic()
    try:
        if not isinstance(source_code, str):
            raise ValueError("source_code must be a string")
        source_bytes = source_code.encode("utf-8")
        if len(source_bytes) > MAX_SOURCE_BYTES:
            raise ValueError("source_code exceeds the size limit")
        if not isinstance(language, str) or language.casefold() not in {"java", "python"}:
            raise ValueError("language must be 'java' or 'python'")
        normalized_language = language.casefold()
        cases, total_points = _validate_tests(tests)
        timeout_seconds = _positive_seconds(timeout_seconds, "timeout_seconds")
        compile_timeout_seconds = _positive_seconds(
            compile_timeout_seconds, "compile_timeout_seconds"
        )
        if (
            not isinstance(max_output_bytes, int)
            or isinstance(max_output_bytes, bool)
            or max_output_bytes <= 0
        ):
            raise ValueError("max_output_bytes must be a positive integer")
        if not isinstance(visible_only, bool):
            raise ValueError("visible_only must be a boolean")
        if env is not None and (
            not isinstance(env, Mapping)
            or any(
                not isinstance(key, str)
                or not isinstance(value, str)
                or "\0" in key
                or "\0" in value
                or "=" in key
                for key, value in env.items()
            )
        ):
            raise ValueError("env must map valid environment variable names to strings")
        environment = dict(os.environ if env is None else env)
        selected_cases = [test for test in cases if test.is_visible or not visible_only]
        if normalized_language == "java":
            binary_class, java_source_path = _java_target(
                target_class, target_package, target_file
            )
        else:
            if target_class is not None or target_package not in (None, ""):
                raise ValueError("target_class and target_package apply only to Java")
            target_file = _safe_single_file(
                "solution.py" if target_file is None else target_file,
                ".py",
                "target_file",
            )
            java_source_path = None
            binary_class = None
        if job_limits is not None and not isinstance(job_limits, JobLimits):
            raise ValueError("job_limits must be a JobLimits value")
        if normalized_language == "java":
            java_heap_limit_mb(job_limits or DEFAULT_JOB_LIMITS)
    except (ValueError, UnicodeEncodeError) as exc:
        return _invalid_result(str(exc), started)

    selected_total = sum_configured_points(
        [{"id": test.test_id, "points": test.points} for test in selected_cases],
        item_name="test",
    )
    process_limits = job_limits or DEFAULT_JOB_LIMITS
    compiler_limits = job_limits or DEFAULT_JAVA_COMPILE_LIMITS
    workspace = None
    compile_summary = None
    test_results: list[StdioTestResult] = []
    result: StdioResult | None = None

    try:
        workspace = RunWorkspace.create(workspace_parent)
        if normalized_language == "java":
            compile_result = compile_java_in_workspace(
                source_code,
                workspace,
                source_path=java_source_path,
                timeout_seconds=compile_timeout_seconds,
                max_output_bytes=max_output_bytes,
                env=environment,
                job_limits=compiler_limits,
            )
            compile_summary = _compilation_summary(compile_result)
            compile_verdict, compile_category = _compile_failure_verdict(
                compile_result.status,
                compile_result.exit_code,
                compile_result.error_category,
            )
            java_config = compile_result.jdk
            if compile_verdict is None and java_config is None:
                compile_verdict = "JUDGE_INFRA_ERROR"
                compile_category = "JUDGE_INFRA_ERROR"
                compile_result = CompilationResult(
                    status=compile_result.status.value,
                    success=False,
                    verdict=None,
                    exit_code=compile_result.exit_code,
                    duration_ms=compile_result.duration_ms,
                    stdout=compile_result.stdout,
                    stderr=compile_result.stderr,
                    error="JDK configuration was unavailable after compilation.",
                    error_category=compile_category,
                    expected_class_file=compile_result.expected_class_file,
                    expected_class_file_exists=compile_result.expected_class_file_exists,
                )
                compile_summary = compile_result
        else:
            python_path = _python_executable(python_executable)
            source_file = workspace.src / target_file
            with source_file.open("w", encoding="utf-8", newline="") as stream:
                stream.write(source_code)
            compile_process = run_process(
                [python_path, "-I", "-B", "-m", "py_compile", str(source_file)],
                cwd=workspace.root,
                timeout_seconds=compile_timeout_seconds,
                max_output_bytes=max_output_bytes,
                env=minimal_environment(environment),
                job_limits=process_limits,
            )
            compile_verdict, compile_category = _compile_failure_verdict(
                compile_process.status,
                compile_process.exit_code,
                compile_process.error_category,
            )
            compile_error = compile_process.error
            if compile_verdict == "CE":
                compile_error = compile_process.stderr.strip() or "Python syntax compilation failed."
            compile_summary = CompilationResult(
                status=compile_process.status.value,
                success=compile_verdict is None,
                verdict=compile_verdict,
                exit_code=compile_process.exit_code,
                duration_ms=compile_process.duration_ms,
                stdout=compile_process.stdout,
                stderr=compile_process.stderr,
                error=compile_error,
                error_category=compile_category or compile_process.error_category,
            )
            java_config = None

        if compile_verdict is not None:
            compile_error = (
                compile_summary.stderr.strip()
                or compile_summary.stdout.strip()
                or compile_summary.error
                or compile_verdict
            )
            test_results = [
                _test_result(
                    test,
                    verdict=compile_verdict,
                    error=compile_error,
                    error_category=compile_category,
                    stderr=compile_summary.stderr,
                )
                for test in selected_cases
            ]
            result = StdioResult(
                verdict=compile_verdict,
                score=0,
                total_points=_plain_number(selected_total),
                tests=test_results,
                run_id=workspace.run_id,
                duration_ms=max(0, int((time.monotonic() - started) * 1000)),
                compile_result=compile_summary,
                error=compile_error,
                error_category=compile_category,
            )
        else:
            if normalized_language == "java":
                heap_mb = java_heap_limit_mb(process_limits)
                command_prefix = [
                    java_config.java,
                    f"-Xmx{heap_mb}m",
                    "-Dfile.encoding=UTF-8",
                    "-cp",
                    str(workspace.out),
                    binary_class,
                ]
            else:
                command_prefix = [
                    python_path,
                    "-I",
                    "-B",
                    "-X",
                    "utf8",
                    str(source_file),
                ]

            for index, test in enumerate(selected_cases):
                process_environment = (
                    _java_runtime_environment(environment, java_config)
                    if normalized_language == "java"
                    else minimal_environment(environment)
                )
                process_result = run_process(
                    command_prefix,
                    cwd=workspace.root,
                    timeout_seconds=timeout_seconds,
                    max_output_bytes=max_output_bytes,
                    env=process_environment,
                    job_limits=process_limits,
                    input_data=test.stdin,
                )
                process_verdict, process_category, process_error = _failure_for_process(
                    process_result, max_output_bytes
                )
                if not process_verdict:
                    comparison = compare_outputs(
                        test.expected_stdout,
                        process_result.stdout,
                        test.compare_mode,
                        abs_tolerance=test.abs_tolerance,
                        rel_tolerance=test.rel_tolerance,
                    )
                    process_verdict = "AC" if comparison.passed else "WA"
                    if not comparison.passed:
                        process_error = comparison.reason
                test_results.append(
                    _test_result(
                        test,
                        verdict=process_verdict,
                        actual_stdout=process_result.stdout,
                        stderr=process_result.stderr,
                        duration_ms=process_result.duration_ms,
                        error=process_error,
                        error_category=process_category,
                        exit_code=process_result.exit_code,
                        stdout_truncated=process_result.stdout_truncated,
                        stderr_truncated=process_result.stderr_truncated,
                    )
                )
                if process_category is not None:
                    for unrun in selected_cases[index + 1 :]:
                        test_results.append(
                            _test_result(
                                unrun,
                                verdict=process_category,
                                error="Not run because the execution infrastructure failed.",
                                error_category=process_category,
                            )
                        )
                    break

            verdict = _overall_verdict(test_results)
            graded = grade_stdio(
                [{"id": test.test_id, "points": test.points} for test in selected_cases],
                [test.to_dict() for test in test_results],
                selected_total,
                force_zero=verdict in _INFRASTRUCTURE_CATEGORIES,
            )
            earned_by_id = {test["id"]: test["points_earned"] for test in graded.results}
            test_results = [
                replace(test, points_earned=earned_by_id[test.id]) for test in test_results
            ]
            result = StdioResult(
                verdict=verdict,
                score=graded.score,
                total_points=_plain_number(selected_total),
                tests=test_results,
                run_id=workspace.run_id,
                duration_ms=max(0, int((time.monotonic() - started) * 1000)),
                compile_result=compile_summary,
                error=next((test.error for test in test_results if test.error), None),
                error_category=(verdict if verdict in _INFRASTRUCTURE_CATEGORIES else None),
            )
    except Exception as exc:
        category = getattr(exc, "category", "JUDGE_INFRA_ERROR")
        if category not in _INFRASTRUCTURE_CATEGORIES:
            category = "JUDGE_INFRA_ERROR"
        error = f"{type(exc).__name__}: {exc}"
        for test in selected_cases[len(test_results) :]:
            test_results.append(
                _test_result(
                    test,
                    verdict=category,
                    error=error,
                    error_category=category,
                )
            )
        result = StdioResult(
            verdict=category,
            score=0,
            total_points=_plain_number(selected_total),
            tests=test_results,
            run_id=workspace.run_id if workspace else None,
            duration_ms=max(0, int((time.monotonic() - started) * 1000)),
            compile_result=compile_summary,
            error=error,
            error_category=category,
        )
    finally:
        if workspace is not None:
            try:
                workspace.cleanup()
            except Exception as exc:
                category = "JUDGE_INFRA_ERROR"
                error = f"Workspace cleanup failed: {type(exc).__name__}: {exc}"
                prior_results = {test.id: test for test in test_results}
                test_results = []
                for test in selected_cases:
                    prior = prior_results.get(test.test_id)
                    test_results.append(
                        _test_result(
                            test,
                            verdict=category,
                            actual_stdout=prior.actual_stdout if prior else "",
                            stderr=prior.stderr if prior else "",
                            duration_ms=prior.duration_ms if prior else 0,
                            error=error,
                            error_category=category,
                            exit_code=prior.exit_code if prior else None,
                            stdout_truncated=prior.stdout_truncated if prior else False,
                            stderr_truncated=prior.stderr_truncated if prior else False,
                        )
                    )
                result = StdioResult(
                    verdict=category,
                    score=0,
                    total_points=_plain_number(selected_total),
                    tests=test_results,
                    run_id=workspace.run_id,
                    duration_ms=max(0, int((time.monotonic() - started) * 1000)),
                    compile_result=compile_summary,
                    error=error,
                    error_category=category,
                )

    if result is None:
        return StdioResult(
            verdict="JUDGE_INFRA_ERROR",
            score=0,
            total_points=_plain_number(selected_total),
            tests=test_results,
            run_id=workspace.run_id if workspace else None,
            duration_ms=max(0, int((time.monotonic() - started) * 1000)),
            compile_result=compile_summary,
            error="Execution ended without a result.",
            error_category="JUDGE_INFRA_ERROR",
        )
    return result
