"""Workspace and bounded subprocess primitives for the Java execution path."""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from enum import Enum
import math
import os
from pathlib import Path
from pathlib import PurePosixPath, PureWindowsPath
import re
import shutil
import subprocess
import tempfile
import threading
import time
from typing import Mapping, Sequence
import uuid
from .windows_job import DEFAULT_JOB_LIMITS, JobLimits, create_job_process


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

    def to_dict(self) -> dict:
        result = asdict(self)
        result["status"] = self.status.value
        return result


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


class JDKNotFoundError(OSError):
    """The configured JDK is absent or does not provide both required tools."""

    category = "JDK_NOT_FOUND"


class JDKConfigurationError(OSError):
    """The selected Java tools cannot be verified as one supported JDK."""

    category = "JUDGE_INFRA_ERROR"


DEFAULT_JAVA_COMPILE_LIMITS = JobLimits(process_memory_limit_bytes=512 * 1024 * 1024)


@dataclass
class RunWorkspace:
    """A unique temporary run directory with the agreed subdirectory layout."""

    run_id: str
    root: Path
    src: Path
    out: Path
    input: Path
    result: Path

    @classmethod
    def create(cls, parent: str | Path | None = None) -> "RunWorkspace":
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
        )
        try:
            for directory in (workspace.src, workspace.out, workspace.input, workspace.result):
                directory.mkdir()
        except Exception:
            shutil.rmtree(root, ignore_errors=True)
            raise
        return workspace

    def cleanup(self) -> None:
        if self.root.exists():
            shutil.rmtree(self.root, ignore_errors=False)

    def __enter__(self) -> "RunWorkspace":
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        self.cleanup()
        return False


def minimal_environment(source: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return only operating-system variables needed to launch local tools."""
    values = os.environ if source is None else source
    allowed = (
        ("SystemRoot", "WINDIR", "TEMP", "TMP", "PATH")
        if os.name == "nt"
        else ("PATH", "HOME", "TMPDIR", "LANG", "LC_ALL")
    )
    return {key: values[key] for key in allowed if key in values}


class _BoundedCapture:
    def __init__(self, max_bytes: int):
        self.max_bytes = max_bytes
        self.lock = threading.Lock()
        self.buffers = {"stdout": bytearray(), "stderr": bytearray()}
        self.bytes_seen = {"stdout": 0, "stderr": 0}
        self.truncated = {"stdout": False, "stderr": False}
        self.stored_bytes = 0
        self.output_limit = threading.Event()
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

    def snapshot(self) -> tuple[dict[str, str], dict[str, int], dict[str, bool], str | None]:
        with self.lock:
            output = {
                name: bytes(value).decode("utf-8", errors="replace")
                for name, value in self.buffers.items()
            }
            return output, dict(self.bytes_seen), dict(self.truncated), self.read_error


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


def run_process(
    command: Sequence[str],
    *,
    cwd: str | Path,
    timeout_seconds: float,
    max_output_bytes: int,
    env: Mapping[str, str] | None = None,
    job_limits: JobLimits | None = None,
) -> ProcessResult:
    """Run a Job-contained process with bounded output and a hard timeout.

    The output limit applies to the combined captured stdout and stderr bytes.
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

    started = time.monotonic()
    process_env = dict(env) if env is not None else minimal_environment()
    try:
        process = create_job_process(
            list(command),
            cwd=str(cwd),
            env=process_env,
            limits=job_limits or DEFAULT_JOB_LIMITS,
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

    capture = _BoundedCapture(max_output_bytes)
    readers = [
        threading.Thread(target=capture.read_stream, args=(name, stream), daemon=True)
        for name, stream in (("stdout", process.stdout), ("stderr", process.stderr))
    ]
    status = ProcessStatus.EXITED
    error = None
    error_category = None
    memory_limit_hit = False
    deadline = time.monotonic() + timeout_seconds
    try:
        for reader in readers:
            reader.start()
        while process.poll() is None:
            if capture.output_limit.is_set():
                status = ProcessStatus.OUTPUT_LIMIT
                if not _terminate_and_reap(process):
                    status = ProcessStatus.START_ERROR
                    error = "Could not stop the child process after reaching the output limit."
                    error_category = "JUDGE_INFRA_ERROR"
                break
            if capture.read_error is not None:
                status = ProcessStatus.START_ERROR
                error = capture.read_error
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
            time.sleep(min(0.01, remaining))

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
                memory_limit_hit = process.memory_limit_hit()
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

    if exit_code is None:
        exit_code = process.poll()

    output, byte_counts, truncated, read_error = capture.snapshot()
    if status == ProcessStatus.EXITED and capture.output_limit.is_set():
        status = ProcessStatus.OUTPUT_LIMIT
    if status == ProcessStatus.EXITED and read_error:
        status = ProcessStatus.START_ERROR
        error = read_error
        error_category = "JUDGE_INFRA_ERROR"
    if status == ProcessStatus.EXITED and memory_limit_hit:
        status = ProcessStatus.MEMORY_LIMIT

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
    )


def _environment_value(environment: Mapping[str, str], name: str) -> str | None:
    target = name.casefold()
    for key, value in environment.items():
        if key.casefold() == target:
            return value
    return None


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


def _java_tool_environment(
    environment: Mapping[str, str], jdk_home: Path, jdk_bin: Path
) -> dict[str, str]:
    allowed = (
        ("SystemRoot", "WINDIR", "TEMP", "TMP", "PATH")
        if os.name == "nt"
        else ("PATH", "HOME", "TMPDIR", "LANG", "LC_ALL")
    )
    result = {
        name: value
        for name in allowed
        if (value := _environment_value(environment, name)) is not None
    }
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
    tool_environment = _java_tool_environment(environment, home, javac.parent)
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


def compile_java(
    source_code: str,
    *,
    source_path: str | Path = "Main.java",
    timeout_seconds: float = 20,
    max_output_bytes: int = 64 * 1024,
    env: Mapping[str, str] | None = None,
    workspace_parent: str | Path | None = None,
    job_limits: JobLimits | None = None,
) -> CompileResult:
    """Compile one Java source file in a temporary workspace and always clean it."""
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
    relative_source, expected_class_file = _validated_source_path(source_path)

    started = time.monotonic()
    environment = dict(os.environ if env is None else env)
    compiler_limits = job_limits or DEFAULT_JAVA_COMPILE_LIMITS
    workspace = None
    jdk = None
    result = None
    try:
        workspace = RunWorkspace.create(workspace_parent)
        source_file = workspace.src / relative_source
        source_file.parent.mkdir(parents=True, exist_ok=True)
        with source_file.open("w", encoding="utf-8", newline="") as stream:
            stream.write(source_code)

        jdk, tool_environment = _detect_jdk(
            environment, cwd=workspace.root, job_limits=compiler_limits
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
        result = CompileResult(
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
        result = _failed_compile_result(
            exc,
            duration_ms=max(0, int((time.monotonic() - started) * 1000)),
            run_id=workspace.run_id if workspace else None,
            expected_class_file=expected_class_file,
            jdk=jdk,
        )
    finally:
        if workspace is not None:
            try:
                workspace.cleanup()
            except Exception as exc:
                if result is None:
                    result = _failed_compile_result(
                        exc,
                        duration_ms=max(0, int((time.monotonic() - started) * 1000)),
                        run_id=workspace.run_id,
                        expected_class_file=expected_class_file,
                        jdk=jdk,
                    )
                else:
                    result = replace(
                        result,
                        status=ProcessStatus.START_ERROR,
                        success=False,
                        verdict=None,
                        error=f"Workspace cleanup failed: {type(exc).__name__}: {exc}",
                        error_category="JUDGE_INFRA_ERROR",
                    )
    if result is None:
        return _failed_compile_result(
            RuntimeError("Compilation ended without a result."),
            duration_ms=max(0, int((time.monotonic() - started) * 1000)),
            run_id=None,
            expected_class_file=expected_class_file,
        )
    return result
