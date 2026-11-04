"""Fail-closed Windows process creation and Job Object lifecycle."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import math
import os
from pathlib import Path
import shutil
import subprocess
from typing import Mapping, Sequence


class JobObjectError(OSError):
    """A Windows process/job operation failed and must not be bypassed."""

    category = "JUDGE_INFRA_ERROR"


@dataclass(frozen=True)
class JobLimits:
    """Per-run Job Object limits; values are configurable by the trusted caller."""

    active_process_limit: int = 16
    process_memory_limit_bytes: int = 256 * 1024 * 1024

    def __post_init__(self) -> None:
        if self.active_process_limit < 1:
            raise ValueError("active_process_limit must be at least 1")
        if self.process_memory_limit_bytes < 1:
            raise ValueError("process_memory_limit_bytes must be positive")


DEFAULT_JOB_LIMITS = JobLimits()

_CREATE_SUSPENDED = 0x00000004
_CREATE_UNICODE_ENVIRONMENT = 0x00000400
_EXTENDED_STARTUPINFO_PRESENT = 0x00080000
_STARTF_USESTDHANDLES = 0x00000100
_HANDLE_FLAG_INHERIT = 0x00000001
_GENERIC_READ = 0x80000000
_FILE_SHARE_READ = 0x00000001
_FILE_SHARE_WRITE = 0x00000002
_OPEN_EXISTING = 3
_FILE_ATTRIBUTE_NORMAL = 0x00000080
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_JOB_OBJECT_ASSOCIATE_COMPLETION_PORT_INFORMATION = 7
_JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x00000008
_JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_PROC_THREAD_ATTRIBUTE_HANDLE_LIST = 0x00020002
_WAIT_OBJECT_0 = 0x00000000
_WAIT_TIMEOUT = 0x00000102
_WAIT_FAILED = 0xFFFFFFFF
_ERROR_TIMEOUT = 258
_INFINITE = 0xFFFFFFFF
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
_JOB_OBJECT_MSG_PROCESS_MEMORY_LIMIT = 9


if os.name == "nt":
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class _SecurityAttributes(ctypes.Structure):
        _fields_ = [
            ("nLength", wintypes.DWORD),
            ("lpSecurityDescriptor", wintypes.LPVOID),
            ("bInheritHandle", wintypes.BOOL),
        ]

    class _IoCounters(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class _BasicLimitInformation(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _ExtendedLimitInformation(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _BasicLimitInformation),
            ("IoInfo", _IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    class _StartupInfoW(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("lpReserved", wintypes.LPWSTR),
            ("lpDesktop", wintypes.LPWSTR),
            ("lpTitle", wintypes.LPWSTR),
            ("dwX", wintypes.DWORD),
            ("dwY", wintypes.DWORD),
            ("dwXSize", wintypes.DWORD),
            ("dwYSize", wintypes.DWORD),
            ("dwXCountChars", wintypes.DWORD),
            ("dwYCountChars", wintypes.DWORD),
            ("dwFillAttribute", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("wShowWindow", wintypes.WORD),
            ("cbReserved2", wintypes.WORD),
            ("lpReserved2", ctypes.POINTER(ctypes.c_byte)),
            ("hStdInput", wintypes.HANDLE),
            ("hStdOutput", wintypes.HANDLE),
            ("hStdError", wintypes.HANDLE),
        ]

    class _StartupInfoExW(ctypes.Structure):
        _fields_ = [
            ("StartupInfo", _StartupInfoW),
            ("lpAttributeList", wintypes.LPVOID),
        ]

    class _ProcessInformation(ctypes.Structure):
        _fields_ = [
            ("hProcess", wintypes.HANDLE),
            ("hThread", wintypes.HANDLE),
            ("dwProcessId", wintypes.DWORD),
            ("dwThreadId", wintypes.DWORD),
        ]

    class _JobObjectAssociateCompletionPort(ctypes.Structure):
        _fields_ = [
            ("CompletionKey", wintypes.LPVOID),
            ("CompletionPort", wintypes.HANDLE),
        ]

    _kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    _kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    _kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    _kernel32.SetInformationJobObject.restype = wintypes.BOOL
    _kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    _kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _kernel32.TerminateJobObject.restype = wintypes.BOOL
    _kernel32.CreatePipe.argtypes = [
        ctypes.POINTER(wintypes.HANDLE),
        ctypes.POINTER(wintypes.HANDLE),
        ctypes.POINTER(_SecurityAttributes),
        wintypes.DWORD,
    ]
    _kernel32.CreatePipe.restype = wintypes.BOOL
    _kernel32.SetHandleInformation.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD]
    _kernel32.SetHandleInformation.restype = wintypes.BOOL
    _kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(_SecurityAttributes),
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    _kernel32.CreateFileW.restype = wintypes.HANDLE
    _kernel32.InitializeProcThreadAttributeList.argtypes = [
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    _kernel32.InitializeProcThreadAttributeList.restype = wintypes.BOOL
    _kernel32.UpdateProcThreadAttribute.argtypes = [
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.c_size_t,
        wintypes.LPVOID,
        ctypes.c_size_t,
        wintypes.LPVOID,
        wintypes.LPVOID,
    ]
    _kernel32.UpdateProcThreadAttribute.restype = wintypes.BOOL
    _kernel32.DeleteProcThreadAttributeList.argtypes = [wintypes.LPVOID]
    _kernel32.DeleteProcThreadAttributeList.restype = None
    _kernel32.CreateProcessW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.LPWSTR,
        wintypes.LPVOID,
        wintypes.LPVOID,
        wintypes.BOOL,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.LPCWSTR,
        ctypes.POINTER(_StartupInfoExW),
        ctypes.POINTER(_ProcessInformation),
    ]
    _kernel32.CreateProcessW.restype = wintypes.BOOL
    _kernel32.ResumeThread.argtypes = [wintypes.HANDLE]
    _kernel32.ResumeThread.restype = wintypes.DWORD
    _kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    _kernel32.WaitForSingleObject.restype = wintypes.DWORD
    _kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    _kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    _kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _kernel32.TerminateProcess.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.CloseHandle.restype = wintypes.BOOL
    _kernel32.CreateIoCompletionPort.argtypes = [
        wintypes.HANDLE,
        wintypes.HANDLE,
        ctypes.c_size_t,
        wintypes.DWORD,
    ]
    _kernel32.CreateIoCompletionPort.restype = wintypes.HANDLE
    _kernel32.GetQueuedCompletionStatus.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(ctypes.c_size_t),
        ctypes.POINTER(wintypes.LPVOID),
        wintypes.DWORD,
    ]
    _kernel32.GetQueuedCompletionStatus.restype = wintypes.BOOL


def _error_message(action: str) -> str:
    code = ctypes.get_last_error() if os.name == "nt" else 0
    detail = ctypes.FormatError(code).strip() if code else "Windows API call failed"
    return f"{action} failed (Windows error {code}: {detail})"


def _handle_value(handle) -> int | None:
    if handle is None:
        return None
    return handle if isinstance(handle, int) else handle.value


def _close_handle(handle) -> None:
    if os.name == "nt" and _handle_value(handle) not in (None, 0, _INVALID_HANDLE_VALUE):
        _kernel32.CloseHandle(handle)


def _check_win32(ok: bool, action: str) -> None:
    if not ok:
        raise JobObjectError(_error_message(action))


def _configure_job(job_handle, limits: JobLimits) -> None:
    info = _ExtendedLimitInformation()
    info.BasicLimitInformation.LimitFlags = (
        _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        | _JOB_OBJECT_LIMIT_ACTIVE_PROCESS
        | _JOB_OBJECT_LIMIT_PROCESS_MEMORY
    )
    info.BasicLimitInformation.ActiveProcessLimit = limits.active_process_limit
    info.ProcessMemoryLimit = limits.process_memory_limit_bytes
    _check_win32(
        _kernel32.SetInformationJobObject(
            job_handle,
            _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(info),
            ctypes.sizeof(info),
        ),
        "SetInformationJobObject",
    )


def _associate_completion_port(job_handle, completion_port) -> None:
    association = _JobObjectAssociateCompletionPort()
    association.CompletionKey = 1
    association.CompletionPort = completion_port
    _check_win32(
        _kernel32.SetInformationJobObject(
            job_handle,
            _JOB_OBJECT_ASSOCIATE_COMPLETION_PORT_INFORMATION,
            ctypes.byref(association),
            ctypes.sizeof(association),
        ),
        "SetInformationJobObject(completion port)",
    )


def _make_pipe():
    security = _SecurityAttributes()
    security.nLength = ctypes.sizeof(security)
    security.bInheritHandle = True
    read_handle = wintypes.HANDLE()
    write_handle = wintypes.HANDLE()
    _check_win32(
        _kernel32.CreatePipe(
            ctypes.byref(read_handle), ctypes.byref(write_handle), ctypes.byref(security), 0
        ),
        "CreatePipe",
    )
    fd = None
    try:
        _check_win32(
            _kernel32.SetHandleInformation(read_handle, _HANDLE_FLAG_INHERIT, 0),
            "SetHandleInformation",
        )
        import msvcrt

        fd = msvcrt.open_osfhandle(
            int(_handle_value(read_handle)), os.O_RDONLY | os.O_BINARY
        )
        read_handle.value = None
        stream = os.fdopen(fd, "rb", buffering=0)
        fd = None
        return stream, write_handle
    except Exception:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        _close_handle(read_handle)
        _close_handle(write_handle)
        raise


def _create_stdin_handle():
    security = _SecurityAttributes()
    security.nLength = ctypes.sizeof(security)
    security.bInheritHandle = True
    handle = _kernel32.CreateFileW(
        "NUL",
        _GENERIC_READ,
        _FILE_SHARE_READ | _FILE_SHARE_WRITE,
        ctypes.byref(security),
        _OPEN_EXISTING,
        _FILE_ATTRIBUTE_NORMAL,
        None,
    )
    if _handle_value(handle) in (None, 0, _INVALID_HANDLE_VALUE):
        raise JobObjectError(_error_message("CreateFileW(NUL)"))
    return handle


def _create_attribute_list(handles):
    size = ctypes.c_size_t()
    _kernel32.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size))
    if size.value <= 0:
        raise JobObjectError(_error_message("InitializeProcThreadAttributeList(size)"))
    buffer = ctypes.create_string_buffer(size.value)
    pointer = ctypes.cast(buffer, wintypes.LPVOID)
    _check_win32(
        _kernel32.InitializeProcThreadAttributeList(pointer, 1, 0, ctypes.byref(size)),
        "InitializeProcThreadAttributeList",
    )
    handle_array = (wintypes.HANDLE * len(handles))(*handles)
    try:
        _check_win32(
            _kernel32.UpdateProcThreadAttribute(
                pointer,
                0,
                _PROC_THREAD_ATTRIBUTE_HANDLE_LIST,
                ctypes.cast(handle_array, wintypes.LPVOID),
                ctypes.sizeof(handle_array),
                None,
                None,
            ),
            "UpdateProcThreadAttribute(handle list)",
        )
    except Exception:
        _kernel32.DeleteProcThreadAttributeList(pointer)
        raise
    return buffer, pointer


class WindowsJobProcess:
    """A process assigned to a Job before its primary thread is resumed."""

    def __init__(
        self, args, process_handle, job_handle, completion_port, pid, stdout, stderr, limits
    ):
        self.args = list(args)
        self._process_handle = process_handle
        self._job_handle = job_handle
        self._completion_port = completion_port
        self.pid = pid
        self.stdout = stdout
        self.stderr = stderr
        self.limits = limits
        self.returncode: int | None = None
        self._closed = False

    def poll(self) -> int | None:
        if self.returncode is not None:
            return self.returncode
        if self._process_handle is None:
            return self.returncode
        result = _kernel32.WaitForSingleObject(self._process_handle, 0)
        if result == _WAIT_TIMEOUT:
            return None
        if result == _WAIT_FAILED:
            raise JobObjectError(_error_message("WaitForSingleObject"))
        if result != _WAIT_OBJECT_0:
            raise JobObjectError(f"Unexpected wait result: {result}")
        code = wintypes.DWORD()
        _check_win32(
            _kernel32.GetExitCodeProcess(self._process_handle, ctypes.byref(code)),
            "GetExitCodeProcess",
        )
        self.returncode = int(code.value)
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        if self.returncode is not None:
            return self.returncode
        milliseconds = _INFINITE if timeout is None else min(
            max(0, math.ceil(timeout * 1000)), _INFINITE - 1
        )
        result = _kernel32.WaitForSingleObject(self._process_handle, milliseconds)
        if result == _WAIT_TIMEOUT:
            raise subprocess.TimeoutExpired(self.args, timeout)
        if result == _WAIT_FAILED:
            raise JobObjectError(_error_message("WaitForSingleObject"))
        if result != _WAIT_OBJECT_0:
            raise JobObjectError(f"Unexpected wait result: {result}")
        return self.poll()

    def terminate(self) -> None:
        if self._job_handle is None:
            return
        _check_win32(
            _kernel32.TerminateJobObject(self._job_handle, 1), "TerminateJobObject"
        )

    def kill(self) -> None:
        self.terminate()

    def memory_limit_hit(self) -> bool:
        if self._job_handle is None or self.limits.process_memory_limit_bytes <= 0:
            return False
        while True:
            message = wintypes.DWORD()
            completion_key = ctypes.c_size_t()
            overlapped = wintypes.LPVOID()
            received = _kernel32.GetQueuedCompletionStatus(
                self._completion_port,
                ctypes.byref(message),
                ctypes.byref(completion_key),
                ctypes.byref(overlapped),
                0,
            )
            if not received:
                error = ctypes.get_last_error()
                if error == _ERROR_TIMEOUT:
                    return False
                raise JobObjectError(_error_message("GetQueuedCompletionStatus"))
            if message.value == _JOB_OBJECT_MSG_PROCESS_MEMORY_LIMIT:
                return True

    def close(self) -> None:
        if self._closed:
            return
        failure = None
        if self._job_handle is not None:
            if not _kernel32.CloseHandle(self._job_handle):
                failure = _error_message("CloseHandle(Job Object)")
                try:
                    _check_win32(
                        _kernel32.TerminateJobObject(self._job_handle, 1),
                        "TerminateJobObject during cleanup",
                    )
                except JobObjectError as exc:
                    failure += f"; {exc}"
                if not _kernel32.CloseHandle(self._job_handle):
                    failure += f"; {_error_message('CloseHandle(Job Object) during cleanup')}"
            self._job_handle = None

        if self._process_handle is not None:
            wait_result = _kernel32.WaitForSingleObject(self._process_handle, 2000)
            if wait_result == _WAIT_TIMEOUT:
                if not _kernel32.TerminateProcess(self._process_handle, 1):
                    failure = failure or _error_message("TerminateProcess after job close")
                wait_result = _kernel32.WaitForSingleObject(self._process_handle, 2000)
            if wait_result != _WAIT_OBJECT_0:
                if wait_result == _WAIT_FAILED:
                    failure = failure or _error_message("WaitForSingleObject after job close")
                else:
                    failure = failure or "Process remained active after job close and termination."
            if not _kernel32.CloseHandle(self._process_handle):
                failure = failure or _error_message("CloseHandle(Process)")
            self._process_handle = None
        if self._completion_port is not None:
            if not _kernel32.CloseHandle(self._completion_port):
                failure = failure or _error_message("CloseHandle(completion port)")
            self._completion_port = None
        for stream in (self.stdout, self.stderr):
            try:
                stream.close()
            except OSError as exc:
                failure = failure or f"Could not close process output stream: {exc}"
        self._closed = True
        if failure:
            raise JobObjectError(failure)


def create_job_process(
    command: Sequence[str],
    *,
    cwd: str | Path,
    env: Mapping[str, str],
    limits: JobLimits = DEFAULT_JOB_LIMITS,
) -> WindowsJobProcess:
    """Create suspended, assign to a configured Job, then resume the primary thread."""
    if os.name != "nt":
        raise JobObjectError("Windows Job Objects are only available on Windows.")
    if not command or any(not isinstance(arg, str) for arg in command):
        raise ValueError("command must be a non-empty sequence of strings")
    limits = limits or DEFAULT_JOB_LIMITS

    environment = dict(env)
    if any("\0" in key or "\0" in value or "=" in key for key, value in environment.items()):
        raise ValueError("Environment keys and values must not contain NUL or '=' in keys")
    executable = shutil.which(command[0], path=environment.get("PATH"))
    if executable is None:
        if Path(command[0]).is_absolute() and Path(command[0]).is_file():
            executable = command[0]
        else:
            raise JobObjectError(f"Executable not found: {command[0]}")

    job_handle = None
    completion_port = None
    process_info = _ProcessInformation()
    stdout_stream = stderr_stream = None
    stdout_writer = stderr_writer = stdin_handle = None
    attribute_pointer = None
    assigned = False
    transferred = False
    try:
        job_handle = _kernel32.CreateJobObjectW(None, None)
        if _handle_value(job_handle) in (None, 0):
            raise JobObjectError(_error_message("CreateJobObjectW"))
        _configure_job(job_handle, limits)
        completion_port = _kernel32.CreateIoCompletionPort(
            _INVALID_HANDLE_VALUE, None, 0, 1
        )
        if _handle_value(completion_port) in (None, 0, _INVALID_HANDLE_VALUE):
            raise JobObjectError(_error_message("CreateIoCompletionPort"))
        _associate_completion_port(job_handle, completion_port)

        stdout_stream, stdout_writer = _make_pipe()
        stderr_stream, stderr_writer = _make_pipe()
        stdin_handle = _create_stdin_handle()
        attribute_buffer, attribute_pointer = _create_attribute_list(
            [stdin_handle, stdout_writer, stderr_writer]
        )

        startup = _StartupInfoExW()
        startup.StartupInfo.cb = ctypes.sizeof(_StartupInfoExW)
        startup.StartupInfo.dwFlags = _STARTF_USESTDHANDLES
        startup.StartupInfo.hStdInput = stdin_handle
        startup.StartupInfo.hStdOutput = stdout_writer
        startup.StartupInfo.hStdError = stderr_writer
        startup.lpAttributeList = attribute_pointer

        command_line = ctypes.create_unicode_buffer(
            subprocess.list2cmdline([executable, *command[1:]])
        )
        environment_block = "\0".join(
            f"{key}={value}" for key, value in sorted(environment.items(), key=lambda pair: pair[0].casefold())
        ) + "\0\0"
        environment_buffer = ctypes.create_unicode_buffer(environment_block)
        process_cwd = str(Path(cwd).resolve())

        _check_win32(
            _kernel32.CreateProcessW(
                executable,
                command_line,
                None,
                None,
                True,
                _CREATE_SUSPENDED | _CREATE_UNICODE_ENVIRONMENT | _EXTENDED_STARTUPINFO_PRESENT,
                ctypes.cast(environment_buffer, wintypes.LPVOID),
                process_cwd,
                ctypes.byref(startup),
                ctypes.byref(process_info),
            ),
            "CreateProcessW(suspended)",
        )

        _check_win32(
            _kernel32.AssignProcessToJobObject(job_handle, process_info.hProcess),
            "AssignProcessToJobObject",
        )
        assigned = True
        resume_result = _kernel32.ResumeThread(process_info.hThread)
        if resume_result == 0xFFFFFFFF:
            raise JobObjectError(_error_message("ResumeThread"))

        _close_handle(process_info.hThread)
        process_info.hThread = None
        process = WindowsJobProcess(
            command,
            process_info.hProcess,
            job_handle,
            completion_port,
            int(process_info.dwProcessId),
            stdout_stream,
            stderr_stream,
            limits,
        )
        process_info.hProcess = None
        job_handle = None
        completion_port = None
        stdout_stream = stderr_stream = None
        transferred = True
        return process
    except JobObjectError:
        raise
    except Exception as exc:
        raise JobObjectError(f"Windows Job Object process setup failed: {exc}") from exc
    finally:
        if attribute_pointer is not None:
            _kernel32.DeleteProcThreadAttributeList(attribute_pointer)
        _close_handle(stdout_writer)
        _close_handle(stderr_writer)
        _close_handle(stdin_handle)
        _close_handle(process_info.hThread)
        if not transferred:
            if process_info.hProcess:
                if assigned and job_handle:
                    _kernel32.TerminateJobObject(job_handle, 1)
                else:
                    _kernel32.TerminateProcess(process_info.hProcess, 1)
                _kernel32.WaitForSingleObject(process_info.hProcess, 1000)
            _close_handle(process_info.hProcess)
            _close_handle(job_handle)
            _close_handle(completion_port)
            if stdout_stream:
                stdout_stream.close()
            if stderr_stream:
                stderr_stream.close()
