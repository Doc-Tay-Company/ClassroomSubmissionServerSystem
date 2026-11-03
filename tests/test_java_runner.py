from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from app.java_runner import (
    ProcessStatus,
    ProcessResult,
    RunWorkspace,
    _resolve_jdk_paths,
    compile_java,
    minimal_environment,
    run_process,
)
from app.windows_job import JobObjectError


REPO_ROOT = Path(__file__).resolve().parents[1]


def python_command(code: str) -> list[str]:
    return [sys.executable, "-c", code]


class RunWorkspaceTests(unittest.TestCase):
    def test_workspace_has_unique_run_layout_and_cleans_up(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            first = RunWorkspace.create(temp_dir)
            second = RunWorkspace.create(temp_dir)
            try:
                self.assertNotEqual(first.run_id, second.run_id)
                self.assertEqual(first.root.name, f"run_{first.run_id}")
                for directory in (first.src, first.out, first.input, first.result):
                    self.assertTrue(directory.is_dir())
                self.assertNotEqual(first.root, second.root)
            finally:
                first.cleanup()
                second.cleanup()
            self.assertFalse(first.root.exists())
            self.assertFalse(second.root.exists())

    def test_workspace_cleans_up_when_context_body_raises(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = None
            with self.assertRaisesRegex(RuntimeError, "expected"):
                with RunWorkspace.create(temp_dir) as workspace:
                    raise RuntimeError("expected")
            self.assertIsNotNone(workspace)
            self.assertFalse(workspace.root.exists())


class JobFailureTests(unittest.TestCase):
    def test_job_failure_returns_infrastructure_error_without_popen_fallback(self):
        with patch(
            "app.java_runner.create_job_process",
            side_effect=JobObjectError("CreateJobObjectW failed"),
        ):
            with patch("app.java_runner.subprocess.Popen") as unrestricted_fallback:
                result = run_process(
                    python_command("pass"),
                    cwd=REPO_ROOT,
                    timeout_seconds=1,
                    max_output_bytes=1024,
                )
        self.assertEqual(result.status, ProcessStatus.START_ERROR)
        self.assertEqual(result.error_category, "JUDGE_INFRA_ERROR")
        unrestricted_fallback.assert_not_called()


@unittest.skipUnless(os.name == "nt", "Windows Job Objects are required for process tests")
class ProcessRunnerTests(unittest.TestCase):
    def execute(self, code: str, **kwargs):
        options = {"cwd": REPO_ROOT, "timeout_seconds": 3, "max_output_bytes": 65536}
        options.update(kwargs)
        return run_process(python_command(code), **options)

    def test_exit_zero(self):
        result = self.execute("pass")
        self.assertEqual(result.status, ProcessStatus.EXITED)
        self.assertEqual(result.exit_code, 0)

    def test_exit_non_zero_is_still_exited(self):
        result = self.execute("raise SystemExit(7)")
        self.assertEqual(result.status, ProcessStatus.EXITED)
        self.assertEqual(result.exit_code, 7)

    def test_timeout_terminates_direct_child(self):
        result = self.execute("import time; time.sleep(30)", timeout_seconds=0.15)
        self.assertEqual(result.status, ProcessStatus.TIMEOUT)
        self.assertIsNotNone(result.exit_code)
        self.assertLess(result.duration_ms, 3000)

    def test_captures_stdout(self):
        result = self.execute("print('out')")
        self.assertEqual(result.stdout, "out\r\n")
        self.assertEqual(result.stderr, "")
        self.assertEqual(result.stdout_bytes, 5)

    def test_captures_stderr(self):
        result = self.execute("import sys; print('err', file=sys.stderr)")
        self.assertEqual(result.stderr, "err\r\n")
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr_bytes, 5)

    def test_large_output_is_bounded_and_stops_process(self):
        result = self.execute(
            "import os; os.write(1, b'x' * 1000000)",
            max_output_bytes=2048,
        )
        self.assertEqual(result.status, ProcessStatus.OUTPUT_LIMIT)
        self.assertLessEqual(len(result.stdout.encode("utf-8")), 2048)
        self.assertLessEqual(
            len(result.stdout.encode("utf-8")) + len(result.stderr.encode("utf-8")),
            2048,
        )
        self.assertTrue(result.stdout_truncated)
        self.assertGreater(result.stdout_bytes, len(result.stdout.encode("utf-8")))

    def test_spawn_exception_returns_start_error(self):
        with patch("app.java_runner.create_job_process", side_effect=OSError("spawn failed")):
            result = self.execute("pass")
        self.assertEqual(result.status, ProcessStatus.START_ERROR)
        self.assertIsNone(result.exit_code)
        self.assertEqual(result.error_category, "JUDGE_INFRA_ERROR")
        self.assertIn("spawn failed", result.error)

    def test_reader_start_exception_terminates_started_child(self):
        with patch("app.java_runner.threading.Thread.start", side_effect=RuntimeError("reader failed")):
            result = self.execute("import time; time.sleep(30)")
        self.assertEqual(result.status, ProcessStatus.START_ERROR)
        self.assertIsNotNone(result.exit_code)
        self.assertIn("reader failed", result.error)

    def test_server_process_survives_failing_child(self):
        script = (
            "from app.java_runner import run_process; "
            "import sys; "
            "r=run_process([sys.executable, '-c', 'raise SystemExit(9)'], "
            "cwd=r'" + str(REPO_ROOT) + "', timeout_seconds=2, max_output_bytes=1024); "
            "print(r.status.value, r.exit_code)"
        )
        server = subprocess.run(
            python_command(script),
            cwd=REPO_ROOT,
            env=minimal_environment(),
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        self.assertEqual(server.returncode, 0, server.stderr)
        self.assertIn("EXITED 9", server.stdout)


@unittest.skipUnless(os.name == "nt", "Java compilation uses the Windows Job Object runner")
class JavaCompileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            _resolve_jdk_paths(os.environ)
        except OSError as exc:
            raise unittest.SkipTest(f"No configured JDK is available: {exc}") from exc

    def test_correct_java_compiles_and_reports_expected_class(self):
        source = "public class Hello { public static void main(String[] args) {} }"
        actual_run_process = run_process
        commands = []

        def capture_command(command, **kwargs):
            commands.append(list(command))
            return actual_run_process(command, **kwargs)

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("app.java_runner.run_process", side_effect=capture_command):
                result = compile_java(
                    source,
                    source_path="Hello.java",
                    workspace_parent=temp_dir,
                )
            self.assertTrue(result.success, result.stderr or result.error)
            self.assertEqual(result.status, ProcessStatus.EXITED)
            self.assertIsNone(result.verdict)
            self.assertEqual(result.expected_class_file, "Hello.class")
            self.assertTrue(result.expected_class_file_exists)
            self.assertIsNotNone(result.jdk)
            self.assertTrue(Path(result.jdk.javac).is_absolute())
            compile_commands = [command for command in commands if "-encoding" in command]
            self.assertEqual(len(compile_commands), 1)
            self.assertEqual(compile_commands[0][1:4], ["-encoding", "UTF-8", "-proc:none"])
            self.assertEqual(list(Path(temp_dir).iterdir()), [])

    def test_java_syntax_error_is_compile_error_ce(self):
        result = compile_java(
            "public class Broken { public void f( }",
            source_path="Broken.java",
        )
        self.assertFalse(result.success)
        self.assertEqual(result.status, ProcessStatus.EXITED)
        self.assertEqual(result.verdict, "CE")
        self.assertIsNone(result.error_category)
        self.assertNotEqual(result.exit_code, 0)
        self.assertTrue(result.stderr or result.stdout)

    def test_package_source_is_written_and_compiled_to_package_output(self):
        result = compile_java(
            "package model; public class Student { public int value() { return 7; } }",
            source_path="model/Student.java",
        )
        self.assertTrue(result.success, result.stderr or result.error)
        self.assertEqual(result.expected_class_file, "model/Student.class")
        self.assertTrue(result.expected_class_file_exists)

    def test_wrong_package_does_not_claim_expected_class_was_created(self):
        result = compile_java(
            "package other; public class Student {}",
            source_path="model/Student.java",
        )
        self.assertFalse(result.success)
        self.assertEqual(result.status, ProcessStatus.EXITED)
        self.assertIsNone(result.verdict)
        self.assertFalse(result.expected_class_file_exists)
        self.assertIn("package declaration", result.error)

    def test_utf8_source_compiles(self):
        result = compile_java(
            'public class Utf8 { public String text() { return "Tiếng Việt"; } }',
            source_path="Utf8.java",
        )
        self.assertTrue(result.success, result.stderr or result.error)
        self.assertTrue(result.expected_class_file_exists)

    def test_compile_timeout_is_preserved(self):
        actual_run_process = run_process

        def timeout_javac(command, **kwargs):
            if "-encoding" in command:
                return ProcessResult(
                    status=ProcessStatus.TIMEOUT,
                    exit_code=None,
                    duration_ms=int(kwargs["timeout_seconds"] * 1000),
                    stdout="",
                    stderr="",
                    stdout_bytes=0,
                    stderr_bytes=0,
                    stdout_truncated=False,
                    stderr_truncated=False,
                )
            return actual_run_process(command, **kwargs)

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("app.java_runner.run_process", side_effect=timeout_javac):
                result = compile_java(
                    "public class Slow {}",
                    source_path="Slow.java",
                    timeout_seconds=0.25,
                    workspace_parent=temp_dir,
                )
            self.assertEqual(result.status, ProcessStatus.TIMEOUT)
            self.assertFalse(result.success)
            self.assertIsNone(result.verdict)
            self.assertIn("compile timeout", result.error)
            self.assertEqual(list(Path(temp_dir).iterdir()), [])


@unittest.skipUnless(os.name == "nt", "Java toolchain detection is Windows-specific")
class MissingJDKTests(unittest.TestCase):
    def test_missing_jdk_is_reported_without_path_fallback(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = compile_java(
                "public class Missing {}",
                source_path="Missing.java",
                env={},
                workspace_parent=temp_dir,
            )
            self.assertEqual(result.status, ProcessStatus.START_ERROR)
            self.assertEqual(result.error_category, "JDK_NOT_FOUND")
            self.assertIsNone(result.jdk)
            self.assertEqual(list(Path(temp_dir).iterdir()), [])

    def test_invalid_java_home_does_not_fall_back_to_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            environment = {"JAVA_HOME": temp_dir, "PATH": os.environ.get("PATH", "")}
            result = compile_java(
                "public class InvalidHome {}",
                source_path="InvalidHome.java",
                env=environment,
            )
            self.assertEqual(result.status, ProcessStatus.START_ERROR)
            self.assertEqual(result.error_category, "JDK_NOT_FOUND")


if __name__ == "__main__":
    unittest.main()
