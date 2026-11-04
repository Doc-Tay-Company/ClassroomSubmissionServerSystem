from __future__ import annotations

from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
import http.client
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
import urllib.parse

from app import storage


_TEST_TEMP = None
_TEST_DATA_ROOT = os.getenv("CSS_CODE_API_TEST_DATA")
if _TEST_DATA_ROOT:
    _TEST_DATA_ROOT = Path(_TEST_DATA_ROOT)
else:
    _TEST_TEMP = tempfile.TemporaryDirectory(prefix="css-code-api-")
    _TEST_DATA_ROOT = Path(_TEST_TEMP.name)
storage.DATA_DIR = _TEST_DATA_ROOT / "data"
storage.LOG_DIR = _TEST_DATA_ROOT / "logs"
storage.DATA_DIR.mkdir(parents=True, exist_ok=True)
storage.LOG_DIR.mkdir(parents=True, exist_ok=True)

from app import main
from app.security import new_session


_VISIBLE = {
    "id": "visible",
    "stdin": "hello\n",
    "expected_stdout": "hello\n",
    "is_visible": True,
    "points": 8,
    "compare_mode": "exact",
}
_HIDDEN = {
    "id": "hidden",
    "stdin": "secret-input\n",
    "expected_stdout": "secret-expected\n",
    "is_visible": False,
    "points": 2,
    "compare_mode": "exact",
}
_SAMPLE_SOURCE = 'value = input()\nprint("secret-expected" if value == "secret-input" else value)\n'


def _execution(*, visible_passed=True, hidden_passed=True, verdict="AC"):
    return {
        "verdict": verdict,
        "score": (8 if visible_passed else 0) + (2 if hidden_passed else 0),
        "total_points": 10,
        "duration_ms": 17,
        "error": None,
        "error_category": None,
        "compile_result": None,
        "tests": [
            {
                "id": "visible",
                "verdict": "AC" if visible_passed else "WA",
                "passed": visible_passed,
                "points": 8,
                "points_earned": 8 if visible_passed else 0,
                "is_visible": True,
                "expected_stdout": "hello\n",
                "actual_stdout": "hello\n" if visible_passed else "wrong\n",
                "stderr": "",
                "duration_ms": 5,
                "error": None,
            },
            {
                "id": "hidden",
                "verdict": "WA",
                "passed": hidden_passed,
                "points": 2,
                "points_earned": 2 if hidden_passed else 0,
                "is_visible": False,
                "expected_stdout": "secret-expected\n",
                "actual_stdout": "secret-expected\n" if hidden_passed else "secret-actual\n",
                "stderr": "",
                "duration_ms": 7,
                "error": "hidden mismatch",
            },
        ],
    }


class CodeApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        main.initialize()
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), main.Handler)
        cls.server.daemon_threads = True
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.port = cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)
        if _TEST_TEMP is not None:
            _TEST_TEMP.cleanup()

    def setUp(self):
        main.initialize()
        for name, value in {
            "students.json": {"student-1": {"active": True}},
            "admins.json": {"admin-1": {"active": True}},
            "settings.json": {
                "exam_state": "idle",
                "exam_released": False,
                "exam_release_id": None,
                "exam_duration_minutes": 90,
                "submission_policy": "configurable",
                "max_submissions": 2,
                "exam_participants": [],
            },
            "assignments.json": {},
            "questions.json": {},
            "code_exams.json": {},
            "code_submissions.json": {},
            "code_runs.json": [],
            "sessions.json": {},
            "login_attempts.json": {},
        }.items():
            storage.write_json(name, value)
        self.admin_cookie = new_session("admin-1", "admin", "127.0.0.1", "test")
        self.student_cookie = new_session("student-1", "student", "127.0.0.1", "test")

    def request(self, method, path, *, cookie=None, payload=None, raw_body=None, content_type=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {}
        if cookie:
            headers["Cookie"] = f"css_session={cookie}"
        if payload is not None:
            raw_body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            content_type = "application/json"
        if raw_body is not None:
            headers["Content-Type"] = content_type or "application/octet-stream"
        connection.request(method, path, body=raw_body, headers=headers)
        response = connection.getresponse()
        raw = response.read()
        status = response.status
        connection.close()
        parsed = json.loads(raw.decode("utf-8")) if raw else None
        return status, parsed

    def create_started_code_exam(self, *, use_real_runner=False):
        question = {
            "id": "echo-question",
            "title": "Echo",
            "statement": "Print the input.",
            "language": "python",
            "grading_mode": "stdio",
            "starter_code": "",
            "time_limit_seconds": 1,
            "memory_limit_mb": 128,
            "max_output_bytes": 4096,
            "allow_pretest": True,
            "max_pretest_runs": 20,
            "total_points": 10,
            "tests": [_VISIBLE, _HIDDEN],
        }
        status, created = self.request("POST", "/api/admin/questions", cookie=self.admin_cookie, payload=question)
        self.assertEqual(status, 201, created)
        if use_real_runner:
            status, published = self.request(
                "POST",
                "/api/admin/questions/echo-question/publish",
                cookie=self.admin_cookie,
                payload={"sample_source": _SAMPLE_SOURCE},
            )
        else:
            with patch("app.code_exams.execute_question", return_value=_execution()):
                status, published = self.request(
                    "POST",
                    "/api/admin/questions/echo-question/publish",
                    cookie=self.admin_cookie,
                    payload={"sample_source": "print(input())\n"},
                )
        self.assertEqual(status, 200, published)
        status, created_exam = self.request(
            "POST",
            "/api/admin/code-exams",
            cookie=self.admin_cookie,
            payload={
                "title": "Code exam",
                "question_ids": ["echo-question"],
                "show_final_score_immediately": False,
                "pretest_cooldown_seconds": 0,
            },
        )
        self.assertEqual(status, 201, created_exam)
        exam_id = created_exam["code_exam"]["id"]
        body = urllib.parse.urlencode({"mode": "random", "code_exam_id": exam_id, "code_only": "true"}).encode()
        with patch("app.exams.list_exam_files", return_value=[]):
            status, distributed = self.request(
                "POST",
                "/api/admin/distribute",
                cookie=self.admin_cookie,
                raw_body=body,
                content_type="application/x-www-form-urlencoded",
            )
        self.assertEqual(status, 200, distributed)
        status, started = self.request("POST", "/api/admin/start-exam", cookie=self.admin_cookie, raw_body=b"")
        self.assertEqual(status, 200, started)
        status, student_started = self.request("POST", "/api/student/start", cookie=self.student_cookie, raw_body=b"")
        self.assertEqual(status, 200, student_started)
        return exam_id

    def test_admin_publish_snapshot_and_code_only_lifecycle(self):
        self.create_started_code_exam()
        status, response = self.request("GET", "/api/student/code-exam", cookie=self.student_cookie)
        self.assertEqual(status, 200, response)
        question = response["questions"][0]
        self.assertEqual([item["id"] for item in question["tests"]], ["visible"])
        self.assertNotIn("total_points", question)
        self.assertNotIn("secret-input", json.dumps(response))
        assignment = storage.read_json("assignments.json")["student-1"]
        self.assertIsNone(assignment["exam_file"])
        self.assertEqual(assignment["status"], "in_progress")

    def test_pretest_filters_hidden_data_and_does_not_return_score(self):
        self.create_started_code_exam()
        with patch("app.code_exams.execute_question", return_value=_execution(visible_passed=False, verdict="WA")) as execute:
            status, result = self.request(
                "POST",
                "/api/student/code/run",
                cookie=self.student_cookie,
                payload={"question_id": "echo-question", "source_code": "print(input())\n"},
            )
        self.assertEqual(status, 200, result)
        self.assertNotIn("score", result)
        self.assertNotIn("total_points", result)
        self.assertEqual([item["id"] for item in result["results"]], ["visible"])
        self.assertNotIn("points_earned", result["results"][0])
        self.assertNotIn("secret-expected", json.dumps(result))
        self.assertFalse(storage.read_json("assignments.json")["student-1"].get("question_submitted", False))
        self.assertTrue(execute.call_args.kwargs["visible_only"])

    def test_reflection_pretest_passes_visible_checks_only_to_judge(self):
        from app.code_exams import execute_question

        question = {
            "grading_mode": "reflection",
            "target_class": "Student",
            "target_package": "model",
            "checks": [
                {"id": "visible", "is_visible": True, "points": 0.1},
                {"id": "hidden", "is_visible": False, "points": 0.2},
            ],
            "total_points": 0.3,
            "time_limit_seconds": 2,
            "max_output_bytes": 1024,
        }
        judge_result = Mock()
        judge_result.to_dict.return_value = {"verdict": "AC"}
        with patch("app.code_exams.run_reflection_judge", return_value=judge_result) as run_judge:
            execute_question(question, "class Student {}", visible_only=True)

        specification = run_judge.call_args.args[2]
        self.assertEqual([check["id"] for check in specification["checks"]], ["visible"])
        self.assertEqual(specification["total_points"], 0.1)

    def test_stdio_pretest_enables_visible_only_execution(self):
        from app.code_exams import execute_question

        question = {
            "grading_mode": "stdio",
            "language": "python",
            "tests": [_VISIBLE, _HIDDEN],
            "time_limit_seconds": 2,
            "max_output_bytes": 1024,
        }
        stdio_result = Mock()
        stdio_result.to_dict.return_value = {"verdict": "AC"}
        with patch("app.code_exams.run_stdio", return_value=stdio_result) as run_stdio:
            execute_question(question, "print(input())", visible_only=True)

        self.assertTrue(run_stdio.call_args.kwargs["visible_only"])

    def test_api_runs_python_submission_through_stdio_runner(self):
        self.create_started_code_exam(use_real_runner=True)
        status, result = self.request(
            "POST",
            "/api/student/code/run",
            cookie=self.student_cookie,
            payload={"question_id": "echo-question", "source_code": _SAMPLE_SOURCE},
        )
        self.assertEqual(status, 200, result)
        self.assertEqual(result["verdict"], "AC")
        self.assertEqual([item["id"] for item in result["results"]], ["visible"])
        self.assertNotIn("score", result)
        self.assertNotIn("secret-expected", json.dumps(result))

        status, submitted = self.request(
            "POST",
            "/api/student/code/submit",
            cookie=self.student_cookie,
            payload={"question_id": "echo-question", "source_code": _SAMPLE_SOURCE},
        )
        self.assertEqual(status, 201, submitted)
        record = storage.read_json("code_submissions.json")["student-1"][0]
        self.assertEqual(record["status"], "graded")
        self.assertEqual(record["score"], 10)
        self.assertNotIn("secret-expected", json.dumps(submitted))

    def test_submit_keeps_score_private_until_exam_ends_and_keeps_zip_route(self):
        self.create_started_code_exam()
        boundary = "css-zip-boundary"
        zip_body = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="file"; filename="answer.zip"\r\n'
            "Content-Type: application/zip\r\n\r\n"
        ).encode() + b"PK\x03\x04dummy\r\n" + f"--{boundary}--\r\n".encode()
        def accept_zip(*args):
            assignments = storage.read_json("assignments.json")
            assignments["student-1"]["status"] = "submitted"
            storage.write_json("assignments.json", assignments)
            return {"filename": "answer.zip"}

        with patch("app.main.accept_submission", side_effect=accept_zip) as accept:
            status, zip_result = self.request(
                "POST",
                "/api/student/submit",
                cookie=self.student_cookie,
                raw_body=zip_body,
                content_type=f"multipart/form-data; boundary={boundary}",
            )
        self.assertEqual(status, 200, zip_result)
        accept.assert_called_once()

        with patch("app.code_exams.execute_question", return_value=_execution()):
            status, result = self.request(
                "POST",
                "/api/student/code/submit",
                cookie=self.student_cookie,
                payload={"question_id": "echo-question", "source_code": "print(input())\n"},
            )
        self.assertEqual(status, 201, result)
        self.assertEqual(result["submission"]["status"], "submitted")
        self.assertNotIn("score", result["submission"])
        self.assertNotIn("secret-expected", json.dumps(result))
        self.assertEqual(storage.read_json("assignments.json")["student-1"]["status"], "submitted")

        status, _ = self.request("POST", "/api/admin/end-exam", cookie=self.admin_cookie, raw_body=b"")
        self.assertEqual(status, 200)
        status, final = self.request(
            "GET",
            "/api/student/code/submission?question_id=echo-question",
            cookie=self.student_cookie,
        )
        self.assertEqual(status, 200, final)
        self.assertEqual(final["score"], 10)
        self.assertEqual([item["id"] for item in final["results"]], ["visible"])
        self.assertNotIn("secret-expected", json.dumps(final))

    def test_admin_code_results_include_hidden_details_and_require_admin_role(self):
        exam_id = self.create_started_code_exam()
        with patch("app.code_exams.execute_question", return_value=_execution()):
            status, _ = self.request(
                "POST",
                "/api/student/code/submit",
                cookie=self.student_cookie,
                payload={"question_id": "echo-question", "source_code": "print(input())\n"},
            )
        self.assertEqual(status, 201)

        path = f"/api/admin/code-results?exam_id={exam_id}&student_id=student-1"
        status, result = self.request("GET", path, cookie=self.admin_cookie)
        self.assertEqual(status, 200, result)
        self.assertEqual(len(result["submissions"]), 1)
        self.assertEqual(result["submissions"][0]["student_id"], "student-1")
        self.assertIn("secret-expected", json.dumps(result["submissions"][0]["results"]))
        self.assertEqual(result["submissions"][0]["source_code"], "print(input())\n")

        status, denied = self.request("GET", path, cookie=self.student_cookie)
        self.assertEqual(status, 403, denied)

    def test_routes_require_student_role_and_enforce_server_deadline(self):
        self.create_started_code_exam()
        status, denied = self.request(
            "POST",
            "/api/student/code/run",
            cookie=self.admin_cookie,
            payload={"question_id": "echo-question", "source_code": "print(input())"},
        )
        self.assertEqual(status, 403, denied)
        assignments = storage.read_json("assignments.json")
        assignments["student-1"]["ends_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        storage.write_json("assignments.json", assignments)
        with patch("app.code_exams.execute_question") as execute:
            status, rejected = self.request(
                "POST",
                "/api/student/code/run",
                cookie=self.student_cookie,
                payload={"question_id": "echo-question", "source_code": "print(input())"},
            )
        self.assertEqual(status, 403, rejected)
        execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
