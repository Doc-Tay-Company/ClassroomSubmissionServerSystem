import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from app.java_runner import (
    ProcessResult,
    ProcessStatus,
    classify_judge_process_result,
    minimal_environment,
    run_process,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
JUDGE_SOURCE = REPO_ROOT / "judge" / "ReflectionJudge.java"


@unittest.skipUnless(
    os.name == "nt" and shutil.which("javac") and shutil.which("java"),
    "ReflectionJudge command-line tests require Windows and a JDK",
)
class ReflectionJudgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_root = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp_root.name)
        cls.judge_out = cls.root / "judge_out"
        cls.judge_out.mkdir()
        compiled = subprocess.run(
            ["javac", "-d", str(cls.judge_out), "ReflectionJudge.java"],
            cwd=JUDGE_SOURCE.parent,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if compiled.returncode != 0:
            cls.temp_root.cleanup()
            raise AssertionError(f"ReflectionJudge did not compile:\n{compiled.stderr}")

    @classmethod
    def tearDownClass(cls):
        cls.temp_root.cleanup()

    def setUp(self):
        self.case_root = Path(tempfile.mkdtemp(dir=self.root))
        self.addCleanup(shutil.rmtree, self.case_root, True)

    def compile_student(self, source: str, filename: str = "Student.java") -> Path:
        source_root = self.case_root / "student_src"
        output_root = self.case_root / "student_out"
        source_file = source_root / filename
        source_file.parent.mkdir(parents=True, exist_ok=True)
        output_root.mkdir(parents=True, exist_ok=True)
        source_file.write_text(source, encoding="utf-8")
        compiled = subprocess.run(
            ["javac", "-encoding", "UTF-8", "-d", str(output_root), str(source_file)],
            cwd=self.case_root,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(compiled.returncode, 0, compiled.stderr)
        return output_root

    def run_judge_process(
        self,
        target: str,
        output_dir: Path,
        specification: str,
        *,
        timeout: float = 10,
        classpath: str | None = None,
        protocol_limit_bytes: int = 1024 * 1024,
    ) -> tuple[subprocess.CompletedProcess, bytes]:
        command = [
            shutil.which("java"), "-Xmx128m", "-cp", classpath or str(self.judge_out),
            "ReflectionJudge", target, str(output_dir), str(protocol_limit_bytes),
        ]
        process_result = run_process(
            command,
            cwd=self.case_root,
            input_data=specification.encode("utf-8"),
            max_output_bytes=1024 * 1024,
            protocol_limit_bytes=protocol_limit_bytes,
            timeout_seconds=timeout,
            env=minimal_environment(),
        )
        if process_result.status == ProcessStatus.TIMEOUT:
            raise subprocess.TimeoutExpired(command, timeout)
        result = subprocess.CompletedProcess(
            command,
            process_result.exit_code,
            process_result.stdout.encode("utf-8"),
            process_result.stderr.encode("utf-8"),
        )
        raw_protocol = process_result.protocol_output or ""
        if raw_protocol.startswith("!J\n"):
            raw_protocol = raw_protocol[3:]
        if raw_protocol.startswith("!S\n"):
            raw_protocol = raw_protocol[3:]
        if raw_protocol.endswith("!C\n"):
            raw_protocol = raw_protocol[:-3]
        return result, raw_protocol.encode("utf-8")

    def run_judge(self, target: str, output_dir: Path, specification: str) -> dict:
        result, protocol = self.run_judge_process(target, output_dir, specification)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", errors="replace"))
        output = protocol.decode("utf-8")
        try:
            return json.loads(output)
        except json.JSONDecodeError as error:
            self.fail(f"Judge result channel was not valid JSON: {error}: {output!r}")

    @staticmethod
    def make_check(check_id: str, kind: str, points: int = 1, **properties) -> dict:
        return {
            "id": check_id,
            "kind": kind,
            "points": points,
            "is_visible": True,
            **properties,
        }

    @staticmethod
    def spec_for(*checks: dict) -> str:
        return json.dumps({
            "total_points": sum(check["points"] for check in checks),
            "checks": list(checks),
        })

    @staticmethod
    def behavior_sample_source() -> str:
        return (
            "package model; public class Student implements Comparable<Student> { "
            "private String name; private double gpa; public Student() { name = \"\"; gpa = 0.0; } "
            "public String getName() { return name; } public void setName(String name) { this.name = name; } "
            "public double getGpa() { return gpa; } "
            "public void setGpa(double gpa) { if (gpa < 0 || gpa > 4) throw new IllegalArgumentException(\"bad gpa\"); this.gpa = gpa; } "
            "public boolean isPassing() { return gpa >= 2.0; } "
            "public String toString() { return \"Student{name='\" + name + \"', gpa=\" + gpa + \"}\"; } "
            "public int compareTo(Student other) { int byGpa = Double.compare(other.gpa, gpa); "
            "return byGpa != 0 ? byGpa : name.compareTo(other.name); } }"
        )

    def final_behavior_spec(self) -> str:
        def setup(name: str, gpa: float) -> list[dict]:
            return [
                {"method": "setName", "args": [name]},
                {"method": "setGpa", "parameter_types": ["double"], "args": [gpa]},
            ]

        instances = [
            {"setup": setup("Bob", 3.0)},
            {"setup": setup("Amy", 3.5)},
            {"setup": setup("Zoe", 3.5)},
        ]
        return self.spec_for(
            self.make_check(
                "getter-setter-name", "behavior", 20,
                method="setName", args=["Mina"],
                expect_state={"getter": "getName", "value": "Mina"},
            ),
            self.make_check(
                "validator-gpa-negative", "behavior", 20,
                method="setGpa", parameter_types=["double"], args=[-1],
                expect_exception="IllegalArgumentException",
            ),
            self.make_check(
                "predicate-passing", "behavior", 10,
                method="isPassing", args=[], setup=setup("Mina", 3.5), expect_return=True,
            ),
            self.make_check(
                "student-tostring", "toString", 20,
                template="Student{name='{name}', gpa={gpa}}", setup=setup("Mina", 3.5),
            ),
            self.make_check(
                "student-comparable", "comparable", 30,
                instances=instances,
                comparisons=[
                    {"left": 1, "right": 0, "expected_sign": -1},
                    {"left": 1, "right": 2, "expected_sign": -1},
                    {"left": 0, "right": 2, "expected_sign": 1},
                ],
                expected_order=[1, 2, 0],
            ),
        )

    def valid_spec(self) -> str:
        return json.dumps(
            {
                "total_points": 2,
                "checks": [
                    self.make_check(
                        "field-value", "field", 2,
                        name="fieldValue", type="int", modifier="private",
                    )
                ],
            }
        )

    def test_correct_class_loads_and_returns_result_contract(self):
        output = self.compile_student("package model; public class Student { private int fieldValue; }")
        result = self.run_judge("model.Student", output, self.valid_spec())
        self.assertEqual(result["score"], 2)
        self.assertEqual(result["total_points"], 2)
        self.assertIsNone(result["failure_type"])
        self.assertEqual(result["checks"][0]["id"], "field-value")
        self.assertTrue(result["checks"][0]["passed"])
        self.assertEqual(result["checks"][0]["points_earned"], 2)
        self.assertEqual(
            set(result["checks"][0]),
            {"id", "passed", "points_earned", "expected", "actual", "error"},
        )
        self.assertIn("type=int", result["checks"][0]["expected"])
        self.assertIn("type=int", result["checks"][0]["actual"])
        self.assertIsNone(result["checks"][0]["error"])

    def test_wrong_package_is_reported_as_class_loading_failure(self):
        output = self.compile_student("package other; public class Student {}")
        result = self.run_judge("model.Student", output, self.valid_spec())
        self.assertEqual(result["failure_type"], "CLASS_LOADING_FAILURE")
        self.assertFalse(result["checks"][0]["passed"])
        self.assertIn("CLASS_LOADING_FAILURE:", result["checks"][0]["error"])

    def test_missing_class_returns_failed_checks_without_crashing(self):
        output = self.case_root / "empty_student_out"
        output.mkdir()
        result = self.run_judge("model.Student", output, self.valid_spec())
        self.assertEqual(result["failure_type"], "CLASS_LOADING_FAILURE")
        self.assertEqual(result["checks"][0]["points_earned"], 0)

    def test_classpath_outside_student_output_is_not_used_for_target_loading(self):
        external_output = self.compile_student("package model; public class Student {}")
        student_output = self.case_root / "empty_student_out"
        student_output.mkdir()
        classpath = os.pathsep.join((str(self.judge_out), str(external_output)))
        process, protocol = self.run_judge_process(
            "model.Student", student_output, self.valid_spec(), classpath=classpath
        )
        self.assertEqual(process.returncode, 0, process.stderr.decode("utf-8", errors="replace"))
        result = json.loads(protocol.decode("utf-8"))
        self.assertEqual(result["failure_type"], "CLASS_LOADING_FAILURE")

    def test_malformed_spec_returns_valid_invalid_request_result(self):
        output = self.case_root / "empty_student_out"
        output.mkdir()
        result = self.run_judge("model.Student", output, "{malformed")
        self.assertEqual(result["error_category"], "INVALID_REQUEST")
        self.assertEqual(result["checks"], [])
        self.assertEqual(result["score"], 0)

    def test_spec_rejects_missing_required_fields_null_visibility_and_extreme_numbers(self):
        missing_total = {"checks": [{"id": "x", "kind": "field", "points": 1, "is_visible": True}]}
        null_visibility = {
            "total_points": 1,
            "checks": [{"id": "x", "kind": "field", "points": 1, "is_visible": None}],
        }
        invalid_hex_escape = r'{"total_points":0,"checks":[],"extra":"\uＦＦＦＦ"}'
        huge_exponent = (
            '{"total_points":1e100000000,"checks":['
            '{"id":"x","kind":"field","points":1e100000000,"is_visible":true}]}'
        )

        for specification in (
            json.dumps(missing_total),
            json.dumps(null_visibility),
            invalid_hex_escape,
            huge_exponent,
        ):
            with self.subTest(specification=specification[:80]):
                result = self.run_judge("model.Student", self.case_root, specification)
                self.assertEqual(result["error_category"], "INVALID_REQUEST")
                self.assertEqual(result["checks"], [])

    def test_student_stdout_cannot_corrupt_json_protocol(self):
        output = self.compile_student(
            'package model; public class Student { '
            'private int fieldValue; '
            'static { System.out.println("STUDENT_STDOUT_SENTINEL"); } }'
        )
        process, protocol = self.run_judge_process(
            "model.Student", output, self.valid_spec()
        )
        self.assertEqual(process.returncode, 0, process.stderr.decode("utf-8", errors="replace"))
        self.assertIn(b"STUDENT_STDOUT_SENTINEL", process.stdout)
        self.assertEqual(process.stdout.count(b"\n"), 1)
        self.assertEqual(json.loads(protocol.decode("utf-8"))["total_points"], 2)

    def test_student_raw_file_descriptor_stdout_is_captured_separately(self):
        output = self.compile_student(
            'package model; public class Student { private int fieldValue; static { '
            'try { new java.io.FileOutputStream(java.io.FileDescriptor.out).write('
            '"RAW_FD_OUT".getBytes(java.nio.charset.StandardCharsets.UTF_8)); '
            '} catch (java.io.IOException error) { throw new RuntimeException(error); } } }'
        )
        process, protocol = self.run_judge_process("model.Student", output, self.valid_spec())
        self.assertEqual(process.returncode, 0, process.stderr.decode("utf-8", errors="replace"))
        self.assertIn(b"RAW_FD_OUT", process.stdout)
        self.assertEqual(json.loads(protocol.decode("utf-8"))["total_points"], 2)

    def test_student_stderr_is_separate_from_result_channel(self):
        output = self.compile_student(
            'package model; public class Student { private int fieldValue; static { '
            'System.err.println("STUDENT_STDERR_SENTINEL"); } }'
        )
        process, protocol = self.run_judge_process("model.Student", output, self.valid_spec())
        self.assertEqual(process.returncode, 0, process.stderr.decode("utf-8", errors="replace"))
        self.assertIn(b"STUDENT_STDERR_SENTINEL", process.stderr)
        self.assertEqual(json.loads(protocol.decode("utf-8"))["total_points"], 2)

    def test_student_json_looking_stdout_is_not_result_transport(self):
        output = self.compile_student(
            'package model; public class Student { private int fieldValue; static { '
            'System.out.println("{\\\"score\\\":999,\\\"checks\\\":[]}"); } }'
        )
        process, protocol = self.run_judge_process("model.Student", output, self.valid_spec())
        self.assertEqual(process.returncode, 0, process.stderr.decode("utf-8", errors="replace"))
        self.assertIn(b'{"score":999,"checks":[]}', process.stdout)
        self.assertEqual(json.loads(protocol.decode("utf-8"))["score"], 2)

    def test_valid_result_is_written_to_private_protocol_file(self):
        output = self.compile_student(self.behavior_sample_source())
        process, protocol = self.run_judge_process("model.Student", output, self.valid_spec())
        self.assertEqual(process.returncode, 0, process.stderr.decode("utf-8", errors="replace"))
        payload = json.loads(protocol.decode("utf-8"))
        self.assertEqual(payload["total_points"], 2)
        self.assertNotIn(b'"total_points"', process.stdout)

    def test_protocol_overflow_writes_bounded_infrastructure_marker(self):
        output = self.compile_student(self.behavior_sample_source())
        process, protocol = self.run_judge_process(
            "model.Student", output, self.valid_spec(), protocol_limit_bytes=64
        )
        self.assertEqual(process.returncode, 0, process.stderr.decode("utf-8", errors="replace"))
        self.assertEqual(protocol, b"JUDGE_PROTOCOL_LIMIT_EXCEEDED\n")
        self.assertLessEqual(len(protocol), 64)

    def test_class_initialization_exception_is_distinguished(self):
        output = self.compile_student(
            'package model; public class Student { private int fieldValue; static { '
            'if (Boolean.parseBoolean("true")) throw new IllegalStateException("init-failed-é"); '
            '} }'
        )
        result = self.run_judge("model.Student", output, self.valid_spec())
        self.assertEqual(result["failure_type"], "STUDENT_EXCEPTION")
        self.assertIn("init-failed-é", result["error"])
        self.assertFalse(result["checks"][0]["passed"])

    def test_all_structural_check_kinds_pass(self):
        output = self.compile_student(
            "package model; public class Student implements java.io.Serializable { "
            "private int age; public Student(int age) { this.age = age; } "
            "public double scale(int value) { return value * 2.0; } }"
        )
        specification = self.spec_for(
            self.make_check("field-age", "field", name="age", type="int", modifier="private"),
            self.make_check("constructor-int", "constructor", parameter_types=["int"], modifier="public"),
            self.make_check(
                "method-scale", "method", name="scale", return_type="double",
                parameter_types=["int"], modifier="public",
            ),
            self.make_check("implements-serializable", "implements", **{"interface": "Serializable"}),
        )

        result = self.run_judge("model.Student", output, specification)
        self.assertEqual(result["score"], 4)
        self.assertEqual([check["passed"] for check in result["checks"]], [True] * 4)
        self.assertTrue(all(check["error"] is None for check in result["checks"]))

    def test_wrong_field_type_reports_expected_and_actual(self):
        output = self.compile_student("package model; public class Student { private int age; }")
        specification = self.spec_for(
            self.make_check("field-age", "field", name="age", type="Integer", modifier="private")
        )
        check = self.run_judge("model.Student", output, specification)["checks"][0]
        self.assertFalse(check["passed"])
        self.assertIn("type=Integer", check["expected"])
        self.assertIn("type=int", check["actual"])
        self.assertIsNone(check["error"])

    def test_builtin_primitive_wrapper_and_string_types_resolve_separately(self):
        output = self.compile_student(
            "package model; public class Student { private int primitiveInt; private Integer boxedInt; "
            "private double primitiveDouble; private Double boxedDouble; private boolean primitiveBoolean; "
            "private Boolean boxedBoolean; private String text; }"
        )
        fields = (
            ("primitiveInt", "int"),
            ("boxedInt", "Integer"),
            ("primitiveDouble", "double"),
            ("boxedDouble", "Double"),
            ("primitiveBoolean", "boolean"),
            ("boxedBoolean", "Boolean"),
            ("text", "String"),
        )
        specification = self.spec_for(*[
            self.make_check(
                "field-" + name, "field", name=name, type=type_name, modifier="private"
            )
            for name, type_name in fields
        ])
        result = self.run_judge("model.Student", output, specification)
        self.assertEqual(result["score"], len(fields))
        self.assertEqual([check["passed"] for check in result["checks"]], [True] * len(fields))

    def test_wrong_field_modifier_fails_exact_modifier_check(self):
        output = self.compile_student("package model; public class Student { private int age; }")
        specification = self.spec_for(
            self.make_check("field-age", "field", name="age", type="int", modifier="public")
        )
        check = self.run_judge("model.Student", output, specification)["checks"][0]
        self.assertFalse(check["passed"])
        self.assertIn("modifier=public", check["expected"])
        self.assertIn("modifier=private", check["actual"])

    def test_wrong_constructor_parameters_fail_without_stopping_judge(self):
        output = self.compile_student("package model; public class Student { public Student(int age) {} }")
        specification = self.spec_for(
            self.make_check("constructor-string", "constructor", parameter_types=["String"], modifier="public")
        )
        check = self.run_judge("model.Student", output, specification)["checks"][0]
        self.assertFalse(check["passed"])
        self.assertEqual(check["error"], "CONSTRUCTOR_NOT_FOUND")
        self.assertIn("[int]", check["actual"])

    def test_wrong_method_return_type_fails(self):
        output = self.compile_student("package model; public class Student { public int score(int value) { return value; } }")
        specification = self.spec_for(
            self.make_check(
                "method-score", "method", name="score", return_type="double",
                parameter_types=["int"], modifier="public",
            )
        )
        check = self.run_judge("model.Student", output, specification)["checks"][0]
        self.assertFalse(check["passed"])
        self.assertIn("return_type=double", check["expected"])
        self.assertIn("return_type=int", check["actual"])

    def test_wrong_parameter_type_does_not_match_an_overload_by_name_only(self):
        output = self.compile_student(
            "package model; public class Student { public int score(int value) { return value; } }"
        )
        specification = self.spec_for(
            self.make_check(
                "method-score", "method", name="score", return_type="int",
                parameter_types=["Integer"], modifier="public",
            )
        )
        check = self.run_judge("model.Student", output, specification)["checks"][0]
        self.assertFalse(check["passed"])
        self.assertEqual(check["error"], "METHOD_NOT_FOUND")
        self.assertIn("parameter_types=[int]", check["actual"])

    def test_overloaded_methods_are_matched_by_name_and_parameter_types(self):
        output = self.compile_student(
            "package model; public class Student { "
            "public String pick(int value) { return \"int\"; } "
            "public int pick(String value) { return value.length(); } }"
        )
        specification = self.spec_for(
            self.make_check(
                "pick-int", "method", name="pick", return_type="String",
                parameter_types=["int"], modifier="public",
            ),
            self.make_check(
                "pick-string", "method", name="pick", return_type="int",
                parameter_types=["String"], modifier="public",
            ),
        )
        result = self.run_judge("model.Student", output, specification)
        self.assertEqual([check["passed"] for check in result["checks"]], [True, True])

    def test_primitive_and_wrapper_types_are_not_interchangeable(self):
        output = self.compile_student("package model; public class Student { public int count() { return 1; } }")
        specification = self.spec_for(
            self.make_check(
                "method-count", "method", name="count", return_type="Integer",
                parameter_types=[], modifier="public",
            )
        )
        check = self.run_judge("model.Student", output, specification)["checks"][0]
        self.assertFalse(check["passed"])
        self.assertIn("return_type=Integer", check["expected"])
        self.assertIn("return_type=int", check["actual"])

    def test_wrong_interface_requirement_fails(self):
        output = self.compile_student(
            "package model; public class Student implements java.io.Serializable {}"
        )
        specification = self.spec_for(
            self.make_check("implements-runnable", "implements", **{"interface": "Runnable"})
        )
        check = self.run_judge("model.Student", output, specification)["checks"][0]
        self.assertFalse(check["passed"])
        self.assertEqual(check["actual"], "implemented=false, direct_interfaces=[java.io.Serializable]")

    def test_array_types_resolve_for_method_parameters_and_return_type(self):
        output = self.compile_student(
            "package model; public class Student { public int[] lengths(String[] names) { return new int[names.length]; } }"
        )
        specification = self.spec_for(
            self.make_check(
                "method-lengths", "method", name="lengths", return_type="int[]",
                parameter_types=["String[]"], modifier="public",
            )
        )
        check = self.run_judge("model.Student", output, specification)["checks"][0]
        self.assertTrue(check["passed"])
        self.assertIn("return_type=int[]", check["actual"])
        self.assertIn("parameter_types=[java.lang.String[]]", check["actual"])

    def test_multiple_failures_are_reported_independently(self):
        output = self.compile_student(
            "package model; public class Student implements java.io.Serializable { "
            "private int age; public Student() {} public int score(int value) { return value; } }"
        )
        specification = self.spec_for(
            self.make_check("missing-field", "field", name="missing", type="int", modifier="private"),
            self.make_check("missing-constructor", "constructor", parameter_types=["String"], modifier="public"),
            self.make_check(
                "wrong-return", "method", name="score", return_type="double",
                parameter_types=["int"], modifier="public",
            ),
            self.make_check("malformed-check", "field", name="age", type="int"),
            self.make_check("correct-interface", "implements", **{"interface": "Serializable"}),
        )
        result = self.run_judge("model.Student", output, specification)
        self.assertEqual(len(result["checks"]), 5)
        self.assertEqual([check["passed"] for check in result["checks"]], [False, False, False, False, True])
        self.assertEqual([check["error"] for check in result["checks"][:2]], ["FIELD_NOT_FOUND", "CONSTRUCTOR_NOT_FOUND"])
        self.assertIn("INVALID_CHECK_SPEC", result["checks"][3]["error"])
        self.assertEqual(result["score"], 1)

    def test_correct_behavior_sample_scores_100_out_of_100(self):
        output = self.compile_student(self.behavior_sample_source())
        result = self.run_judge("model.Student", output, self.final_behavior_spec())
        self.assertEqual(result["score"], 100)
        self.assertEqual(result["total_points"], 100)
        self.assertEqual([check["passed"] for check in result["checks"]], [True] * 5)
        self.assertIn("java.lang.IllegalArgumentException: bad gpa", result["checks"][1]["actual"])
        self.assertIsNone(result["checks"][1]["error"])

    def test_wrong_tostring_fails_exact_template_comparison(self):
        output = self.compile_student(
            'package model; public class Student { private String name; private double gpa; '
            'public Student() {} public void setName(String name) { this.name = name; } '
            'public void setGpa(double gpa) { this.gpa = gpa; } '
            'public String toString() { return "prefix Student{name=\'" + name + "\', gpa=" + gpa + "}"; } }'
        )
        specification = self.spec_for(
            self.make_check(
                "student-tostring", "toString", template="Student{name='{name}', gpa={gpa}}",
                setup=[
                    {"method": "setName", "args": ["Mina"]},
                    {"method": "setGpa", "parameter_types": ["double"], "args": [3.5]},
                ],
            )
        )
        check = self.run_judge("model.Student", output, specification)["checks"][0]
        self.assertFalse(check["passed"])
        self.assertEqual(check["expected"], "Student{name='Mina', gpa=3.5}")
        self.assertTrue(check["actual"].startswith("prefix "))

    def test_tostring_normalizes_crlf_to_lf_before_exact_comparison(self):
        output = self.compile_student(
            'package model; public class Student { public Student() {} '
            'public String toString() { return "line1\\r\\nline2"; } }'
        )
        specification = self.spec_for(
            self.make_check("student-tostring", "toString", template="line1\nline2")
        )
        check = self.run_judge("model.Student", output, specification)["checks"][0]
        self.assertTrue(check["passed"])
        self.assertEqual(check["expected"], "line1\nline2")
        self.assertEqual(check["actual"], "line1\nline2")

    def test_validator_requires_exception_and_predicate_uses_boolean_result(self):
        output = self.compile_student(
            "package model; public class Student { private double gpa; "
            "public Student() {} public void setGpa(double gpa) { this.gpa = gpa; } "
            "public boolean isPassing() { return gpa >= 2.0; } }"
        )
        specification = self.spec_for(
            self.make_check(
                "validator", "behavior", method="setGpa", parameter_types=["double"],
                args=[-1], expect_exception="IllegalArgumentException",
            ),
            self.make_check(
                "predicate", "behavior", method="isPassing", args=[],
                setup=[{"method": "setGpa", "parameter_types": ["double"], "args": [1.0]}],
                expect_return=False,
            ),
        )
        result = self.run_judge("model.Student", output, specification)
        self.assertEqual([check["passed"] for check in result["checks"]], [False, True])
        self.assertEqual(result["checks"][0]["error"], "EXPECTED_EXCEPTION_NOT_THROWN")

    def test_wrong_comparable_order_and_sign_fail(self):
        output = self.compile_student(
            "package model; public class Student implements Comparable<Student> { private int rank; "
            "public Student(int rank) { this.rank = rank; } "
            "public int compareTo(Student other) { return Integer.compare(rank, other.rank); } }"
        )
        specification = self.spec_for(
            self.make_check(
                "rank-order", "comparable",
                instances=[
                    {"constructor_parameter_types": ["int"], "constructor_args": [1]},
                    {"constructor_parameter_types": ["int"], "constructor_args": [2]},
                ],
                comparisons=[{"left": 1, "right": 0, "expected_sign": -1}],
                expected_order=[1, 0],
            )
        )
        check = self.run_judge("model.Student", output, specification)["checks"][0]
        self.assertFalse(check["passed"])
        self.assertIn("1 vs 0=-1", check["expected"])
        self.assertIn("1 vs 0=1", check["actual"])

    def test_infinite_getter_is_stopped_by_runner_timeout(self):
        output = self.compile_student(
            "package model; public class Student { public String getName() { while (true) {} } }"
        )
        specification = self.spec_for(
            self.make_check(
                "infinite-getter", "behavior", method="getName", args=[], expect_return="never",
            )
        )
        with self.assertRaises(subprocess.TimeoutExpired):
            self.run_judge_process("model.Student", output, specification, timeout=1.5)

    def test_system_exit_is_classified_as_re_and_next_judge_run_recovers(self):
        output = self.compile_student(
            "package model; public class Student { public void terminate() { System.exit(0); } }"
        )
        specification = self.spec_for(
            self.make_check("terminate", "behavior", method="terminate", args=[], expect_return=None)
        )
        exited, exit_protocol = self.run_judge_process(
            "model.Student", output, specification
        )
        self.assertEqual(exited.returncode, 0, exited.stderr.decode("utf-8", errors="replace"))
        exit_payload = json.loads(exit_protocol.decode("utf-8"))
        self.assertEqual(exit_payload["failure_type"], "STUDENT_PROCESS_EXIT")
        self.assertEqual(
            classify_judge_process_result(self.as_process_result(exited, exit_protocol)), "RE"
        )

        recovered_output = self.compile_student(self.behavior_sample_source())
        recovered, recovered_protocol = self.run_judge_process(
            "model.Student", recovered_output, self.final_behavior_spec(), timeout=15
        )
        self.assertEqual(recovered.returncode, 0, recovered.stderr.decode("utf-8", errors="replace"))
        recovered_payload = json.loads(recovered_protocol.decode("utf-8"))
        self.assertEqual(recovered_payload["score"], 100)
        self.assertEqual(
            classify_judge_process_result(self.as_process_result(recovered, recovered_protocol)),
            "AC",
        )

    @staticmethod
    def as_process_result(
        process: subprocess.CompletedProcess, protocol: bytes
    ) -> ProcessResult:
        stdout = process.stdout.decode("utf-8", errors="replace")
        stderr = process.stderr.decode("utf-8", errors="replace")
        return ProcessResult(
            status=ProcessStatus.EXITED,
            exit_code=process.returncode,
            duration_ms=0,
            stdout=protocol.decode("utf-8", errors="replace"),
            stderr=stderr,
            stdout_bytes=len(protocol),
            stderr_bytes=len(process.stderr),
            stdout_truncated=False,
            stderr_truncated=False,
        )


if __name__ == "__main__":
    unittest.main()
