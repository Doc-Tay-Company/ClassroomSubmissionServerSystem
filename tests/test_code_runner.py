from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch

from app.code_runner import _failure_for_process, compare_outputs, outputs_match, run_stdio
from app.code_exams import _job_limits
from app.questions import QuestionError, _validate_question
from app.java_runner import ProcessResult, ProcessStatus
from app.windows_job import JobLimits, JobObjectError

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_PARENT = REPO_ROOT / ".test-code-runner-workspaces"


def make_test(test_id, stdin, expected, points=1, *, mode="exact", visible=True, **extra):
    return {
        "id": test_id,
        "stdin": stdin,
        "expected_stdout": expected,
        "is_visible": visible,
        "points": points,
        "compare_mode": mode,
        **extra,
    }


class OutputComparisonTests(unittest.TestCase):
    def test_exact_accepts_equal_output(self):
        result = compare_outputs("value\n", "value\n", "exact")
        self.assertTrue(result.passed)
        self.assertEqual((result.expected, result.actual, result.reason), ("value\n", "value\n", None))

    def test_exact_converts_crlf_to_lf_only(self):
        self.assertTrue(outputs_match("a\r\nb\r\n", "a\nb\n", "exact"))
        self.assertFalse(outputs_match("value", "value\n", "exact"))
        self.assertFalse(outputs_match("a\nb", "a b", "exact"))

    def test_normalized_trims_each_line_tail_and_all_final_blank_lines(self):
        self.assertTrue(
            outputs_match("answer \t\r\n\r\n \t\n", "answer", "normalized")
        )

    def test_normalized_preserves_leading_internal_and_internal_blank_whitespace(self):
        self.assertFalse(outputs_match(" answer\n", "answer\n", "normalized"))
        self.assertFalse(outputs_match("a  b\n", "a b\n", "normalized"))
        self.assertFalse(outputs_match("a\n\nb\n", "a\nb\n", "normalized"))

    def test_tokens_ignore_whitespace_but_preserve_token_sequence(self):
        self.assertTrue(outputs_match("1  2\n3", "1\n2 3", "tokens"))
        result = compare_outputs("1 2", "1 3", "tokens")
        self.assertFalse(result.passed)
        self.assertEqual(result.expected, "1 2")
        self.assertEqual(result.actual, "1 3")
        self.assertIn("token sequences", result.reason)

    def test_float_absolute_tolerance_within_and_outside_boundary(self):
        self.assertTrue(
            compare_outputs(
                "x 1.000", "x 1.005", "float_tolerance", abs_tolerance=Decimal("0.01")
            ).passed
        )
        self.assertTrue(
            outputs_match("1", "1.005", "float_tolerance", Decimal("0.01"))
        )
        result = compare_outputs("1", "1.02", "float_tolerance", abs_tolerance=Decimal("0.01"))
        self.assertFalse(result.passed)
        self.assertIn("exceeds", result.reason)

    def test_float_relative_tolerance_is_scaled_by_larger_magnitude(self):
        self.assertTrue(
            compare_outputs(
                "1000000000", "1000000001", "float_tolerance", rel_tolerance=Decimal("1e-9")
            ).passed
        )
        self.assertFalse(
            compare_outputs(
                "1000000000", "1000000002", "float_tolerance", rel_tolerance=Decimal("1e-9")
            ).passed
        )

    def test_float_combines_absolute_and_relative_tolerance_using_larger_allowance(self):
        self.assertTrue(
            compare_outputs(
                "0",
                "0.005",
                "float_tolerance",
                abs_tolerance=Decimal("0.01"),
                rel_tolerance=Decimal("0"),
            ).passed
        )

    def test_float_mode_has_no_implicit_tolerance(self):
        result = compare_outputs("1", "1", "float_tolerance")
        self.assertFalse(result.passed)
        self.assertIn("requires", result.reason)

    def test_malformed_numeric_token_fails_with_reason(self):
        result = compare_outputs(
            "1.25", "1.25oops", "float_tolerance", abs_tolerance=Decimal("0.1")
        )
        self.assertFalse(result.passed)
        self.assertIn("malformed", result.reason)
        self.assertFalse(
            compare_outputs(
                "NaN", "NaN", "float_tolerance", abs_tolerance=Decimal("1")
            ).passed
        )

    def test_identical_literal_labels_are_allowed_in_float_output(self):
        self.assertTrue(
            compare_outputs(
                "result 1.0",
                "result 1.001",
                "float_tolerance",
                abs_tolerance=Decimal("0.01"),
            ).passed
        )


class ProcessVerdictTests(unittest.TestCase):
    def make_process(self, status, *, exit_code=None, error_category=None):
        return ProcessResult(
            status=status,
            exit_code=exit_code,
            duration_ms=0,
            stdout="",
            stderr="",
            stdout_bytes=0,
            stderr_bytes=0,
            stdout_truncated=False,
            stderr_truncated=False,
            error_category=error_category,
        )

    def test_process_limit_statuses_map_to_stdio_verdicts(self):
        expected = {
            ProcessStatus.TIMEOUT: "TLE",
            ProcessStatus.MEMORY_LIMIT: "MLE",
            ProcessStatus.OUTPUT_LIMIT: "OLE",
        }
        for status, verdict in expected.items():
            with self.subTest(status=status):
                actual, category, _ = _failure_for_process(self.make_process(status), 1024)
                self.assertEqual((actual, category), (verdict, None))


class QuestionMemoryLimitTests(unittest.TestCase):
    def test_question_memory_is_both_per_process_and_total_job_budget(self):
        limits = _job_limits({"memory_limit_mb": 128})
        expected = 128 * 1024 * 1024
        self.assertEqual(limits.process_memory_limit_bytes, expected)
        self.assertEqual(limits.job_memory_limit_bytes, expected)

    def test_invalid_question_memory_config_is_rejected(self):
        for value in (True, 15, 2049, 128.0, "128", None):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    _job_limits({"memory_limit_mb": value})
        with self.assertRaises(ValueError):
            _job_limits({"language": "java", "memory_limit_mb": 128})

    def test_java_question_config_rejects_budget_below_jvm_minimum(self):
        with self.assertRaisesRegex(QuestionError, "at least 256"):
            _validate_question(
                {
                    "title": "Low memory Java",
                    "statement": "",
                    "language": "java",
                    "grading_mode": "reflection",
                    "starter_code": "",
                    "time_limit_seconds": 2,
                    "memory_limit_mb": 128,
                },
                question_id="low-memory-java",
                actor="admin",
            )


class WorkspaceTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        WORKSPACE_PARENT.mkdir(exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        if WORKSPACE_PARENT.exists():
            WORKSPACE_PARENT.rmdir()


class StdioRequestValidationTests(WorkspaceTestCase):
    def test_invalid_request_does_not_create_workspace(self):
        result = run_stdio(
            "print('x')",
            "python",
            [make_test("duplicate", "", "x\n"), make_test("duplicate", "", "x\n")],
            workspace_parent=WORKSPACE_PARENT,
        )
        self.assertEqual(result.verdict, "INVALID_REQUEST")
        self.assertEqual(result.error_category, "INVALID_REQUEST")
        self.assertIsNone(result.run_id)
        self.assertEqual(list(WORKSPACE_PARENT.iterdir()), [])

    def test_invalid_compare_mode_is_rejected(self):
        result = run_stdio(
            "pass",
            "python",
            [make_test("t1", "", "", mode="contains")],
        )
        self.assertEqual(result.verdict, "INVALID_REQUEST")

    def test_java_memory_budget_below_runtime_minimum_is_invalid(self):
        result = run_stdio(
            "public class Main { public static void main(String[] args) {} }",
            "java",
            [make_test("low-memory", "", "")],
            target_class="Main",
            job_limits=JobLimits(
                process_memory_limit_bytes=128 * 1024 * 1024,
                job_memory_limit_bytes=128 * 1024 * 1024,
            ),
        )
        self.assertEqual(result.verdict, "INVALID_REQUEST")
        self.assertIn("at least 256 MiB", result.error)

    def test_float_mode_requires_explicit_tolerance_configuration(self):
        result = run_stdio(
            "pass",
            "python",
            [make_test("float", "", "1", mode="float_tolerance")],
            workspace_parent=WORKSPACE_PARENT,
        )
        self.assertEqual(result.verdict, "INVALID_REQUEST")
        self.assertIn("requires abs_tolerance", result.error)
        self.assertEqual(list(WORKSPACE_PARENT.iterdir()), [])

    def test_visible_only_does_not_run_or_score_hidden_cases(self):
        result = run_stdio(
            "import sys; print(sys.stdin.read().strip())",
            "python",
            [
                make_test("visible", "v", "v\n", 2, visible=True),
                make_test("hidden", "h", "wrong", 8, visible=False),
            ],
            visible_only=True,
        ) if os.name == "nt" else None
        if result is None:
            self.skipTest("Windows Job Objects are required")
        self.assertEqual((result.verdict, result.score, result.total_points), ("AC", 2, 2))
        self.assertEqual([test.id for test in result.tests], ["visible"])


@unittest.skipUnless(os.name == "nt", "STDIO execution requires Windows Job Objects")
class PythonStdioIntegrationTests(WorkspaceTestCase):
    def test_multiple_inputs_are_run_in_separate_processes(self):
        source = "import sys; print(sys.stdin.read().strip().upper())"
        result = run_stdio(
            source,
            "python",
            [make_test("lower", "hello", "HELLO\n"), make_test("mixed", "Hi", "HI\n")],
        )
        self.assertEqual((result.verdict, result.score, result.total_points), ("AC", 2, 2))
        self.assertEqual([test.verdict for test in result.tests], ["AC", "AC"])
        self.assertEqual(result.compile_result.status, "EXITED")

    def test_syntax_error_is_ce_and_workspace_is_cleaned(self):
        result = run_stdio(
            "if:",
            "python",
            [make_test("syntax", "", "")],
            workspace_parent=WORKSPACE_PARENT,
        )
        self.assertEqual(result.verdict, "CE")
        self.assertEqual(result.tests[0].verdict, "CE")
        self.assertIn("SyntaxError", result.error)
        self.assertEqual(list(WORKSPACE_PARENT.iterdir()), [])

    def test_nonzero_exit_is_re_even_when_stdout_matches(self):
        source = "import sys; print('expected'); raise SystemExit(7)"
        result = run_stdio(source, "python", [make_test("exit", "", "expected\n")])
        self.assertEqual(result.verdict, "RE")
        self.assertEqual(result.tests[0].verdict, "RE")
        self.assertEqual(result.tests[0].actual_stdout.replace("\r\n", "\n"), "expected\n")
        self.assertEqual(result.score, 0)

    def test_timeout_does_not_prevent_later_test(self):
        source = (
            "import sys\n"
            "value = sys.stdin.read().strip()\n"
            "if value == 'hang':\n"
            "    while True: pass\n"
            "print(value)\n"
        )
        result = run_stdio(
            source,
            "python",
            [make_test("slow", "hang", "hang\n"), make_test("next", "ok", "ok\n")],
            timeout_seconds=0.25,
        )
        self.assertEqual(result.verdict, "TLE")
        self.assertEqual([test.verdict for test in result.tests], ["TLE", "AC"])
        self.assertEqual(result.score, 1)

    def test_output_limit_does_not_prevent_later_test(self):
        source = (
            "import sys\n"
            "value = sys.stdin.read().strip()\n"
            "print('x' * 10000 if value == 'large' else value)\n"
        )
        result = run_stdio(
            source,
            "python",
            [make_test("large", "large", "", 1), make_test("next", "ok", "ok\n", 2)],
            max_output_bytes=1024,
        )
        self.assertEqual(result.verdict, "OLE")
        self.assertEqual([test.verdict for test in result.tests], ["OLE", "AC"])
        self.assertTrue(result.tests[0].stdout_truncated)
        self.assertEqual(result.score, 2)

    def test_stderr_is_captured_without_affecting_matching_stdout(self):
        result = run_stdio(
            "import sys; print('ok'); print('diagnostic', file=sys.stderr)",
            "python",
            [make_test("stderr", "", "ok\n")],
        )
        self.assertEqual(result.verdict, "AC")
        self.assertIn("diagnostic", result.tests[0].stderr)

    def test_broken_stdin_consumer_is_student_failure_not_infrastructure(self):
        result = run_stdio(
            "print('done')",
            "python",
            [make_test("ignored-input", "x" * (1024 * 1024), "done\n")],
        )
        self.assertEqual(result.verdict, "AC")

    def test_job_creation_failure_fails_closed(self):
        with patch("app.java_runner.create_job_process", side_effect=JobObjectError("job denied")):
            result = run_stdio("print('x')", "python", [make_test("t1", "", "x\n")])
        self.assertEqual(result.verdict, "JUDGE_INFRA_ERROR")
        self.assertEqual(result.error_category, "JUDGE_INFRA_ERROR")

    def test_relative_python_executable_is_rejected_without_py_fallback(self):
        result = run_stdio(
            "print('x')",
            "python",
            [make_test("t1", "", "x\n")],
            python_executable="py.exe",
            workspace_parent=WORKSPACE_PARENT,
        )
        self.assertEqual(result.verdict, "JUDGE_INFRA_ERROR")
        self.assertIn("absolute path", result.error)
        self.assertEqual(list(WORKSPACE_PARENT.iterdir()), [])


@unittest.skipUnless(
    os.name == "nt" and shutil.which("java") and shutil.which("javac"),
    "Java STDIO execution requires Windows and a configured JDK",
)
class JavaStdioIntegrationTests(WorkspaceTestCase):
    SOURCE = (
        "package sample; import java.util.Scanner; public class Main { "
        "public static void main(String[] args) { Scanner scanner = new Scanner(System.in); "
        "System.out.println(scanner.nextLine().toUpperCase()); } }"
    )

    def test_java_compiles_once_and_runs_each_test_separately(self):
        from app.java_runner import run_process as real_run_process

        commands = []

        def recording_process(command, **kwargs):
            commands.append(list(command))
            return real_run_process(command, **kwargs)

        with patch("app.java_runner.run_process", side_effect=recording_process):
            result = run_stdio(
                self.SOURCE,
                "java",
                [make_test("one", "alpha", "ALPHA\n"), make_test("two", "beta", "BETA\n")],
                target_class="Main",
                target_package="sample",
            )
        javac_commands = [command for command in commands if Path(command[0]).name.lower() == "javac.exe"]
        self.assertEqual(len(javac_commands), 2)  # javac version probe plus one source compile
        source_compiles = [command for command in javac_commands if "-encoding" in command]
        self.assertEqual(len(source_compiles), 1)
        self.assertEqual((result.verdict, result.score, result.total_points), ("AC", 2, 2))
        self.assertEqual([test.verdict for test in result.tests], ["AC", "AC"])

    def test_java_compile_error_is_ce(self):
        result = run_stdio(
            "package sample; public class Main { syntax error }",
            "java",
            [make_test("compile", "", "")],
            target_class="sample.Main",
        )
        self.assertEqual(result.verdict, "CE")
        self.assertEqual(result.tests[0].verdict, "CE")
        self.assertIn("error", result.compile_result.stderr.lower())

    def test_java_nonzero_exit_is_re_even_if_stdout_matches(self):
        source = (
            "public class Main { public static void main(String[] args) { "
            "System.out.println(\"expected\"); System.exit(3); } }"
        )
        result = run_stdio(source, "java", [make_test("exit", "", "expected\n")], target_class="Main")
        self.assertEqual(result.verdict, "RE")
        self.assertEqual(result.tests[0].actual_stdout.replace("\r\n", "\n"), "expected\n")

    def test_java_student_process_gets_minimal_environment(self):
        from app.java_runner import run_process as real_run_process

        runtime_environments = []

        def recording_process(command, **kwargs):
            if Path(command[0]).name.lower() == "java.exe" and "-cp" in command:
                runtime_environments.append(dict(kwargs["env"]))
            return real_run_process(command, **kwargs)

        process_environment = dict(os.environ)
        process_environment["CLASSROOM_TEST_SECRET"] = "must-not-reach-student"
        with patch("app.code_runner.run_process", side_effect=recording_process):
            result = run_stdio(
                self.SOURCE,
                "java",
                [make_test("env", "hello", "HELLO\n")],
                target_class="sample.Main",
                env=process_environment,
            )
        self.assertEqual(result.verdict, "AC")
        self.assertEqual(len(runtime_environments), 1)
        self.assertNotIn("CLASSROOM_TEST_SECRET", runtime_environments[0])

    def test_java_heap_allocation_near_derived_limit_fits_job_budget(self):
        source = (
            "public class Main { public static void main(String[] args) { "
            "byte[] data = new byte[112 * 1024 * 1024]; "
            "for (int i = 0; i < data.length; i += 4096) data[i] = 1; "
            "System.out.println(data[0]); } }"
        )
        memory_bytes = 256 * 1024 * 1024
        result = run_stdio(
            source,
            "java",
            [make_test("heap-near-limit", "", "1\n")],
            target_class="Main",
            job_limits=JobLimits(
                process_memory_limit_bytes=memory_bytes,
                job_memory_limit_bytes=memory_bytes,
            ),
        )
        self.assertEqual((result.verdict, result.score), ("AC", 1), result.error)

    def test_java_package_mismatch_is_runtime_error_and_workspace_is_cleaned(self):
        source = "package wrong; public class Main { public static void main(String[] a) {} }"
        result = run_stdio(
            source,
            "java",
            [make_test("package", "", "")],
            target_class="sample.Main",
            workspace_parent=WORKSPACE_PARENT,
        )
        self.assertEqual(result.verdict, "RE")
        self.assertEqual(list(WORKSPACE_PARENT.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
