from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from app.java_runner import (
    ProcessStatus,
    ProcessResult,
    JDKConfig,
    JDKConfigurationError,
    JDKNotFoundError,
    RunWorkspace,
    _resolve_jdk_paths,
    classify_judge_process_result,
    compile_java,
    is_java_identifier,
    java_heap_limit_mb,
    java_process_environment,
    minimal_environment,
    run_reflection_judge,
    run_process,
    verify_jdk_configuration,
)
from app.code_runner import run_stdio
from app.windows_job import JobLimits, JobObjectError, create_job_process


REPO_ROOT = Path(__file__).resolve().parents[1]


class JavaIdentifierTests(unittest.TestCase):
    def test_classroom_identifier_subset(self):
        for value in ("Student", "_Student", "$Student", "MônHọc"):
            with self.subTest(value=value):
                self.assertTrue(is_java_identifier(value))
        for value in ("", "_", "class", "1Student", "Name\u200c"):
            with self.subTest(value=value):
                self.assertFalse(is_java_identifier(value))


class JavaEnvironmentTests(unittest.TestCase):
    def test_startup_jdk_check_rejects_missing_toolchain(self):
        with self.assertRaises((JDKConfigurationError, JDKNotFoundError)):
            verify_jdk_configuration({})

    def test_tool_and_runtime_share_minimal_java_environment_builder(self):
        source = {
            "SystemRoot": "C:\\Windows",
            "WINDIR": "C:\\Windows",
            "TEMP": "C:\\Temp",
            "TMP": "C:\\Temp",
            "PATH": "existing-path",
            "JAVA_HOME": "untrusted-old-jdk",
            "PROJECT_SECRET": "not-for-student-processes",
        }
        environment = java_process_environment(
            source, Path("selected-jdk"), Path("selected-jdk") / "bin"
        )
        self.assertEqual(environment["JAVA_HOME"], "selected-jdk")
        self.assertEqual(
            environment["PATH"],
            f"{Path('selected-jdk') / 'bin'}{os.pathsep}existing-path",
        )
        self.assertNotIn("PROJECT_SECRET", environment)

    @unittest.skipUnless(os.name == "nt", "Windows environment variable names are case-insensitive")
    def test_minimal_environment_accepts_mixed_case_windows_variable_names(self):
        environment = minimal_environment(
            {
                "systemroot": "C:\\Windows",
                "windir": "C:\\Windows",
                "temp": "C:\\Temp",
                "tmp": "C:\\Temp",
                "path": "safe-path",
                "PROJECT_SECRET": "not-for-student-processes",
            }
        )
        self.assertEqual(environment["SystemRoot"], "C:\\Windows")
        self.assertEqual(environment["WINDIR"], "C:\\Windows")
        self.assertEqual(environment["TEMP"], "C:\\Temp")
        self.assertEqual(environment["TMP"], "C:\\Temp")
        self.assertEqual(environment["PATH"], "safe-path")
        self.assertNotIn("PROJECT_SECRET", environment)


class JavaHeapBudgetTests(unittest.TestCase):
    def test_java_heap_uses_half_of_effective_job_budget(self):
        for memory_mb, expected_heap_mb in ((256, 128), (512, 256), (2048, 1024)):
            with self.subTest(memory_mb=memory_mb):
                budget = memory_mb * 1024 * 1024
                limits = JobLimits(
                    process_memory_limit_bytes=budget,
                    job_memory_limit_bytes=budget,
                )
                self.assertEqual(java_heap_limit_mb(limits), expected_heap_mb)
                self.assertLess(expected_heap_mb * 1024 * 1024, budget)

    def test_java_heap_respects_the_tighter_limit(self):
        limits = JobLimits(
            process_memory_limit_bytes=512 * 1024 * 1024,
            job_memory_limit_bytes=256 * 1024 * 1024,
        )
        self.assertEqual(java_heap_limit_mb(limits), 128)

    def test_java_heap_rejects_unusable_or_invalid_budget(self):
        for budget in (1, True, None):
            with self.subTest(budget=budget):
                with self.assertRaises(ValueError):
                    java_heap_limit_mb(budget)
        with self.assertRaises(ValueError):
            java_heap_limit_mb(
                JobLimits(
                    process_memory_limit_bytes=128 * 1024 * 1024,
                    job_memory_limit_bytes=128 * 1024 * 1024,
                )
            )


class JudgeClassificationTests(unittest.TestCase):
    @staticmethod
    def process_result(status=ProcessStatus.EXITED, *, exit_code=0, stdout="", error_category=None):
        stdout_bytes = stdout.encode("utf-8")
        return ProcessResult(
            status=status,
            exit_code=exit_code,
            duration_ms=0,
            stdout=stdout,
            stderr="",
            stdout_bytes=len(stdout_bytes),
            stderr_bytes=0,
            stdout_truncated=False,
            stderr_truncated=False,
            error_category=error_category,
        )

    def test_student_process_exit_failure_type_maps_to_re(self):
        payload = {
            "score": 0,
            "total_points": 1,
            "checks": [],
            "error_category": None,
            "failure_type": "STUDENT_PROCESS_EXIT",
            "error": "Student called System.exit().",
        }
        result = self.process_result(stdout=json.dumps(payload))
        self.assertEqual(classify_judge_process_result(result), "RE")

    def test_student_fatal_error_failure_type_maps_to_re(self):
        payload = {
            "score": 0,
            "total_points": 1,
            "checks": [],
            "error_category": None,
            "failure_type": "STUDENT_FATAL_ERROR",
            "error": "Student caused a fatal JVM error.",
        }
        self.assertEqual(
            classify_judge_process_result(self.process_result(stdout=json.dumps(payload))), "RE"
        )

    def test_judge_lifecycle_distinguishes_student_and_infrastructure_termination(self):
        from app.java_runner import _parse_judge_lifecycle

        self.assertEqual(_parse_judge_lifecycle("!J\n"), ("INFRA_BEFORE_STUDENT", None))
        self.assertEqual(
            _parse_judge_lifecycle("!J\n!S\n"), ("STUDENT_TERMINATED", None)
        )
        self.assertEqual(
            _parse_judge_lifecycle("!J\n!S\n{}!C\n"), ("COMPLETED", "{}")
        )
        self.assertEqual(
            _parse_judge_lifecycle("!J\n{}!C\n"), ("COMPLETED", "{}")
        )
        self.assertEqual(_parse_judge_lifecycle("!S\n{}!C\n"), ("INFRA_BEFORE_START", None))

    def test_missing_protocol_after_process_exit_is_infrastructure_protocol_error(self):
        self.assertEqual(classify_judge_process_result(self.process_result()), "PROTOCOL_ERROR")

    def test_protocol_capture_is_omitted_from_serialized_process_result(self):
        result = replace(
            self.process_result(),
            protocol_output='{"score":999,"total_points":999,"checks":[]}',
            protocol_output_bytes=47,
        )
        serialized = result.to_dict()
        self.assertNotIn("protocol_output", serialized)
        self.assertNotIn("protocol_output_bytes", serialized)
        self.assertNotIn("protocol_truncated", serialized)

    def test_process_limits_map_to_judge_verdicts(self):
        self.assertEqual(
            classify_judge_process_result(self.process_result(ProcessStatus.TIMEOUT, exit_code=None)),
            "TLE",
        )
        self.assertEqual(
            classify_judge_process_result(self.process_result(ProcessStatus.MEMORY_LIMIT)),
            "MLE",
        )
        self.assertEqual(
            classify_judge_process_result(self.process_result(ProcessStatus.OUTPUT_LIMIT)),
            "OLE",
        )

    def test_exit_without_windows_memory_event_is_not_mle(self):
        result = self.process_result(exit_code=137)
        self.assertNotEqual(classify_judge_process_result(result), "MLE")

    def test_valid_check_results_map_to_ac_or_wa(self):
        check = {"id": "x", "passed": True, "points_earned": 1,
                 "expected": "1", "actual": "1", "error": None}
        payload = {"score": 1, "total_points": 1, "checks": [check]}
        self.assertEqual(
            classify_judge_process_result(self.process_result(stdout=json.dumps(payload))), "AC"
        )
        payload["checks"] = [{**check, "passed": False, "points_earned": 0}]
        self.assertEqual(
            classify_judge_process_result(self.process_result(stdout=json.dumps(payload))), "WA"
        )

    def test_infrastructure_and_malformed_protocol_remain_distinct(self):
        payload = {
            "score": 0,
            "total_points": 1,
            "checks": [],
            "error_category": "JUDGE_INFRA_ERROR",
        }
        self.assertEqual(
            classify_judge_process_result(self.process_result(stdout=json.dumps(payload))),
            "JUDGE_INFRA_ERROR",
        )
        self.assertEqual(
            classify_judge_process_result(self.process_result(stdout="not json")),
            "PROTOCOL_ERROR",
        )
        payload["checks"] = None
        self.assertEqual(
            classify_judge_process_result(self.process_result(stdout=json.dumps(payload))),
            "PROTOCOL_ERROR",
        )
        self.assertEqual(
            classify_judge_process_result(
                self.process_result(ProcessStatus.START_ERROR, exit_code=None, error_category="UNKNOWN")
            ),
            "JUDGE_INFRA_ERROR",
        )


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

    def test_cleanup_removes_read_only_and_nested_read_only_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = RunWorkspace.create(temp_dir)
            top_level = workspace.root / "readonly.txt"
            nested_dir = workspace.result / "nested"
            nested_dir.mkdir()
            nested_file = nested_dir / "readonly.txt"
            top_level.write_text("read only", encoding="utf-8")
            nested_file.write_text("nested read only", encoding="utf-8")
            top_level.chmod(stat.S_IREAD)
            nested_file.chmod(stat.S_IREAD)

            workspace.cleanup()

            self.assertFalse(workspace.root.exists())
            self.assertIsNone(workspace.cleanup_error)

    def test_cleanup_is_idempotent_and_keep_temp_is_preserved(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = RunWorkspace.create(temp_dir)
            workspace.cleanup()
            workspace.cleanup()
            self.assertFalse(workspace.root.exists())

            retained = RunWorkspace.create(temp_dir, keep_temp=True)
            retained.cleanup()
            retained.cleanup()
            self.assertTrue(retained.root.is_dir())
            shutil.rmtree(retained.root)

    def test_cleanup_failure_is_logged_and_can_be_retried(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = RunWorkspace.create(temp_dir)
            with self.assertLogs("app.java_runner", level="ERROR"):
                with patch(
                    "app.java_runner._remove_workspace_tree",
                    side_effect=PermissionError("workspace is temporarily locked"),
                ):
                    workspace.cleanup()
            self.assertTrue(workspace.root.is_dir())
            self.assertIn("PermissionError", workspace.cleanup_error)

            workspace.cleanup()
            self.assertFalse(workspace.root.exists())
            self.assertIsNone(workspace.cleanup_error)

    def test_cleanup_does_not_follow_directory_symlink(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = RunWorkspace.create(temp_dir)
            outside = Path(temp_dir) / "outside"
            outside.mkdir()
            sentinel = outside / "keep.txt"
            sentinel.write_text("outside workspace", encoding="utf-8")
            link = workspace.root / "link_to_outside"
            try:
                os.symlink(outside, link, target_is_directory=True)
            except (OSError, NotImplementedError) as symlink_error:
                junction_created = False
                if os.name == "nt":
                    command = f'mklink /J "{link}" "{outside}"'
                    junction = subprocess.run(
                        ["cmd.exe", "/d", "/c", command],
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    junction_created = junction.returncode == 0
                if not junction_created:
                    workspace.cleanup()
                    self.skipTest(
                        f"Symlink/junction creation is unavailable: {symlink_error}"
                    )

            workspace.cleanup()

            self.assertTrue(sentinel.is_file())
            self.assertFalse(workspace.root.exists())

    def test_concurrent_workspaces_are_unique_and_cleanup_independently(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            def create_and_cleanup(index):
                workspace = RunWorkspace.create(temp_dir)
                root = workspace.root
                (workspace.src / f"{index}.txt").write_text(str(index), encoding="utf-8")
                workspace.cleanup()
                return workspace.run_id, root

            with ThreadPoolExecutor(max_workers=8) as executor:
                results = list(executor.map(create_and_cleanup, range(16)))

            run_ids = [run_id for run_id, _ in results]
            roots = [root for _, root in results]
            self.assertEqual(len(run_ids), len(set(run_ids)))
            self.assertEqual(len(roots), len(set(roots)))
            self.assertTrue(all(not root.exists() for root in roots))

    @unittest.skipUnless(os.name == "nt", "Windows Job Object process lifecycle test")
    def test_live_process_workspace_is_untouched_and_cleans_after_job_termination(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            active_workspace = RunWorkspace.create(temp_dir)
            other_workspace = RunWorkspace.create(temp_dir)
            process = create_job_process(
                python_command("import time; time.sleep(30)"),
                cwd=active_workspace.root,
                env=minimal_environment(),
            )
            try:
                other_workspace.cleanup()
                self.assertIsNone(process.poll())
                self.assertTrue(active_workspace.root.is_dir())
                self.assertFalse(other_workspace.root.exists())
            finally:
                process.terminate()
                process.wait(timeout=3)
                process.close()
                active_workspace.cleanup()
            self.assertFalse(active_workspace.root.exists())

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

    def execute_observing_jobs(self, code: str, **kwargs):
        created_jobs = []
        real_create = create_job_process

        def record_job(*args, **options):
            process = real_create(*args, **options)
            created_jobs.append(process)
            return process

        with patch("app.java_runner.create_job_process", side_effect=record_job):
            result = self.execute(code, **kwargs)
        return result, created_jobs

    def assert_jobs_reaped(self, created_jobs):
        self.assertTrue(created_jobs, "Expected at least one Job Object process.")
        self.assertTrue(all(process._job_empty_on_close is True for process in created_jobs))
        self.assertTrue(all(process._closed and process._job_handle is None for process in created_jobs))
        self.assertTrue(all(process.poll() is not None for process in created_jobs))

    def test_exit_zero(self):
        result = self.execute("pass")
        self.assertEqual(result.status, ProcessStatus.EXITED)
        self.assertEqual(result.exit_code, 0)

    def test_exit_non_zero_is_still_exited(self):
        result = self.execute("raise SystemExit(7)")
        self.assertEqual(result.status, ProcessStatus.EXITED)
        self.assertEqual(result.exit_code, 7)

    def test_timeout_terminates_direct_child(self):
        result, jobs = self.execute_observing_jobs(
            "import time; time.sleep(30)", timeout_seconds=0.15
        )
        self.assertEqual(result.status, ProcessStatus.TIMEOUT)
        self.assertIsNotNone(result.exit_code)
        self.assertLess(result.duration_ms, 3000)
        self.assert_jobs_reaped(jobs)

    def test_infinite_loop_observes_hard_timeout(self):
        result, jobs = self.execute_observing_jobs(
            "while True: pass", timeout_seconds=0.2
        )
        self.assertEqual(result.status, ProcessStatus.TIMEOUT)
        self.assertLess(result.duration_ms, 1500)
        self.assert_jobs_reaped(jobs)

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

    def test_sends_input_through_bounded_job_stdin_pipe(self):
        result = run_process(
            python_command("import sys; print(sys.stdin.buffer.read().decode('utf-8'))"),
            cwd=REPO_ROOT,
            timeout_seconds=3,
            max_output_bytes=4096,
            input_data=b"judge-spec",
        )
        self.assertEqual(result.status, ProcessStatus.EXITED)
        self.assertEqual(result.stdout.strip(), "judge-spec")

    def test_stdin_writer_does_not_block_process_timeout(self):
        result = run_process(
            python_command("import time; time.sleep(30)"),
            cwd=REPO_ROOT,
            timeout_seconds=0.2,
            max_output_bytes=4096,
            input_data=b"x" * (1024 * 1024),
        )
        self.assertEqual(result.status, ProcessStatus.TIMEOUT)
        self.assertIsNotNone(result.exit_code)

    def test_large_output_is_bounded_and_stops_process(self):
        result, jobs = self.execute_observing_jobs(
            "import os; os.write(1, b'x' * 1000000)",
            timeout_seconds=8,
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
        self.assertLess(result.duration_ms, 4000)
        self.assert_jobs_reaped(jobs)

    def test_output_limit_wakes_monitor_even_with_timeout_active(self):
        result, jobs = self.execute_observing_jobs(
            "import os; exec(\"while True: os.write(1, b'x' * 4096)\")",
            timeout_seconds=0.2,
            max_output_bytes=8192,
        )
        self.assertEqual(result.status, ProcessStatus.OUTPUT_LIMIT)
        self.assertLess(result.duration_ms, 1500)
        self.assert_jobs_reaped(jobs)

    def test_large_stderr_is_bounded_and_stops_process(self):
        result, jobs = self.execute_observing_jobs(
            "import os; os.write(2, b'e' * 1000000)",
            timeout_seconds=8,
            max_output_bytes=2048,
        )
        self.assertEqual(result.status, ProcessStatus.OUTPUT_LIMIT)
        self.assertLessEqual(
            len(result.stdout.encode("utf-8")) + len(result.stderr.encode("utf-8")),
            2048,
        )
        self.assertTrue(result.stderr_truncated)
        self.assertLess(result.duration_ms, 4000)
        self.assert_jobs_reaped(jobs)

    def test_active_process_limit_is_enforced_and_children_are_reaped(self):
        code = (
            "import subprocess,sys\n"
            "children=[]\n"
            "for _ in range(8):\n"
            " try:\n"
            "  children.append(subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']))\n"
            " except OSError:\n"
            "  break\n"
            "print('started=' + str(len(children)), flush=True)\n"
        )
        result, jobs = self.execute_observing_jobs(
            code,
            timeout_seconds=8,
            job_limits=JobLimits(active_process_limit=3),
        )
        self.assertEqual(result.status, ProcessStatus.EXITED)
        self.assertEqual(result.stdout.strip(), "started=1")
        self.assert_jobs_reaped(jobs)

    def test_parent_exit_cleans_up_spawned_child(self):
        code = (
            "import subprocess,sys; "
            "subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); "
            "print('parent-exit', flush=True)"
        )
        result, jobs = self.execute_observing_jobs(code)
        self.assertEqual(result.status, ProcessStatus.EXITED)
        self.assertEqual(result.stdout.strip(), "parent-exit")
        self.assert_jobs_reaped(jobs)

    def test_abnormal_child_exit_is_reaped_without_server_failure(self):
        result, jobs = self.execute_observing_jobs(
            "import os; os._exit(17)"
        )
        self.assertEqual(result.status, ProcessStatus.EXITED)
        self.assertEqual(result.exit_code, 17)
        self.assert_jobs_reaped(jobs)

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

    def test_compile_keep_temp_retains_workspace_when_requested(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = compile_java(
                "public class Retained { public static void main(String[] args) {} }",
                source_path="Retained.java",
                workspace_parent=temp_dir,
                keep_temp=True,
            )
            workspace_path = Path(temp_dir) / f"run_{result.run_id}"
            try:
                self.assertTrue(result.success, result.error or result.stderr)
                self.assertTrue(workspace_path.is_dir())
                self.assertTrue((workspace_path / "out" / "Retained.class").is_file())
            finally:
                shutil.rmtree(workspace_path, ignore_errors=True)

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


@unittest.skipUnless(
    os.name == "nt" and shutil.which("javac") and shutil.which("java"),
    "Reflection vertical-slice tests require Windows and a JDK",
)
class ReflectionVerticalSliceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            _resolve_jdk_paths(os.environ)
        except OSError as exc:
            raise unittest.SkipTest(f"No configured JDK is available: {exc}") from exc

    @staticmethod
    def sample_source() -> str:
        return (
            "package model; public class Student implements Comparable<Student> { "
            "private String name = \"\"; private double gpa; public Student() {} "
            "public String getName() { return name; } "
            "public void setName(String name) { this.name = name; } "
            "public double getGpa() { return gpa; } "
            "public void setGpa(double gpa) { "
            "if (gpa < 0 || gpa > 4) throw new IllegalArgumentException(\"invalid gpa\"); "
            "this.gpa = gpa; } "
            "public boolean isPassing() { return gpa >= 2.0; } "
            "public String toString() { return \"Student{name='\" + name + \"', gpa=\" + gpa + \"}\"; } "
            "public int compareTo(Student other) { int byGpa = Double.compare(other.gpa, gpa); "
            "return byGpa != 0 ? byGpa : name.compareTo(other.name); } }"
        )

    @classmethod
    def sample_spec(cls) -> dict:
        def check(check_id, kind, points, **properties):
            return {
                "id": check_id,
                "kind": kind,
                "points": points,
                "is_visible": True,
                **properties,
            }

        def setup(name, gpa):
            return [
                {"method": "setName", "args": [name]},
                {"method": "setGpa", "parameter_types": ["double"], "args": [gpa]},
            ]

        return {
            "total_points": 100,
            "checks": [
                check("name-field", "field", 10, name="name", type="String", modifier="private"),
                check(
                    "name-setter", "behavior", 30,
                    method="setName", args=["Mina"],
                    expect_state={"getter": "getName", "value": "Mina"},
                ),
                check(
                    "student-tostring", "toString", 10,
                    template="Student{name='{name}', gpa={gpa}}",
                    setup=setup("Mina", 3.5),
                ),
                check(
                    "gpa-validator", "behavior", 15,
                    method="setGpa", parameter_types=["double"], args=[-1],
                    expect_exception="IllegalArgumentException",
                ),
                check(
                    "passing-predicate", "behavior", 15,
                    method="isPassing", args=[], setup=setup("Mina", 3.5), expect_return=True,
                ),
                check(
                    "student-order", "comparable", 20,
                    instances=[
                        {"setup": setup("Mina", 3.5)},
                        {"setup": setup("Amy", 3.0)},
                    ],
                    comparisons=[{"left": 0, "right": 1, "expected_sign": -1}],
                    expected_order=[0, 1],
                ),
            ],
        }

    def run_sample(self, source=None, specification=None, **options):
        return run_reflection_judge(
            source if source is not None else self.sample_source(),
            "model.Student",
            specification if specification is not None else self.sample_spec(),
            **options,
        )

    @staticmethod
    def is_judge_source_compile(command):
        return "-encoding" in command and Path(command[-1]).name == "ReflectionJudge.java"

    def test_reflection_judge_build_is_compiled_once_then_reused(self):
        actual_run_process = run_process
        commands = []

        def record_command(command, **kwargs):
            commands.append(list(command))
            return actual_run_process(command, **kwargs)

        with tempfile.TemporaryDirectory() as temp_dir:
            cache_root = Path(temp_dir) / "judge_cache"
            with patch("app.java_runner._REFLECTION_JUDGE_CACHE_ROOT", cache_root):
                with patch("app.java_runner.run_process", side_effect=record_command):
                    first = self.run_sample(workspace_parent=temp_dir)
                    second = self.run_sample(workspace_parent=temp_dir)

            self.assertEqual((first.verdict, first.score), ("AC", 100))
            self.assertEqual((second.verdict, second.score), ("AC", 100))
            judge_compiles = [command for command in commands if self.is_judge_source_compile(command)]
            self.assertEqual(len(judge_compiles), 1)
            cache_entries = [path for path in cache_root.iterdir() if path.is_dir()]
            self.assertEqual(len(cache_entries), 1)
            self.assertTrue((cache_entries[0] / "manifest.json").is_file())
            self.assertTrue((cache_entries[0] / "classes" / "ReflectionJudge.class").is_file())
            self.assertFalse(any(path.name.endswith(".tmp") for path in cache_root.iterdir()))

    def test_reflection_judge_source_change_selects_a_new_cache_entry(self):
        actual_run_process = run_process
        commands = []

        def record_command(command, **kwargs):
            commands.append(list(command))
            return actual_run_process(command, **kwargs)

        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = Path(temp_dir) / "source" / "ReflectionJudge.java"
            source_path.parent.mkdir()
            source_path.write_bytes((REPO_ROOT / "judge" / "ReflectionJudge.java").read_bytes())
            cache_root = Path(temp_dir) / "judge_cache"
            with patch("app.java_runner._REFLECTION_JUDGE_SOURCE", source_path):
                with patch("app.java_runner._REFLECTION_JUDGE_CACHE_ROOT", cache_root):
                    with patch("app.java_runner.run_process", side_effect=record_command):
                        first = self.run_sample(workspace_parent=temp_dir)
                        source_path.write_bytes(source_path.read_bytes() + b"\n// cache version change\n")
                        second = self.run_sample(workspace_parent=temp_dir)

            self.assertEqual((first.verdict, second.verdict), ("AC", "AC"))
            self.assertEqual(
                sum(self.is_judge_source_compile(command) for command in commands), 2
            )
            self.assertEqual(len([path for path in cache_root.iterdir() if path.is_dir()]), 2)

    def test_corrupted_reflection_judge_cache_is_rebuilt(self):
        actual_run_process = run_process
        commands = []

        def record_command(command, **kwargs):
            commands.append(list(command))
            return actual_run_process(command, **kwargs)

        with tempfile.TemporaryDirectory() as temp_dir:
            cache_root = Path(temp_dir) / "judge_cache"
            with patch("app.java_runner._REFLECTION_JUDGE_CACHE_ROOT", cache_root):
                with patch("app.java_runner.run_process", side_effect=record_command):
                    first = self.run_sample(workspace_parent=temp_dir)
                    class_file = next(cache_root.glob("*/classes/ReflectionJudge.class"))
                    class_file.write_bytes(class_file.read_bytes() + b"corrupt")
                    second = self.run_sample(workspace_parent=temp_dir)

            self.assertEqual((first.verdict, second.verdict), ("AC", "AC"))
            self.assertEqual(
                sum(self.is_judge_source_compile(command) for command in commands), 2
            )

    def test_concurrent_first_use_compiles_only_one_cache_entry(self):
        actual_run_process = run_process
        commands = []
        command_lock = threading.Lock()

        def record_command(command, **kwargs):
            with command_lock:
                commands.append(list(command))
            return actual_run_process(command, **kwargs)

        with tempfile.TemporaryDirectory() as temp_dir:
            cache_root = Path(temp_dir) / "judge_cache"
            with patch("app.java_runner._REFLECTION_JUDGE_CACHE_ROOT", cache_root):
                with patch("app.java_runner.run_process", side_effect=record_command):
                    with ThreadPoolExecutor(max_workers=2) as executor:
                        futures = [
                            executor.submit(self.run_sample, workspace_parent=temp_dir)
                            for _ in range(2)
                        ]
                        results = [future.result(timeout=45) for future in futures]

            self.assertEqual([(result.verdict, result.score) for result in results], [("AC", 100)] * 2)
            self.assertEqual(
                sum(self.is_judge_source_compile(command) for command in commands), 1
            )
            self.assertEqual(len([path for path in cache_root.iterdir() if path.is_dir()]), 1)
            self.assertFalse(any(path.name.endswith(".tmp") for path in cache_root.iterdir()))

    def test_compile_failure_leaves_no_cache_and_later_use_recovers(self):
        actual_run_process = run_process
        commands = []

        def fail_first_judge_compile(command, **kwargs):
            commands.append(list(command))
            if self.is_judge_source_compile(command) and sum(
                self.is_judge_source_compile(item) for item in commands
            ) == 1:
                return ProcessResult(
                    status=ProcessStatus.EXITED,
                    exit_code=1,
                    duration_ms=1,
                    stdout="",
                    stderr="synthetic ReflectionJudge compile failure",
                    stdout_bytes=0,
                    stderr_bytes=42,
                    stdout_truncated=False,
                    stderr_truncated=False,
                )
            return actual_run_process(command, **kwargs)

        with tempfile.TemporaryDirectory() as temp_dir:
            cache_root = Path(temp_dir) / "judge_cache"
            with patch("app.java_runner._REFLECTION_JUDGE_CACHE_ROOT", cache_root):
                with patch("app.java_runner.run_process", side_effect=fail_first_judge_compile):
                    failed = self.run_sample(workspace_parent=temp_dir)
                    self.assertEqual(failed.verdict, "JUDGE_INFRA_ERROR")
                    self.assertIn("synthetic ReflectionJudge compile failure", failed.error)
                    self.assertFalse(any(cache_root.iterdir()))
                    recovered = self.run_sample(workspace_parent=temp_dir)
                    reused = self.run_sample(workspace_parent=temp_dir)

            self.assertEqual((recovered.verdict, recovered.score), ("AC", 100))
            self.assertEqual((reused.verdict, reused.score), ("AC", 100))
            self.assertEqual(
                sum(self.is_judge_source_compile(command) for command in commands), 2
            )

    def test_correct_submission_scores_100_and_cleans_workspace(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = self.run_sample(workspace_parent=temp_dir)
            self.assertEqual((result.verdict, result.score, result.total_points), ("AC", 100, 100))
            self.assertEqual(len(result.checks), 6)
            self.assertEqual(list(Path(temp_dir).iterdir()), [])
            self.assertIsNotNone(result.run_id)

    def test_reflection_keep_temp_retains_workspace_when_requested(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = self.run_sample(workspace_parent=temp_dir, keep_temp=True)
            workspace_path = Path(temp_dir) / f"run_{result.run_id}"
            try:
                self.assertEqual((result.verdict, result.score), ("AC", 100))
                self.assertTrue(workspace_path.is_dir())
            finally:
                shutil.rmtree(workspace_path, ignore_errors=True)

    def test_reflection_heap_is_derived_from_total_job_memory(self):
        memory_bytes = 512 * 1024 * 1024
        commands = []
        actual_run_process = run_process

        def capture_command(command, **kwargs):
            commands.append(list(command))
            return actual_run_process(command, **kwargs)

        with patch("app.java_runner.run_process", side_effect=capture_command):
            result = self.run_sample(
                job_limits=JobLimits(
                    process_memory_limit_bytes=memory_bytes,
                    job_memory_limit_bytes=memory_bytes,
                )
            )

        self.assertEqual((result.verdict, result.score), ("AC", 100))
        judge_commands = [command for command in commands if "ReflectionJudge" in command]
        self.assertEqual(len(judge_commands), 1)
        self.assertIn("-Xmx256m", judge_commands[0])

    def test_reflection_rejects_java_budget_below_runtime_minimum(self):
        memory_bytes = 128 * 1024 * 1024
        result = self.run_sample(
            job_limits=JobLimits(
                process_memory_limit_bytes=memory_bytes,
                job_memory_limit_bytes=memory_bytes,
            )
        )
        self.assertEqual(result.verdict, "INVALID_REQUEST")
        self.assertEqual(result.error_category, "INVALID_REQUEST")
        self.assertIsNone(result.run_id)

    def test_wrong_modifier_scores_90(self):
        source = self.sample_source().replace("private String name", "public String name")
        result = self.run_sample(source=source)
        self.assertEqual((result.verdict, result.score), ("WA", 90))

    def test_wrong_tostring_scores_90(self):
        source = self.sample_source().replace(
            'return "Student{name=\'" + name + "\', gpa=" + gpa + "}";',
            'return "Student: " + name;',
        )
        result = self.run_sample(source=source)
        self.assertEqual((result.verdict, result.score), ("WA", 90))

    def test_validator_failure_scores_85(self):
        source = self.sample_source().replace(
            'if (gpa < 0 || gpa > 4) throw new IllegalArgumentException("invalid gpa"); ',
            "",
        )
        result = self.run_sample(source=source)
        self.assertEqual((result.verdict, result.score), ("WA", 85))

    def test_compile_error_returns_ce_without_launching_judge(self):
        commands = []
        actual_run_process = run_process

        def record_command(command, **kwargs):
            commands.append(list(command))
            return actual_run_process(command, **kwargs)

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("app.java_runner.run_process", side_effect=record_command):
                result = self.run_sample(
                    source="package model; public class Student { syntax error }",
                    workspace_parent=temp_dir,
                )
            self.assertEqual(result.verdict, "CE")
            self.assertEqual(result.score, 0)
            self.assertEqual(result.compile_result.verdict, "CE")
            self.assertFalse(any("ReflectionJudge.java" in command for command in commands))
            self.assertEqual(list(Path(temp_dir).iterdir()), [])

    def test_student_compile_resource_limits_keep_their_verdicts(self):
        jdk = JDKConfig(
            home=str(REPO_ROOT),
            javac=str(REPO_ROOT / "javac.exe"),
            java=str(REPO_ROOT / "java.exe"),
            javac_version="17",
            java_version="17",
        )
        for status, verdict in (
            (ProcessStatus.TIMEOUT, "TLE"),
            (ProcessStatus.MEMORY_LIMIT, "MLE"),
            (ProcessStatus.OUTPUT_LIMIT, "OLE"),
        ):
            with self.subTest(status=status):
                process = ProcessResult(
                    status=status,
                    exit_code=None,
                    duration_ms=10,
                    stdout="",
                    stderr="",
                    stdout_bytes=0,
                    stderr_bytes=0,
                    stdout_truncated=False,
                    stderr_truncated=False,
                )
                with tempfile.TemporaryDirectory() as temp_dir:
                    with patch(
                        "app.java_runner._detect_jdk", return_value=(jdk, {})
                    ):
                        with patch("app.java_runner.run_process", return_value=process):
                            result = self.run_sample(workspace_parent=temp_dir)
                    self.assertEqual(result.verdict, verdict)
                    self.assertIsNone(result.error_category)
                    self.assertEqual(result.score, 0)
                    self.assertEqual(list(Path(temp_dir).iterdir()), [])

    def test_wrong_package_fails_all_checks(self):
        source = self.sample_source().replace("package model;", "package other;")
        result = self.run_sample(source=source)
        self.assertEqual(result.verdict, "WA")
        self.assertEqual(result.score, 0)
        self.assertEqual(len(result.checks), 6)
        self.assertTrue(all(not check["passed"] for check in result.checks))

    def test_infinite_getter_returns_tle_and_next_run_can_succeed(self):
        source = self.sample_source().replace(
            "public String getName() { return name; }",
            "public String getName() { while (true) {} }",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            failed = self.run_sample(
                source=source, judge_timeout_seconds=1.5, workspace_parent=temp_dir
            )
            self.assertEqual(failed.verdict, "TLE")
            self.assertEqual(list(Path(temp_dir).iterdir()), [])
            recovered = self.run_sample(workspace_parent=temp_dir)
            self.assertEqual((recovered.verdict, recovered.score), ("AC", 100))
            self.assertEqual(list(Path(temp_dir).iterdir()), [])

    def test_system_exit_returns_re_and_server_process_recovers(self):
        source = self.sample_source().replace(
            "public String getName() { return name; }",
            "public String getName() { System.exit(0); return name; }",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            failed = self.run_sample(source=source, workspace_parent=temp_dir)
            self.assertEqual(failed.verdict, "RE")
            self.assertEqual(list(Path(temp_dir).iterdir()), [])
            recovered = self.run_sample(workspace_parent=temp_dir)
            self.assertEqual((recovered.verdict, recovered.score), ("AC", 100))
            self.assertEqual(list(Path(temp_dir).iterdir()), [])

    def test_system_exit_nonzero_runtime_halt_and_vm_fatal_recover(self):
        abnormal_sources = (
            ("if (System.nanoTime() != Long.MIN_VALUE) System.exit(23);", "exit-nonzero"),
            ("Runtime.getRuntime().halt(0);", "runtime-halt"),
            ("if (System.nanoTime() != Long.MIN_VALUE) throw new OutOfMemoryError(\"test\");", "oom"),
            ("getName();", "stack-overflow"),
        )
        for statement, name in abnormal_sources:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp_dir:
                source = self.sample_source().replace(
                    "public String getName() { return name; }",
                    f"public String getName() {{ {statement} return name; }}",
                )
                failed = self.run_sample(source=source, workspace_parent=temp_dir)
                self.assertEqual(failed.verdict, "RE")
                recovered = self.run_sample(workspace_parent=temp_dir)
                self.assertEqual((recovered.verdict, recovered.score), ("AC", 100))

    def test_unexpected_runtime_exception_is_a_failed_check_not_judge_failure(self):
        source = self.sample_source().replace(
            "public String getName() { return name; }",
            "public String getName() { if (System.nanoTime() != Long.MIN_VALUE) "
            "throw new IllegalStateException(\"unexpected\"); return name; }",
        )
        result = self.run_sample(source=source)
        self.assertEqual((result.verdict, result.score), ("WA", 70))
        failed = next(check for check in result.checks if check["id"] == "name-setter")
        self.assertIn("IllegalStateException", failed["error"])

    def test_fatal_class_initialization_error_is_re_and_next_run_recovers(self):
        source = self.sample_source().replace(
            "package model; public class Student implements Comparable<Student> {",
            "package model; public class Student implements Comparable<Student> { "
            "static { if (System.nanoTime() != Long.MIN_VALUE) "
            "throw new InternalError(\"fatal initialization\"); }",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            failed = self.run_sample(source=source, workspace_parent=temp_dir)
            self.assertEqual(failed.verdict, "RE")
            recovered = self.run_sample(workspace_parent=temp_dir)
            self.assertEqual((recovered.verdict, recovered.score), ("AC", 100))

    def test_student_stdout_does_not_corrupt_judge_json(self):
        source = self.sample_source().replace(
            "private String name = \"\";",
            "static { System.out.println(\"student output\"); System.err.println(\"student error\"); } private String name = \"\";",
        )
        result = self.run_sample(source=source)
        self.assertEqual((result.verdict, result.score), ("AC", 100))
        self.assertIn("student output", result.process_result.stdout)
        self.assertIn("student error", result.process_result.stderr)

    def test_student_raw_file_descriptor_stdout_is_bounded_and_separate(self):
        source = self.sample_source().replace(
            "private String name = \"\";",
            "static { try { new java.io.FileOutputStream(java.io.FileDescriptor.out).write("
            "new byte[65536]); } catch (java.io.IOException e) { throw new RuntimeException(e); } } "
            "private String name = \"\";",
        )
        result = self.run_sample(source=source, student_stdout_limit_bytes=1024)
        self.assertEqual(result.verdict, "OLE")
        self.assertLessEqual(len(result.process_result.stdout.encode("utf-8")), 1024)
        self.assertTrue(result.process_result.stdout_truncated)
        self.assertEqual(result.error_category, None)

    def test_student_stderr_has_an_independent_output_limit(self):
        source = self.sample_source().replace(
            "private String name = \"\";",
            "static { System.err.print(\"e\".repeat(65536)); } private String name = \"\";",
        )
        result = self.run_sample(source=source, student_stderr_limit_bytes=1024)
        self.assertEqual(result.verdict, "OLE")
        self.assertEqual(result.process_result.stdout_bytes, 0)
        self.assertTrue(result.process_result.stderr_truncated)

    def test_protocol_limit_is_infrastructure_error_not_student_ole(self):
        result = self.run_sample(judge_protocol_limit_bytes=64)
        self.assertEqual(result.verdict, "JUDGE_INFRA_ERROR")
        self.assertEqual(result.error_category, "JUDGE_INFRA_ERROR")

    def test_student_output_overflow_wins_even_if_protocol_file_is_valid(self):
        source = self.sample_source().replace(
            "private String name = \"\";",
            "static { System.out.print(\"x\".repeat(65536)); } private String name = \"\";",
        )
        actual_run_process = run_process

        def seed_valid_protocol(command, **kwargs):
            result = actual_run_process(command, **kwargs)
            if "ReflectionJudge" in command:
                result = replace(
                    result,
                    protocol_output=json.dumps(
                        {"score": 100, "total_points": 100, "checks": []}
                    ),
                    protocol_output_bytes=48,
                )
            return result

        with patch("app.java_runner.run_process", side_effect=seed_valid_protocol):
            result = self.run_sample(source=source, student_stdout_limit_bytes=1024)
        self.assertEqual(result.verdict, "OLE")

    def test_resource_failures_recover_and_every_job_is_empty(self):
        exit_source = self.sample_source().replace(
            "public String getName() { return name; }",
            "public String getName() { System.exit(0); return name; }",
        )
        timeout_source = self.sample_source().replace(
            "public String getName() { return name; }",
            "public String getName() { while (true) {} }",
        )
        created_jobs = []
        real_create = create_job_process

        def record_job(*args, **options):
            process = real_create(*args, **options)
            created_jobs.append(process)
            return process

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("app.java_runner.create_job_process", side_effect=record_job):
                first = self.run_sample(workspace_parent=temp_dir)
                exited = self.run_sample(source=exit_source, workspace_parent=temp_dir)
                timed_out = self.run_sample(
                    source=timeout_source,
                    judge_timeout_seconds=1.2,
                    workspace_parent=temp_dir,
                )
                output_limited = run_stdio(
                    "import os; os.write(1, b'x' * 10000000)",
                    "python",
                    [{
                        "id": "output-bomb",
                        "stdin": "",
                        "expected_stdout": "",
                        "is_visible": True,
                        "points": 100,
                        "compare_mode": "exact",
                    }],
                    timeout_seconds=8,
                    max_output_bytes=4096,
                    workspace_parent=temp_dir,
                )
                recovered = self.run_sample(workspace_parent=temp_dir)

            self.assertEqual((first.verdict, first.score), ("AC", 100))
            self.assertEqual(exited.verdict, "RE")
            self.assertEqual(timed_out.verdict, "TLE")
            self.assertEqual(output_limited.verdict, "OLE")
            self.assertLess(output_limited.duration_ms, 4000)
            self.assertEqual((recovered.verdict, recovered.score), ("AC", 100))
            self.assertEqual(list(Path(temp_dir).iterdir()), [])

        self.assertTrue(created_jobs, "Expected execution jobs to be created.")
        self.assertTrue(all(process._job_empty_on_close is True for process in created_jobs))
        self.assertTrue(all(process._closed and process._job_handle is None for process in created_jobs))
        self.assertTrue(all(process.poll() is not None for process in created_jobs))

    def test_invalid_specification_is_rejected_before_workspace_creation(self):
        specification = self.sample_spec()
        specification["total_points"] = 101
        with tempfile.TemporaryDirectory() as temp_dir:
            result = self.run_sample(specification=specification, workspace_parent=temp_dir)
            self.assertEqual(result.verdict, "INVALID_REQUEST")
            self.assertEqual(result.error_category, "INVALID_REQUEST")
            self.assertIsNone(result.run_id)
            self.assertEqual(list(Path(temp_dir).iterdir()), [])

    def test_job_object_failure_is_infrastructure_error_without_fallback(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch(
                "app.java_runner.create_job_process",
                side_effect=JobObjectError("Job creation failed"),
            ):
                with patch("app.java_runner.subprocess.Popen") as unrestricted_fallback:
                    result = self.run_sample(workspace_parent=temp_dir)
            self.assertEqual(result.verdict, "JUDGE_INFRA_ERROR")
            self.assertEqual(result.error_category, "JUDGE_INFRA_ERROR")
            self.assertEqual(list(Path(temp_dir).iterdir()), [])
            unrestricted_fallback.assert_not_called()

    def test_malformed_judge_output_returns_protocol_error(self):
        actual_run_process = run_process

        def corrupt_judge_result(command, **kwargs):
            process_result = actual_run_process(command, **kwargs)
            if "ReflectionJudge" in command:
                return replace(
                    process_result,
                    protocol_output="!J\n!S\nnot json!C\n",
                    protocol_output_bytes=16,
                )
            return process_result

        with patch("app.java_runner.run_process", side_effect=corrupt_judge_result):
            result = self.run_sample()
        self.assertEqual(result.verdict, "PROTOCOL_ERROR")
        self.assertEqual(result.error_category, "PROTOCOL_ERROR")
        self.assertEqual(result.score, 0)


if __name__ == "__main__":
    unittest.main()
