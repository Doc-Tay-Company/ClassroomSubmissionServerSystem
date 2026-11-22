from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from http.server import ThreadingHTTPServer
import http.client
import json
import os
from pathlib import Path
import tempfile
from concurrent.futures import ThreadPoolExecutor
import threading
import unittest
import io
import zipfile
from unittest.mock import Mock, patch
import urllib.parse

from app import storage


_ORIGINAL_DATA_DIR = storage.DATA_DIR
_ORIGINAL_LOG_DIR = storage.LOG_DIR
_TEST_TEMP = tempfile.TemporaryDirectory(prefix="css-code-api-")
_TEST_DATA_ROOT = Path(_TEST_TEMP.name)
storage.DATA_DIR = _TEST_DATA_ROOT / "data"
storage.LOG_DIR = _TEST_DATA_ROOT / "logs"
storage.DATA_DIR.mkdir(parents=True, exist_ok=True)
storage.LOG_DIR.mkdir(parents=True, exist_ok=True)

from app import code_exams, exams as exam_service, general_exams, main
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
        try:
            cls.server.shutdown()
            cls.server.server_close()
            cls.thread.join(timeout=2)
        finally:
            storage.DATA_DIR = _ORIGINAL_DATA_DIR
            storage.LOG_DIR = _ORIGINAL_LOG_DIR
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
            "submissions.json": {},
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

    def create_general_code_exam(self, *, duration=60, participants=None, title="Timing test exam"):
        participants = participants or ["student1"]
        students = storage.read_json("students.json")
        for student_id in participants:
            students.setdefault(student_id, {"active": True})
        storage.write_json("students.json", students)
        self.timing_student_cookies = {
            student_id: new_session(student_id, "student", "127.0.0.1", "test")
            for student_id in participants
        }
        payload = {
            "title": title,
            "config": {"duration_minutes": duration, "participants": participants},
            "items": [{"type": "code", "question_ids": ["echo-question"]}],
        }
        status, created = self.request("POST", "/api/admin/exam-records", cookie=self.admin_cookie, payload=payload)
        self.assertEqual(status, 201, created)
        exam_id = created["exam"]["id"]
        with patch("app.general_exams.list_exam_files", return_value=[]), patch("app.exams.list_exam_files", return_value=[]):
            status, published = self.request("POST", f"/api/admin/exam-records/{exam_id}/publish", cookie=self.admin_cookie)
            self.assertEqual(status, 200, published)
            status, started = self.request("POST", f"/api/admin/exam-records/{exam_id}/start", cookie=self.admin_cookie)
        self.assertEqual(status, 200, started)
        return exam_id, started["exam"]["release"]["release_id"]

    def start_student(self, cookie=None):
        return self.request("POST", "/api/student/start", cookie=cookie or self.timing_student_cookies["student1"], raw_body=b"")

    def set_release_deadline(self, exam_id, deadline):
        exams = storage.read_json("exams.json")
        exams[exam_id]["release"]["official_deadline"] = deadline
        storage.write_json("exams.json", exams)

    def test_teacher_start_release_timing_is_shared_and_student_start_is_idempotent(self):
        self.create_published_question("echo-question")
        exam_id, release_id = self.create_general_code_exam(duration=60)
        exam = storage.read_json("exams.json")[exam_id]
        release = exam["release"]
        official_start = datetime.fromisoformat(release["official_started_at"])
        official_deadline = datetime.fromisoformat(release["official_deadline"])
        self.assertEqual(release["duration_minutes"], 60)
        self.assertEqual(official_deadline - official_start, timedelta(minutes=60))
        self.assertEqual(storage.read_json("settings.json")["exam_started_at"], release["official_started_at"])
        # Application startup reopens the persisted Release timing instead of
        # deriving it from the next Student's start time.
        storage.initialize()
        persisted_timing = general_exams.release_timing(release_id)
        self.assertEqual(persisted_timing["official_started_at"], release["official_started_at"])
        self.assertEqual(persisted_timing["official_deadline"], release["official_deadline"])
        status, first = self.start_student()
        self.assertEqual(status, 200, first)
        assignment = storage.read_json("assignments.json")["student1"]
        self.assertEqual(assignment["ends_at"], release["official_deadline"])
        self.assertEqual(assignment["started_at"], first["started_at"])
        marker = storage.read_json("exams.json")[exam_id]["release"].get("student_started_at", {}).get("student1")
        self.assertEqual(marker, first["started_at"])
        status, repeated = self.start_student()
        self.assertEqual(status, 200, repeated)
        self.assertEqual(repeated["started_at"], first["started_at"])
        current = storage.read_json("assignments.json")["student1"]
        self.assertEqual(current["ends_at"], first["ends_at"])
        self.assertEqual(storage.read_json("exams.json")[exam_id]["release"]["student_started_at"]["student1"], marker)

    def test_late_student_gets_shared_deadline_and_start_at_deadline_is_rejected(self):
        self.create_published_question("echo-question")
        students = storage.read_json("students.json")
        students["student2"] = {"active": True}
        students["student3"] = {"active": True}
        storage.write_json("students.json", students)
        exam_id, _ = self.create_general_code_exam(duration=60, participants=["student1", "student2", "student3"])
        late_start = datetime.now(timezone.utc) - timedelta(minutes=53)
        deadline = (late_start + timedelta(minutes=60)).isoformat(timespec="seconds")
        exams = storage.read_json("exams.json")
        exams[exam_id]["release"].update({"official_started_at": late_start.isoformat(timespec="seconds"), "official_deadline": deadline})
        storage.write_json("exams.json", exams)
        status, result = self.start_student()
        self.assertEqual(status, 200, result)
        self.assertEqual(result["ends_at"], deadline)
        self.assertLessEqual(result["remaining_seconds"], 7 * 60)
        status, late_student = self.start_student(self.timing_student_cookies["student2"])
        self.assertEqual(status, 200, late_student)
        self.assertEqual(late_student["ends_at"], deadline)
        self.set_release_deadline(exam_id, (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(timespec="seconds"))
        status, rejected = self.start_student(self.timing_student_cookies["student3"])
        self.assertEqual(status, 400, rejected)
        self.assertIsNone(storage.read_json("assignments.json")["student3"]["started_at"])
        self.assertNotIn("student3", storage.read_json("exams.json")[exam_id]["release"]["student_started_at"])
        self.assertNotIn("student3", storage.read_json("code_attempts.json")["attempts"])

    def test_random_paper_snapshots_share_release_deadline(self):
        students = storage.read_json("students.json")
        students.update({"student1": {"active": True}, "student2": {"active": True}})
        storage.write_json("students.json", students)
        self.timing_student_cookies = {sid: new_session(sid, "student", "127.0.0.1", "test") for sid in ("student1", "student2")}
        storage.write_json("papers.json", {
            "paper-1": {"id": "paper-1", "schema_version": 1, "status": "published",
                        "versions": {"paper-1:v1": {"id": "paper-1:v1", "title": "One", "questions": [
                            {"question_id": "q1", "order": 0, "total_points": 10},
                        ]}}},
            "paper-2": {"id": "paper-2", "schema_version": 1, "status": "published",
                        "versions": {"paper-2:v1": {"id": "paper-2:v1", "title": "Two", "questions": [
                            {"question_id": "q2", "order": 0, "total_points": 10},
                        ]}}},
        })
        payload = {
            "title": "Random Paper timing",
            "config": {"duration_minutes": 60, "participants": ["student1", "student2"]},
            "items": [{"type": "code", "distribution": {"mode": "random", "paper_versions": [
                {"paper_id": "paper-1", "paper_version_id": "paper-1:v1"},
                {"paper_id": "paper-2", "paper_version_id": "paper-2:v1"},
            ]}}],
        }
        status, created = self.request("POST", "/api/admin/exam-records", cookie=self.admin_cookie, payload=payload)
        self.assertEqual(status, 201, created)
        exam_id = created["exam"]["id"]
        picks = iter((0, 1))
        with patch("app.general_exams._choose_random_paper", side_effect=lambda refs: refs[next(picks)]), \
             patch("app.general_exams.list_exam_files", return_value=[]), patch("app.exams.list_exam_files", return_value=[]):
            status, published = self.request("POST", f"/api/admin/exam-records/{exam_id}/publish", cookie=self.admin_cookie)
            self.assertEqual(status, 200, published)
            release_id = published["exam"]["release"]["release_id"]
            paper_assignments = storage.read_json("exams.json")[exam_id]["release"]["paper_assignments"]
            self.assertNotEqual(paper_assignments["student1"]["code_exam_id"], paper_assignments["student2"]["code_exam_id"])
            status, started = self.request("POST", f"/api/admin/exam-records/{exam_id}/start", cookie=self.admin_cookie)
        self.assertEqual(status, 200, started)
        base_deadline = storage.read_json("exams.json")[exam_id]["release"]["official_deadline"]
        for student_id in ("student1", "student2"):
            status, result = self.start_student(self.timing_student_cookies[student_id])
            self.assertEqual(status, 200, result)
            self.assertEqual(storage.read_json("assignments.json")[student_id]["release_id"], release_id)
            self.assertEqual(result["ends_at"], base_deadline)

    def test_individual_extension_changes_only_effective_deadline_and_keeps_attempt_active(self):
        self.create_published_question("echo-question")
        exam_id, _ = self.create_general_code_exam(duration=60)
        status, started = self.start_student()
        self.assertEqual(status, 200, started)
        official_deadline = storage.read_json("exams.json")[exam_id]["release"]["official_deadline"]
        status, adjusted = self.request("POST", "/api/admin/students/student1/adjust-time", cookie=self.admin_cookie,
                                        raw_body=urllib.parse.urlencode({"minutes": 30}).encode(),
                                        content_type="application/x-www-form-urlencoded")
        self.assertEqual(status, 200, adjusted)
        self.assertNotEqual(adjusted["ends_at"], official_deadline)
        self.assertEqual(storage.read_json("exams.json")[exam_id]["release"]["official_deadline"], official_deadline)
        self.set_release_deadline(exam_id, (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(timespec="seconds"))
        status, state = self.request("GET", "/api/student/status", cookie=self.timing_student_cookies["student1"])
        self.assertEqual(status, 200, state)
        self.assertTrue(state["active_exam_attempt"])
        status, ended = self.request("POST", f"/api/admin/exam-records/{exam_id}/end", cookie=self.admin_cookie)
        self.assertEqual(status, 200, ended)
        status, state = self.request("GET", "/api/student/status", cookie=self.timing_student_cookies["student1"])
        self.assertEqual(status, 200, state)
        self.assertFalse(state["active_exam_attempt"])

    def test_never_started_students_are_not_finalized_or_given_results(self):
        self.create_published_question("echo-question")
        students = storage.read_json("students.json")
        students["student2"] = {"active": True}
        storage.write_json("students.json", students)
        exam_id, _ = self.create_general_code_exam(duration=60, participants=["student1", "student2"])
        deadline = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(timespec="seconds")
        self.set_release_deadline(exam_id, deadline)
        main.exam_completion.finalize_due_attempts()
        self.assertEqual(storage.read_json("code_attempts.json")["attempts"], {})
        self.assertEqual(storage.read_json("code_submissions.json"), {})
        result = general_exams.get_exam_results(exam_id)
        self.assertEqual({row["student_id"]: row["participation_status"] for row in result["matrix"]},
                         {"student1": "no_show", "student2": "no_show"})
        self.assertEqual(storage.read_json("assignments.json")["student1"]["status"], "assigned")

    def test_older_release_without_start_markers_does_not_infer_absence(self):
        self.create_published_question("echo-question")
        exam_id, _ = self.create_general_code_exam(duration=60)
        exams = storage.read_json("exams.json")
        exams[exam_id]["release"].pop("student_started_at", None)
        storage.write_json("exams.json", exams)
        result = general_exams.get_exam_results(exam_id)
        self.assertEqual(result["matrix"][0]["participation_status"], "unknown")

    def test_participation_marker_survives_a_later_release_replacing_assignments(self):
        self.create_published_question("echo-question")
        exam_id, old_release_id = self.create_general_code_exam(duration=60)
        status, started = self.start_student()
        self.assertEqual(status, 200, started)
        original_marker = storage.read_json("exams.json")[exam_id]["release"]["student_started_at"]["student1"]
        status, ended = self.request("POST", f"/api/admin/exam-records/{exam_id}/end", cookie=self.admin_cookie)
        self.assertEqual(status, 200, ended)
        status, copied = self.request("POST", f"/api/admin/exam-records/{exam_id}/copy", cookie=self.admin_cookie)
        self.assertEqual(status, 200, copied)
        new_exam_id = copied["exam"]["id"]
        with patch("app.general_exams.list_exam_files", return_value=[]), patch("app.exams.list_exam_files", return_value=[]):
            status, published = self.request("POST", f"/api/admin/exam-records/{new_exam_id}/publish", cookie=self.admin_cookie)
            self.assertEqual(status, 200, published)
            status, started_new = self.request("POST", f"/api/admin/exam-records/{new_exam_id}/start", cookie=self.admin_cookie)
        self.assertEqual(status, 200, started_new)
        new_release_id = started_new["exam"]["release"]["release_id"]
        self.assertNotEqual(new_release_id, old_release_id)
        self.assertEqual(storage.read_json("assignments.json")["student1"]["release_id"], new_release_id)
        self.assertEqual(storage.read_json("exams.json")[exam_id]["release"]["student_started_at"]["student1"], original_marker)

    def test_started_blank_attempt_expires_without_submission_or_grade(self):
        self.create_published_question("echo-question")
        exam_id, _ = self.create_general_code_exam(duration=60, participants=["student1", "student2"])
        status, _ = self.start_student()
        self.assertEqual(status, 200)
        assignments = storage.read_json("assignments.json")
        assignments["student1"]["ends_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(timespec="seconds")
        storage.write_json("assignments.json", assignments)
        main.exam_completion.finalize_due_attempts()
        self.assertEqual(storage.read_json("code_submissions.json"), {})
        ledger = storage.read_json("code_attempts.json")["attempts"]["student1"]
        self.assertTrue(ledger)
        self.assertEqual(storage.read_json("assignments.json")["student1"]["status"], "submitted")
        result = general_exams.get_exam_results(exam_id)
        self.assertEqual(result["matrix"][0]["participation_status"], "started_no_submission")
        self.assertIsNone(result["matrix"][0]["total_score"])

    def test_teacher_end_finalizes_only_started_blank_attempts_without_fake_submissions(self):
        self.create_published_question("echo-question")
        students = storage.read_json("students.json")
        students["student2"] = {"active": True}
        storage.write_json("students.json", students)
        exam_id, _ = self.create_general_code_exam(duration=60, participants=["student1", "student2"])
        status, _ = self.start_student()
        self.assertEqual(status, 200)
        status, ended = self.request("POST", f"/api/admin/exam-records/{exam_id}/end", cookie=self.admin_cookie)
        self.assertEqual(status, 200, ended)
        main.exam_completion.finalize_due_attempts()
        self.assertEqual(storage.read_json("code_submissions.json"), {})
        attempts = storage.read_json("code_attempts.json")["attempts"]
        self.assertIn("student1", attempts)
        self.assertNotIn("student2", attempts)
        result = general_exams.get_exam_results(exam_id)
        self.assertEqual({row["student_id"]: row["participation_status"] for row in result["matrix"]},
                         {"student1": "started_no_submission", "student2": "no_show"})

    def question_state_tokens(self, question_id):
        question = storage.read_json("questions.json").get(question_id)
        self.assertIsNotNone(question, f"missing Question Bank record: {question_id}")
        tokens = {"expected_version": question.get("version", 1)}
        if "practice_revision" in question:
            tokens["expected_practice_revision"] = question["practice_revision"]
        return tokens

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
                payload={"sample_source": _SAMPLE_SOURCE, **self.question_state_tokens(question_id)},
            )
            self.assertEqual(status, 200, validation)
            status, published = self.request(
                "POST",
                f"/api/admin/questions/{question_id}/publish",
                cookie=self.admin_cookie,
                payload=self.question_state_tokens(question_id),
            )
        self.assertEqual(status, 200, published)
        return published["question"]

    def create_draft_code_exam(self, question_ids, **options):
        return code_exams.create_code_exam(
            {"title": "Draft exam", "question_ids": question_ids, **options}, "admin-1", "127.0.0.1"
        )

    def distribute_and_start_code_exam(self, exam_id, *, start_student=True):
        settings = storage.read_json("settings.json")
        settings.update(exam_participants=["student-1"], exam_duration_minutes=90)
        storage.write_json("settings.json", settings)
        with patch("app.exams.list_exam_files", return_value=[]):
            distributed = exam_service.distribute_exams("random", {"code_exam_id": exam_id, "code_only": True})
        snapshot = code_exams.get_code_exam(exam_id)
        release = {
            "release_id": distributed["release_id"],
            "released_at": storage.read_json("assignments.json")["student-1"]["assigned_at"],
            "applied": True,
            "assigned_count": distributed["assigned_count"],
            "assignments": distributed["distribution"],
            "student_started_at": {},
        }
        record = general_exams._legacy_exam(
            exam_id, snapshot["title"], {**general_exams._default_config(), "participants": ["student-1"]},
            [general_exams._code_item_from_snapshot(snapshot)], "distributed", release, "admin-1", snapshot.get("created_at"),
        )
        storage.write_json("exams.json", {exam_id: record})
        general_exams.start_exam(exam_id, "admin-1", "127.0.0.1")
        if start_student:
            status, student_started = self.request("POST", "/api/student/start", cookie=self.student_cookie, raw_body=b"")
            self.assertEqual(status, 200, student_started)
        return exam_id

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
                payload={"sample_source": _SAMPLE_SOURCE, **self.question_state_tokens("echo-question")},
            )
        else:
            with patch("app.code_exams.execute_question", return_value=_execution()):
                status, validation = self.request(
                    "POST",
                    "/api/admin/questions/echo-question/validate",
                    cookie=self.admin_cookie,
                    payload={"sample_source": "print(input())\n", **self.question_state_tokens("echo-question")},
                )
        self.assertEqual(status, 200, validation)
        status, published = self.request(
            "POST",
            "/api/admin/questions/echo-question/publish",
            cookie=self.admin_cookie,
            payload=self.question_state_tokens("echo-question"),
        )
        self.assertEqual(status, 200, published)
        created_exam = self.create_draft_code_exam(["echo-question"], title="Code exam",
            show_final_score_immediately=False, pretest_cooldown_seconds=0)
        exam_id = created_exam["id"]
        self.distribute_and_start_code_exam(exam_id)
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

    def test_exam_record_edit_and_reload_preserve_selected_item_type(self):
        storage.write_json("papers.json", {
            "paper-1": {
                "id": "paper-1", "schema_version": 1, "status": "published",
                "versions": {"paper-1:v1": {"id": "paper-1:v1", "title": "Legacy Paper",
                    "questions": [{"question_id": "q-1", "order": 0, "total_points": 10}]}},
            },
            "paper-2": {
                "id": "paper-2", "schema_version": 1, "status": "published",
                "versions": {"paper-2:v2": {"id": "paper-2:v2", "title": "Second Legacy Paper",
                    "questions": [{"question_id": "q-2", "order": 0, "total_points": 10}]}},
            },
        })
        item_cases = (
            {
                "type": "code",
                "item_id": "code-item",
                "distribution": {"mode": "common", "paper_versions": [{"paper_id": "paper-1", "paper_version_id": "paper-1:v1"}]},
            },
            {
                "type": "code",
                "item_id": "random-code-item",
                "distribution": {"mode": "random", "paper_versions": [
                    {"paper_id": "paper-1", "paper_version_id": "paper-1:v1"},
                    {"paper_id": "paper-2", "paper_version_id": "paper-2:v2"},
                ]},
            },
            {
                "type": "zip",
                "item_id": "zip-item",
                "distribution_mode": "selected",
                "distribution_config": {"exam_files": ["exam.zip"]},
            },
        )
        for item in item_cases:
            with self.subTest(item_type=item["type"]):
                payload = {
                    "title": f"{item['type']} exam",
                    "config": {"duration_minutes": 75, "participants": ["student1"]},
                    "items": [item],
                }
                status, created = self.request(
                    "POST", "/api/admin/exam-records", cookie=self.admin_cookie, payload=payload
                )
                self.assertEqual(status, 201, created)
                exam_id = created["exam"]["id"]

                status, loaded = self.request(
                    "GET", f"/api/admin/exam-records/{exam_id}", cookie=self.admin_cookie
                )
                self.assertEqual(status, 200, loaded)
                self.assertEqual([entry["type"] for entry in loaded["exam"]["items"]], [item["type"]])
                if item["type"] == "code":
                    self.assertEqual(loaded["exam"]["items"][0]["distribution"], item["distribution"])

                payload["title"] = f"edited {item['type']} exam"
                payload["expected_revision"] = created["exam"]["revision"]
                status, updated = self.request(
                    "POST", f"/api/admin/exam-records/{exam_id}/update", cookie=self.admin_cookie, payload=payload
                )
                self.assertEqual(status, 200, updated)
                self.assertEqual(updated["exam"]["config"]["duration_minutes"], 75)
                self.assertEqual(updated["exam"]["config"]["participants"], ["student1"])

                status, reloaded = self.request(
                    "GET", f"/api/admin/exam-records/{exam_id}", cookie=self.admin_cookie
                )
                self.assertEqual(status, 200, reloaded)
                self.assertEqual([entry["type"] for entry in reloaded["exam"]["items"]], [item["type"]])
                self.assertEqual(reloaded["exam"]["title"], f"edited {item['type']} exam")
                if item["type"] == "code":
                    self.assertEqual(reloaded["exam"]["items"][0]["distribution"], item["distribution"])

    def test_exam_records_get_migrates_wrapped_code_exam_store(self):
        legacy_exam = {
            "id": "legacy-code-exam",
            "title": "Legacy code exam",
            "status": "draft",
            "release_id": None,
            "questions": [],
        }
        storage.write_json("code_exams.json", {"code_exams": {legacy_exam["id"]: legacy_exam}})

        main.initialize()
        status, response = self.request(
            "GET", "/api/admin/exam-records", cookie=self.admin_cookie
        )

        self.assertEqual(status, 200, response)
        self.assertIn(legacy_exam["id"], {exam["id"] for exam in response["exams"]})
        self.assertEqual(storage.read_json("code_exams.json"), {legacy_exam["id"]: legacy_exam})

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

    def test_legacy_distribution_and_start_routes_are_disabled(self):
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
                    if status == 410:
                        self.assertIn("Legacy distribution", result["detail"])
                        continue
                    self.assertEqual(status, 400, result)
                    self.assertIn("kh么ng th峄?k岷縯 h峄", result["detail"])
        status, result = self.request("POST", "/api/admin/start-exam", cookie=self.admin_cookie, raw_body=b"")
        self.assertEqual(status, 410, result)
        self.assertIn("Exam Management", result["detail"])
        prepare.assert_not_called()
        self.assertFalse(storage.read_json("settings.json")["exam_released"])

    def test_admin_publish_snapshot_and_code_only_lifecycle(self):
        self.create_started_code_exam()
        status, response = self.request("GET", "/api/student/code-exam", cookie=self.student_cookie)
        self.assertEqual(status, 200, response)
        question = response["questions"][0]
        self.assertEqual([item["id"] for item in question["tests"]], ["visible"])
        # The current official exam projection exposes the question maximum but only
        # public tests; hidden inputs and expected outputs remain private.
        self.assertEqual(question["total_points"], 10)
        self.assertEqual(len(question["tests"]), 1)
        self.assertNotIn("secret-input", json.dumps(response))
        self.assertEqual(storage.read_json("questions.json")["echo-question"]["usage_count"], 1)
        assignment = storage.read_json("assignments.json")["student-1"]
        self.assertIsNone(assignment["exam_file"])
        self.assertEqual(assignment["status"], "in_progress")

    def test_obsolete_code_exam_endpoints_are_removed_without_deleting_runtime_data(self):
        records = {"retained": {"id": "retained", "status": "draft", "questions": []}}
        storage.write_json("code_exams.json", records)
        for method, path in (
            ("GET", "/api/admin/code-exams"),
            ("POST", "/api/admin/code-exams"),
            ("GET", "/api/admin/code-exams/retained"),
            ("PUT", "/api/admin/code-exams/retained"),
        ):
            with self.subTest(method=method, path=path):
                status, _ = self.request(method, path, cookie=self.admin_cookie,
                    payload={} if method in {"POST", "PUT"} else None, parse_json=False)
                self.assertEqual(status, 404)
                self.assertEqual(storage.read_json("code_exams.json"), records)

    def test_obsolete_code_exam_tab_and_script_are_removed(self):
        for tab in ("questions", "papers", "results", "exams"):
            with self.subTest(tab=tab):
                status, page = self.request("GET", f"/admin?section=exam-management&tab={tab}",
                    cookie=self.admin_cookie, parse_json=False)
                self.assertEqual(status, 200)
                html = page.decode("utf-8")
                self.assertNotIn("tab=exams", html)
                self.assertNotIn('id="code-exams-view"', html)
                self.assertNotIn("/static/js/code-exams.js", html)
                self.assertIn('href="/admin?section=exams"', html)
        status, _ = self.request("GET", "/static/js/code-exams.js", parse_json=False)
        self.assertEqual(status, 404)

    def test_exam_end_keeps_scores_private_when_immediate_review_is_disabled(self):
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
        self.assertNotIn("score", result)
        self.assertNotIn("exam_score", result)
        self.assertEqual(storage.read_json("code_exams.json")[exam_id]["status"], "ended")

    def test_shared_json_parser_rejects_invalid_json(self):
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
            "target_class": "StaleJavaClass",
            "target_package": "legacy.java",
            "tests": [_VISIBLE, _HIDDEN],
            "time_limit_seconds": 2,
            "max_output_bytes": 1024,
        }
        stdio_result = Mock()
        stdio_result.to_dict.return_value = {"verdict": "AC"}
        with patch("app.code_exams.run_stdio", return_value=stdio_result) as run_stdio:
            execute_question(question, "print(input())", visible_only=True)

        self.assertTrue(run_stdio.call_args.kwargs["visible_only"])
        self.assertIsNone(run_stdio.call_args.kwargs["target_class"])
        self.assertIsNone(run_stdio.call_args.kwargs["target_package"])

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

    def test_code_submission_keeps_score_private_even_after_exam_end(self):
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
        self.assertNotIn("score", final)
        self.assertNotIn("results", final)
        self.assertNotIn("secret-expected", json.dumps(final))

    def test_bulk_submit_grades_all_questions_and_marks_exam_submitted(self):
        self.create_published_question("first-question")
        self.create_published_question("second-question")
        created = self.create_draft_code_exam(["first-question", "second-question"], title="Bulk exam",
            show_final_score_immediately=True, pretest_cooldown_seconds=0)
        self.distribute_and_start_code_exam(created["id"])

        answers = {
            "first-question": "print(input())\n",
            "second-question": "print(input())\n",
        }
        with patch("app.code_exams.execute_question", return_value=_execution()) as execute:
            status, result = self.request(
                "POST",
                "/api/student/code/submit-exam",
                cookie=self.student_cookie,
                payload={"answers": answers},
            )
        self.assertEqual(status, 200, result)
        self.assertTrue(result["all_questions_submitted"])
        self.assertEqual(result["exam_score"], 20)
        self.assertEqual(result["exam_total_points"], 20)
        self.assertEqual(len(result["submissions"]), 2)
        self.assertEqual([item["question_id"] for item in result["submissions"]], ["first-question", "second-question"])
        self.assertEqual(execute.call_count, 2)
        records = storage.read_json("code_submissions.json")["student-1"]
        self.assertEqual([item["status"] for item in records], ["graded", "graded"])
        self.assertEqual(storage.read_json("assignments.json")["student-1"]["status"], "submitted")

        with patch("app.code_exams.execute_question") as execute_again:
            status, repeated = self.request(
                "POST",
                "/api/student/code/submit-exam",
                cookie=self.student_cookie,
                payload={"answers": answers},
            )
        self.assertEqual(status, 200, repeated)
        self.assertTrue(repeated["all_questions_submitted"])
        self.assertEqual(repeated["submissions"], [])
        self.assertEqual(sorted(repeated["skipped_question_ids"]), ["first-question", "second-question"])
        execute_again.assert_not_called()

    def test_bulk_submit_requires_every_question_and_hides_scores(self):
        self.create_published_question("first-question")
        self.create_published_question("second-question")
        created = self.create_draft_code_exam(["first-question", "second-question"], title="Bulk exam",
            show_final_score_immediately=False, pretest_cooldown_seconds=0)
        self.distribute_and_start_code_exam(created["id"])

        status, missing = self.request(
            "POST",
            "/api/student/code/submit-exam",
            cookie=self.student_cookie,
            payload={"answers": {"first-question": "print(input())\n"}},
        )
        self.assertEqual(status, 400, missing)

        with patch("app.code_exams.execute_question", return_value=_execution()):
            status, result = self.request(
                "POST",
                "/api/student/code/submit-exam",
                cookie=self.student_cookie,
                payload={
                    "answers": {
                        "first-question": "print(input())\n",
                        "second-question": "print(input())\n",
                    }
                },
            )
        self.assertEqual(status, 200, result)
        self.assertNotIn("exam_score", result)
        self.assertNotIn("score", json.dumps(result["submissions"]))
        self.assertNotIn("secret-expected", json.dumps(result))

    def test_bulk_submit_skips_already_submitted_question_without_consuming_attempts(self):
        self.create_published_question("first-question")
        self.create_published_question("second-question")
        created = self.create_draft_code_exam(["first-question", "second-question"], title="Bulk exam",
            show_final_score_immediately=True, pretest_cooldown_seconds=0)
        self.distribute_and_start_code_exam(created["id"])

        with patch("app.code_exams.execute_question", return_value=_execution()):
            status, first = self.request(
                "POST",
                "/api/student/code/submit",
                cookie=self.student_cookie,
                payload={"question_id": "first-question", "source_code": "print(input())\n"},
            )
        self.assertEqual(status, 201, first)

        with patch("app.code_exams.execute_question", return_value=_execution()) as execute:
            status, result = self.request(
                "POST",
                "/api/student/code/submit-exam",
                cookie=self.student_cookie,
                payload={
                    "answers": {
                        "first-question": "",
                        "second-question": "print(input())\n",
                    }
                },
            )
        self.assertEqual(status, 200, result)
        self.assertEqual([item["question_id"] for item in result["submissions"]], ["second-question"])
        self.assertEqual(result["skipped_question_ids"], ["first-question"])
        self.assertTrue(result["all_questions_submitted"])
        self.assertEqual(result["exam_score"], 20)
        self.assertEqual(execute.call_count, 1)
        records = storage.read_json("code_submissions.json")["student-1"]
        self.assertEqual(
            sorted(item["question_id"] for item in records),
            ["first-question", "second-question"],
        )
        self.assertEqual(storage.read_json("assignments.json")["student-1"]["status"], "submitted")

    def test_completed_result_route_authorization_disclosure_and_home_confirmation(self):
        self.create_started_code_exam()
        assignment = storage.read_json('assignments.json')['student-1']
        exam_id = assignment['code_exam_id']
        storage.update_json('code_exams.json', lambda exams: exams[exam_id].update(show_final_score_immediately=True))
        source = 'print("<script>saved source</script>")'
        status, result = self.request('POST', '/api/student/code/draft', cookie=self.student_cookie,
                                      payload={'exam_id': exam_id, 'answers': {'echo-question': source}})
        self.assertEqual(status, 200, result)
        with patch('app.code_exams.execute_question', return_value=_execution()):
            status, result = self.request('POST', '/api/student/code/submit-exam', cookie=self.student_cookie,
                                          payload={'exam_id': exam_id, 'answers': {'echo-question': source}})
        self.assertEqual(status, 200, result)
        self.assertTrue(result['finalized'])
        path = '/student/results?exam_id=' + exam_id
        status, page = self.request('GET', path, cookie=self.student_cookie, parse_json=False)
        self.assertEqual(status, 200, page)
        html = page.decode('utf-8')
        self.assertIn('&lt;script&gt;saved source&lt;/script&gt;', html)
        self.assertNotIn('secret-expected', html)
        self.assertNotIn('secret-input', html)
        status, home = self.request('GET', '/?view=home', cookie=self.student_cookie, parse_json=False)
        self.assertEqual(status, 200)
        self.assertIn('Ch煤c m峄玭g! B岷 膽茫 ho脿n th脿nh b脿i thi.', home.decode('utf-8'))
        self.assertIn('Xem k岷縯 qu岷?chi ti岷縯', home.decode('utf-8'))
        other = new_session('student-2', 'student', '127.0.0.1', 'test')
        storage.update_json('students.json', lambda students: students.update({'student-2': {'active': True}}))
        self.assertEqual(self.request('GET', path, cookie=other, parse_json=False)[0], 404)
        self.assertIn(self.request('GET', path, parse_json=False)[0], (302, 401))
        storage.update_json('code_exams.json', lambda exams: exams[exam_id].update(show_final_score_immediately=False))
        self.assertEqual(self.request('GET', path, cookie=self.student_cookie, parse_json=False)[0], 403)
        status, home = self.request('GET', '/?view=home', cookie=self.student_cookie, parse_json=False)
        self.assertNotIn('Xem k岷縯 qu岷?chi ti岷縯', home.decode('utf-8'))
        storage.update_json('code_exams.json', lambda exams: exams[exam_id].pop('show_final_score_immediately'))
        self.assertEqual(self.request('GET', path, cookie=self.student_cookie, parse_json=False)[0], 403)
        status, snapshot = self.request('GET', '/api/student/code-exam', cookie=self.student_cookie)
        self.assertEqual(status, 200, snapshot)
        self.assertFalse(snapshot['show_final_score_immediately'])

    def test_teacher_end_during_whole_exam_grading_preserves_finalization(self):
        self.create_started_code_exam()
        exam_id = storage.read_json('assignments.json')['student-1']['code_exam_id']
        entered, finish = threading.Event(), threading.Event()
        results = []
        def grade(*args):
            entered.set()
            if not finish.wait(4): raise RuntimeError('test synchronization timed out')
            return _execution()
        def submit():
            results.append(self.request('POST', '/api/student/code/submit-exam', cookie=self.student_cookie,
                                        payload={'exam_id': exam_id, 'answers': {'echo-question': _SAMPLE_SOURCE}}))
        with patch('app.code_exams.execute_question', side_effect=grade) as runner:
            worker = threading.Thread(target=submit)
            worker.start()
            try:
                self.assertTrue(entered.wait(3))
                marker = storage.read_json('assignments.json')['student-1']['finalized_at']
                status, ended = self.request('POST', '/api/admin/end-exam', cookie=self.admin_cookie, raw_body=b'')
                self.assertEqual(status, 200, ended)
                self.assertEqual(storage.read_json('assignments.json')['student-1']['finalized_at'], marker)
            finally:
                finish.set()
                worker.join(5)
            self.assertFalse(worker.is_alive())
            self.assertEqual(results[0][0], 200, results)
            status, replay = self.request('POST', '/api/student/code/submit-exam', cookie=self.student_cookie,
                                         payload={'exam_id': exam_id, 'automatic': True})
            self.assertEqual(status, 200, replay)
            self.assertTrue(replay['finalized'])
            self.assertEqual(runner.call_count, 1)
        self.assertEqual(len(storage.read_json('code_submissions.json')['student-1']), 1)

    def test_student_page_exposes_bulk_submit_and_home_view(self):
        self.create_started_code_exam()
        status, page = self.request("GET", "/", cookie=self.student_cookie, parse_json=False)
        self.assertEqual(status, 200)
        self.assertIn("N峄檖 c岷?b脿i", page.decode("utf-8"))

        status, home = self.request("GET", "/?view=home", cookie=self.student_cookie, parse_json=False)
        self.assertEqual(status, 200)
        self.assertIn("M脿n h矛nh ch铆nh", home.decode("utf-8"))
        self.assertIn("Quay l岷 b脿i thi", home.decode("utf-8"))

    def test_home_view_offers_the_next_exam_before_the_student_starts(self):
        self.create_published_question("echo-question")
        created = self.create_draft_code_exam(["echo-question"], title="Next code exam",
            show_final_score_immediately=False, pretest_cooldown_seconds=0)
        self.distribute_and_start_code_exam(created["id"], start_student=False)

        status, home = self.request("GET", "/?view=home", cookie=self.student_cookie, parse_json=False)
        self.assertEqual(status, 200)
        page = home.decode("utf-8")
        self.assertIn('data-home-view="true"', page)
        self.assertIn("Next code exam", page)
        self.assertIn("V脿o l脿m b脿i", page)
        self.assertNotIn("Hi峄噉 t岷 b岷 ch瓢a c贸 b脿i thi 膽ang l脿m.", page)

        assignment = storage.read_json("assignments.json")["student-1"]
        self.assertIn(f'data-assignment-release="{assignment["release_id"]}"', page)
        self.assertIn('data-assignment-status="assigned"', page)
        self.assertIn('data-assignment-started-at=""', page)
        self.assertIn('data-exam-state="started"', page)
        status, live = self.request("GET", "/api/student/status", cookie=self.student_cookie)
        self.assertEqual(status, 200, live)
        self.assertEqual(live["release_id"], assignment["release_id"])
        self.assertEqual(live["status"], "assigned")
        self.assertEqual(live["exam_state"], "started")
        self.assertIsNone(live["started_at"])
        self.assertFalse(live["started"])

    def test_home_view_moves_to_the_next_exam_after_the_previous_one_ends(self):
        self.create_started_code_exam()
        with patch("app.code_exams.execute_question", return_value=_execution()):
            status, submitted = self.request(
                "POST",
                "/api/student/code/submit",
                cookie=self.student_cookie,
                payload={"question_id": "echo-question", "source_code": "print(input())\n"},
            )
        self.assertEqual(status, 201, submitted)
        status, _ = self.request("POST", "/api/admin/end-exam", cookie=self.admin_cookie, raw_body=b"")
        self.assertEqual(status, 200)

        status, home = self.request("GET", "/?view=home", cookie=self.student_cookie, parse_json=False)
        self.assertEqual(status, 200)
        self.assertIn("Code exam", home.decode("utf-8"))

        self.create_published_question("second-question")
        created = self.create_draft_code_exam(["second-question"], title="Second code exam", pretest_cooldown_seconds=0)
        self.distribute_and_start_code_exam(created["id"], start_student=False)

        status, next_home = self.request("GET", "/?view=home", cookie=self.student_cookie, parse_json=False)
        self.assertEqual(status, 200)
        page = next_home.decode("utf-8")
        self.assertIn("Second code exam", page)
        self.assertIn("V脿o l脿m b脿i", page)
        self.assertNotIn("Hi峄噉 t岷 b岷 ch瓢a c贸 b脿i thi 膽ang l脿m.", page)

    def _file_exam_assignment(self, **overrides):
        storage.write_json("submissions.json", {})
        now = datetime.now(timezone.utc)
        settings = storage.read_json("settings.json")
        settings.update({"exam_state": "started", "exam_released": True,
                         "exam_release_id": "file-release", "submission_policy": "configurable",
                         "max_submissions": 2, "overwrite_previous": True})
        storage.write_json("settings.json", settings)
        assignment = {"release_id": "file-release", "exam_file": "exam.zip",
                      "status": "in_progress", "started_at": (now - timedelta(minutes=1)).isoformat(),
                      "ends_at": (now + timedelta(minutes=10)).isoformat()}
        assignment.update(overrides)
        assignments = storage.read_json("assignments.json")
        assignments["student-1"] = assignment
        storage.write_json("assignments.json", assignments)
        return assignment

    @staticmethod
    def _valid_zip(payload=b"answer"):
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("answer.txt", payload)
        return output.getvalue()

    def _upload_zip(self, payload=b"answer"):
        boundary = "css-file-exam-boundary"
        body = (f"--{boundary}\r\n"
                'Content-Disposition: form-data; name="file"; filename="answer.zip"\r\n'
                "Content-Type: application/zip\r\n\r\n").encode() + self._valid_zip(payload) + f"\r\n--{boundary}--\r\n".encode()
        return self.request("POST", "/api/student/submit", cookie=self.student_cookie,
                            raw_body=body, content_type=f"multipart/form-data; boundary={boundary}")

    def test_configurable_zip_uploads_remain_allowed_for_active_attempt(self):
        self._file_exam_assignment()
        with tempfile.TemporaryDirectory(prefix="css-zip-upload-") as upload_root:
            upload_dir = Path(upload_root)
            with patch("app.submissions.UPLOAD_DIR", upload_dir):
                first_status, first = self._upload_zip(b"first")
                self.assertEqual(first_status, 200, first)
                self.assertTrue(first["zip_submission"]["eligible"])
                self.assertEqual((first["zip_submission"]["count"], first["zip_submission"]["limit"]), (1, 2))
                self.assertTrue((upload_dir / first["submission"]["filename"]).is_file())
                second_status, second = self._upload_zip(b"second")
                self.assertEqual(second_status, 200, second)
                self.assertFalse(second["zip_submission"]["eligible"])
                self.assertEqual(second["zip_submission"]["reason"], "quota_exhausted")
                records = storage.read_json("submissions.json")["student-1"]
                self.assertEqual(len(records), 2)
                self.assertFalse(records[0]["payload_retained"])
                self.assertTrue(records[1]["payload_retained"])
                self.assertEqual(len(list(upload_dir.iterdir())), 1)

    def test_zip_once_submission_exhausts_attempt_without_another_upload(self):
        self._file_exam_assignment()
        settings = storage.read_json("settings.json")
        settings.update({"submission_policy": "once", "max_submissions": 2})
        storage.write_json("settings.json", settings)
        with tempfile.TemporaryDirectory(prefix="css-zip-once-") as upload_root, patch("app.submissions.UPLOAD_DIR", Path(upload_root)):
            status, submitted = self._upload_zip(b"once")
            self.assertEqual(status, 200, submitted)
            self.assertFalse(submitted["zip_submission"]["eligible"])
            self.assertEqual(submitted["zip_submission"]["reason"], "quota_exhausted")
            status, state = self.request("GET", "/api/student/status", cookie=self.student_cookie)
            self.assertTrue(state["completion"]["finalized"])
            self.assertFalse(state["practice_locked"])
            status, rejected = self._upload_zip(b"second")
            self.assertEqual(status, 400, rejected)
            self.assertEqual(len(storage.read_json("submissions.json")["student-1"]), 1)
    def test_zip_submission_one_of_two_keeps_workspace_and_completion_open_after_reload(self):
        self._file_exam_assignment()
        with tempfile.TemporaryDirectory(prefix="css-zip-workspace-") as upload_root, patch("app.submissions.UPLOAD_DIR", Path(upload_root)):
            status, first = self._upload_zip(b"first")
            self.assertEqual(status, 200, first)
            status, state = self.request("GET", "/api/student/status", cookie=self.student_cookie)
            self.assertEqual(status, 200, state)
            self.assertFalse(state["completion"]["finalized"])
            self.assertTrue(state["zip_submission"]["eligible"])
            self.assertTrue(state["practice_locked"])
            status, page = self.request("GET", "/", cookie=self.student_cookie, parse_json=False)
            self.assertEqual(status, 200)
            html = page.decode("utf-8")
            self.assertIn('id="submission-form"', html)
            self.assertRegex(html, r'id="zip-submission-allowance"[^>]*>[^<]*1/2')

            status, second = self._upload_zip(b"second")
            self.assertEqual(status, 200, second)
            status, state = self.request("GET", "/api/student/status", cookie=self.student_cookie)
            self.assertTrue(state["completion"]["finalized"])
            self.assertFalse(state["zip_submission"]["eligible"])
            self.assertFalse(state["practice_locked"])

    def test_adjust_time_remains_available_after_first_configurable_zip_submission(self):
        self._file_exam_assignment()
        with tempfile.TemporaryDirectory(prefix="css-zip-adjust-") as upload_root, patch("app.submissions.UPLOAD_DIR", Path(upload_root)):
            status, uploaded = self._upload_zip(b"first")
            self.assertEqual(status, 200, uploaded)
            original_end = storage.read_json("assignments.json")["student-1"]["ends_at"]
            status, adjusted = self.request("POST", "/api/admin/students/student-1/adjust-time", cookie=self.admin_cookie,
                                            raw_body=urllib.parse.urlencode({"minutes": "5"}).encode(),
                                            content_type="application/x-www-form-urlencoded")
            self.assertEqual(status, 200, adjusted)
            self.assertGreater(datetime.fromisoformat(adjusted["ends_at"]), datetime.fromisoformat(original_end))
            self._upload_zip(b"second")
            exhausted_end = storage.read_json("assignments.json")["student-1"]["ends_at"]
            status, rejected = self.request("POST", "/api/admin/students/student-1/adjust-time", cookie=self.admin_cookie,
                                            raw_body=urllib.parse.urlencode({"minutes": "5"}).encode(),
                                            content_type="application/x-www-form-urlencoded")
            self.assertEqual(status, 409, rejected)
            self.assertEqual(storage.read_json("assignments.json")["student-1"]["ends_at"], exhausted_end)

    def test_force_submit_zip_preserves_received_file_and_prevents_later_upload(self):
        for overwrite in (True, False):
            with self.subTest(overwrite_previous=overwrite), tempfile.TemporaryDirectory(prefix="css-zip-force-") as upload_root:
                self._file_exam_assignment()
                settings = storage.read_json("settings.json")
                settings["overwrite_previous"] = overwrite
                storage.write_json("settings.json", settings)
                upload_dir = Path(upload_root)
                with patch("app.submissions.UPLOAD_DIR", upload_dir):
                    status, uploaded = self._upload_zip(b"accepted")
                    self.assertEqual(status, 200, uploaded)
                    accepted = upload_dir / uploaded["submission"]["filename"]
                    self.assertTrue(accepted.is_file())
                    status, forced = self.request("POST", "/api/admin/students/student-1/force-submit", cookie=self.admin_cookie)
                    self.assertEqual(status, 200, forced)
                    assignment = storage.read_json("assignments.json")["student-1"]
                    self.assertTrue(assignment["forced_submit"])
                    self.assertTrue(accepted.is_file())
                    before = len(storage.read_json("submissions.json")["student-1"])
                    status, rejected = self._upload_zip(b"not accepted after force")
                    self.assertEqual(status, 400, rejected)
                    self.assertEqual(len(storage.read_json("submissions.json")["student-1"]), before)
                    self.assertTrue(accepted.is_file())

    def test_force_submit_without_an_uploaded_zip_does_not_create_an_artifact(self):
        self._file_exam_assignment()
        with tempfile.TemporaryDirectory(prefix="css-zip-force-empty-") as upload_root, patch("app.submissions.UPLOAD_DIR", Path(upload_root)):
            status, forced = self.request("POST", "/api/admin/students/student-1/force-submit", cookie=self.admin_cookie)
            self.assertEqual(status, 200, forced)
            self.assertTrue(storage.read_json("assignments.json")["student-1"]["forced_submit"])
            self.assertEqual(storage.read_json("submissions.json").get("student-1", []), [])
            status, rejected = self._upload_zip(b"selected locally, not accepted")
            self.assertEqual(status, 400, rejected)
            self.assertEqual(storage.read_json("submissions.json").get("student-1", []), [])
            self.assertEqual(list(Path(upload_root).iterdir()), [])

    def test_force_submit_racing_zip_upload_obeys_serialized_admission(self):
        self._file_exam_assignment()
        barrier = threading.Barrier(3)
        with tempfile.TemporaryDirectory(prefix="css-zip-force-race-") as upload_root, patch("app.submissions.UPLOAD_DIR", Path(upload_root)):
            def upload():
                barrier.wait()
                return self._upload_zip(b"race")

            def force_submit():
                barrier.wait()
                return self.request("POST", "/api/admin/students/student-1/force-submit", cookie=self.admin_cookie)

            with ThreadPoolExecutor(max_workers=2) as pool:
                upload_future = pool.submit(upload)
                force_future = pool.submit(force_submit)
                barrier.wait()
                upload_status, upload_result = upload_future.result(timeout=10)
                force_status, force_result = force_future.result(timeout=10)

            self.assertEqual(force_status, 200, force_result)
            self.assertTrue(storage.read_json("assignments.json")["student-1"]["forced_submit"])
            records = storage.read_json("submissions.json").get("student-1", [])
            if upload_status == 200:
                self.assertEqual(len(records), 1)
                retained = Path(upload_root) / upload_result["submission"]["filename"]
                self.assertTrue(retained.is_file())
            else:
                self.assertEqual(upload_status, 400, upload_result)
                self.assertEqual(records, [])
                self.assertEqual(list(Path(upload_root).iterdir()), [])
    def test_force_finalized_ended_and_expired_file_attempts_reject_zip_without_saving(self):
        now = datetime.now(timezone.utc)
        cases = {
            "forced": ({"status": "submitted", "forced_submit": True}, {}),
            "finalized": ({"status": "submitted", "finalized_at": now.isoformat()}, {}),
            "ended": ({"status": "ended"}, {}),
            "teacher-ended-release": ({"status": "in_progress"}, {"exam_state": "ended", "exam_released": False, "exam_release_id": None}),
            "expired": ({"status": "in_progress", "ends_at": (now - timedelta(seconds=1)).isoformat()}, {}),
        }
        for name, (overrides, settings_overrides) in cases.items():
            with self.subTest(state=name), tempfile.TemporaryDirectory(prefix="css-zip-reject-") as upload_root:
                self._file_exam_assignment(**overrides)
                if settings_overrides:
                    settings = storage.read_json("settings.json")
                    settings.update(settings_overrides)
                    storage.write_json("settings.json", settings)
                storage.write_json("submissions.json", {"student-1": []})
                with patch("app.submissions.UPLOAD_DIR", Path(upload_root)):
                    status, result = self._upload_zip(name.encode())
                self.assertEqual(status, 400, result)
                self.assertEqual(list(Path(upload_root).iterdir()), [])
                self.assertEqual(storage.read_json("submissions.json")["student-1"], [])

    def test_finalized_overwrite_policy_cannot_replace_retained_zip(self):
        self._file_exam_assignment()
        with tempfile.TemporaryDirectory(prefix="css-zip-retained-") as upload_root:
            upload_dir = Path(upload_root)
            with patch("app.submissions.UPLOAD_DIR", upload_dir):
                status, result = self._upload_zip(b"original")
                self.assertEqual(status, 200, result)
                original = upload_dir / result["submission"]["filename"]
                self.assertEqual(original.read_bytes(), self._valid_zip(b"original"))
                assignments = storage.read_json("assignments.json")
                assignments["student-1"].update({"status": "submitted", "forced_submit": True,
                                                  "finalized_at": datetime.now(timezone.utc).isoformat()})
                storage.write_json("assignments.json", assignments)
                status, rejected = self._upload_zip(b"replacement")
                self.assertEqual(status, 400, rejected)
                self.assertTrue(original.is_file())
                self.assertEqual(original.read_bytes(), self._valid_zip(b"original"))
                self.assertEqual(len(storage.read_json("submissions.json")["student-1"]), 1)
                self.assertEqual(len(list(upload_dir.iterdir())), 1)

    def test_adjust_time_requires_a_current_unexpired_active_attempt(self):
        assignment = self._file_exam_assignment()
        original_end = assignment["ends_at"]
        body = urllib.parse.urlencode({"minutes": "5"}).encode()
        status, response = self.request("POST", "/api/admin/students/student-1/adjust-time", cookie=self.admin_cookie,
                                        raw_body=body, content_type="application/x-www-form-urlencoded")
        self.assertEqual(status, 200, response)
        extended = storage.read_json("assignments.json")["student-1"]["ends_at"]
        self.assertGreater(datetime.fromisoformat(extended), datetime.fromisoformat(original_end))

        body = urllib.parse.urlencode({"minutes": "-2"}).encode()
        status, response = self.request("POST", "/api/admin/students/student-1/adjust-time", cookie=self.admin_cookie,
                                        raw_body=body, content_type="application/x-www-form-urlencoded")
        self.assertEqual(status, 200, response)

        # A valid active reduction may put the deadline in the past; protected
        # attempt checks immediately stop treating the assignment as active.
        assignment = storage.read_json("assignments.json")["student-1"]
        assignment["ends_at"] = (datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat()
        storage.write_json("assignments.json", {"student-1": assignment})
        body = urllib.parse.urlencode({"minutes": "-5"}).encode()
        status, response = self.request("POST", "/api/admin/students/student-1/adjust-time", cookie=self.admin_cookie,
                                        raw_body=body, content_type="application/x-www-form-urlencoded")
        self.assertEqual(status, 200, response)
        reduced = storage.read_json("assignments.json")["student-1"]
        self.assertLess(datetime.fromisoformat(reduced["ends_at"]), datetime.now(timezone.utc))
        self.assertFalse(main.is_active_exam_attempt("student-1", storage.read_json("settings.json"), reduced))

        assignment = storage.read_json("assignments.json")["student-1"]
        expired_end = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        assignment["ends_at"] = expired_end
        storage.write_json("assignments.json", {"student-1": assignment})
        body = urllib.parse.urlencode({"minutes": "10"}).encode()
        status, rejected = self.request("POST", "/api/admin/students/student-1/adjust-time", cookie=self.admin_cookie,
                                        raw_body=body, content_type="application/x-www-form-urlencoded")
        self.assertEqual(status, 409, rejected)
        self.assertEqual(storage.read_json("assignments.json")["student-1"]["ends_at"], expired_end)

    def test_deadline_reduction_into_past_blocks_code_exam_operations(self):
        self.create_started_code_exam()
        body = urllib.parse.urlencode({"minutes": "-1440"}).encode()
        status, response = self.request("POST", "/api/admin/students/student-1/adjust-time", cookie=self.admin_cookie,
                                        raw_body=body, content_type="application/x-www-form-urlencoded")
        self.assertEqual(status, 200, response)
        with patch("app.code_exams.execute_question", return_value=_execution()) as execute:
            status, rejected = self.request("POST", "/api/student/code/run", cookie=self.student_cookie,
                                            payload={"question_id": "echo-question", "source_code": "print(input())"})
        self.assertEqual(status, 409, rejected)
        execute.assert_not_called()

    def test_adjust_time_rejects_unstarted_finalized_and_teacher_ended_attempts(self):
        body = urllib.parse.urlencode({"minutes": "5"}).encode()
        for name, assignment_overrides, settings_overrides in (
            ("unstarted", {"started_at": None}, {}),
            ("finalized", {"finalized_at": datetime.now(timezone.utc).isoformat()}, {}),
            ("forced", {"forced_submit": True}, {}),
            ("submitted-quota-exhausted", {"status": "submitted"}, {}),
            ("teacher-ended", {"status": "ended"}, {"exam_state": "ended", "exam_released": False, "exam_release_id": None}),
        ):
            with self.subTest(state=name):
                assignment = self._file_exam_assignment(**assignment_overrides)
                original_end = assignment["ends_at"]
                if name == "submitted-quota-exhausted":
                    storage.write_json("submissions.json", {"student-1": [
                        {"release_id": "file-release", "filename": "first.zip"},
                        {"release_id": "file-release", "filename": "second.zip"},
                    ]})
                if settings_overrides:
                    settings = storage.read_json("settings.json")
                    settings.update(settings_overrides)
                    storage.write_json("settings.json", settings)
                status, rejected = self.request("POST", "/api/admin/students/student-1/adjust-time", cookie=self.admin_cookie,
                                                raw_body=body, content_type="application/x-www-form-urlencoded")
                self.assertEqual(status, 409, rejected)
                self.assertEqual(storage.read_json("assignments.json")["student-1"]["ends_at"], original_end)

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

    def result_exam_fixture(self):
        self.addCleanup(storage.write_json, "exams.json", storage.read_json("exams.json"))
        exam = {
            "id": "main-exam", "title": "Current main exam", "status": "ended",
            "items": [{"type": "code", "paper_code_exam_ids": {"paper-a": "runtime-a", "paper-b": "runtime-b"}}],
            "release": {"release_id": "current-release", "paper_assignments": {
                "student-1": {"code_exam_id": "runtime-a"}, "student-2": {"code_exam_id": "runtime-b"},
            }},
        }
        storage.write_json("exams.json", {exam["id"]: exam, "deleted": {**exam, "id": "deleted", "deleted_at": "now"},
                                          "zip-only": {**exam, "id": "zip-only", "items": [{"type": "zip"}]}})
        submissions = {}
        snapshots = {}
        for index, suffix in enumerate(("a", "b"), 1):
            qid = f"question-{suffix}"
            runtime_id = f"runtime-{suffix}"
            snapshots[runtime_id] = {"id": runtime_id, "release_id": "current-release", "status": "ended",
                                     "questions": [{"question_id": qid, "title": f"Frozen {suffix}", "total_points": 10}]}
            submissions[f"student-{index}"] = [{"id": f"submission-{suffix}", "exam_id": runtime_id,
                "release_id": "current-release", "question_id": qid, "status": "graded", "score": 8,
                "total_points": 10, "source_code": "print('answer')", "results": [{"is_visible": False, "expected": "secret"}],
                "attempt": 1, "submitted_at": "2026-11-17T09:00:00+00:00", "verdict": "WA"}]
        submissions["student-1"].append({**submissions["student-1"][0], "id": "old-release", "release_id": "old-release"})
        storage.write_json("code_exams.json", snapshots)
        storage.write_json("code_submissions.json", submissions)
        return exam

    def test_exam_results_use_main_exams_and_release_scoped_submissions(self):
        exam = self.result_exam_fixture()
        before = storage.read_json("exams.json")
        status, response = self.request("GET", "/api/admin/exam-results", cookie=self.admin_cookie)
        self.assertEqual(status, 200, response)
        self.assertEqual(response["exams"], [{"id": exam["id"], "title": exam["title"], "status": "ended"}])
        self.assertEqual(storage.read_json("exams.json"), before)
        status, result = self.request("GET", "/api/admin/exam-results/main-exam", cookie=self.admin_cookie)
        self.assertEqual(status, 200, result)
        self.assertEqual(result["exam_id"], "main-exam")
        self.assertEqual({record["id"] for record in result["submissions"]}, {"submission-a", "submission-b"})
        self.assertEqual([q["title"] for q in result["questions"]], ["Frozen a", "Frozen b"])
        self.assertEqual([entry["total_score"] for entry in result["matrix"]], [8, 8])
        self.assertEqual([entry["total_points"] for entry in result["matrix"]], [10, 10])
        self.assertEqual(result["matrix"][0]["cells"][1]["status"], "not_assigned")
        self.assertIn("secret", json.dumps(result["submissions"]))
        status, filtered = self.request("GET", "/api/admin/exam-results/main-exam?student_id=student-2&question_id=question-b", cookie=self.admin_cookie)
        self.assertEqual(status, 200, filtered)
        self.assertEqual([record["id"] for record in filtered["submissions"]], ["submission-b"])
        self.assertEqual(len(filtered["matrix"]), 1)
        self.assertEqual(len(filtered["questions"]), 2)
        for path in ("/api/admin/exam-results", "/api/admin/exam-results/main-exam"):
            status, denied = self.request("GET", path, cookie=self.student_cookie)
            self.assertEqual(status, 403, denied)
        status, deleted = self.request("GET", "/api/admin/exam-results/deleted", cookie=self.admin_cookie)
        self.assertEqual(status, 404, deleted)

    def test_exam_results_remain_readable_without_runtime_snapshots_and_do_not_migrate_data(self):
        self.result_exam_fixture()
        storage.write_json("code_exams.json", {})
        original = storage.read_json("code_submissions.json")
        status, listing = self.request("GET", "/api/admin/exam-results", cookie=self.admin_cookie)
        self.assertEqual(status, 200, listing)
        self.assertEqual(listing["exams"][0]["id"], "main-exam")
        status, result = self.request("GET", "/api/admin/exam-results/main-exam", cookie=self.admin_cookie)
        self.assertEqual(status, 200, result)
        self.assertEqual(len(result["submissions"]), 2)
        self.assertTrue(result["warnings"])
        self.assertIsNone(result["matrix"][0]["total_score"])
        self.assertEqual(storage.read_json("code_submissions.json"), original)
        storage.write_json("code_submissions.json", {"code_submissions": original})
        status, invalid = self.request("GET", "/api/admin/exam-results/main-exam", cookie=self.admin_cookie)
        self.assertEqual(status, 409, invalid)
        self.assertIn("Invalid code_submissions.json", invalid["detail"])
        self.assertEqual(storage.read_json("code_submissions.json"), {"code_submissions": original})

    def test_exam_results_regrading_resolves_runtime_ids_and_rejects_other_releases(self):
        exam = self.result_exam_fixture()
        with patch("app.general_exams.regrade_submission", return_value={"id": "submission-a"}) as regrade:
            status, response = self.request("POST", "/api/admin/exam-results/main-exam/regrade", cookie=self.admin_cookie,
                payload={"submission_id": "submission-a", "use_latest_spec": False})
            self.assertEqual(status, 200, response)
            regrade.assert_called_once_with("runtime-a", "submission-a", "admin-1", "127.0.0.1", use_latest_spec=False, lifecycle_status="ended")
            regrade.reset_mock()
            status, response = self.request("POST", "/api/admin/exam-results/main-exam/regrade", cookie=self.admin_cookie,
                payload={"submission_id": "old-release"})
            self.assertEqual(status, 404, response)
            regrade.assert_not_called()
            with patch("app.general_exams.release_student_exam_scores") as release:
                status, response = self.request("POST", "/api/admin/exam-results/main-exam/regrade-student", cookie=self.admin_cookie,
                    payload={"student_id": "student-1", "question_id": "question-a"})
            self.assertEqual(status, 200, response)
            self.assertEqual(len(response["result"]["regraded"]), 1)
            release.assert_called_once_with("current-release")
            regrade.reset_mock()
            storage.write_json("exams.json", {"main-exam": {**exam, "status": "started"}})
            status, response = self.request("POST", "/api/admin/exam-results/main-exam/regrade", cookie=self.admin_cookie,
                payload={"submission_id": "submission-a"})
            self.assertEqual(status, 409, response)
            regrade.assert_not_called()

    def test_exam_results_regrading_uses_main_lifecycle_not_stale_runtime_status(self):
        self.addCleanup(storage.write_json, "exams.json", storage.read_json("exams.json"))
        runtime_id = self.create_started_code_exam()
        with patch("app.code_exams.execute_question", return_value=_execution()):
            status, submitted = self.request("POST", "/api/student/code/submit", cookie=self.student_cookie,
                payload={"question_id": "echo-question", "source_code": "print(input())\n"})
        self.assertEqual(status, 201, submitted)
        runtime = storage.read_json("code_exams.json")[runtime_id]
        storage.write_json("exams.json", {"main-exam": {
            "id": "main-exam", "title": "Main exam", "status": "ended",
            "items": [{"type": "code", "code_exam_id": runtime_id}],
            "release": {"release_id": runtime["release_id"]},
        }})
        record = storage.read_json("code_submissions.json")["student-1"][0]
        with patch("app.code_exams.execute_question", return_value=_execution()):
            status, response = self.request("POST", "/api/admin/exam-results/main-exam/regrade", cookie=self.admin_cookie,
                payload={"submission_id": record["id"]})
        self.assertEqual(status, 200, response)
        self.assertEqual(len(response["submission"]["grading_history"]), 1)
        self.assertEqual(storage.read_json("code_exams.json")[runtime_id]["status"], "started")

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
        updated_payload.update(self.question_state_tokens("draft-question"))
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
            payload=self.question_state_tokens("draft-question"),
        )
        self.assertEqual(status, 201, duplicate)
        duplicate_id = duplicate["question"]["id"]
        self.assertNotEqual(duplicate_id, "draft-question")
        status, deleted = self.request(
            "POST",
            f"/api/admin/questions/{duplicate_id}/delete",
            cookie=self.admin_cookie,
            payload=self.question_state_tokens(duplicate_id),
        )
        self.assertEqual(status, 200, deleted)

        exam_id = self.create_started_code_exam()
        status, blocked = self.request(
            "POST",
            "/api/admin/questions/echo-question/delete",
            cookie=self.admin_cookie,
            payload=self.question_state_tokens("echo-question"),
        )
        self.assertEqual(status, 409, blocked)
        status, archived = self.request(
            "POST",
            "/api/admin/questions/echo-question/archive",
            cookie=self.admin_cookie,
            payload=self.question_state_tokens("echo-question"),
        )
        self.assertEqual(status, 200, archived)
        self.assertEqual(archived["question"]["status"], "archived")
        self.assertEqual(storage.read_json("code_exams.json")[exam_id]["status"], "started")
        status, rejected = self.request(
            "POST",
            "/api/admin/questions/echo-question/update",
            cookie=self.admin_cookie,
            payload={**archived["question"], **self.question_state_tokens("echo-question")},
        )
        self.assertEqual(status, 409, rejected)

    def test_question_delete_handles_legacy_submission_wrapper(self):
        question = {
            "id": "wrapper-question",
            "title": "Wrapper question",
            "language": "python",
            "grading_mode": "stdio",
            "total_points": 10,
            "tests": [_VISIBLE, _HIDDEN],
        }
        status, created = self.request(
            "POST", "/api/admin/questions", cookie=self.admin_cookie, payload=question
        )
        self.assertEqual(status, 201, created)

        storage.write_json(
            "code_submissions.json",
            {
                "code_submissions": {
                    "legacy-student": [{"question_id": "wrapper-question"}]
                },
                "student-1": [],
            },
        )
        status, blocked = self.request(
            "POST",
            "/api/admin/questions/wrapper-question/delete",
            cookie=self.admin_cookie,
            payload=self.question_state_tokens("wrapper-question"),
        )
        self.assertEqual(status, 409, blocked)

        storage.write_json(
            "code_submissions.json",
            {
                "code_submissions": {
                    "legacy-student": [{"question_id": "unrelated-question"}]
                },
                "student-1": [],
            },
        )
        status, deleted = self.request(
            "POST",
            "/api/admin/questions/wrapper-question/delete",
            cookie=self.admin_cookie,
            payload=self.question_state_tokens("wrapper-question"),
        )
        self.assertEqual(status, 200, deleted)

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
        update_payload = {
            **current,
            **self.question_state_tokens("echo-question"),
            "sample_source": _SAMPLE_SOURCE,
        }
        with patch("app.code_exams.execute_question", return_value=_execution()):
            status, updated = self.request(
                "POST",
                "/api/admin/questions/echo-question/update",
                cookie=self.admin_cookie,
                payload=update_payload,
            )
        self.assertEqual(status, 200, updated)
        new_version = updated["question"]["version"]

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
                payload={"sample_source": _SAMPLE_SOURCE, **self.question_state_tokens("echo-question")},
            )
        self.assertEqual(status, 200, validation)
        status, published = self.request(
            "POST",
            "/api/admin/questions/echo-question/publish",
            cookie=self.admin_cookie,
            payload=self.question_state_tokens("echo-question"),
        )
        self.assertEqual(status, 200, published)
        created = self.create_draft_code_exam(["echo-question"], title="Visible after each submission", show_final_score_immediately=True)
        exam_id = created["id"]
        self.distribute_and_start_code_exam(exam_id)
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

    def test_submission_list_resolves_exam_by_release_and_numbers_attempts_per_release(self):
        storage.write_json("students.json", {"student-1": {"active": True, "full_name": "Student One"}})
        storage.write_json("exams.json", {
            "exam-old": {"id": "exam-old", "title": "Old Exam", "release": {"release_id": "release-old"}},
            "exam-current": {"id": "exam-current", "title": "Current Exam", "release": {"release_id": "release-current"}},
            "exam-duplicate-a": {"id": "exam-duplicate-a", "title": "Duplicate Name", "release": {"release_id": "release-a"}},
            "exam-duplicate-b": {"id": "exam-duplicate-b", "title": "Duplicate Name", "release": {"release_id": "release-b"}},
        })
        storage.write_json("submissions.json", {"student-1": [
            {"filename": "old-1.zip", "release_id": "release-old", "submitted_at": "2026-01-01T00:00:00Z"},
            {"filename": "old-2.zip", "release_id": "release-old", "submitted_at": "2026-01-02T00:00:00Z"},
            {"filename": "current-1.zip", "release_id": "release-current", "submitted_at": "2026-01-03T00:00:00Z"},
            {"filename": "duplicate-a.zip", "release_id": "release-a", "submitted_at": "2026-01-04T00:00:00Z"},
            {"filename": "duplicate-b.zip", "release_id": "release-b", "submitted_at": "2026-01-05T00:00:00Z"},
            {"filename": "unresolved.zip", "release_id": "missing-release", "submitted_at": "2026-01-06T00:00:00Z"},
            {"filename": "legacy.zip", "submitted_at": "2026-01-07T00:00:00Z"},
        ], "student-2": [
            {"filename": "student-2-first.zip", "release_id": "release-old", "submitted_at": "2026-01-08T00:00:00Z"},
        ]})

        status, response = self.request("GET", "/api/admin/submissions", cookie=self.admin_cookie)
        self.assertEqual(status, 200, response)
        rows = {row["filename"]: row for row in response["submissions"]}
        self.assertEqual([rows[name]["attempt"] for name in ("old-1.zip", "old-2.zip", "current-1.zip")], [1, 2, 1])
        self.assertEqual(rows["old-1.zip"]["exam_name"], "Old Exam")
        self.assertEqual(rows["current-1.zip"]["exam_name"], "Current Exam")
        self.assertEqual(rows["duplicate-a.zip"]["exam_name"], "Duplicate Name")
        self.assertEqual(rows["duplicate-b.zip"]["exam_name"], "Duplicate Name")
        self.assertEqual(rows["unresolved.zip"]["exam_name"], "\u004b\u0068\u00f4\u006e\u0067 \u0078\u00e1\u0063 \u0111\u1ecb\u006e\u0068")
        self.assertEqual(rows["legacy.zip"]["exam_name"], "\u004b\u0068\u00f4\u006e\u0067 \u0078\u00e1\u0063 \u0111\u1ecb\u006e\u0068")
        self.assertIsNone(rows["legacy.zip"]["attempt"])
        self.assertEqual(rows["student-2-first.zip"]["attempt"], 1)

    def test_submission_exam_file_matches_monitor_assignment_for_each_student(self):
        now = datetime.now(timezone.utc)
        end = (now + timedelta(minutes=10)).isoformat()
        started = (now - timedelta(minutes=1)).isoformat()
        release_id = "zip-file-release"
        storage.write_json("students.json", {
            "student-1": {"active": True, "full_name": "Student One"},
            "student-2": {"active": True, "full_name": "Student Two"},
            "student-3": {"active": True, "full_name": "Student Three"},
        })
        settings = storage.read_json("settings.json")
        settings.update({"exam_state": "started", "exam_released": True, "exam_release_id": release_id})
        storage.write_json("settings.json", settings)
        assignments = {
            sid: {"release_id": release_id, "exam_file": filename, "status": "in_progress",
                  "started_at": started, "ends_at": end}
            for sid, filename in (("student-1", "\u0110\u1ec1 1.pdf"), ("student-2", "\u0110\u1ec1 3.pdf"))
        }
        storage.write_json("assignments.json", assignments)
        storage.write_json("exams.json", {
            "exam-current": {"id": "exam-current", "title": "SIU", "status": "started",
                             "release": {"release_id": release_id, "assignments": {
                                 "student-1": "\u0110\u1ec1 1.pdf", "student-2": "\u0110\u1ec1 3.pdf"}}}
        })
        storage.write_json("submissions.json", {
            "student-1": [{"filename": "one.zip", "release_id": release_id}],
            "student-2": [{"filename": "two.zip", "release_id": release_id}],
            "student-3": [{"filename": "unknown.zip", "release_id": release_id}],
        })

        status, submission_response = self.request("GET", "/api/admin/submissions", cookie=self.admin_cookie)
        self.assertEqual(status, 200, submission_response)
        submission_files = {row["student_id"]: row["exam_file"] for row in submission_response["submissions"]}
        status, monitor_response = self.request("GET", "/api/admin/monitor", cookie=self.admin_cookie)
        self.assertEqual(status, 200, monitor_response)
        monitor_files = {row["student_id"]: row["exam_file"] for row in monitor_response["students"]}
        self.assertEqual(submission_files["student-1"], "\u0110\u1ec1 1.pdf")
        self.assertEqual(submission_files["student-2"], "\u0110\u1ec1 3.pdf")
        self.assertEqual(submission_files["student-3"], "\u004b\u0068\u00f4\u006e\u0067 \u0078\u00e1\u0063 \u0111\u1ecb\u006e\u0068")
        self.assertEqual(submission_files["student-1"], monitor_files["student-1"])
        self.assertEqual(submission_files["student-2"], monitor_files["student-2"])

    def test_new_zip_filename_is_readable_safe_and_immediately_downloadable(self):
        assignment = self._file_exam_assignment()
        assignment["exam_file"] = "De:02?.zip"
        storage.write_json("assignments.json", {"student-1": assignment})
        storage.write_json("students.json", {"student-1": {"active": True, "full_name": "Nguy\u1ec5n V\u0103n A"}})
        storage.write_json("exams.json", {
            "exam-1": {"id": "exam-1", "title": "Java: Cu\u1ed1i k\u1ef3?", "release": {"release_id": "file-release"}}
        })
        with tempfile.TemporaryDirectory(prefix="css-zip-readable-") as upload_root:
            upload_dir = Path(upload_root)
            with patch("app.submissions.UPLOAD_DIR", upload_dir):
                status, result = self._upload_zip(b"filename test")
                self.assertEqual(status, 200, result)
                record = result["submission"]
                filename = record["filename"]
                self.assertEqual(filename, next(iter(upload_dir.iterdir())).name)
                self.assertLessEqual(len(filename), 180)
                self.assertRegex(filename, r"^student-1_Nguyen_Van_A_Java_Cuoi_ky_L01_[0-9a-f]{6}\.zip$")
                self.assertFalse(any(char in filename for char in '<>:"/\\|?*'))
                self.assertEqual((upload_dir / filename).read_bytes(), self._valid_zip(b"filename test"))

                status, downloaded = self.request(
                    "GET", f"/admin/submissions/student-1/{urllib.parse.quote(filename, safe='')}",
                    cookie=self.admin_cookie, parse_json=False,
                )
                self.assertEqual(status, 200)
                self.assertEqual(downloaded, self._valid_zip(b"filename test"))

                status, listing = self.request("GET", "/api/admin/submissions", cookie=self.admin_cookie)
                self.assertEqual(status, 200, listing)
                row = next(item for item in listing["submissions"] if item["filename"] == filename)
                self.assertEqual(row["attempt"], 1)
                self.assertEqual(row["exam_name"], "Java: Cu\u1ed1i k\u1ef3?")

                # Historical filenames remain downloadable through stored metadata.
                (upload_dir / "legacy-name.zip").write_bytes(b"legacy")
                records = storage.read_json("submissions.json")
                records["student-1"].append({"filename": "legacy-name.zip", "release_id": "file-release", "payload_retained": True})
                storage.write_json("submissions.json", records)
                status, legacy = self.request("GET", "/admin/submissions/student-1/legacy-name.zip", cookie=self.admin_cookie, parse_json=False)
                self.assertEqual((status, legacy), (200, b"legacy"))

    def test_readable_zip_filename_retries_exclusive_create_collisions(self):
        self._file_exam_assignment()
        with tempfile.TemporaryDirectory(prefix="css-zip-name-collision-") as upload_root:
            upload_dir = Path(upload_root)
            collision = upload_dir / "student-1_Student_Khong_xac_dinh_L01_abcdef.zip"
            collision.write_bytes(b"do not overwrite")
            with patch("app.submissions.UPLOAD_DIR", upload_dir), patch(
                "app.submissions.uuid.uuid4", side_effect=[Mock(hex="abcdef"), Mock(hex="123456")]
            ):
                status, result = self._upload_zip(b"new submission")
            self.assertEqual(status, 200, result)
            self.assertTrue(result["submission"]["filename"].endswith("_123456.zip"))
            self.assertEqual(collision.read_bytes(), b"do not overwrite")
            self.assertEqual((upload_dir / result["submission"]["filename"]).read_bytes(), self._valid_zip(b"new submission"))

    def test_readable_zip_filenames_and_attempt_numbers_follow_overwrite_policy(self):
        for overwrite in (False, True):
            with self.subTest(overwrite_previous=overwrite), tempfile.TemporaryDirectory(prefix="css-zip-attempt-names-") as upload_root:
                self._file_exam_assignment()
                settings = storage.read_json("settings.json")
                settings["overwrite_previous"] = overwrite
                storage.write_json("settings.json", settings)
                with patch("app.submissions.UPLOAD_DIR", Path(upload_root)):
                    first_status, first = self._upload_zip(b"first")
                    second_status, second = self._upload_zip(b"second")
                    self.assertEqual(first_status, 200, first)
                    self.assertEqual(second_status, 200, second)
                    self.assertIn("_L01_", first["submission"]["filename"])
                    self.assertIn("_L02_", second["submission"]["filename"])
                    self.assertNotEqual(first["submission"]["filename"], second["submission"]["filename"])
                    records = storage.read_json("submissions.json")["student-1"]
                    self.assertEqual(len(records), 2)
                    if overwrite:
                        self.assertFalse(records[0]["payload_retained"])
                        self.assertTrue(records[1]["payload_retained"])
                    else:
                        self.assertTrue(records[0]["payload_retained"])
                        self.assertTrue(records[1]["payload_retained"])
                    status, listing = self.request("GET", "/api/admin/submissions", cookie=self.admin_cookie)
                    self.assertEqual(status, 200, listing)
                    displayed = {row["filename"]: row["attempt"] for row in listing["submissions"]}
                    self.assertEqual(displayed[first["submission"]["filename"]], 1)
                    self.assertEqual(displayed[second["submission"]["filename"]], 2)

if __name__ == "__main__":
    unittest.main()
