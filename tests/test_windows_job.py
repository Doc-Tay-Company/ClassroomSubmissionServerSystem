import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from app.java_runner import ProcessStatus, minimal_environment, run_process
from app.windows_job import JobLimits, JobObjectError, create_job_process


REPO_ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == "nt", "Windows Job Objects are only available on Windows")
class WindowsJobIntegrationTests(unittest.TestCase):
    def create_process(self, command, cwd, limits=None):
        return create_job_process(
            command,
            cwd=cwd,
            env=minimal_environment(),
            limits=limits or JobLimits(),
        )

    def wait_for_file(self, path: Path, timeout: float = 5.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if path.exists():
                return
            time.sleep(0.02)
        self.fail(f"Timed out waiting for {path.name}")

    def test_normal_process_is_assigned_before_it_runs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            process = self.create_process(
                [sys.executable, "-c", "print('job-ok')"], temp_dir
            )
            try:
                self.assertEqual(process.wait(timeout=5), 0)
                self.assertEqual(process.stdout.read(), b"job-ok\r\n")
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
        with tempfile.TemporaryDirectory() as temp_dir:
            marker = Path(temp_dir) / "child-finished.txt"
            child_source = "import pathlib,sys; pathlib.Path(sys.argv[1]).write_text('ok')"
            parent_source = (
                "import subprocess,sys; "
                "subprocess.run([sys.executable,'-c',sys.argv[1],sys.argv[2]],check=True); "
                "print('child-finished')"
            )
            process = self.create_process(
                [sys.executable, "-c", parent_source, child_source, str(marker)], temp_dir
            )
            try:
                self.assertEqual(process.wait(timeout=5), 0)
                self.assertTrue(marker.is_file())
                self.assertEqual(process.stdout.read(), b"child-finished\r\n")
            finally:
                process.close()

    def test_terminating_job_kills_entire_process_tree(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            ready = Path(temp_dir) / "child-ready.txt"
            marker = Path(temp_dir) / "child-survived.txt"
            child_source = (
                "import pathlib,sys,time; time.sleep(1); "
                "pathlib.Path(sys.argv[1]).write_text('survived')"
            )
            parent_source = (
                "import pathlib,subprocess,sys,time; "
                "subprocess.Popen([sys.executable,'-c',sys.argv[1],sys.argv[2]]); "
                "pathlib.Path(sys.argv[3]).write_text('ready'); time.sleep(30)"
            )
            process = self.create_process(
                [sys.executable, "-c", parent_source, child_source, str(marker), str(ready)],
                temp_dir,
            )
            try:
                self.wait_for_file(ready)
                process.terminate()
                process.wait(timeout=3)
            finally:
                process.close()
            time.sleep(1.2)
            self.assertFalse(marker.exists())

    def test_job_close_kills_remaining_descendants(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            ready = Path(temp_dir) / "child-ready.txt"
            marker = Path(temp_dir) / "child-survived.txt"
            child_source = (
                "import pathlib,sys,time; time.sleep(1); "
                "pathlib.Path(sys.argv[1]).write_text('survived')"
            )
            parent_source = (
                "import pathlib,subprocess,sys,time; "
                "subprocess.Popen([sys.executable,'-c',sys.argv[1],sys.argv[2]]); "
                "pathlib.Path(sys.argv[3]).write_text('ready'); time.sleep(30)"
            )
            process = self.create_process(
                [sys.executable, "-c", parent_source, child_source, str(marker), str(ready)],
                temp_dir,
            )
            self.wait_for_file(ready)
            process.close()
            time.sleep(1.2)
            self.assertFalse(marker.exists())

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

    def test_job_creation_failure_is_reported_as_infrastructure_error(self):
        with patch("app.windows_job._kernel32.CreateJobObjectW", return_value=None):
            with self.assertRaises(JobObjectError) as caught:
                self.create_process([sys.executable, "-c", "pass"], REPO_ROOT)
        self.assertEqual(caught.exception.category, "JUDGE_INFRA_ERROR")

    def test_assignment_failure_does_not_resume_unassigned_process(self):
        with patch(
            "app.windows_job._kernel32.AssignProcessToJobObject", return_value=False
        ):
            with patch("app.windows_job._kernel32.ResumeThread") as resume_thread:
                with self.assertRaises(JobObjectError) as caught:
                    self.create_process([sys.executable, "-c", "pass"], REPO_ROOT)
        self.assertEqual(caught.exception.category, "JUDGE_INFRA_ERROR")
        resume_thread.assert_not_called()


if __name__ == "__main__":
    unittest.main()
