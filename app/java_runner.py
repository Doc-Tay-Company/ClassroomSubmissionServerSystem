"""Workspace and bounded subprocess primitives for the Java execution path."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from decimal import Decimal
from enum import Enum
import hashlib
import json
import logging
import math
import os
from pathlib import Path
from pathlib import PurePosixPath, PureWindowsPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
from typing import Mapping, Sequence
import uuid

from .grading import (
    GradingError,
    grade_reflection,
    parse_nonnegative_decimal,
    plain_number,
)
from .windows_job import (
    DEFAULT_JOB_LIMITS,
    MIN_JAVA_JOB_MEMORY_MB,
    JobLimits,
    create_job_process,
)

logger = logging.getLogger(__name__)


class ProcessStatus(str, Enum):
    EXITED = "EXITED"
    TIMEOUT = "TIMEOUT"
    MEMORY_LIMIT = "MEMORY_LIMIT"
    OUTPUT_LIMIT = "OUTPUT_LIMIT"
    START_ERROR = "START_ERROR"


@dataclass(frozen=True)
class ProcessResult:
    status: ProcessStatus
    exit_code: int | None
    duration_ms: int
    stdout: str
    stderr: str
    stdout_bytes: int
    stderr_bytes: int
    stdout_truncated: bool
    stderr_truncated: bool
    error: str | None = None
    error_category: str | None = None
    protocol_output: str | None = field(default=None, repr=False)
    protocol_output_bytes: int = field(default=0, repr=False)
    protocol_truncated: bool = field(default=False, repr=False)

    def to_dict(self) -> dict:
        result = asdict(self)
        # Protocol bytes are internal judge data and must not enter API payloads.
        result.pop("protocol_output", None)
        result.pop("protocol_output_bytes", None)
        result.pop("protocol_truncated", None)
        result["status"] = self.status.value
        return result


def classify_judge_process_result(result: ProcessResult) -> str:
    """Map the Judge process/protocol outcome to the frozen verdict categories."""
    infrastructure_categories = {
        "INVALID_REQUEST", "JDK_NOT_FOUND", "JUDGE_INFRA_ERROR", "PROTOCOL_ERROR"
    }
    process_verdicts = {
        ProcessStatus.TIMEOUT: "TLE",
        ProcessStatus.MEMORY_LIMIT: "MLE",
        ProcessStatus.OUTPUT_LIMIT: "OLE",
    }
    if result.status in process_verdicts:
        return process_verdicts[result.status]
    if result.status == ProcessStatus.START_ERROR:
        return result.error_category if result.error_category in infrastructure_categories else "JUDGE_INFRA_ERROR"
    if result.status != ProcessStatus.EXITED or result.exit_code is None:
        return "PROTOCOL_ERROR"

    if not result.stdout.strip():
        return "PROTOCOL_ERROR"
    try:
        payload = json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError):
        return "PROTOCOL_ERROR"
    if not isinstance(payload, dict):
        return "PROTOCOL_ERROR"

    if not {"score", "total_points", "checks"}.issubset(payload):
        return "PROTOCOL_ERROR"
    for key in ("score", "total_points"):
        value = payload[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return "PROTOCOL_ERROR"
        if isinstance(value, float) and not math.isfinite(value):
            return "PROTOCOL_ERROR"

    checks = payload["checks"]
    if not isinstance(checks, list):
        return "PROTOCOL_ERROR"
    required_check_fields = {"id", "passed", "points_earned", "expected", "actual", "error"}
    for check in checks:
        if not isinstance(check, dict) or not required_check_fields.issubset(check):
            return "PROTOCOL_ERROR"
        if not isinstance(check["id"], str) or not isinstance(check["passed"], bool):
            return "PROTOCOL_ERROR"
        points = check["points_earned"]
        if isinstance(points, bool) or not isinstance(points, (int, float)):
            return "PROTOCOL_ERROR"
        if isinstance(points, float) and not math.isfinite(points):
            return "PROTOCOL_ERROR"
        if check["error"] is not None and not isinstance(check["error"], str):
            return "PROTOCOL_ERROR"

    error_category = payload.get("error_category")
    if error_category is not None:
        if not isinstance(error_category, str):
            return "PROTOCOL_ERROR"
        return error_category if error_category in infrastructure_categories else "PROTOCOL_ERROR"

    failure_type = payload.get("failure_type")
    if failure_type is not None and not isinstance(failure_type, str):
        return "PROTOCOL_ERROR"
    if failure_type in {"STUDENT_EXCEPTION", "STUDENT_PROCESS_EXIT", "STUDENT_FATAL_ERROR"}:
        return "RE"
    if result.exit_code != 0:
        return "RE"
    if failure_type not in (None, "CLASS_LOADING_FAILURE"):
        return "PROTOCOL_ERROR"
    return "AC" if all(check["passed"] for check in checks) else "WA"


@dataclass(frozen=True)
class JDKConfig:
    """Absolute paths and verified versions for one configured JDK."""

    home: str
    javac: str
    java: str
    javac_version: str
    java_version: str


@dataclass(frozen=True)
class CompileResult:
    """Compiler outcome; process status and judge verdict remain separate."""

    status: ProcessStatus
    success: bool
    verdict: str | None
    exit_code: int | None
    duration_ms: int
    stdout: str
    stderr: str
    stdout_bytes: int
    stderr_bytes: int
    stdout_truncated: bool
    stderr_truncated: bool
    run_id: str | None
    expected_class_file: str
    expected_class_file_exists: bool
    jdk: JDKConfig | None = None
    error: str | None = None
    error_category: str | None = None

    def to_dict(self) -> dict:
        result = asdict(self)
        result["status"] = self.status.value
        result["success"] = self.success
        return result


@dataclass(frozen=True)
class JudgeResult:
    """Normalized end-to-end result for one Java Reflection execution."""

    verdict: str
    score: int | float
    total_points: int | float
    checks: list[dict]
    run_id: str | None
    duration_ms: int
    error: str | None = None
    error_category: str | None = None
    compile_result: CompileResult | None = None
    process_result: ProcessResult | None = None

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "score": self.score,
            "total_points": self.total_points,
            "checks": list(self.checks),
            "run_id": self.run_id,
            "duration_ms": self.duration_ms,
            "error": self.error,
            "error_category": self.error_category,
            "compile_result": self.compile_result.to_dict() if self.compile_result else None,
            "process_result": self.process_result.to_dict() if self.process_result else None,
        }


class JDKNotFoundError(OSError):
    """The configured JDK is absent or does not provide both required tools."""

    category = "JDK_NOT_FOUND"


class JDKConfigurationError(OSError):
    """The selected Java tools cannot be verified as one supported JDK."""

    category = "JUDGE_INFRA_ERROR"


DEFAULT_JAVA_COMPILE_LIMITS = JobLimits(
    process_memory_limit_bytes=512 * 1024 * 1024,
    job_memory_limit_bytes=512 * 1024 * 1024,
)
JAVA_HEAP_BUDGET_DIVISOR = 2
MAX_REFLECTION_SOURCE_BYTES = 1024 * 1024
MAX_REFLECTION_SPEC_BYTES = 1024 * 1024
DEFAULT_REFLECTION_OUTPUT_BYTES = 256 * 1024
DEFAULT_REFLECTION_PROTOCOL_BYTES = 1024 * 1024
_JUDGE_PROTOCOL_OVERFLOW_MARKER = "JUDGE_PROTOCOL_LIMIT_EXCEEDED\n"
_JUDGE_STARTED_FRAME = "!J\n"
_STUDENT_STARTED_FRAME = "!S\n"
_JUDGE_COMPLETED_FRAME = "!C\n"
_REFLECTION_JUDGE_SOURCE = Path(__file__).resolve().parents[1] / "judge" / "ReflectionJudge.java"
_REFLECTION_JUDGE_CACHE_ROOT = (
    Path(tempfile.gettempdir()) / "ClassroomSubmissionServer" / "judge_build_cache"
)
_REFLECTION_JUDGE_CACHE_FORMAT = 1
_REFLECTION_JUDGE_CACHE_LOCK_GUARD = threading.Lock()
_REFLECTION_JUDGE_CACHE_LOCKS: dict[str, threading.Lock] = {}


def _reflection_judge_cache_identity(
    source_bytes: bytes, jdk: JDKConfig
) -> tuple[str, str, dict[str, str]]:
    source_hash = hashlib.sha256(source_bytes).hexdigest()
    compiler = {
        "javac": os.path.normcase(str(Path(jdk.javac).resolve())).casefold(),
        "version": jdk.javac_version,
    }
    identity = hashlib.sha256(
        json.dumps(
            {"source_sha256": source_hash, "compiler": compiler},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return identity, source_hash, compiler


def _reflection_judge_cache_lock(identity: str) -> threading.Lock:
    with _REFLECTION_JUDGE_CACHE_LOCK_GUARD:
        lock = _REFLECTION_JUDGE_CACHE_LOCKS.get(identity)
        if lock is None:
            lock = threading.Lock()
            _REFLECTION_JUDGE_CACHE_LOCKS[identity] = lock
        return lock


def _class_hashes(classes_dir: Path) -> dict[str, str] | None:
    if not classes_dir.is_dir() or classes_dir.is_symlink():
        return None
    entries = list(classes_dir.rglob("*"))
    if any(path.is_symlink() for path in entries):
        return None
    files = [path for path in entries if path.is_file()]
    if any(path.suffix.casefold() != ".class" for path in files):
        return None
    hashes = {
        path.relative_to(classes_dir).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in files
    }
    return hashes if "ReflectionJudge.class" in hashes else None


def _validated_reflection_judge_cache(
    cache_dir: Path,
    *,
    source_hash: str,
    compiler: Mapping[str, str],
) -> Path | None:
    try:
        if cache_dir.is_symlink() or not cache_dir.is_dir():
            return None
        manifest_path = cache_dir / "manifest.json"
        if manifest_path.is_symlink() or not manifest_path.is_file():
            return None
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (
            not isinstance(manifest, dict)
            or manifest.get("format") != _REFLECTION_JUDGE_CACHE_FORMAT
            or manifest.get("source_sha256") != source_hash
            or manifest.get("compiler") != dict(compiler)
            or not isinstance(manifest.get("class_hashes"), dict)
        ):
            return None
        classes_dir = cache_dir / "classes"
        actual_hashes = _class_hashes(classes_dir)
        if actual_hashes is None or actual_hashes != manifest["class_hashes"]:
            return None
        return classes_dir
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def _remove_reflection_judge_cache_entry(cache_dir: Path) -> None:
    if cache_dir.is_symlink():
        cache_dir.unlink()
    elif cache_dir.exists():
        shutil.rmtree(cache_dir)


def _judge_build_infra_failure(message: str) -> ProcessResult:
    return ProcessResult(
        status=ProcessStatus.START_ERROR,
        exit_code=None,
        duration_ms=0,
        stdout="",
        stderr="",
        stdout_bytes=0,
        stderr_bytes=0,
        stdout_truncated=False,
        stderr_truncated=False,
        error=message,
        error_category="JUDGE_INFRA_ERROR",
    )


def _get_reflection_judge_build(
    *,
    source_bytes: bytes,
    jdk: JDKConfig,
    cwd: Path,
    environment: Mapping[str, str],
    timeout_seconds: float,
    max_output_bytes: int,
    job_limits: JobLimits,
) -> tuple[Path | None, ProcessResult | None]:
    """Return a validated cached Judge class directory, compiling it once per key."""
    identity, source_hash, compiler = _reflection_judge_cache_identity(source_bytes, jdk)
    cache_root = _REFLECTION_JUDGE_CACHE_ROOT
    cache_dir = cache_root / identity
    with _reflection_judge_cache_lock(identity):
        cached_classes = _validated_reflection_judge_cache(
            cache_dir, source_hash=source_hash, compiler=compiler
        )
        if cached_classes is not None:
            return cached_classes, None

        _remove_reflection_judge_cache_entry(cache_dir)
        cache_root.mkdir(parents=True, exist_ok=True)
        if cache_root.is_symlink():
            raise OSError("ReflectionJudge cache root must not be a symbolic link.")
        staging_dir = cache_root / f".{identity}.{uuid.uuid4().hex}.tmp"
        source_dir = staging_dir / "src"
        classes_dir = staging_dir / "classes"
        try:
            source_dir.mkdir(parents=True)
            classes_dir.mkdir()
            staged_source = source_dir / "ReflectionJudge.java"
            staged_source.write_bytes(source_bytes)
            compile_result = run_process(
                [
                    jdk.javac,
                    "-encoding",
                    "UTF-8",
                    "-proc:none",
                    "-d",
                    str(classes_dir),
                    str(staged_source),
                ],
                cwd=staging_dir,
                timeout_seconds=timeout_seconds,
                max_output_bytes=max_output_bytes,
                env=environment,
                job_limits=job_limits,
            )
            if compile_result.status != ProcessStatus.EXITED or compile_result.exit_code != 0:
                return None, compile_result

            hashes = _class_hashes(classes_dir)
            if hashes is None:
                return None, _judge_build_infra_failure(
                    "javac succeeded but did not produce a complete ReflectionJudge build."
                )
            shutil.rmtree(source_dir)
            manifest = {
                "format": _REFLECTION_JUDGE_CACHE_FORMAT,
                "source_sha256": source_hash,
                "compiler": compiler,
                "class_hashes": hashes,
            }
            manifest_path = staging_dir / "manifest.json"
            with manifest_path.open("w", encoding="utf-8", newline="\n") as stream:
                json.dump(manifest, stream, sort_keys=True, separators=(",", ":"))
                stream.flush()
                os.fsync(stream.fileno())

            os.replace(staging_dir, cache_dir)
            published_classes = _validated_reflection_judge_cache(
                cache_dir, source_hash=source_hash, compiler=compiler
            )
            if published_classes is None:
                _remove_reflection_judge_cache_entry(cache_dir)
                return None, _judge_build_infra_failure(
                    "Published ReflectionJudge cache failed integrity validation."
                )
            return published_classes, None
        finally:
            if staging_dir.exists():
                shutil.rmtree(staging_dir, ignore_errors=True)


def _parse_judge_lifecycle(protocol_text: str) -> tuple[str, str | None]:
    """Return (state, JSON payload); lifecycle frames travel only on judge pipe."""
    if not protocol_text.startswith(_JUDGE_STARTED_FRAME):
        return "INFRA_BEFORE_START", None
    remainder = protocol_text[len(_JUDGE_STARTED_FRAME):]
    student_started = remainder.startswith(_STUDENT_STARTED_FRAME)
    if student_started:
        remainder = remainder[len(_STUDENT_STARTED_FRAME):]
    completed = remainder.endswith(_JUDGE_COMPLETED_FRAME)
    if completed:
        remainder = remainder[:-len(_JUDGE_COMPLETED_FRAME)]
    if not student_started:
        if not completed:
            return "INFRA_BEFORE_STUDENT", None
        if not remainder:
            return "PROTOCOL_ERROR", None
        return "COMPLETED", remainder
    if not completed and not remainder:
        return "STUDENT_TERMINATED", None
    if not completed or not remainder:
        return "PROTOCOL_ERROR", None
    return "COMPLETED", remainder
DEFAULT_REFLECTION_TIMEOUT_SECONDS = 10
_INFRASTRUCTURE_CATEGORIES = frozenset(
    {"INVALID_REQUEST", "JDK_NOT_FOUND", "JUDGE_INFRA_ERROR", "PROTOCOL_ERROR"}
)


def java_heap_limit_mb(limits: JobLimits) -> int:
    """Set Java heap to at most half its effective committed-memory budget.

    The remaining budget is native/runtime headroom; Windows Job limits still
    account for the complete JVM process, including ReflectionJudge and student
    objects. Job Object limits are commit limits, not working-set limits.
    """
    if not isinstance(limits, JobLimits):
        raise ValueError("limits must be a JobLimits value")
    effective_limit_bytes = min(
        limits.process_memory_limit_bytes,
        limits.job_memory_limit_bytes,
    )
    if effective_limit_bytes < MIN_JAVA_JOB_MEMORY_MB * 1024 * 1024:
        raise ValueError(
            f"Java memory budget must be at least {MIN_JAVA_JOB_MEMORY_MB} MiB"
        )
    heap_limit_mb = effective_limit_bytes // (
        JAVA_HEAP_BUDGET_DIVISOR * 1024 * 1024
    )
    return heap_limit_mb


@dataclass
class RunWorkspace:
    """A unique temporary run directory with the agreed subdirectory layout."""

    run_id: str
    root: Path
    src: Path
    out: Path
    input: Path
    result: Path
    keep_temp: bool = False
    cleanup_error: str | None = field(default=None, init=False, repr=False)
    _cleaned: bool = field(default=False, init=False, repr=False)

    @classmethod
    def create(
        cls, parent: str | Path | None = None, *, keep_temp: bool = False
    ) -> "RunWorkspace":
        if not isinstance(keep_temp, bool):
            raise ValueError("keep_temp must be a boolean")
        base = Path(parent) if parent is not None else Path(tempfile.gettempdir()) / "ClassroomSubmissionServer"
        base.mkdir(parents=True, exist_ok=True)

        run_id = uuid.uuid4().hex
        root = base / f"run_{run_id}"
        root.mkdir(exist_ok=False)
        workspace = cls(
            run_id=run_id,
            root=root,
            src=root / "src",
            out=root / "out",
            input=root / "input",
            result=root / "result",
            keep_temp=keep_temp,
        )
        try:
            for directory in (workspace.src, workspace.out, workspace.input, workspace.result):
                directory.mkdir()
        except Exception as exc:
            try:
                _remove_workspace_tree(root)
            except Exception as cleanup_exc:
                _log_workspace_cleanup_failure(run_id, root, cleanup_exc)
            raise
        return workspace

    def cleanup(self) -> None:
        if self.keep_temp or self._cleaned:
            return
        try:
            _remove_workspace_tree(self.root)
            self._cleaned = True
            self.cleanup_error = None
        except Exception as exc:
            self.cleanup_error = f"{type(exc).__name__}: {exc}"
            _log_workspace_cleanup_failure(self.run_id, self.root, exc)

    def __enter__(self) -> "RunWorkspace":
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        self.cleanup()
        return False


def _is_reparse_point(path: Path) -> bool:
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return False
    attributes = getattr(info, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return stat.S_ISLNK(info.st_mode) or bool(attributes & reparse_flag)


def _is_directory_reparse_point(path: Path) -> bool:
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return False
    attributes = getattr(info, "st_file_attributes", 0)
    directory_flag = getattr(stat, "FILE_ATTRIBUTE_DIRECTORY", 0x10)
    return bool(attributes & directory_flag)


def _remove_readonly_on_error(function, path, error) -> None:
    target = Path(path)
    if not os.path.lexists(target):
        return
    if _is_reparse_point(target):
        # Never chmod or descend through symlinks, junctions, or other reparse points.
        raise error
    if not isinstance(error, PermissionError) and getattr(error, "winerror", None) != 5:
        raise error
    os.chmod(target, stat.S_IREAD | stat.S_IWRITE)
    retry_result = function(path)
    close = getattr(retry_result, "close", None)
    if close is not None:
        close()


def _remove_workspace_tree(root: Path) -> None:
    if not os.path.lexists(root):
        return
    if _is_reparse_point(root):
        if _is_directory_reparse_point(root):
            os.rmdir(root)
        else:
            os.unlink(root)
        return

    last_error = None
    for attempt in range(3):
        try:
            if os.name == "nt" and sys.version_info >= (3, 12):
                shutil.rmtree(root, onexc=_remove_readonly_on_error)
            else:
                shutil.rmtree(
                    root,
                    onerror=lambda function, path, exc_info: _remove_readonly_on_error(
                        function, path, exc_info[1]
                    ),
                )
            return
        except FileNotFoundError:
            return
        except OSError as exc:
            if not os.path.lexists(root):
                return
            last_error = exc
            if attempt < 2:
                time.sleep(0.05 * (attempt + 1))
    if last_error is not None:
        raise last_error


def _log_workspace_cleanup_failure(run_id: str, root: Path, error: Exception) -> None:
    try:
        logger.error(
            "Execution workspace cleanup failed (run_id=%s, path=%s): %s: %s",
            run_id,
            root,
            type(error).__name__,
            error,
        )
    except Exception:
        # Logging must not turn best-effort cleanup into a server failure.
        pass


def _environment_value(environment: Mapping[str, str], name: str) -> str | None:
    target = name.casefold()
    for key, value in environment.items():
        if key.casefold() == target:
            return value
    return None


def minimal_environment(source: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return only operating-system variables needed to launch local tools."""
    values = os.environ if source is None else source
    allowed = (
        ("SystemRoot", "WINDIR", "TEMP", "TMP", "PATH")
        if os.name == "nt"
        else ("PATH", "HOME", "TMPDIR", "LANG", "LC_ALL")
    )
    if os.name == "nt":
        return {
            name: value
            for name in allowed
            if (value := _environment_value(values, name)) is not None
        }
    return {name: values[name] for name in allowed if name in values}


class _BoundedCapture:
    def __init__(
        self,
        max_bytes: int,
        *,
        stdout_limit_bytes: int | None = None,
        stderr_limit_bytes: int | None = None,
        protocol_limit_bytes: int | None = None,
    ):
        self.max_bytes = max_bytes
        self.stream_limits = {
            "stdout": stdout_limit_bytes,
            "stderr": stderr_limit_bytes,
        }
        self.lock = threading.Lock()
        self.buffers = {"stdout": bytearray(), "stderr": bytearray()}
        self.bytes_seen = {"stdout": 0, "stderr": 0}
        self.truncated = {"stdout": False, "stderr": False}
        self.stored_bytes = 0
        self.output_limit = threading.Event()
        self.protocol_limit = protocol_limit_bytes
        self.protocol_buffer = bytearray()
        self.protocol_bytes_seen = 0
        self.protocol_truncated = False
        self.protocol_limit_event = threading.Event()
        self.read_error: str | None = None

    def read_stream(self, name: str, stream) -> None:
        try:
            while True:
                chunk = stream.read(8192)
                if not chunk:
                    return
                with self.lock:
                    self.bytes_seen[name] += len(chunk)
                    available = self.max_bytes - self.stored_bytes
                    stream_limit = self.stream_limits[name]
                    if stream_limit is not None:
                        available = min(available, stream_limit - len(self.buffers[name]))
                    available = max(0, available)
                    kept = min(available, len(chunk))
                    if kept:
                        self.buffers[name].extend(chunk[:kept])
                        self.stored_bytes += kept
                    if kept < len(chunk):
                        self.truncated[name] = True
                        self.output_limit.set()
        except Exception as exc:
            with self.lock:
                self.read_error = f"{type(exc).__name__}: {exc}"

    def read_protocol(self, stream) -> None:
        try:
            while True:
                chunk = stream.read(8192)
                if not chunk:
                    return
                with self.lock:
                    self.protocol_bytes_seen += len(chunk)
                    available = self.protocol_limit - len(self.protocol_buffer)
                    kept = min(max(0, available), len(chunk))
                    if kept:
                        self.protocol_buffer.extend(chunk[:kept])
                    if kept < len(chunk):
                        self.protocol_truncated = True
                        self.protocol_limit_event.set()
        except Exception as exc:
            with self.lock:
                self.read_error = f"{type(exc).__name__}: {exc}"

    def snapshot(self):
        with self.lock:
            output = {
                name: bytes(value).decode("utf-8", errors="replace")
                for name, value in self.buffers.items()
            }
            protocol = bytes(self.protocol_buffer).decode("utf-8", errors="replace")
            return (
                output,
                dict(self.bytes_seen),
                dict(self.truncated),
                self.read_error,
                protocol,
                self.protocol_bytes_seen,
                self.protocol_truncated,
            )


# Wait in the kernel between checks instead of waking every 10 ms. Reader
# threads keep draining both pipes and signal output_limit as soon as the
# combined cap is crossed; this bounds event response latency to 100 ms.
_PROCESS_MONITOR_WAIT_SECONDS = 0.1


def _terminate_and_reap(process: subprocess.Popen) -> bool:
    """Stop and reap the process; Windows Job termination also kills descendants."""
    if process.poll() is None:
        try:
            process.terminate()
        except OSError:
            pass
        try:
            process.wait(timeout=0.25)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
            except OSError:
                pass
    try:
        process.wait(timeout=1.0)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
        except OSError:
            pass
        try:
            process.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            pass
    return process.poll() is not None


def _write_process_input(stream, input_data: bytes, errors: list[str]) -> None:
    try:
        remaining = memoryview(input_data)
        while remaining:
            written = stream.write(remaining)
            if written is None or written <= 0:
                raise OSError("Process stdin pipe stopped accepting input.")
            remaining = remaining[written:]
    except BrokenPipeError:
        # A program may legitimately exit without consuming all of its stdin.
        pass
    except Exception as exc:
        errors.append(f"Could not send process stdin: {type(exc).__name__}: {exc}")
    finally:
        try:
            stream.close()
        except OSError:
            pass


def run_process(
    command: Sequence[str],
    *,
    cwd: str | Path,
    timeout_seconds: float,
    max_output_bytes: int,
    env: Mapping[str, str] | None = None,
    job_limits: JobLimits | None = None,
    input_data: bytes | None = None,
    stdout_limit_bytes: int | None = None,
    stderr_limit_bytes: int | None = None,
    protocol_limit_bytes: int | None = None,
) -> ProcessResult:
    """Run a Job-contained process with bounded output and a hard timeout.

    Student output is bounded separately from an optional bounded Judge
    protocol pipe. Protocol data is intentionally omitted from public dicts.
    Job creation/assignment errors fail closed and never fall back to Popen.
    """
    if isinstance(command, (str, bytes)) or not command or any(not isinstance(arg, str) for arg in command):
        raise ValueError("command must be a non-empty sequence of strings")
    if not command[0]:
        raise ValueError("command executable must not be empty")
    if timeout_seconds <= 0 or not float(timeout_seconds) < float("inf"):
        raise ValueError("timeout_seconds must be a positive finite number")
    if not isinstance(max_output_bytes, int) or isinstance(max_output_bytes, bool) or max_output_bytes < 0:
        raise ValueError("max_output_bytes must not be negative")
    for name, value in (
        ("stdout_limit_bytes", stdout_limit_bytes),
        ("stderr_limit_bytes", stderr_limit_bytes),
        ("protocol_limit_bytes", protocol_limit_bytes),
    ):
        if value is not None and (
            not isinstance(value, int) or isinstance(value, bool) or value < 0
        ):
            raise ValueError(f"{name} must be a non-negative integer or None")
    if input_data is not None and not isinstance(input_data, bytes):
        raise ValueError("input_data must be bytes or None")

    started = time.monotonic()
    process_env = dict(env) if env is not None else minimal_environment()
    try:
        process = create_job_process(
            list(command),
            cwd=str(cwd),
            env=process_env,
            limits=job_limits or DEFAULT_JOB_LIMITS,
            stdin_pipe=input_data is not None or protocol_limit_bytes is not None,
            protocol_pipe=protocol_limit_bytes is not None,
        )
    except Exception as exc:
        return ProcessResult(
            status=ProcessStatus.START_ERROR,
            exit_code=None,
            duration_ms=max(0, int((time.monotonic() - started) * 1000)),
            stdout="",
            stderr="",
            stdout_bytes=0,
            stderr_bytes=0,
            stdout_truncated=False,
            stderr_truncated=False,
            error=f"{type(exc).__name__}: {exc}",
            error_category=getattr(exc, "category", "JUDGE_INFRA_ERROR"),
        )

    capture = _BoundedCapture(
        max_output_bytes,
        stdout_limit_bytes=stdout_limit_bytes,
        stderr_limit_bytes=stderr_limit_bytes,
        protocol_limit_bytes=protocol_limit_bytes,
    )
    readers = [
        threading.Thread(target=capture.read_stream, args=(name, stream), daemon=True)
        for name, stream in (("stdout", process.stdout), ("stderr", process.stderr))
    ]
    if process.protocol is not None:
        readers.append(
            threading.Thread(
                target=capture.read_protocol, args=(process.protocol,), daemon=True
            )
        )
    input_errors: list[str] = []
    input_writer = None
    status = ProcessStatus.EXITED
    error = None
    error_category = None
    memory_limit_hit = False
    deadline = time.monotonic() + timeout_seconds
    try:
        for reader in readers:
            reader.start()
        if input_data is not None or protocol_limit_bytes is not None:
            if protocol_limit_bytes is not None:
                handle_value = process.protocol_handle_value
                if not isinstance(handle_value, int) or handle_value <= 0:
                    raise RuntimeError("Protocol pipe handle is unavailable.")
                input_payload = handle_value.to_bytes(8, byteorder="big") + (input_data or b"")
            else:
                input_payload = input_data or b""
            input_writer = threading.Thread(
                target=_write_process_input,
                args=(process.stdin, input_payload, input_errors),
                daemon=True,
            )
            input_writer.start()
        while True:
            if input_errors:
                status = ProcessStatus.START_ERROR
                error = input_errors[0]
                error_category = "JUDGE_INFRA_ERROR"
                if not _terminate_and_reap(process):
                    error += "; child process could not be stopped"
                break
            if capture.output_limit.is_set():
                status = ProcessStatus.OUTPUT_LIMIT
                if not _terminate_and_reap(process):
                    status = ProcessStatus.START_ERROR
                    error = "Could not stop the child process after reaching the output limit."
                    error_category = "JUDGE_INFRA_ERROR"
                break
            if capture.protocol_limit_event.is_set():
                status = ProcessStatus.START_ERROR
                error = "Judge protocol exceeded its configured output limit."
                error_category = "JUDGE_INFRA_ERROR"
                if not _terminate_and_reap(process):
                    error += " Child process could not be stopped."
                break
            if capture.read_error is not None:
                status = ProcessStatus.START_ERROR
                error = capture.read_error
                error_category = "JUDGE_INFRA_ERROR"
                if not _terminate_and_reap(process):
                    error += "; child process could not be stopped"
                break
            try:
                if process.memory_limit_hit():
                    status = ProcessStatus.MEMORY_LIMIT
                    if not _terminate_and_reap(process):
                        status = ProcessStatus.START_ERROR
                        error = "Could not stop the Job Object after a memory limit event."
                        error_category = "JUDGE_INFRA_ERROR"
                    break
            except Exception as exc:
                status = ProcessStatus.START_ERROR
                error = f"Could not inspect Job Object memory events: {type(exc).__name__}: {exc}"
                error_category = "JUDGE_INFRA_ERROR"
                if not _terminate_and_reap(process):
                    error += "; child process could not be stopped"
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                status = ProcessStatus.TIMEOUT
                if not _terminate_and_reap(process):
                    status = ProcessStatus.START_ERROR
                    error = "Could not stop the child process after timeout."
                    error_category = "JUDGE_INFRA_ERROR"
                break
            try:
                process.wait(timeout=min(remaining, _PROCESS_MONITOR_WAIT_SECONDS))
                break
            except subprocess.TimeoutExpired:
                # A blocking kernel wait bounds monitoring frequency while
                # retaining prompt checks for reader and Job Object events.
                continue

        exit_code = process.wait(timeout=1.0)
    except Exception as exc:
        status = ProcessStatus.START_ERROR
        error = f"{type(exc).__name__}: {exc}"
        error_category = getattr(exc, "category", "JUDGE_INFRA_ERROR")
        if not _terminate_and_reap(process):
            error += "; child process could not be stopped"
        exit_code = process.poll()
    finally:
        if process.poll() is None:
            if not _terminate_and_reap(process):
                status = ProcessStatus.START_ERROR
                error = "Child process remained alive after terminate and kill attempts."
                error_category = "JUDGE_INFRA_ERROR"
        if status == ProcessStatus.EXITED:
            try:
                memory_limit_hit = process.memory_limit_hit(wait_ms=25)
            except Exception as exc:
                status = ProcessStatus.START_ERROR
                error = f"Could not inspect Job Object memory usage: {type(exc).__name__}: {exc}"
                error_category = "JUDGE_INFRA_ERROR"
        try:
            process.close()
        except Exception as exc:
            status = ProcessStatus.START_ERROR
            error = f"Job cleanup failed: {type(exc).__name__}: {exc}"
            error_category = "JUDGE_INFRA_ERROR"
        for reader in readers:
            if reader.ident is not None:
                reader.join(timeout=1.0)
        if input_writer is not None and input_writer.ident is not None:
            input_writer.join(timeout=1.0)
        if process.stdout:
            try:
                process.stdout.close()
            except OSError:
                pass
        if process.stderr:
            try:
                process.stderr.close()
            except OSError:
                pass
        if process.protocol:
            try:
                process.protocol.close()
            except OSError:
                pass

    if exit_code is None:
        exit_code = process.poll()

    (
        output,
        byte_counts,
        truncated,
        read_error,
        protocol_output,
        protocol_bytes,
        protocol_truncated,
    ) = capture.snapshot()
    if status == ProcessStatus.EXITED and capture.output_limit.is_set():
        status = ProcessStatus.OUTPUT_LIMIT
    if status == ProcessStatus.EXITED and read_error:
        status = ProcessStatus.START_ERROR
        error = read_error
        error_category = "JUDGE_INFRA_ERROR"
    if status == ProcessStatus.EXITED and memory_limit_hit:
        status = ProcessStatus.MEMORY_LIMIT
    if status == ProcessStatus.EXITED and protocol_truncated:
        status = ProcessStatus.START_ERROR
        error = "Judge protocol exceeded its configured output limit."
        error_category = "JUDGE_INFRA_ERROR"

    return ProcessResult(
        status=status,
        exit_code=exit_code,
        duration_ms=max(0, int((time.monotonic() - started) * 1000)),
        stdout=output["stdout"],
        stderr=output["stderr"],
        stdout_bytes=byte_counts["stdout"],
        stderr_bytes=byte_counts["stderr"],
        stdout_truncated=truncated["stdout"],
        stderr_truncated=truncated["stderr"],
        error=error,
        error_category=error_category,
        protocol_output=protocol_output if protocol_limit_bytes is not None else None,
        protocol_output_bytes=protocol_bytes,
        protocol_truncated=protocol_truncated,
    )


def _resolve_jdk_paths(environment: Mapping[str, str]) -> tuple[Path, Path, Path]:
    executable_suffix = ".exe" if os.name == "nt" else ""
    configured_home = _environment_value(environment, "JAVA_HOME")
    if configured_home:
        home = Path(configured_home).expanduser().resolve()
        java = home / "bin" / f"java{executable_suffix}"
        javac = home / "bin" / f"javac{executable_suffix}"
        if not java.is_file() or not javac.is_file():
            raise JDKNotFoundError(
                "JAVA_HOME is set but its bin directory does not contain both java and javac."
            )
        return home, javac.resolve(), java.resolve()

    search_path = _environment_value(environment, "PATH")
    if search_path and search_path.strip():
        javac_path = shutil.which("javac", path=search_path)
        java_path = shutil.which("java", path=search_path)
    else:
        javac_path = java_path = None
    if not javac_path or not java_path:
        missing = []
        if not javac_path:
            missing.append("javac")
        if not java_path:
            missing.append("java")
        raise JDKNotFoundError(
            "JDK tools not found on PATH: " + ", ".join(missing) + "."
        )

    javac = Path(javac_path).resolve()
    java = Path(java_path).resolve()
    if javac.parent != java.parent:
        raise JDKNotFoundError(
            "java and javac resolve to different bin directories; set JAVA_HOME to select one JDK."
        )
    return javac.parent.parent, javac, java


def java_process_environment(
    environment: Mapping[str, str], jdk_home: Path, jdk_bin: Path
) -> dict[str, str]:
    result = minimal_environment(environment)
    original_path = _environment_value(environment, "PATH")
    result["PATH"] = str(jdk_bin) + (os.pathsep + original_path if original_path else "")
    result["JAVA_HOME"] = str(jdk_home)
    return result


def _parse_java_version(output: str) -> tuple[str, int] | None:
    match = re.search(r"\b(?:javac|version)\s+\"?([0-9]+(?:\.[0-9]+)*)", output, re.IGNORECASE)
    if not match:
        return None
    version = match.group(1)
    components = tuple(int(component) for component in version.split("."))
    major = components[1] if components[0] == 1 and len(components) > 1 else components[0]
    return version, major


def _probe_java_tool(
    executable: Path,
    *,
    cwd: Path,
    environment: Mapping[str, str],
    job_limits: JobLimits,
) -> tuple[str, int]:
    result = run_process(
        [str(executable), "-version"],
        cwd=cwd,
        timeout_seconds=5,
        max_output_bytes=4096,
        env=environment,
        job_limits=job_limits,
    )
    if result.status != ProcessStatus.EXITED or result.exit_code != 0:
        detail = result.error or result.stderr or result.stdout or result.status.value
        raise JDKConfigurationError(
            f"Could not verify {executable.name} version: {detail}"
        )
    parsed = _parse_java_version(result.stdout + "\n" + result.stderr)
    if parsed is None:
        raise JDKConfigurationError(
            f"Could not parse {executable.name} version output."
        )
    return parsed


def _detect_jdk(
    environment: Mapping[str, str], *, cwd: Path, job_limits: JobLimits
) -> tuple[JDKConfig, dict[str, str]]:
    home, javac, java = _resolve_jdk_paths(environment)
    tool_environment = java_process_environment(environment, home, javac.parent)
    javac_version, javac_major = _probe_java_tool(
        javac, cwd=cwd, environment=tool_environment, job_limits=job_limits
    )
    java_version, java_major = _probe_java_tool(
        java, cwd=cwd, environment=tool_environment, job_limits=job_limits
    )
    if javac_major < 17 or java_major < 17:
        raise JDKConfigurationError(
            f"JDK 17 or newer is required (javac {javac_version}, java {java_version})."
        )
    if javac_major != java_major:
        raise JDKConfigurationError(
            f"javac and java versions do not match (javac {javac_version}, java {java_version})."
        )
    return (
        JDKConfig(
            home=str(home),
            javac=str(javac),
            java=str(java),
            javac_version=javac_version,
            java_version=java_version,
        ),
        tool_environment,
    )


def verify_jdk_configuration(
    environment: Mapping[str, str] | None = None,
) -> JDKConfig:
    """Validate the configured Java toolchain before starting the server."""
    if os.name != "nt":
        raise JDKConfigurationError(
            "Java code grading requires Windows Job Objects on this server."
        )
    jdk, _ = _detect_jdk(
        os.environ if environment is None else environment,
        cwd=Path.cwd(),
        job_limits=DEFAULT_JAVA_COMPILE_LIMITS,
    )
    return jdk


def _validated_source_path(source_path: str | Path) -> tuple[Path, str]:
    if not isinstance(source_path, (str, Path)):
        raise ValueError("source_path must be a relative .java path")
    raw_path = str(source_path)
    normalized = raw_path.replace("\\", "/")
    posix_path = PurePosixPath(normalized)
    windows_path = PureWindowsPath(raw_path)
    if (
        not normalized
        or "\0" in normalized
        or posix_path.is_absolute()
        or windows_path.is_absolute()
        or windows_path.drive
        or any(part in ("", ".", "..") for part in posix_path.parts)
        or posix_path.suffix.casefold() != ".java"
    ):
        raise ValueError("source_path must be a safe relative path ending in .java")
    relative_path = Path(*posix_path.parts)
    expected_class_file = posix_path.with_suffix(".class").as_posix()
    return relative_path, expected_class_file


def _failed_compile_result(
    exc: Exception,
    *,
    duration_ms: int,
    run_id: str | None,
    expected_class_file: str,
    jdk: JDKConfig | None = None,
) -> CompileResult:
    return CompileResult(
        status=ProcessStatus.START_ERROR,
        success=False,
        verdict=None,
        exit_code=None,
        duration_ms=duration_ms,
        stdout="",
        stderr="",
        stdout_bytes=0,
        stderr_bytes=0,
        stdout_truncated=False,
        stderr_truncated=False,
        run_id=run_id,
        expected_class_file=expected_class_file,
        expected_class_file_exists=False,
        jdk=jdk,
        error=f"{type(exc).__name__}: {exc}",
        error_category=getattr(exc, "category", "JUDGE_INFRA_ERROR"),
    )


def compile_java_in_workspace(
    source_code: str,
    workspace: RunWorkspace,
    *,
    source_path: str | Path = "Main.java",
    timeout_seconds: float = 20,
    max_output_bytes: int = 64 * 1024,
    env: Mapping[str, str] | None = None,
    job_limits: JobLimits | None = None,
) -> CompileResult:
    """Compile one Java source into an existing run workspace without cleaning it."""
    if not isinstance(source_code, str):
        raise ValueError("source_code must be a string")
    if not isinstance(workspace, RunWorkspace):
        raise ValueError("workspace must be a RunWorkspace")
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or timeout_seconds <= 0
        or not math.isfinite(timeout_seconds)
    ):
        raise ValueError("timeout_seconds must be a positive finite number")
    if (
        not isinstance(max_output_bytes, int)
        or isinstance(max_output_bytes, bool)
        or max_output_bytes < 0
    ):
        raise ValueError("max_output_bytes must not be negative")
    relative_source, expected_class_file = _validated_source_path(source_path)
    started = time.monotonic()
    jdk = None
    try:
        source_file = workspace.src / relative_source
        source_file.parent.mkdir(parents=True, exist_ok=True)
        with source_file.open("w", encoding="utf-8", newline="") as stream:
            stream.write(source_code)

        environment = dict(os.environ if env is None else env)
        compiler_limits = job_limits or DEFAULT_JAVA_COMPILE_LIMITS
        jdk, tool_environment = _detect_jdk(
            environment, cwd=workspace.root, job_limits=DEFAULT_JAVA_COMPILE_LIMITS
        )
        process_result = run_process(
            [
                jdk.javac,
                "-encoding",
                "UTF-8",
                "-proc:none",
                "-d",
                str(workspace.out),
                str(source_file),
            ],
            cwd=workspace.root,
            timeout_seconds=timeout_seconds,
            max_output_bytes=max_output_bytes,
            env=tool_environment,
            job_limits=compiler_limits,
        )
        compiler_succeeded = (
            process_result.status == ProcessStatus.EXITED
            and process_result.exit_code == 0
        )
        verdict = (
            "CE"
            if process_result.status == ProcessStatus.EXITED
            and process_result.exit_code != 0
            else None
        )
        error = process_result.error
        if process_result.status == ProcessStatus.TIMEOUT:
            error = f"javac exceeded the {timeout_seconds:g}-second compile timeout."
        elif process_result.status == ProcessStatus.MEMORY_LIMIT:
            error = "javac exceeded its configured process memory limit."
        elif process_result.status == ProcessStatus.OUTPUT_LIMIT:
            error = f"javac exceeded its {max_output_bytes}-byte output limit."
        elif verdict == "CE":
            error = f"javac exited with code {process_result.exit_code}."
        expected_output = workspace.out / relative_source.with_suffix(".class")
        expected_class_file_exists = compiler_succeeded and expected_output.is_file()
        success = compiler_succeeded and expected_class_file_exists
        if compiler_succeeded and not expected_class_file_exists:
            error = (
                f"javac did not produce the expected class file {expected_class_file}; "
                "check the package declaration and source_path."
            )
        return CompileResult(
            status=process_result.status,
            success=success,
            verdict=verdict,
            exit_code=process_result.exit_code,
            duration_ms=process_result.duration_ms,
            stdout=process_result.stdout,
            stderr=process_result.stderr,
            stdout_bytes=process_result.stdout_bytes,
            stderr_bytes=process_result.stderr_bytes,
            stdout_truncated=process_result.stdout_truncated,
            stderr_truncated=process_result.stderr_truncated,
            run_id=workspace.run_id,
            expected_class_file=expected_class_file,
            expected_class_file_exists=expected_class_file_exists,
            jdk=jdk,
            error=error,
            error_category=process_result.error_category,
        )
    except Exception as exc:
        return _failed_compile_result(
            exc,
            duration_ms=max(0, int((time.monotonic() - started) * 1000)),
            run_id=workspace.run_id,
            expected_class_file=expected_class_file,
            jdk=jdk,
        )


def compile_java(
    source_code: str,
    *,
    source_path: str | Path = "Main.java",
    timeout_seconds: float = 20,
    max_output_bytes: int = 64 * 1024,
    env: Mapping[str, str] | None = None,
    workspace_parent: str | Path | None = None,
    job_limits: JobLimits | None = None,
    keep_temp: bool = False,
) -> CompileResult:
    """Compile one Java source file; retain its workspace only when keep_temp is true."""
    if not isinstance(source_code, str):
        raise ValueError("source_code must be a string")
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or timeout_seconds <= 0
        or not math.isfinite(timeout_seconds)
    ):
        raise ValueError("timeout_seconds must be a positive finite number")
    if (
        not isinstance(max_output_bytes, int)
        or isinstance(max_output_bytes, bool)
        or max_output_bytes < 0
    ):
        raise ValueError("max_output_bytes must not be negative")
    if not isinstance(keep_temp, bool):
        raise ValueError("keep_temp must be a boolean")
    relative_source, expected_class_file = _validated_source_path(source_path)

    started = time.monotonic()
    workspace = None
    jdk = None
    result = None
    try:
        workspace = RunWorkspace.create(workspace_parent, keep_temp=keep_temp)
        result = compile_java_in_workspace(
            source_code,
            workspace,
            source_path=relative_source,
            timeout_seconds=timeout_seconds,
            max_output_bytes=max_output_bytes,
            env=env,
            job_limits=job_limits,
        )
    except Exception as exc:
        result = _failed_compile_result(
            exc,
            duration_ms=max(0, int((time.monotonic() - started) * 1000)),
            run_id=workspace.run_id if workspace else None,
            expected_class_file=expected_class_file,
            jdk=jdk,
        )
    finally:
        if workspace is not None:
            workspace.cleanup()
    if result is None:
        return _failed_compile_result(
            RuntimeError("Compilation ended without a result."),
            duration_ms=max(0, int((time.monotonic() - started) * 1000)),
            run_id=None,
            expected_class_file=expected_class_file,
        )
    return result


_JAVA_KEYWORDS = frozenset(
    "abstract assert boolean break byte case catch char class const continue default do double else enum "
    "extends final finally float for goto if implements import instanceof int interface long native new "
    "package private protected public return short static strictfp super switch synchronized this throw _ "
    "throws transient try void volatile while true false null"
    .split()
)


def is_java_identifier(value: str) -> bool:
    """Validate the classroom identifier subset, not every JLS identifier character.

    The accepted Unicode start/continuation rules follow Python's identifier
    categories, with Java's ``$`` allowed. Java identifier-ignorable format
    characters are intentionally excluded; javac remains authoritative for
    identifiers inside student source.
    """
    if not value or value in _JAVA_KEYWORDS:
        return False
    if any(unicodedata.category(character) == "Cf" for character in value):
        return False
    first = value[0]
    if first not in "_$" and not first.isidentifier():
        return False
    return all(character in "_$" or ("A" + character).isidentifier() for character in value[1:])


def _normalized_number(value: int | float | Decimal) -> int | float:
    if isinstance(value, Decimal):
        return plain_number(value)
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _validate_reflection_request(
    source_code: str, target_class_name: str, specification: Mapping
) -> tuple[bytes, Path, str, bytes, Decimal, list[Mapping]]:
    if not isinstance(source_code, str):
        raise ValueError("source_code must be a string")
    try:
        source_bytes = source_code.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError("source_code must be valid UTF-8 text") from exc
    if not source_bytes or len(source_bytes) > MAX_REFLECTION_SOURCE_BYTES:
        raise ValueError("source_code must be non-empty and within the size limit")

    if not isinstance(target_class_name, str) or not all(
        is_java_identifier(part) for part in target_class_name.split(".")
    ):
        raise ValueError("target_class_name must be a valid Java binary class name")
    source_path, expected_class_file = _validated_source_path(
        target_class_name.replace(".", "/") + ".java"
    )

    if not isinstance(specification, Mapping):
        raise ValueError("specification must be a JSON object")
    try:
        specification_bytes = json.dumps(
            dict(specification), ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise ValueError("specification must contain only valid JSON values") from exc
    if len(specification_bytes) > MAX_REFLECTION_SPEC_BYTES:
        raise ValueError("specification exceeds the size limit")

    checks = specification.get("checks")
    if not isinstance(checks, list):
        raise ValueError("specification must contain a checks array")
    declared_total = parse_nonnegative_decimal(
        specification.get("total_points"), "total_points", allow_decimal=False
    )
    seen_ids: set[str] = set()
    points_total = Decimal(0)
    validated_checks: list[Mapping] = []
    for index, check in enumerate(checks):
        if not isinstance(check, Mapping):
            raise ValueError(f"check at index {index} must be an object")
        check_id = check.get("id")
        kind = check.get("kind")
        if not isinstance(check_id, str) or not check_id.strip() or check_id in seen_ids:
            raise ValueError(f"check at index {index} must have a unique non-empty id")
        if not isinstance(kind, str) or not kind.strip():
            raise ValueError(f"check '{check_id}' must have a non-empty kind")
        if not isinstance(check.get("is_visible"), bool):
            raise ValueError(f"check '{check_id}' is_visible must be a boolean")
        points_total += parse_nonnegative_decimal(
            check.get("points"), f"check '{check_id}' points", allow_decimal=False
        )
        seen_ids.add(check_id)
        validated_checks.append(check)
    if declared_total != points_total:
        raise ValueError("total_points must equal the sum of check points")
    return source_bytes, source_path, expected_class_file, specification_bytes, declared_total, validated_checks


def _failed_judge_checks(checks: Sequence[Mapping], error: str) -> list[dict]:
    return [
        {
            "id": check["id"],
            "passed": False,
            "points_earned": 0,
            "expected": None,
            "actual": None,
            "error": error,
        }
        for check in checks
    ]


def _compile_result_from_process(
    process_result: ProcessResult,
    workspace: RunWorkspace,
    source_path: Path,
    expected_class_file: str,
    jdk: JDKConfig,
    timeout_seconds: float,
) -> CompileResult:
    compiler_succeeded = (
        process_result.status == ProcessStatus.EXITED and process_result.exit_code == 0
    )
    verdict = (
        "CE"
        if process_result.status == ProcessStatus.EXITED and process_result.exit_code != 0
        else None
    )
    expected_output = workspace.out / source_path.with_suffix(".class")
    expected_exists = compiler_succeeded and expected_output.is_file()
    error = process_result.error
    if verdict == "CE":
        error = f"javac exited with code {process_result.exit_code}."
    elif process_result.status == ProcessStatus.TIMEOUT:
        error = f"javac exceeded the {timeout_seconds:g}-second compile timeout."
    elif process_result.status == ProcessStatus.MEMORY_LIMIT:
        error = "javac exceeded its configured process memory limit."
    elif process_result.status == ProcessStatus.OUTPUT_LIMIT:
        error = "javac exceeded its configured output limit."
    elif compiler_succeeded and not expected_exists:
        error = f"javac did not produce the expected class file {expected_class_file}."
    return CompileResult(
        status=process_result.status,
        success=compiler_succeeded and expected_exists,
        verdict=verdict,
        exit_code=process_result.exit_code,
        duration_ms=process_result.duration_ms,
        stdout=process_result.stdout,
        stderr=process_result.stderr,
        stdout_bytes=process_result.stdout_bytes,
        stderr_bytes=process_result.stderr_bytes,
        stdout_truncated=process_result.stdout_truncated,
        stderr_truncated=process_result.stderr_truncated,
        run_id=workspace.run_id,
        expected_class_file=expected_class_file,
        expected_class_file_exists=expected_exists,
        jdk=jdk,
        error=error,
        error_category=process_result.error_category,
    )


def run_reflection_judge(
    source_code: str,
    target_class_name: str,
    specification: Mapping,
    *,
    compile_timeout_seconds: float = 20,
    judge_timeout_seconds: float = DEFAULT_REFLECTION_TIMEOUT_SECONDS,
    max_output_bytes: int = DEFAULT_REFLECTION_OUTPUT_BYTES,
    student_stdout_limit_bytes: int | None = None,
    student_stderr_limit_bytes: int | None = None,
    judge_protocol_limit_bytes: int = DEFAULT_REFLECTION_PROTOCOL_BYTES,
    env: Mapping[str, str] | None = None,
    workspace_parent: str | Path | None = None,
    job_limits: JobLimits | None = None,
    keep_temp: bool = False,
) -> JudgeResult:
    """Compile and judge in one workspace, cleaned unless keep_temp is enabled."""
    started = time.monotonic()
    try:
        (
            source_bytes,
            source_path,
            expected_class_file,
            specification_bytes,
            total_points,
            checks,
        ) = _validate_reflection_request(source_code, target_class_name, specification)
    except ValueError as exc:
        return JudgeResult(
            verdict="INVALID_REQUEST",
            score=0,
            total_points=0,
            checks=[],
            run_id=None,
            duration_ms=max(0, int((time.monotonic() - started) * 1000)),
            error=str(exc),
            error_category="INVALID_REQUEST",
        )
    for name, value in (
        ("compile_timeout_seconds", compile_timeout_seconds),
        ("judge_timeout_seconds", judge_timeout_seconds),
    ):
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value <= 0
        ):
            return JudgeResult(
                verdict="INVALID_REQUEST",
                score=0,
                total_points=_normalized_number(total_points),
                checks=_failed_judge_checks(checks, "INVALID_REQUEST"),
                run_id=None,
                duration_ms=max(0, int((time.monotonic() - started) * 1000)),
                error=f"{name} must be a positive finite number",
                error_category="INVALID_REQUEST",
            )
    if (
        not isinstance(max_output_bytes, int)
        or isinstance(max_output_bytes, bool)
        or max_output_bytes <= 0
    ):
        return JudgeResult(
            verdict="INVALID_REQUEST",
            score=0,
            total_points=_normalized_number(total_points),
            checks=_failed_judge_checks(checks, "INVALID_REQUEST"),
            run_id=None,
            duration_ms=max(0, int((time.monotonic() - started) * 1000)),
            error="max_output_bytes must be a positive integer",
            error_category="INVALID_REQUEST",
        )
    if not isinstance(keep_temp, bool):
        return JudgeResult(
            verdict="INVALID_REQUEST",
            score=0,
            total_points=_normalized_number(total_points),
            checks=_failed_judge_checks(checks, "INVALID_REQUEST"),
            run_id=None,
            duration_ms=max(0, int((time.monotonic() - started) * 1000)),
            error="keep_temp must be a boolean",
            error_category="INVALID_REQUEST",
        )
    if student_stdout_limit_bytes is None:
        student_stdout_limit_bytes = max_output_bytes
    if student_stderr_limit_bytes is None:
        student_stderr_limit_bytes = max_output_bytes
    for name, value in (
        ("student_stdout_limit_bytes", student_stdout_limit_bytes),
        ("student_stderr_limit_bytes", student_stderr_limit_bytes),
    ):
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            return JudgeResult(
                verdict="INVALID_REQUEST",
                score=0,
                total_points=_normalized_number(total_points),
                checks=_failed_judge_checks(checks, "INVALID_REQUEST"),
                run_id=None,
                duration_ms=max(0, int((time.monotonic() - started) * 1000)),
                error=f"{name} must be a non-negative integer",
                error_category="INVALID_REQUEST",
            )
    if (
        not isinstance(judge_protocol_limit_bytes, int)
        or isinstance(judge_protocol_limit_bytes, bool)
        or judge_protocol_limit_bytes < len(_JUDGE_PROTOCOL_OVERFLOW_MARKER.encode("ascii"))
        or judge_protocol_limit_bytes > 2**31 - 1
    ):
        return JudgeResult(
            verdict="INVALID_REQUEST",
            score=0,
            total_points=_normalized_number(total_points),
            checks=_failed_judge_checks(checks, "INVALID_REQUEST"),
            run_id=None,
            duration_ms=max(0, int((time.monotonic() - started) * 1000)),
            error="judge_protocol_limit_bytes is outside the supported range",
            error_category="INVALID_REQUEST",
        )

    workspace = None
    result = None
    jdk = None
    total_points_value = _normalized_number(total_points)
    if job_limits is not None and not isinstance(job_limits, JobLimits):
        return JudgeResult(
            verdict="INVALID_REQUEST",
            score=0,
            total_points=total_points_value,
            checks=_failed_judge_checks(checks, "INVALID_REQUEST"),
            run_id=None,
            duration_ms=max(0, int((time.monotonic() - started) * 1000)),
            error="job_limits must be a JobLimits value",
            error_category="INVALID_REQUEST",
        )
    compile_limits = job_limits or DEFAULT_JAVA_COMPILE_LIMITS
    judge_limits = job_limits or DEFAULT_JOB_LIMITS
    try:
        java_heap_limit_mb(judge_limits)
    except ValueError as exc:
        return JudgeResult(
            verdict="INVALID_REQUEST",
            score=0,
            total_points=total_points_value,
            checks=_failed_judge_checks(checks, "INVALID_REQUEST"),
            run_id=None,
            duration_ms=max(0, int((time.monotonic() - started) * 1000)),
            error=str(exc),
            error_category="INVALID_REQUEST",
        )
    environment = dict(os.environ if env is None else env)
    try:
        workspace = RunWorkspace.create(workspace_parent, keep_temp=keep_temp)
        source_file = workspace.src / source_path
        source_file.parent.mkdir(parents=True, exist_ok=True)
        source_file.write_bytes(source_bytes)

        jdk, tool_environment = _detect_jdk(
            environment, cwd=workspace.root, job_limits=DEFAULT_JAVA_COMPILE_LIMITS
        )
        student_compile_process = run_process(
            [
                jdk.javac,
                "-encoding",
                "UTF-8",
                "-proc:none",
                "-d",
                str(workspace.out),
                str(source_file),
            ],
            cwd=workspace.root,
            timeout_seconds=compile_timeout_seconds,
            max_output_bytes=max_output_bytes,
            env=tool_environment,
            job_limits=compile_limits,
        )
        compile_result = _compile_result_from_process(
            student_compile_process,
            workspace,
            source_path,
            expected_class_file,
            jdk,
            compile_timeout_seconds,
        )
        if compile_result.verdict == "CE":
            error = "\n".join(
                part for part in (compile_result.stderr, compile_result.stdout) if part
            ).strip() or compile_result.error
            result = JudgeResult(
                verdict="CE",
                score=0,
                total_points=total_points_value,
                checks=_failed_judge_checks(checks, "CE"),
                run_id=workspace.run_id,
                duration_ms=max(0, int((time.monotonic() - started) * 1000)),
                error=error,
                compile_result=compile_result,
                process_result=student_compile_process,
            )
        elif student_compile_process.status != ProcessStatus.EXITED or student_compile_process.exit_code != 0:
            compile_verdicts = {
                ProcessStatus.TIMEOUT: "TLE",
                ProcessStatus.MEMORY_LIMIT: "MLE",
                ProcessStatus.OUTPUT_LIMIT: "OLE",
            }
            if student_compile_process.status in compile_verdicts:
                verdict = compile_verdicts[student_compile_process.status]
                error_category = None
            else:
                error_category = (
                    student_compile_process.error_category
                    if student_compile_process.error_category in _INFRASTRUCTURE_CATEGORIES
                    else "JUDGE_INFRA_ERROR"
                )
                verdict = error_category
            result = JudgeResult(
                verdict=verdict,
                score=0,
                total_points=total_points_value,
                checks=_failed_judge_checks(checks, verdict),
                run_id=workspace.run_id,
                duration_ms=max(0, int((time.monotonic() - started) * 1000)),
                error=student_compile_process.error or compile_result.error,
                error_category=error_category,
                compile_result=compile_result,
                process_result=student_compile_process,
            )
        else:
            judge_source_bytes = _REFLECTION_JUDGE_SOURCE.read_bytes()
            judge_output, judge_compile_process = _get_reflection_judge_build(
                source_bytes=judge_source_bytes,
                jdk=jdk,
                cwd=workspace.root,
                environment=tool_environment,
                timeout_seconds=compile_timeout_seconds,
                max_output_bytes=max_output_bytes,
                job_limits=compile_limits,
            )
            if judge_compile_process is not None:
                detail = "\n".join(
                    part for part in (judge_compile_process.stderr, judge_compile_process.stdout) if part
                ).strip()
                result = JudgeResult(
                    verdict="JUDGE_INFRA_ERROR",
                    score=0,
                    total_points=total_points_value,
                    checks=_failed_judge_checks(checks, "JUDGE_INFRA_ERROR"),
                    run_id=workspace.run_id,
                    duration_ms=max(0, int((time.monotonic() - started) * 1000)),
                    error=detail or judge_compile_process.error or "Could not compile ReflectionJudge.",
                    error_category="JUDGE_INFRA_ERROR",
                    compile_result=compile_result,
                    process_result=judge_compile_process,
                )
            else:
                judge_process = run_process(
                    [
                        jdk.java,
                        f"-Xmx{java_heap_limit_mb(judge_limits)}m",
                        "-cp",
                        str(judge_output),
                        "ReflectionJudge",
                        target_class_name,
                        str(workspace.out),
                        str(judge_protocol_limit_bytes),
                    ],
                    cwd=workspace.root,
                    timeout_seconds=judge_timeout_seconds,
                    max_output_bytes=(
                        student_stdout_limit_bytes + student_stderr_limit_bytes
                    ),
                    stdout_limit_bytes=student_stdout_limit_bytes,
                    stderr_limit_bytes=student_stderr_limit_bytes,
                    protocol_limit_bytes=judge_protocol_limit_bytes,
                    env=tool_environment,
                    job_limits=judge_limits,
                    input_data=specification_bytes,
                )
                if judge_process.status != ProcessStatus.EXITED:
                    verdict = classify_judge_process_result(judge_process)
                    score = 0
                    check_results = _failed_judge_checks(checks, verdict)
                    error = judge_process.error or judge_process.stderr or verdict
                else:
                    lifecycle, protocol_text = _parse_judge_lifecycle(
                        judge_process.protocol_output or ""
                    )
                    if lifecycle in {"INFRA_BEFORE_START", "INFRA_BEFORE_STUDENT"}:
                        verdict = "JUDGE_INFRA_ERROR"
                        score = 0
                        check_results = _failed_judge_checks(checks, verdict)
                        error = "Judge terminated before student execution started."
                    elif lifecycle == "STUDENT_TERMINATED":
                        verdict = "RE"
                        score = 0
                        check_results = _failed_judge_checks(checks, verdict)
                        error = "Student terminated the Judge JVM before it completed."
                    elif lifecycle == "PROTOCOL_ERROR" or protocol_text is None:
                        verdict = "PROTOCOL_ERROR"
                        score = 0
                        check_results = _failed_judge_checks(checks, verdict)
                        error = "Judge lifecycle protocol was malformed or incomplete."
                    elif protocol_text == _JUDGE_PROTOCOL_OVERFLOW_MARKER:
                        verdict = "JUDGE_INFRA_ERROR"
                        score = 0
                        check_results = _failed_judge_checks(checks, verdict)
                        error = "Judge protocol exceeded its configured output limit."
                    else:
                        protocol_result = replace(
                            judge_process,
                            stdout=protocol_text,
                            stdout_bytes=judge_process.protocol_output_bytes,
                        )
                        verdict = classify_judge_process_result(protocol_result)
                        payload = None
                        try:
                            payload = json.loads(protocol_text)
                        except (json.JSONDecodeError, TypeError):
                            pass
                        try:
                            graded = grade_reflection(
                                checks, payload, total_points, verdict=verdict
                            )
                        except GradingError as exc:
                            verdict = exc.category
                            score = 0
                            check_results = _failed_judge_checks(checks, verdict)
                            error = str(exc)
                        else:
                            score, check_results = graded.score, graded.results
                            error = payload.get("error") or None
                        if verdict in {"TLE", "MLE", "OLE", "RE", "PROTOCOL_ERROR", "JUDGE_INFRA_ERROR"}:
                            score = 0
                            check_results = _failed_judge_checks(checks, verdict)
                            error = error or verdict
                error_category = verdict if verdict in _INFRASTRUCTURE_CATEGORIES else None
                result = JudgeResult(
                    verdict=verdict,
                    score=score,
                    total_points=total_points_value,
                    checks=check_results,
                    run_id=workspace.run_id,
                    duration_ms=max(0, int((time.monotonic() - started) * 1000)),
                    error=error,
                    error_category=error_category,
                    compile_result=compile_result,
                    process_result=judge_process,
                )
    except Exception as exc:
        error_category = getattr(exc, "category", "JUDGE_INFRA_ERROR")
        if error_category not in _INFRASTRUCTURE_CATEGORIES:
            error_category = "JUDGE_INFRA_ERROR"
        result = JudgeResult(
            verdict=error_category,
            score=0,
            total_points=total_points_value,
            checks=_failed_judge_checks(checks, error_category),
            run_id=workspace.run_id if workspace else None,
            duration_ms=max(0, int((time.monotonic() - started) * 1000)),
            error=f"{type(exc).__name__}: {exc}",
            error_category=error_category,
        )
    finally:
        if workspace is not None:
            workspace.cleanup()
    if result is None:
        return JudgeResult(
            verdict="JUDGE_INFRA_ERROR",
            score=0,
            total_points=total_points_value,
            checks=_failed_judge_checks(checks, "JUDGE_INFRA_ERROR"),
            run_id=None,
            duration_ms=max(0, int((time.monotonic() - started) * 1000)),
            error="Execution ended without a result.",
            error_category="JUDGE_INFRA_ERROR",
        )
    return result
