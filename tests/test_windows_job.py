import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from app import windows_job
from app.java_runner import ProcessStatus, minimal_environment, run_process
from app.windows_job import JobLimits, JobObjectError, create_job_process


REPO_ROOT = Path(__file__).resolve().parents[1]


class JobLimitsValidationTests(unittest.TestCase):
    def test_limits_require_positive_integers(self):
        for value in (True, 1.5, 0, -1):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    JobLimits(active_process_limit=value)
                with self.assertRaises(ValueError):
                    JobLimits(process_memory_limit_bytes=value)
                with self.assertRaises(ValueError):
                    JobLimits(job_memory_limit_bytes=value)
        with self.assertRaises(ValueError):
            JobLimits(job_memory_limit_bytes=None)
        self.assertEqual(JobLimits().job_memory_limit_bytes, 256 * 1024 * 1024)


@unittest.skipUnless(os.name == "nt", "Windows Job Objects are only available on Windows")
class WindowsJobIntegrationTests(unittest.TestCase):
    def create_process(self, command, cwd, limits=None):
        return create_job_process(
            command,
            cwd=cwd,
            env=minimal_environment(),
            limits=limits or JobLimits(),
        )

    def assert_process_exited(self, pid: int) -> None:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        synchronize = 0x00100000
        process_handle = kernel32.OpenProcess(synchronize, False, pid)
        if not process_handle:
            self.assertEqual(ctypes.get_last_error(), 87, f"Could not inspect child process {pid}")
            return
        try:
            self.assertEqual(kernel32.WaitForSingleObject(process_handle, 2000), 0)
        finally:
            kernel32.CloseHandle(process_handle)

    def test_normal_process_is_assigned_before_it_runs(self):
        process = self.create_process(
            [sys.executable, "-c", "print('job-ok')"], REPO_ROOT
        )
        try:
            self.assertEqual(process.wait(timeout=5), 0)
            self.assertEqual(process.stdout.read(), b"job-ok\r\n")
        finally:
            process.close()

    def test_process_can_read_bounded_protocol_input_from_pipe(self):
        process = create_job_process(
            [sys.executable, "-c", "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())"],
            cwd=REPO_ROOT,
            env=minimal_environment(),
            stdin_pipe=True,
        )
        try:
            process.stdin.write(b'{"checks":[]}')
            process.stdin.close()
            self.assertEqual(process.wait(timeout=5), 0)
            self.assertEqual(process.stdout.read(), b'{"checks":[]}')
        finally:
            process.close()

    def test_dedicated_protocol_pipe_is_inherited_and_separate_from_stdio(self):
        code = (
            "import msvcrt,os,sys; "
            "handle=int.from_bytes(sys.stdin.buffer.read(8),'big'); "
            "fd=msvcrt.open_osfhandle(handle,os.O_WRONLY|os.O_BINARY); "
            "stream=os.fdopen(fd,'wb',buffering=0); stream.write(b'judge-json'); stream.close(); "
            "print('student-stdout')"
        )
        process = create_job_process(
            [sys.executable, "-c", code],
            cwd=REPO_ROOT,
            env=minimal_environment(),
            stdin_pipe=True,
            protocol_pipe=True,
        )
        try:
            handle_value = process.protocol_handle_value
            self.assertIsInstance(handle_value, int)
            process.stdin.write(handle_value.to_bytes(8, "big"))
            process.stdin.close()
            self.assertEqual(process.wait(timeout=5), 0)
            self.assertEqual(process.protocol.read(), b"judge-json")
            self.assertEqual(process.stdout.read(), b"student-stdout\r\n")
            self.assertEqual(process.stderr.read(), b"")
        finally:
            process.close()

    def test_timeout_terminates_job(self):
        result = run_process(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            cwd=REPO_ROOT,
            timeout_seconds=0.2,
            max_output_bytes=4096,
        )
        self.assertEqual(result.status, ProcessStatus.TIMEOUT)
        self.assertIsNotNone(result.exit_code)

    def test_child_process_can_run_inside_job(self):
        child_source = "print('child-finished', flush=True)"
        parent_source = (
            "import subprocess,sys; "
            "subprocess.run([sys.executable,'-c',sys.argv[1]],check=True); "
            "print('parent-finished', flush=True)"
        )
        process = self.create_process(
            [sys.executable, "-c", parent_source, child_source], REPO_ROOT
        )
        try:
            self.assertEqual(process.wait(timeout=5), 0)
            self.assertEqual(
                process.stdout.read(), b"child-finished\r\nparent-finished\r\n"
            )
        finally:
            process.close()

    def test_terminating_job_kills_entire_process_tree(self):
        parent_source = (
            "import subprocess,sys,time; "
            "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); "
            "print(child.pid, flush=True); time.sleep(30)"
        )
        process = self.create_process([sys.executable, "-c", parent_source], REPO_ROOT)
        try:
            child_pid = int(process.stdout.readline().strip())
            process.terminate()
            process.wait(timeout=3)
        finally:
            process.close()
        self.assertTrue(process._job_empty_on_close)
        self.assertTrue(process._closed and process._job_handle is None)
        self.assertIsNotNone(process.poll())
        self.assert_process_exited(child_pid)

    def test_job_close_kills_remaining_descendants(self):
        parent_source = (
            "import subprocess,sys,time; "
            "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); "
            "print(child.pid, flush=True); time.sleep(30)"
        )
        process = self.create_process([sys.executable, "-c", parent_source], REPO_ROOT)
        child_pid = int(process.stdout.readline().strip())
        process.close()
        process.close()
        self.assertTrue(process._job_empty_on_close)
        self.assertTrue(process._closed and process._job_handle is None)
        self.assertIsNotNone(process.poll())
        self.assert_process_exited(child_pid)

    def test_close_is_idempotent_and_releases_owned_handles(self):
        process = self.create_process(
            [sys.executable, "-c", "import time; time.sleep(30)"], REPO_ROOT
        )
        process.close()
        process.close()
        self.assertTrue(process._closed)
        self.assertIsNone(process._job_handle)
        self.assertIsNone(process._process_handle)
        self.assertIsNone(process._completion_port)

    def test_failed_close_retains_handle_for_retry_without_double_close(self):
        process = self.create_process([sys.executable, "-c", "pass"], REPO_ROOT)
        process.wait(timeout=5)
        job_handle = process._job_handle
        job_value = windows_job._handle_value(job_handle)
        real_close_handle = windows_job._kernel32.CloseHandle
        failed_once = False

        def fail_first_job_close(handle):
            nonlocal failed_once
            if windows_job._handle_value(handle) == job_value and not failed_once:
                failed_once = True
                return False
            return real_close_handle(handle)

        with patch(
            "app.windows_job._kernel32.CloseHandle", side_effect=fail_first_job_close
        ):
            with self.assertRaises(JobObjectError):
                process.close()
            self.assertIs(process._job_handle, job_handle)
            self.assertFalse(process._closed)
            process.close()

        self.assertIsNone(process._job_handle)
        self.assertTrue(process._closed)

    def test_process_memory_limit_is_enforced_when_supported(self):
        limits = JobLimits(
            active_process_limit=8,
            process_memory_limit_bytes=64 * 1024 * 1024,
        )
        code = (
            "chunks=[]\n"
            "try:\n"
            " while True: chunks.append(bytearray(4 * 1024 * 1024))\n"
            "except MemoryError:\n"
            " print('memory-limited', flush=True)\n"
        )
        result = run_process(
            [sys.executable, "-c", code],
            cwd=REPO_ROOT,
            timeout_seconds=10,
            max_output_bytes=4096,
            job_limits=limits,
        )
        if result.status == ProcessStatus.MEMORY_LIMIT:
            return
        if result.status != ProcessStatus.EXITED:
            self.fail(f"Job Object memory test ended with {result.status}: {result.error}")
        if "memory-limited" not in result.stdout:
            self.skipTest(f"Windows did not report the configured memory cap: {result.status}")
        self.fail(f"The process reached its memory cap but returned {result.status}")

    def test_job_memory_limit_is_enforced_when_supported(self):
        limits = JobLimits(
            active_process_limit=8,
            process_memory_limit_bytes=512 * 1024 * 1024,
            job_memory_limit_bytes=96 * 1024 * 1024,
        )
        code = (
            "chunks=[]\n"
            "try:\n"
            " while True: chunks.append(bytearray(4 * 1024 * 1024))\n"
            "except MemoryError:\n"
            " print('memory-limited', flush=True)\n"
        )
        result = run_process(
            [sys.executable, "-c", code],
            cwd=REPO_ROOT,
            timeout_seconds=10,
            max_output_bytes=4096,
            job_limits=limits,
        )
        if result.status == ProcessStatus.MEMORY_LIMIT:
            return
        if result.status != ProcessStatus.EXITED:
            self.fail(f"Job memory test ended with {result.status}: {result.error}")
        if "memory-limited" not in result.stdout:
            self.skipTest("Windows did not report the configured aggregate job memory cap")
        self.fail(f"The process reached its aggregate job memory cap but returned {result.status}")

    def test_job_memory_limit_accounts_for_multiple_child_processes(self):
        child_code = "import time; data=bytearray(48 * 1024 * 1024); time.sleep(30)"
        parent_code = (
            "import subprocess,sys,time; "
            "children=[subprocess.Popen([sys.executable,'-c',sys.argv[1]]) for _ in range(3)]; "
            "time.sleep(30)"
        )
        result = run_process(
            [sys.executable, "-c", parent_code, child_code],
            cwd=REPO_ROOT,
            timeout_seconds=15,
            max_output_bytes=4096,
            job_limits=JobLimits(
                active_process_limit=8,
                process_memory_limit_bytes=512 * 1024 * 1024,
                job_memory_limit_bytes=128 * 1024 * 1024,
            ),
        )
        self.assertEqual(result.status, ProcessStatus.MEMORY_LIMIT, result.error)

    def test_active_process_limit_is_enforced(self):
        code = (
            "import subprocess,sys\n"
            "child=[sys.executable,'-c','import time; time.sleep(5)']\n"
            "first=subprocess.Popen(child)\n"
            "try:\n"
            " second=subprocess.Popen(child)\n"
            " print('second-started', flush=True)\n"
            " second.terminate(); second.wait()\n"
            "except OSError:\n"
            " print('limit-enforced', flush=True)\n"
            "first.terminate(); first.wait()\n"
        )
        result = run_process(
            [sys.executable, "-c", code],
            cwd=REPO_ROOT,
            timeout_seconds=10,
            max_output_bytes=4096,
            job_limits=JobLimits(active_process_limit=3),
        )
        self.assertEqual(result.status, ProcessStatus.EXITED, result.error)
        self.assertIn("limit-enforced", result.stdout)

    def test_job_creation_failure_is_reported_as_infrastructure_error(self):
        with patch("app.windows_job._kernel32.CreateJobObjectW", return_value=None):
            with self.assertRaises(JobObjectError) as caught:
                self.create_process([sys.executable, "-c", "pass"], REPO_ROOT)
        self.assertEqual(caught.exception.category, "JUDGE_INFRA_ERROR")

    def test_job_configuration_failure_does_not_create_process(self):
        with patch("app.windows_job._kernel32.SetInformationJobObject", return_value=False):
            with patch("app.windows_job._kernel32.CreateProcessW") as create_process:
                with self.assertRaises(JobObjectError) as caught:
                    self.create_process([sys.executable, "-c", "pass"], REPO_ROOT)
        self.assertEqual(caught.exception.category, "JUDGE_INFRA_ERROR")
        create_process.assert_not_called()

    def test_assignment_failure_does_not_resume_unassigned_process(self):
        with patch(
            "app.windows_job._kernel32.AssignProcessToJobObject", return_value=False
        ):
            with patch("app.windows_job._kernel32.ResumeThread") as resume_thread:
                with patch(
                    "app.windows_job._kernel32.TerminateProcess",
                    wraps=windows_job._kernel32.TerminateProcess,
                ) as terminate_process:
                    with self.assertRaises(JobObjectError) as caught:
                        self.create_process([sys.executable, "-c", "pass"], REPO_ROOT)
        self.assertEqual(caught.exception.category, "JUDGE_INFRA_ERROR")
        resume_thread.assert_not_called()
        terminate_process.assert_called_once()

    def test_resume_failure_terminates_assigned_suspended_process(self):
        with patch("app.windows_job._kernel32.ResumeThread", return_value=0xFFFFFFFF) as resume:
            with patch("app.windows_job._kernel32.TerminateJobObject", wraps=
                windows_job._kernel32.TerminateJobObject
            ) as terminate_job:
                with self.assertRaises(JobObjectError):
                    self.create_process([sys.executable, "-c", "pass"], REPO_ROOT)
        resume.assert_called_once()
        terminate_job.assert_called_once()


if __name__ == "__main__":
    unittest.main()
