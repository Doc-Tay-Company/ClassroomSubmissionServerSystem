from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
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
from app.java_runner import JDKConfigurationError


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

    def request(self, method, path, *, cookie=None, payload=None, raw_body=None, content_type=None, parse_json=True):
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
        parsed = json.loads(raw.decode("utf-8")) if raw and parse_json else raw
        return status, parsed

    def create_published_question(self, question_id, *, statement="Print the input."):
        question = {
            "id": question_id,
            "title": question_id,
            "statement": statement,
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
        status, created = self.request(
            "POST", "/api/admin/questions", cookie=self.admin_cookie, payload=question
        )
        self.assertEqual(status, 201, created)
        with patch("app.code_exams.execute_question", return_value=_execution()):
            status, validation = self.request(
                "POST",
                f"/api/admin/questions/{question_id}/validate",
                cookie=self.admin_cookie,
                payload={"sample_source": _SAMPLE_SOURCE},
            )
            self.assertEqual(status, 200, validation)
            status, published = self.request(
                "POST",
                f"/api/admin/questions/{question_id}/publish",
                cookie=self.admin_cookie,
            )
        self.assertEqual(status, 200, published)
        return published["question"]

    def create_draft_code_exam(self, question_ids):
        status, result = self.request(
            "POST",
            "/api/admin/code-exams",
            cookie=self.admin_cookie,
            payload={"title": "Draft exam", "question_ids": question_ids},
        )
        self.assertEqual(status, 201, result)
        return result["code_exam"]

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
            status, validation = self.request(
                "POST",
                "/api/admin/questions/echo-question/validate",
                cookie=self.admin_cookie,
                payload={"sample_source": _SAMPLE_SOURCE},
            )
        else:
            with patch("app.code_exams.execute_question", return_value=_execution()):
                status, validation = self.request(
                    "POST",
                    "/api/admin/questions/echo-question/validate",
                    cookie=self.admin_cookie,
                    payload={"sample_source": "print(input())\n"},
                )
        self.assertEqual(status, 200, validation)
        status, published = self.request(
            "POST",
            "/api/admin/questions/echo-question/publish",
            cookie=self.admin_cookie,
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
        distribution = {"mode": "random", "code_exam_id": exam_id, "code_only": "true"}
        body = urllib.parse.urlencode(distribution).encode()
        files = []
        with patch("app.exams.list_exam_files", return_value=files):
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

    def test_exam_records_reject_mixed_types_and_require_one_type_to_publish(self):
        mixed = {
            "title": "Mixed exam",
            "items": [
                {"type": "code", "question_ids": ["echo-question"]},
                {
                    "type": "zip",
                    "distribution_mode": "selected",
                    "distribution_config": {"exam_files": ["exam.pdf"]},
                },
            ],
        }
        status, result = self.request(
            "POST", "/api/admin/exam-records", cookie=self.admin_cookie, payload=mixed
        )
        self.assertEqual(status, 400, result)
        self.assertEqual(result["fields"], ["items"])

        status, created = self.request(
            "POST",
            "/api/admin/exam-records",
            cookie=self.admin_cookie,
            payload={"title": "Empty draft", "items": []},
        )
        self.assertEqual(status, 201, created)
        status, result = self.request(
            "POST",
            f"/api/admin/exam-records/{created['exam']['id']}/publish",
            cookie=self.admin_cookie,
        )
        self.assertEqual(status, 400, result)
        self.assertIn("items", result["fields"])

    def test_zip_only_exam_publishes_without_a_code_snapshot(self):
        payload = {
            "title": "ZIP-only exam",
            "config": {"participants": ["student1"]},
            "items": [
                {
                    "type": "zip",
                    "distribution_mode": "selected",
                    "distribution_config": {"exam_files": ["exam.pdf"]},
                }
            ],
        }
        with patch("app.general_exams.list_exam_files", return_value=[{"name": "exam.pdf"}]), patch(
            "app.exams.list_exam_files", return_value=[{"name": "exam.pdf"}]
        ):
            status, created = self.request(
                "POST", "/api/admin/exam-records", cookie=self.admin_cookie, payload=payload
            )
            self.assertEqual(status, 201, created)
            status, published = self.request(
                "POST",
                f"/api/admin/exam-records/{created['exam']['id']}/publish",
                cookie=self.admin_cookie,
            )
        self.assertEqual(status, 200, published)
        self.assertEqual(published["exam"]["status"], "distributed")
        self.assertEqual([item["type"] for item in published["exam"]["items"]], ["zip"])
        self.assertEqual(storage.read_json("code_exams.json"), {})

    def test_legacy_distribution_rejects_mixed_code_and_file_exam(self):
        requests = (
            {"mode": "selected", "exam_files": "exam.pdf", "code_exam_id": "code-exam-1", "code_only": "false"},
            {"mode": "selected", "exam_files": "exam.pdf", "code_exam_id": "code-exam-1", "code_only": "true"},
        )
        with patch("app.exams.list_exam_files", return_value=[{"name": "exam.pdf"}]), patch(
            "app.exams.prepare_code_exam_distribution"
        ) as prepare:
            for payload in requests:
                with self.subTest(code_only=payload["code_only"]):
                    body = urllib.parse.urlencode(payload).encode()
                    status, result = self.request(
                        "POST",
                        "/api/admin/distribute",
                        cookie=self.admin_cookie,
                        raw_body=body,
                        content_type="application/x-www-form-urlencoded",
                    )
                    self.assertEqual(status, 400, result)
                    self.assertIn("không thể kết hợp", result["detail"])
        prepare.assert_not_called()
        self.assertFalse(storage.read_json("settings.json")["exam_released"])

    def test_admin_publish_snapshot_and_code_only_lifecycle(self):
        self.create_started_code_exam()
        status, response = self.request("GET", "/api/student/code-exam", cookie=self.student_cookie)
        self.assertEqual(status, 200, response)
        question = response["questions"][0]
        self.assertEqual([item["id"] for item in question["tests"]], ["visible"])
        self.assertNotIn("total_points", question)
        self.assertNotIn("secret-input", json.dumps(response))
        self.assertEqual(storage.read_json("questions.json")["echo-question"]["usage_count"], 1)
        assignment = storage.read_json("assignments.json")["student-1"]
        self.assertIsNone(assignment["exam_file"])
        self.assertEqual(assignment["status"], "in_progress")

    def test_code_exam_creation_rejects_duplicate_question_ids_with_422(self):
        self.create_published_question("duplicate-target")
        status, response = self.request(
            "POST",
            "/api/admin/code-exams",
            cookie=self.admin_cookie,
            payload={"title": "Duplicate exam", "question_ids": ["duplicate-target", "duplicate-target"]},
        )
        self.assertEqual(status, 422, response)
        self.assertIn("detail", response)

    def test_code_exam_update_refreshes_ordered_snapshots_only_for_drafts(self):
        first = self.create_published_question("first-question")
        second = self.create_published_question("second-question")
        exam = self.create_draft_code_exam(["first-question", "second-question"])
        exam_id = exam["id"]
        original_first_snapshot = exam["questions"][0]
        initial_usage = {
            question_id: storage.read_json("questions.json")[question_id]["usage_count"]
            for question_id in ("first-question", "second-question")
        }

        updated_bank_question = dict(first)
        updated_bank_question["statement"] = "Updated after exam creation."
        status, updated = self.request(
            "POST",
            "/api/admin/questions/first-question/update",
            cookie=self.admin_cookie,
            payload=updated_bank_question,
        )
        self.assertEqual(status, 200, updated)
        self.assertEqual(
            storage.read_json("code_exams.json")[exam_id]["questions"][0]["statement"],
            original_first_snapshot["statement"],
        )
        with patch("app.code_exams.execute_question", return_value=_execution()):
            status, validation = self.request(
                "POST",
                "/api/admin/questions/first-question/validate",
                cookie=self.admin_cookie,
                payload={"sample_source": _SAMPLE_SOURCE},
            )
        self.assertEqual(status, 200, validation)
        status, republished = self.request(
            "POST",
            "/api/admin/questions/first-question/publish",
            cookie=self.admin_cookie,
        )
        self.assertEqual(status, 200, republished)

        payload = {
            "title": "Reordered and refreshed",
            "question_ids": ["second-question", "first-question"],
            "submission_policy": "configurable",
            "max_submissions": 2,
            "show_final_score_immediately": True,
            "allow_pretest": True,
            "max_pretest_runs": 20,
            "pretest_cooldown_seconds": 2,
        }
        status, response = self.request(
            "PUT",
            f"/api/admin/code-exams/{exam_id}",
            cookie=self.admin_cookie,
            payload=payload,
        )
        self.assertEqual(status, 200, response)
        refreshed = response["code_exam"]
        self.assertEqual([item["question_id"] for item in refreshed["questions"]], payload["question_ids"])
        self.assertEqual([item["order"] for item in refreshed["questions"]], [0, 1])
        self.assertEqual(refreshed["questions"][1]["statement"], "Updated after exam creation.")
        self.assertEqual(refreshed["questions"][1]["snapshot_version"], republished["question"]["version"])
        self.assertEqual(refreshed["created_at"], exam["created_at"])
        usages_after_update = storage.read_json("questions.json")
        self.assertEqual(
            usages_after_update["first-question"]["usage_count"], initial_usage["first-question"]
        )
        self.assertEqual(
            usages_after_update["second-question"]["usage_count"], initial_usage["second-question"]
        )

        payload["question_ids"] = ["first-question"]
        status, response = self.request(
            "PUT",
            f"/api/admin/code-exams/{exam_id}",
            cookie=self.admin_cookie,
            payload=payload,
        )
        self.assertEqual(status, 200, response)
        usages_after_removal = storage.read_json("questions.json")
        self.assertEqual(
            usages_after_removal["first-question"]["usage_count"], initial_usage["first-question"]
        )
        self.assertEqual(
            usages_after_removal["second-question"]["usage_count"],
            initial_usage["second-question"] - 1,
        )

        status, missing = self.request(
            "PUT",
            "/api/admin/code-exams/not-a-real-exam",
            cookie=self.admin_cookie,
            payload=payload,
        )
        self.assertEqual(status, 404, missing)
        status, duplicate = self.request(
            "PUT",
            f"/api/admin/code-exams/{exam_id}",
            cookie=self.admin_cookie,
            payload={**payload, "question_ids": ["first-question", "first-question"]},
        )
        self.assertEqual(status, 422, duplicate)
        self.assertEqual(
            [item["question_id"] for item in storage.read_json("code_exams.json")[exam_id]["questions"]],
            payload["question_ids"],
        )

    def test_code_exam_update_after_distribution_is_conflict(self):
        exam_id = self.create_started_code_exam()
        payload = {
            "title": "Cannot update distributed exam",
            "question_ids": ["echo-question"],
        }
        status, response = self.request(
            "PUT",
            f"/api/admin/code-exams/{exam_id}",
            cookie=self.admin_cookie,
            payload=payload,
        )
        self.assertEqual(status, 409, response)
        self.assertEqual(storage.read_json("code_exams.json")[exam_id]["status"], "started")

    def test_code_exam_update_checks_auth_role_and_missing_exam(self):
        question = self.create_published_question("update-auth-question")
        payload = {"title": "Auth test", "question_ids": [question["id"]]}
        status, response = self.request(
            "PUT",
            "/api/admin/code-exams/not-found",
            cookie=self.admin_cookie,
            payload=payload,
        )
        self.assertEqual(status, 404, response)
        status, response = self.request(
            "PUT",
            "/api/admin/code-exams/not-found",
            cookie=self.student_cookie,
            payload=payload,
        )
        self.assertEqual(status, 403, response)
        status, response = self.request(
            "PUT",
            "/api/admin/code-exams/not-found",
            payload=payload,
        )
        self.assertEqual(status, 401, response)

    def test_exam_end_releases_scores_for_hidden_policy(self):
        exam_id = self.create_started_code_exam()
        with patch("app.code_exams.execute_question", return_value=_execution()):
            status, submitted = self.request(
                "POST",
                "/api/student/code/submit",
                cookie=self.student_cookie,
                payload={"question_id": "echo-question", "source_code": "print(input())\n"},
            )
        self.assertEqual(status, 201, submitted)
        self.assertNotIn("score", submitted["submission"])
        self.assertEqual(
            self.request("POST", "/api/admin/end-exam", cookie=self.admin_cookie, raw_body=b"")[0],
            200,
        )
        record = storage.read_json("code_submissions.json")["student-1"][0]
        self.assertEqual(record["exam_score"], 10)
        status, result = self.request(
            "GET",
            "/api/student/code/submission?question_id=echo-question",
            cookie=self.student_cookie,
        )
        self.assertEqual(status, 200, result)
        self.assertEqual(result["score"], 10)
        self.assertEqual(result["exam_score"], 10)
        self.assertEqual(storage.read_json("code_exams.json")[exam_id]["status"], "ended")

    def test_code_exam_routes_map_invalid_json_to_422_without_changing_shared_parser(self):
        status, response = self.request(
            "POST",
            "/api/admin/code-exams",
            cookie=self.admin_cookie,
            raw_body=b"{",
            content_type="application/json",
        )
        self.assertEqual(status, 422, response)
        status, response = self.request(
            "POST",
            "/api/admin/questions",
            cookie=self.admin_cookie,
            raw_body=b"{",
            content_type="application/json",
        )
        self.assertEqual(status, 400, response)

    def test_java_stdio_question_api_distributes_total_points_equally(self):
        question = {
            "id": "java-equal-points",
            "title": "Java equal points",
            "statement": "Echo each input.",
            "language": "java",
            "grading_mode": "stdio",
            "target_class": "Main",
            "time_limit_seconds": 2,
            "memory_limit_mb": 256,
            "max_output_bytes": 4096,
            "total_points": 1,
            "tests": [
                {
                    "id": f"case-{index}",
                    "stdin": f"{index}\n",
                    "expected_stdout": f"{index}\n",
                    "is_visible": index % 2 == 0,
                    "compare_mode": "exact",
                }
                for index in range(10)
            ],
        }

        status, response = self.request(
            "POST",
            "/api/admin/questions",
            cookie=self.admin_cookie,
            payload=question,
        )
        self.assertEqual(status, 201, response)
        points = [test["points"] for test in response["question"]["tests"]]
        self.assertEqual(points, [0.1] * 10)
        self.assertEqual(
            sum((Decimal(str(point)) for point in points), Decimal(0)),
            Decimal(str(response["question"]["total_points"])),
        )

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
        self.assertEqual(storage.read_json("assignments.json")["student-1"]["status"], "submitted")
        self.assertNotIn("secret-expected", json.dumps(submitted))

    def test_code_submission_keeps_score_private_until_exam_ends(self):
        self.create_started_code_exam()
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

    def test_code_only_exam_rejects_file_submission(self):
        self.create_started_code_exam()
        boundary = "css-code-only-boundary"
        body = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="file"; filename="answer.zip"\r\n'
            "Content-Type: application/zip\r\n\r\n"
        ).encode() + b"PK\x03\x04dummy\r\n" + f"--{boundary}--\r\n".encode()
        status, result = self.request(
            "POST",
            "/api/student/submit",
            cookie=self.student_cookie,
            raw_body=body,
            content_type=f"multipart/form-data; boundary={boundary}",
        )
        self.assertEqual(status, 400, result)
        self.assertEqual(storage.read_json("assignments.json")["student-1"]["status"], "in_progress")

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

    def test_question_crud_preserves_versions_and_blocks_deleting_used_questions(self):
        question = {
            "id": "draft-question",
            "title": "Draft",
            "language": "python",
            "grading_mode": "stdio",
            "total_points": 10,
            "tests": [_VISIBLE, _HIDDEN],
        }
        status, created = self.request(
            "POST", "/api/admin/questions", cookie=self.admin_cookie, payload=question
        )
        self.assertEqual(status, 201, created)

        status, loaded = self.request(
            "GET", "/api/admin/questions/draft-question", cookie=self.admin_cookie
        )
        self.assertEqual(status, 200, loaded)
        updated_payload = dict(loaded["question"])
        updated_payload["statement"] = "Updated statement."
        status, updated = self.request(
            "POST",
            "/api/admin/questions/draft-question/update",
            cookie=self.admin_cookie,
            payload=updated_payload,
        )
        self.assertEqual(status, 200, updated)
        self.assertEqual(updated["question"]["version"], 2)
        self.assertEqual(updated["question"]["status"], "draft")

        status, duplicate = self.request(
            "POST",
            "/api/admin/questions/draft-question/duplicate",
            cookie=self.admin_cookie,
            raw_body=b"",
        )
        self.assertEqual(status, 201, duplicate)
        duplicate_id = duplicate["question"]["id"]
        self.assertNotEqual(duplicate_id, "draft-question")
        status, deleted = self.request(
            "POST",
            f"/api/admin/questions/{duplicate_id}/delete",
            cookie=self.admin_cookie,
            raw_body=b"",
        )
        self.assertEqual(status, 200, deleted)

        exam_id = self.create_started_code_exam()
        status, blocked = self.request(
            "POST",
            "/api/admin/questions/echo-question/delete",
            cookie=self.admin_cookie,
            raw_body=b"",
        )
        self.assertEqual(status, 409, blocked)
        status, archived = self.request(
            "POST",
            "/api/admin/questions/echo-question/archive",
            cookie=self.admin_cookie,
            raw_body=b"",
        )
        self.assertEqual(status, 200, archived)
        self.assertEqual(archived["question"]["status"], "archived")
        self.assertEqual(storage.read_json("code_exams.json")[exam_id]["status"], "started")
        status, rejected = self.request(
            "POST",
            "/api/admin/questions/echo-question/update",
            cookie=self.admin_cookie,
            payload=archived["question"],
        )
        self.assertEqual(status, 409, rejected)

    def test_admin_can_regrade_after_question_update_and_history_is_retained(self):
        exam_id = self.create_started_code_exam()
        with patch("app.code_exams.execute_question", return_value=_execution()):
            status, submitted = self.request(
                "POST",
                "/api/student/code/submit",
                cookie=self.student_cookie,
                payload={"question_id": "echo-question", "source_code": "print(input())\n"},
            )
        self.assertEqual(status, 201, submitted)
        submission_id = storage.read_json("code_submissions.json")["student-1"][0]["id"]

        status, _ = self.request(
            "POST", "/api/admin/end-exam", cookie=self.admin_cookie, raw_body=b""
        )
        self.assertEqual(status, 200)
        current = storage.read_json("questions.json")["echo-question"]
        current["statement"] = "Corrected statement."
        status, updated = self.request(
            "POST",
            "/api/admin/questions/echo-question/update",
            cookie=self.admin_cookie,
            payload=current,
        )
        self.assertEqual(status, 200, updated)
        with patch("app.code_exams.execute_question", return_value=_execution()):
            status, validation = self.request(
                "POST",
                "/api/admin/questions/echo-question/validate",
                cookie=self.admin_cookie,
                payload={"sample_source": _SAMPLE_SOURCE},
            )
        self.assertEqual(status, 200, validation)
        status, republished = self.request(
            "POST",
            "/api/admin/questions/echo-question/publish",
            cookie=self.admin_cookie,
        )
        self.assertEqual(status, 200, republished)
        new_version = republished["question"]["version"]

        with patch(
            "app.code_exams.execute_question",
            return_value=_execution(visible_passed=False, verdict="WA"),
        ) as execute:
            status, regraded = self.request(
                "POST",
                f"/api/admin/code-results/{exam_id}/regrade",
                cookie=self.admin_cookie,
                payload={"submission_id": submission_id, "use_latest_spec": True},
            )
        self.assertEqual(status, 200, regraded)
        execute.assert_called_once()
        record = storage.read_json("code_submissions.json")["student-1"][0]
        self.assertEqual(record["grading_spec_version"], new_version)
        self.assertEqual(record["grading_history"][0]["score"], 10)
        self.assertNotEqual(record["score"], 10)
        retained_score = record["score"]
        with patch(
            "app.code_exams.execute_question",
            return_value=_execution(verdict="JUDGE_INFRA_ERROR"),
        ):
            status, failed = self.request(
                "POST",
                f"/api/admin/code-results/{exam_id}/regrade",
                cookie=self.admin_cookie,
                payload={"submission_id": submission_id, "use_latest_spec": True},
            )
        self.assertEqual(status, 503, failed)
        retained = storage.read_json("code_submissions.json")["student-1"][0]
        self.assertEqual(retained["score"], retained_score)
        self.assertEqual(len(retained["grading_history"]), 1)

    def test_monitor_reports_admin_only_code_submission_summary(self):
        self.create_started_code_exam()
        with patch("app.code_exams.execute_question", return_value=_execution()):
            self.request(
                "POST",
                "/api/student/code/submit",
                cookie=self.student_cookie,
                payload={"question_id": "echo-question", "source_code": "print(input())\n"},
            )
        status, response = self.request(
            "GET", "/api/admin/monitor", cookie=self.admin_cookie
        )
        self.assertEqual(status, 200, response)
        summary = response["students"][0]["latest_code_submission"]
        self.assertEqual(summary["score"], 10)
        self.assertNotIn("source_code", summary)

    @unittest.skipUnless(os.name == "nt", "code-grading startup preflight is Windows-only")
    def test_server_startup_reports_missing_jdk_clearly(self):
        with patch(
            "app.main.verify_jdk_configuration",
            side_effect=JDKConfigurationError("javac was not found"),
        ):
            with self.assertRaisesRegex(SystemExit, "JDK 17 or newer"):
                main.main()

    def test_force_submit_closes_code_exam_submission_path(self):
        self.create_started_code_exam()
        status, response = self.request(
            "POST",
            "/api/admin/students/student-1/force-submit",
            cookie=self.admin_cookie,
            raw_body=b"",
        )
        self.assertEqual(status, 200, response)
        assignment = storage.read_json("assignments.json")["student-1"]
        self.assertEqual(assignment["status"], "submitted")
        self.assertTrue(assignment["forced_submit"])
        status, rejected = self.request(
            "POST",
            "/api/student/code/submit",
            cookie=self.student_cookie,
            payload={"question_id": "echo-question", "source_code": "print(input())\n"},
        )
        self.assertEqual(status, 403, rejected)

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
        self.assertEqual(status, 409, rejected)
        execute.assert_not_called()

    def test_student_score_can_be_revealed_after_each_submission(self):
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
        status, _ = self.request(
            "POST", "/api/admin/questions", cookie=self.admin_cookie, payload=question
        )
        self.assertEqual(status, 201)
        with patch("app.code_exams.execute_question", return_value=_execution()):
            status, validation = self.request(
                "POST",
                "/api/admin/questions/echo-question/validate",
                cookie=self.admin_cookie,
                payload={"sample_source": _SAMPLE_SOURCE},
            )
        self.assertEqual(status, 200, validation)
        status, published = self.request(
            "POST",
            "/api/admin/questions/echo-question/publish",
            cookie=self.admin_cookie,
        )
        self.assertEqual(status, 200, published)
        status, created = self.request(
            "POST",
            "/api/admin/code-exams",
            cookie=self.admin_cookie,
            payload={
                "title": "Visible after each submission",
                "question_ids": ["echo-question"],
                "show_final_score_immediately": True,
            },
        )
        self.assertEqual(status, 201, created)
        exam_id = created["code_exam"]["id"]
        body = urllib.parse.urlencode(
            {"mode": "random", "code_exam_id": exam_id, "code_only": "true"}
        ).encode()
        with patch("app.exams.list_exam_files", return_value=[]):
            status, _ = self.request(
                "POST",
                "/api/admin/distribute",
                cookie=self.admin_cookie,
                raw_body=body,
                content_type="application/x-www-form-urlencoded",
            )
        self.assertEqual(status, 200)
        self.assertEqual(
            self.request("POST", "/api/admin/start-exam", cookie=self.admin_cookie, raw_body=b"")[0],
            200,
        )
        self.assertEqual(
            self.request("POST", "/api/student/start", cookie=self.student_cookie, raw_body=b"")[0],
            200,
        )
        with patch("app.code_exams.execute_question", return_value=_execution()):
            status, result = self.request(
                "POST",
                "/api/student/code/submit",
                cookie=self.student_cookie,
                payload={"question_id": "echo-question", "source_code": "print(input())\n"},
            )
        self.assertEqual(status, 201, result)
        self.assertEqual(result["submission"]["score"], 10)
        self.assertEqual(result["submission"]["exam_score"], 10)
        self.assertNotIn("secret-expected", json.dumps(result))

if __name__ == "__main__":
    unittest.main()
