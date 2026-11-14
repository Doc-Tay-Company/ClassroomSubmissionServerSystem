from http.server import ThreadingHTTPServer
import http.client
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
import unittest
from unittest.mock import patch

from app import storage
from app import main
from app import practice
from app.code_exams import (
    compute_spec_hash,
    compute_grading_hash,
    publish_question,
    publish_question_candidate,
    update_published_question,
)
from app.practice import (
    PracticeError,
    classify_practice_percentage,
    compute_catalog_token,
    compute_practice_percentage,
    delete_student_question_progress,
    get_active_run,
    get_practice_catalog,
    get_progress_with_availability,
    get_student_progress,
    is_practice_eligible,
    is_valid_revision,
    practice_public_projection,
    release_active_run,
    reserve_active_run,
    update_question_progress,
)
from app.questions import (
    QuestionError,
    archive_question,
    create_question,
    duplicate_question,
    get_question,
    revoke_question,
    update_question,
)
from app.security import new_session


_CANARY_REF = "CANARY_SECRET_REFERENCE_SOURCE_CODE"
_CANARY_HIDDEN = "CANARY_SECRET_HIDDEN_EXPECTED_OUTPUT"
_CANARY_NOTE = "CANARY_SECRET_INTERNAL_NOTE"

_SAMPLE_STDIO = "print('hello')\n"


def _mock_exec():
    return {
        "verdict": "AC",
        "score": 10,
        "total_points": 10,
        "duration_ms": 10,
        "error": None,
        "error_category": None,
        "tests": [
            {"id": "v1", "verdict": "AC", "passed": True, "points": 5, "points_earned": 5, "is_visible": True, "expected_stdout": "hello\n", "actual_stdout": "hello\n", "stderr": "", "duration_ms": 5, "error": None},
            {"id": "h1", "verdict": "AC", "passed": True, "points": 5, "points_earned": 5, "is_visible": False, "expected_stdout": _CANARY_HIDDEN, "actual_stdout": _CANARY_HIDDEN, "stderr": "", "duration_ms": 5, "error": None},
        ],
    }


def _make_stdio_payload(qid="q1", *, practice_enabled=False, client_rev=None):
    payload = {
        "id": qid,
        "title": f"Question {qid}",
        "statement": "Print hello world",
        "language": "python",
        "grading_mode": "stdio",
        "starter_code": "# start here\n",
        "time_limit_seconds": 2.0,
        "memory_limit_mb": 128,
        "max_output_bytes": 4096,
        "category": "Basic",
        "tags": ["intro", "io"],
        "difficulty": "Dễ",
        "practice_enabled": practice_enabled,
        "tests": [
            {
                "id": "v1",
                "name": "Visible 1",
                "stdin": "1\n",
                "expected_stdout": "hello\n",
                "points": 5,
                "is_visible": True,
                "secret_internal_detail": "SHOULD_NOT_LEAK",
            },
            {
                "id": "h1",
                "name": "Hidden 1",
                "stdin": "2\n",
                "expected_stdout": _CANARY_HIDDEN,
                "points": 5,
                "is_visible": False,
            },
        ],
        "total_points": 10,
        "reference_source": _CANARY_REF,
        "internal_teacher_notes": _CANARY_NOTE,
    }
    if client_rev is not None:
        payload["practice_revision"] = client_rev
    return payload


def _make_reflection_payload(qid="q_refl", *, practice_enabled=True):
    return {
        "id": qid,
        "title": "Reflection Q",
        "statement": "Implement Student class",
        "language": "java",
        "grading_mode": "reflection",
        "problem_kind": "java_reflection",
        "target_class": "model.Student",
        "target_package": "model",
        "target_file": "Student.java",
        "starter_code": "package model;\npublic class Student {}\n",
        "time_limit_seconds": 3.0,
        "memory_limit_mb": 256,
        "max_output_bytes": 8192,
        "category": "OOP",
        "tags": ["java", "class"],
        "difficulty": "Trung bình",
        "practice_enabled": practice_enabled,
        "checks": [
            {
                "id": "chk_v",
                "kind": "field",
                "name": "Field name check",
                "description": "Must have private String name",
                "points": 4,
                "is_visible": True,
                "hidden_extra_eval": "SECRET_CHECK_EVAL",
            },
            {
                "id": "chk_h",
                "kind": "method",
                "name": "Hidden method check",
                "description": "Hidden private logic",
                "points": 6,
                "is_visible": False,
            },
        ],
        "total_points": 10,
        "reference_source": "public class Student { private String name; }",
    }


class PracticeFoundationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._orig_data_dir = storage.DATA_DIR
        cls._orig_log_dir = storage.LOG_DIR
        cls._test_temp = tempfile.TemporaryDirectory(prefix="css-practice-test-")
        cls._test_data_root = Path(cls._test_temp.name)
        storage.DATA_DIR = cls._test_data_root / "data"
        storage.LOG_DIR = cls._test_data_root / "logs"
        storage.DATA_DIR.mkdir(parents=True, exist_ok=True)
        storage.LOG_DIR.mkdir(parents=True, exist_ok=True)

        main.initialize()
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), main.Handler)
        cls.server.daemon_threads = True
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        try:
            cls.server.shutdown()
            cls.server.server_close()
            cls.thread.join(timeout=2)
        finally:
            storage.DATA_DIR = cls._orig_data_dir
            storage.LOG_DIR = cls._orig_log_dir
            cls._test_temp.cleanup()

    def setUp(self):
        for name, value in {
            "admins.json": {"admin-1": {"password": "x", "active": True}},
            "students.json": {
                "student-1": {"password": "x", "active": True, "full_name": "Nguyen Van A"},
                "student-2": {"password": "x", "active": True, "full_name": "Tran Van B"},
                "student-inactive": {"password": "x", "active": False, "full_name": "Inactive Student"},
            },
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
            "notifications.json": [],
            "practice_progress.json": {},
        }.items():
            storage.write_json(name, value)
        self.admin_cookie = new_session("admin-1", "admin", "127.0.0.1", "test")
        self.student_cookie = new_session("student-1", "student", "127.0.0.1", "test")
        self.student2_cookie = new_session("student-2", "student", "127.0.0.1", "test")
        self.inactive_cookie = new_session("student-inactive", "student", "127.0.0.1", "test")

    def request(self, method, path, *, cookie=None, payload=None, parse_json=True):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {}
        raw_body = None
        if cookie:
            headers["Cookie"] = f"css_session={cookie}"
        if payload is not None:
            raw_body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        connection.request(method, path, body=raw_body, headers=headers)
        response = connection.getresponse()
        raw = response.read()
        status = response.status
        connection.close()
        parsed = json.loads(raw.decode("utf-8")) if raw and parse_json else raw.decode("utf-8", "replace")
        return status, parsed

    # -------------------------------------------------------------------------
    # 1. Practice enabled normalization and strict boolean validation (F-02)
    # -------------------------------------------------------------------------
    def test_practice_enabled_strict_boolean_and_defaults(self):
        # Default when omitted is False (tested without practice_enabled key)
        raw_payload = _make_stdio_payload("q_omitted")
        raw_payload.pop("practice_enabled", None)
        q_omitted = create_question(raw_payload, "admin-1", "127.0.0.1")
        self.assertFalse(q_omitted["practice_enabled"])
        self.assertTrue(is_valid_revision(q_omitted["practice_revision"]))

        # Explicit True
        q2 = create_question(_make_stdio_payload("q2", practice_enabled=True), "admin-1", "127.0.0.1")
        self.assertTrue(q2["practice_enabled"])
        self.assertTrue(is_valid_revision(q2["practice_revision"]))

        # Rejection of non-boolean types on create
        for bad_val in ["false", "true", "0", "1", 0, 1, None, [], {}]:
            bad_payload = _make_stdio_payload("q_bad")
            bad_payload["practice_enabled"] = bad_val
            with self.assertRaises(QuestionError):
                create_question(bad_payload, "admin-1", "127.0.0.1")

        # Rejection of non-boolean types on update
        for bad_val in ["false", 0, None]:
            bad_update = dict(q2)
            bad_update["practice_enabled"] = bad_val
            with self.assertRaises(QuestionError):
                update_question("q2", bad_update, "admin-1", "127.0.0.1")

        # Update omitting practice_enabled retains existing value
        up_payload = {
            "title": "Updated Title",
            "statement": "New statement",
            "language": q2["language"],
            "grading_mode": q2["grading_mode"],
            "tests": q2["tests"],
            "total_points": q2["total_points"],
            "time_limit_seconds": 2,
            "memory_limit_mb": 128,
            "max_output_bytes": 4096,
            "expected_version": q2["version"],
            "expected_practice_revision": q2["practice_revision"],
        }
        up1 = update_question("q2", up_payload, "admin-1", "127.0.0.1")
        self.assertTrue(up1["practice_enabled"])
        self.assertNotEqual(up1["practice_revision"], q2["practice_revision"])

        # Duplicate question forces practice_enabled=False
        dup = duplicate_question("q2", {"expected_version": up1["version"], "expected_practice_revision": up1["practice_revision"]}, "admin-1", "127.0.0.1")
        self.assertFalse(dup["practice_enabled"])
        self.assertNotEqual(dup["id"], q2["id"])

    # -------------------------------------------------------------------------
    # 2. Canonical STDIO fields projection & canaries (F-03)
    # -------------------------------------------------------------------------
    def test_canonical_stdio_fields_and_canaries(self):
        q = _make_stdio_payload("q_stdio_canon", practice_enabled=True)
        q["status"] = "published"
        q["practice_revision"] = "f" * 32
        q["validation"] = {"passed": True, "canary": "SECRET_VALIDATION_CANARY"}

        proj = practice_public_projection(q)
        serialized = json.dumps(proj)

        # Ensure canonical stdin / expected_stdout are present
        self.assertEqual(len(proj["tests"]), 1)
        visible_test = proj["tests"][0]
        self.assertEqual(visible_test["id"], "v1")
        self.assertEqual(visible_test["stdin"], "1\n")
        self.assertEqual(visible_test["expected_stdout"], "hello\n")

        # Check that NO canaries leak
        self.assertNotIn(_CANARY_REF, serialized)
        self.assertNotIn(_CANARY_HIDDEN, serialized)
        self.assertNotIn(_CANARY_NOTE, serialized)
        self.assertNotIn("SECRET_VALIDATION_CANARY", serialized)
        self.assertNotIn("SHOULD_NOT_LEAK", serialized)
        self.assertNotIn("internal_teacher_notes", proj)
        self.assertNotIn("reference_source", proj)
        self.assertNotIn("validation", proj)

        # Reflection mode projection
        refl_q = _make_reflection_payload("refl_canary", practice_enabled=True)
        refl_q["status"] = "published"
        refl_q["practice_revision"] = "e" * 32
        refl_proj = practice_public_projection(refl_q)
        refl_serialized = json.dumps(refl_proj)

        self.assertNotIn("SECRET_CHECK_EVAL", refl_serialized)
        self.assertNotIn("checks", proj)
        self.assertIn("checks", refl_proj)
        self.assertEqual(len(refl_proj["checks"]), 1)
        self.assertEqual(refl_proj["checks"][0]["id"], "chk_v")

    # -------------------------------------------------------------------------
    # 3. Active account verification on Practice APIs (F-04)
    # -------------------------------------------------------------------------
    def test_practice_apis_active_student_account_required(self):
        q = _make_stdio_payload("q_active_test", practice_enabled=True)
        q["status"] = "published"
        q["practice_revision"] = "a" * 32
        questions = storage.read_json("questions.json")
        questions["q_active_test"] = q
        storage.write_json("questions.json", questions)

        # Active student gets 200
        status, res = self.request("GET", "/api/student/practice/questions", cookie=self.student_cookie)
        self.assertEqual(status, 200)

        status, res = self.request("GET", "/api/student/practice/questions/q_active_test", cookie=self.student_cookie)
        self.assertEqual(status, 200)
        self.assertEqual(res["question"]["tests"][0]["stdin"], "1\n")
        self.assertEqual(res["question"]["tests"][0]["expected_stdout"], "hello\n")

        # Inactive student gets 401
        status, res = self.request("GET", "/api/student/practice/questions", cookie=self.inactive_cookie)
        self.assertEqual(status, 401)

        status, res = self.request("GET", "/api/student/practice/questions/q_active_test", cookie=self.inactive_cookie)
        self.assertEqual(status, 401)

        # Deleted student session gets 401
        ghost_cookie = new_session("ghost-user", "student", "127.0.0.1", "test")
        status, res = self.request("GET", "/api/student/practice/questions", cookie=ghost_cookie)
        self.assertEqual(status, 401)
        status, res = self.request("GET", "/api/student/practice/questions/q_active_test", cookie=ghost_cookie)
        self.assertEqual(status, 401)

    # -------------------------------------------------------------------------
    # 4. Single-snapshot catalog and token generation (F-05)
    # -------------------------------------------------------------------------
    def test_single_snapshot_catalog_and_token(self):
        q = _make_stdio_payload("q_snap", practice_enabled=True)
        q["status"] = "published"
        q["practice_revision"] = "b" * 32
        questions = storage.read_json("questions.json")
        questions["q_snap"] = q
        storage.write_json("questions.json", questions)

        status, res = self.request("GET", "/api/student/practice/questions", cookie=self.student_cookie)
        self.assertEqual(status, 200)
        expected_token = compute_catalog_token({"q_snap": q})
        self.assertEqual(res["catalog_token"], expected_token)

    # -------------------------------------------------------------------------
    # 5. Optimistic concurrency protection (F-07)
    # -------------------------------------------------------------------------
    def test_optimistic_concurrency_protection(self):
        q = create_question(_make_stdio_payload("q_concur", practice_enabled=True), "admin-1", "127.0.0.1")
        initial_version = q["version"]
        initial_revision = q["practice_revision"]

        # Teacher 1 saves draft update with expected version
        update_payload = {
            "title": "T1 Update",
            "statement": q["statement"],
            "language": q["language"],
            "grading_mode": q["grading_mode"],
            "tests": q["tests"],
            "total_points": q["total_points"],
            "time_limit_seconds": 2,
            "memory_limit_mb": 128,
            "max_output_bytes": 4096,
            "expected_version": initial_version,
            "expected_practice_revision": initial_revision,
        }
        up1 = update_question("q_concur", update_payload, "admin-1", "127.0.0.1")
        self.assertEqual(up1["version"], initial_version + 1)

        # Teacher 2 attempts save with stale expected version -> 409 QUESTION_CHANGED
        stale_payload = {
            "title": "T2 Stale Update",
            "statement": q["statement"],
            "language": q["language"],
            "grading_mode": q["grading_mode"],
            "tests": q["tests"],
            "total_points": q["total_points"],
            "time_limit_seconds": 2,
            "memory_limit_mb": 128,
            "max_output_bytes": 4096,
            "expected_version": initial_version,
            "expected_practice_revision": initial_revision,
        }
        with self.assertRaises(QuestionError) as ctx:
            update_question("q_concur", stale_payload, "admin-1", "127.0.0.1")
        self.assertEqual(ctx.exception.status, 409)

    # -------------------------------------------------------------------------
    # 6. Practice revision lifecycle & security
    # -------------------------------------------------------------------------
    def test_practice_revision_lifecycle(self):
        # Client cannot inject practice_revision
        q = create_question(_make_stdio_payload("q_inject", client_rev="evil_custom_revision_token_1234"), "admin-1", "127.0.0.1")
        self.assertNotEqual(q["practice_revision"], "evil_custom_revision_token_1234")
        self.assertTrue(is_valid_revision(q["practice_revision"]))
        initial_rev = q["practice_revision"]

        # Update draft changes revision
        up = update_question("q_inject", {
            "title": "Title changed",
            "statement": q["statement"],
            "language": q["language"],
            "grading_mode": q["grading_mode"],
            "tests": q["tests"],
            "total_points": q["total_points"],
            "time_limit_seconds": 2,
            "memory_limit_mb": 128,
            "max_output_bytes": 4096,
            "expected_version": q["version"],
            "expected_practice_revision": q["practice_revision"],
        }, "admin-1", "127.0.0.1")
        self.assertNotEqual(up["practice_revision"], initial_rev)
        draft_rev = up["practice_revision"]

        # Archive changes revision
        arch = archive_question("q_inject", {"expected_version": up["version"], "expected_practice_revision": up["practice_revision"]}, "admin-1", "127.0.0.1")
        self.assertEqual(arch["status"], "archived")
        self.assertNotEqual(arch["practice_revision"], draft_rev)

    # -------------------------------------------------------------------------
    # 7. Spec hash and grading hash immunity
    # -------------------------------------------------------------------------
    def test_spec_and_grading_hash_ignore_practice_metadata(self):
        base = _make_stdio_payload("q_hash")
        h1 = compute_spec_hash(base)
        g1 = compute_grading_hash(base)

        with_practice = dict(base)
        with_practice["practice_enabled"] = True
        with_practice["practice_revision"] = "0" * 32
        h2 = compute_spec_hash(with_practice)
        g2 = compute_grading_hash(with_practice)

        self.assertEqual(h1, h2, "compute_spec_hash must ignore practice_enabled and practice_revision")
        self.assertEqual(g1, g2, "compute_grading_hash must ignore practice_enabled and practice_revision")

    # -------------------------------------------------------------------------
    # 8. Eligibility logic
    # -------------------------------------------------------------------------
    def test_eligibility_logic(self):
        q_draft = create_question(_make_stdio_payload("q_e1", practice_enabled=True), "admin-1", "127.0.0.1")
        self.assertFalse(is_practice_eligible(q_draft))

        q_pub_disabled = dict(q_draft)
        q_pub_disabled["status"] = "published"
        q_pub_disabled["practice_enabled"] = False
        self.assertFalse(is_practice_eligible(q_pub_disabled))

        q_bad_rev = dict(q_draft)
        q_bad_rev["status"] = "published"
        q_bad_rev["practice_enabled"] = True
        q_bad_rev["practice_revision"] = "too-short"
        self.assertFalse(is_practice_eligible(q_bad_rev))

        q_eligible = dict(q_draft)
        q_eligible["status"] = "published"
        q_eligible["practice_enabled"] = True
        q_eligible["practice_revision"] = "a" * 32
        self.assertTrue(is_practice_eligible(q_eligible))

    # -------------------------------------------------------------------------
    # 9. Publication transitions, revoke/republish, and validation reuse
    # -------------------------------------------------------------------------
    def test_revoke_republish_and_validation_reuse(self):
        payload = _make_stdio_payload("q_pub", practice_enabled=True)
        with patch("app.code_exams.execute_question", return_value=_mock_exec()):
            pub1 = publish_question_candidate(payload, _SAMPLE_STDIO, "admin-1", "127.0.0.1")
        self.assertTrue(pub1["published"])
        rev1 = pub1["question"]["practice_revision"]
        self.assertTrue(is_valid_revision(rev1))

        up1 = update_published_question("q_pub", dict(payload, title="Title V2", practice_enabled=True, expected_version=pub1["question"]["version"], expected_practice_revision=pub1["question"]["practice_revision"]), _SAMPLE_STDIO, "admin-1", "127.0.0.1")
        self.assertTrue(up1["saved"])
        self.assertTrue(up1.get("reused"), "Metadata-only edit should reuse sample validation")
        rev2 = up1["question"]["practice_revision"]
        self.assertNotEqual(rev1, rev2)

        revoked = revoke_question("q_pub", {"expected_version": up1["question"]["version"], "expected_practice_revision": up1["question"]["practice_revision"]}, "admin-1", "127.0.0.1")
        self.assertEqual(revoked["status"], "draft")
        rev3 = revoked["practice_revision"]
        self.assertNotEqual(rev2, rev3)

        repub = publish_question("q_pub", {"expected_version": revoked["version"], "expected_practice_revision": revoked["practice_revision"]}, "admin-1", "127.0.0.1")
        self.assertEqual(repub["status"], "published")
        rev4 = repub["practice_revision"]
        self.assertNotEqual(rev3, rev4)
        self.assertNotEqual(rev1, rev4)

    # -------------------------------------------------------------------------
    # 10. Official exam creation non-interference
    # -------------------------------------------------------------------------
    def test_exam_creation_from_published_practice_disabled(self):
        from app.code_exams import create_code_exam

        payload = _make_stdio_payload("q_exam", practice_enabled=False)
        with patch("app.code_exams.execute_question", return_value=_mock_exec()):
            pub = publish_question_candidate(payload, _SAMPLE_STDIO, "admin-1", "127.0.0.1")
        self.assertTrue(pub["published"])
        self.assertFalse(pub["question"]["practice_enabled"])

        exam = create_code_exam({
            "title": "Official Coding Exam",
            "question_ids": ["q_exam"],
        }, "admin-1", "127.0.0.1")
        self.assertEqual(len(exam["questions"]), 1)
        self.assertEqual(exam["questions"][0]["question_id"], "q_exam")
        self.assertEqual(exam["questions"][0]["title"], "Question q_exam")

    # -------------------------------------------------------------------------
    # 11. Teacher toggle published question Practice on/off round-trip
    # -------------------------------------------------------------------------
    def test_teacher_toggle_practice_for_published_question(self):
        # 1. Publish a question with practice_enabled=False
        payload = _make_stdio_payload("q_toggle", practice_enabled=False)
        with patch("app.code_exams.execute_question", return_value=_mock_exec()):
            pub = publish_question_candidate(payload, _SAMPLE_STDIO, "admin-1", "127.0.0.1")
        self.assertTrue(pub["published"])
        self.assertFalse(pub["question"]["practice_enabled"])

        # Not in student catalog
        status, res = self.request("GET", "/api/student/practice/questions", cookie=self.student_cookie)
        self.assertEqual(len(res["questions"]), 0)

        # 2. Teacher edits published question: toggles practice_enabled=True
        edit_payload = dict(payload, practice_enabled=True, expected_version=pub["question"]["version"], expected_practice_revision=pub["question"]["practice_revision"])
        up = update_published_question("q_toggle", edit_payload, _SAMPLE_STDIO, "admin-1", "127.0.0.1")
        self.assertTrue(up["saved"])
        self.assertTrue(up["question"]["practice_enabled"])

        # Question now appears in student catalog
        status, res = self.request("GET", "/api/student/practice/questions", cookie=self.student_cookie)
        self.assertEqual(len(res["questions"]), 1)
        self.assertEqual(res["questions"][0]["question_id"], "q_toggle")

        # 3. Teacher toggles back to practice_enabled=False
        disable_payload = dict(payload, practice_enabled=False, expected_version=up["question"]["version"], expected_practice_revision=up["question"]["practice_revision"])
        up2 = update_published_question("q_toggle", disable_payload, _SAMPLE_STDIO, "admin-1", "127.0.0.1")
        self.assertTrue(up2["saved"])
        self.assertFalse(up2["question"]["practice_enabled"])

        # Question is removed from student catalog after refresh
        status, res = self.request("GET", "/api/student/practice/questions", cookie=self.student_cookie)
        self.assertEqual(len(res["questions"]), 0)

    # -------------------------------------------------------------------------
    # 12. HTML Template CSP and Script dependencies verification (F-01, F-06, Checkpoint 2)
    # -------------------------------------------------------------------------
    def test_practice_html_csp_and_dependencies(self):
        status, html = self.request("GET", "/practice", cookie=self.student_cookie, parse_json=False)
        self.assertEqual(status, 200)
        self.assertIn('<link rel="stylesheet" href="/static/css/student-practice.css">', html)
        self.assertNotIn("<style>", html, "Must not contain inline <style> block under CSP")
        self.assertNotIn("style=", html, "Must not contain inline style attributes under CSP")
        self.assertIn('<script defer src="/static/js/student-practice.js"></script>', html)

        # Checkpoint 2: Library & Workspace DOM structure and Student dataset
        self.assertIn('id="practice-root"', html)
        self.assertIn('data-student-id="student-1"', html)
        self.assertIn('id="practice-library-view"', html)
        self.assertIn('id="practice-workspace-view"', html)
        self.assertIn('id="practice-code-editor"', html)
        self.assertIn('id="practice-retest-badge"', html)
        self.assertIn('id="practice-restore-starter-btn"', html)
        self.assertIn('id="practice-modal-host"', html)

    # -------------------------------------------------------------------------
    # 13. Checkpoint 1: Percentage computation & Owner-approved color rules
    # -------------------------------------------------------------------------
    def test_percentage_computation_and_color_thresholds(self):
        # 100% -> green
        p100 = compute_practice_percentage(10, 10)
        self.assertEqual(p100, 100.0)
        self.assertEqual(classify_practice_percentage(p100), "green")

        # > 50% and < 100% -> orange (light orange)
        p75 = compute_practice_percentage(7.5, 10)
        self.assertEqual(p75, 75.0)
        self.assertEqual(classify_practice_percentage(p75), "orange")

        p50_1 = compute_practice_percentage(5.01, 10)
        self.assertEqual(classify_practice_percentage(p50_1), "orange")

        # Exactly 50% -> orange (Owner-approved: 50% is light orange)
        p50 = compute_practice_percentage(5, 10)
        self.assertEqual(p50, 50.0)
        self.assertEqual(classify_practice_percentage(p50), "orange")

        # < 50% -> red
        p49_9 = compute_practice_percentage(4.99, 10)
        self.assertEqual(classify_practice_percentage(p49_9), "red")

        p0 = compute_practice_percentage(0, 10)
        self.assertEqual(p0, 0.0)
        self.assertEqual(classify_practice_percentage(p0), "red")

        # Invalid or 0 denominator -> None (unscored)
        self.assertIsNone(compute_practice_percentage(5, 0))
        self.assertIsNone(compute_practice_percentage(5, -10))
        self.assertIsNone(compute_practice_percentage(5, "invalid"))
        self.assertIsNone(compute_practice_percentage("invalid", 10))
        self.assertIsNone(classify_practice_percentage(None))

    # -------------------------------------------------------------------------
    # 14. Checkpoint 1: Progress projection, availability union, and student isolation
    # -------------------------------------------------------------------------
    def test_student_progress_get_endpoint_and_availability_union(self):
        # Create published practice-enabled question (available)
        q_avail = _make_stdio_payload("q_avail", practice_enabled=True)
        q_avail["status"] = "published"
        q_avail["practice_revision"] = "1" * 32

        # Create published practice-disabled question (unavailable)
        q_unavail = _make_stdio_payload("q_unavail", practice_enabled=False)
        q_unavail["status"] = "published"
        q_unavail["practice_revision"] = "2" * 32

        questions = {"q_avail": q_avail, "q_unavail": q_unavail}
        storage.write_json("questions.json", questions)

        # Record progress for student-1 on both questions
        attempt_1 = "a" * 32
        attempt_2 = "b" * 32
        storage.write_json("practice_progress.json", {
            "student-1": {
                "q_avail": {
                    "practice_revision": "1" * 32,
                    "attempt_id": attempt_1,
                    "last_run_sequence": 1,
                    "has_result": True,
                    "earned_visible_points": 5,
                    "maximum_visible_points": 5,
                    "practice_percentage": 100.0,
                    "score_available": True,
                    "result_summary": [{"id": "v1", "verdict": "AC", "passed": True, "points_earned": 5}],
                    "updated_at": "2026-11-13T00:00:00Z",
                },
                "q_unavail": {
                    "practice_revision": "2" * 32,
                    "attempt_id": attempt_2,
                    "last_run_sequence": 1,
                    "has_result": True,
                    "earned_visible_points": 2.5,
                    "maximum_visible_points": 5,
                    "practice_percentage": 50.0,
                    "score_available": True,
                    "result_summary": [],
                    "updated_at": "2026-11-13T00:00:00Z",
                },
            },
            "student-2": {
                "q_avail": {
                    "practice_revision": "1" * 32,
                    "attempt_id": "c" * 32,
                    "last_run_sequence": 1,
                    "has_result": True,
                    "earned_visible_points": 0,
                    "maximum_visible_points": 5,
                    "practice_percentage": 0.0,
                    "score_available": True,
                    "result_summary": [],
                    "updated_at": "2026-11-13T00:00:00Z",
                }
            }
        })

        # Inactive student receives 401
        status, _ = self.request("GET", "/api/student/practice/progress", cookie=self.inactive_cookie)
        self.assertEqual(status, 401)

        # Student-1 requests progress: gets both available and unavailable progress union
        status, res = self.request("GET", "/api/student/practice/progress", cookie=self.student_cookie)
        self.assertEqual(status, 200)
        self.assertTrue(res["ok"])
        items = {item["question_id"]: item for item in res["progress"]}

        # q_avail is available
        self.assertIn("q_avail", items)
        self.assertTrue(items["q_avail"]["available"])
        self.assertIsNotNone(items["q_avail"]["progress"])
        self.assertEqual(items["q_avail"]["progress"]["practice_percentage"], 100.0)
        self.assertEqual(items["q_avail"]["progress"]["attempt_id"], attempt_1)

        # q_unavail is unavailable but retained with available=False and its progress
        self.assertIn("q_unavail", items)
        self.assertFalse(items["q_unavail"]["available"])
        self.assertIsNotNone(items["q_unavail"]["progress"])
        self.assertEqual(items["q_unavail"]["progress"]["practice_percentage"], 50.0)
        self.assertEqual(items["q_unavail"]["progress"]["attempt_id"], attempt_2)

        # Student isolation: student-2 sees their own progress, NOT student-1's progress
        status, res2 = self.request("GET", "/api/student/practice/progress", cookie=self.student2_cookie)
        self.assertEqual(status, 200)
        items2 = {item["question_id"]: item for item in res2["progress"]}
        self.assertIn("q_avail", items2)
        self.assertEqual(items2["q_avail"]["progress"]["practice_percentage"], 0.0)
        self.assertEqual(items2["q_avail"]["progress"]["attempt_id"], "c" * 32)
        # student-2 has no progress on q_unavail, so it must NOT appear in student-2's progress list
        self.assertNotIn("q_unavail", items2)

        # Canaries: no reference source or hidden test leaks in progress projection
        serialized = json.dumps(res)
        self.assertNotIn(_CANARY_REF, serialized)
        self.assertNotIn(_CANARY_HIDDEN, serialized)
        self.assertNotIn(_CANARY_NOTE, serialized)

    def test_progress_result_summary_is_allowlisted_and_malformed_rows_are_omitted(self):
        q = _make_stdio_payload("q_safe_summary", practice_enabled=True)
        q["status"] = "published"
        q["practice_revision"] = "1" * 32
        storage.write_json("questions.json", {"q_safe_summary": q})
        storage.write_json("practice_progress.json", {
            "student-1": {
                "q_safe_summary": {
                    "practice_revision": "1" * 32,
                    "attempt_id": "a" * 32,
                    "has_result": True,
                    "result_summary": [
                        {
                            "id": "visible-1", "verdict": "AC", "passed": True,
                            "points_earned": 5, "is_visible": True,
                            "expected_stdout": _CANARY_HIDDEN,
                            "reference_source": _CANARY_REF,
                            "internal_note": _CANARY_NOTE,
                        },
                        {"id": "hidden-1", "verdict": "AC", "passed": True,
                         "is_visible": False, "expected_stdout": _CANARY_HIDDEN},
                        "malformed row with " + _CANARY_NOTE,
                        {"id": "bad-verdict", "verdict": ["AC"], "passed": True},
                        {"id": "bad-points", "verdict": "WA", "passed": False,
                         "points_earned": float("nan")},
                        None,
                    ],
                }
            }
        })

        status, response = self.request("GET", "/api/student/practice/progress", cookie=self.student_cookie)
        self.assertEqual(status, 200, response)
        rows = {item["question_id"]: item for item in response["progress"]}
        visible = rows["q_safe_summary"]["progress"]["result_summary"]
        self.assertEqual(visible, [{
            "id": "visible-1", "verdict": "AC", "passed": True, "points_earned": 5,
        }])
        serialized = json.dumps(response)
        self.assertNotIn(_CANARY_HIDDEN, serialized)
        self.assertNotIn(_CANARY_REF, serialized)
        self.assertNotIn(_CANARY_NOTE, serialized)

    def _assert_question_change_serializes_with_progress(self, teacher_change):
        qid = f"q_lock_update_{teacher_change}"
        base_revision = "1" * 32
        target_revision = "2" * 32
        current = _make_stdio_payload(qid, practice_enabled=True)
        current.update({"status": "published", "practice_revision": target_revision,
                        "version": 3, "source": {"created_by": "admin-1"}})
        storage.write_json("questions.json", {qid: current})
        old_attempt = "a" * 32
        progress_revision = base_revision
        storage.write_json("practice_progress.json", {
            "student-1": {qid: {
                "practice_revision": progress_revision,
                "attempt_id": old_attempt,
                "last_run_sequence": 4,
                "has_result": True,
                "earned_visible_points": 5,
                "maximum_visible_points": 5,
                "practice_percentage": 100.0,
                "score_available": True,
                "result_summary": [{"id": "visible", "verdict": "AC", "passed": True}],
                "updated_at": "2026-11-13T00:00:00Z",
            }}
        })

        eligibility_checked = threading.Event()
        allow_progress_commit = threading.Event()
        teacher_started = threading.Event()
        teacher_finished = threading.Event()
        errors = []
        original_eligibility = practice.is_practice_eligible

        def pause_after_eligibility(question):
            result = original_eligibility(question)
            if threading.current_thread().name == "student-progress-mutation":
                eligibility_checked.set()
                if not allow_progress_commit.wait(timeout=3):
                    raise AssertionError("test did not release the Student mutation")
            return result

        def student_mutation():
            try:
                update_question_progress("student-1", qid, old_attempt, base_revision, target_revision)
            except BaseException as exc:
                errors.append(exc)

        def teacher_mutation():
            teacher_started.set()
            try:
                if teacher_change == "revoke":
                    revoke_question(qid, {
                        "expected_version": current["version"],
                        "expected_practice_revision": current["practice_revision"],
                    }, "admin-1", "127.0.0.1")
                else:
                    def change_revision(questions):
                        questions[qid]["practice_revision"] = "3" * 32
                        questions[qid]["version"] += 1
                    storage.update_json("questions.json", change_revision)
            except BaseException as exc:
                errors.append(exc)
            finally:
                teacher_finished.set()

        with patch("app.practice.is_practice_eligible", side_effect=pause_after_eligibility):
            student_thread = threading.Thread(target=student_mutation, name="student-progress-mutation")
            student_thread.start()
            self.assertTrue(eligibility_checked.wait(timeout=2), "Student did not reach eligibility check")
            teacher_thread = threading.Thread(target=teacher_mutation, name="teacher-question-mutation")
            teacher_thread.start()
            self.assertTrue(teacher_started.wait(timeout=2), "Teacher mutation did not start")
            self.assertFalse(teacher_finished.wait(timeout=0.1), "Teacher mutation interleaved before progress commit")
            allow_progress_commit.set()
            student_thread.join(timeout=3)
            teacher_thread.join(timeout=3)

        self.assertFalse(student_thread.is_alive())
        self.assertFalse(teacher_thread.is_alive())
        self.assertEqual(errors, [])
        stored_question = storage.read_json("questions.json")[qid]
        stored_progress = storage.read_json("practice_progress.json")["student-1"][qid]
        if teacher_change == "revoke":
            self.assertEqual(stored_question["status"], "draft")
        else:
            self.assertEqual(stored_question["practice_revision"], "3" * 32)
        self.assertEqual(stored_progress["attempt_id"], old_attempt)
        self.assertEqual(stored_progress["practice_revision"], target_revision)
        self.assertFalse(stored_progress["has_result"])
        self.assertIsNone(stored_progress["practice_percentage"])

    def test_update_serializes_with_teacher_revoke_and_revision_change(self):
        for teacher_change in ("revoke", "revision"):
            with self.subTest(teacher_change=teacher_change):
                self._assert_question_change_serializes_with_progress(teacher_change)

    # -------------------------------------------------------------------------
    # 15. Checkpoint 1: Owner-only atomic deletion
    # -------------------------------------------------------------------------
    def test_student_progress_delete_endpoint(self):
        # Set up progress for student-1
        storage.write_json("practice_progress.json", {
            "student-1": {
                "q_del": {
                    "practice_revision": "1" * 32,
                    "attempt_id": "a" * 32,
                    "has_result": True,
                    "earned_visible_points": 5,
                    "maximum_visible_points": 5,
                    "practice_percentage": 100.0,
                    "score_available": True,
                    "result_summary": [],
                    "updated_at": "2026-11-13T00:00:00Z",
                }
            }
        })

        # Student-2 attempts to delete student-1's record -> 404 (isolation)
        status, _ = self.request("DELETE", "/api/student/practice/progress/q_del", cookie=self.student2_cookie)
        self.assertEqual(status, 404)
        progress = storage.read_json("practice_progress.json")
        self.assertIn("q_del", progress["student-1"])

        # Inactive student attempts delete -> 401
        status, _ = self.request("DELETE", "/api/student/practice/progress/q_del", cookie=self.inactive_cookie)
        self.assertEqual(status, 401)

        # Student-1 deletes their own progress -> 200
        status, res = self.request("DELETE", "/api/student/practice/progress/q_del", cookie=self.student_cookie)
        self.assertEqual(status, 200)
        self.assertTrue(res["ok"])
        progress = storage.read_json("practice_progress.json")
        self.assertNotIn("student-1", progress)

        # Second delete returns 404 (idempotent 404 on already deleted)
        status, _ = self.request("DELETE", "/api/student/practice/progress/q_del", cookie=self.student_cookie)
        self.assertEqual(status, 404)

    # -------------------------------------------------------------------------
    # 16. Checkpoint 1: Update CAS lifecycle
    # -------------------------------------------------------------------------
    def test_update_cas_lifecycle(self):
        # Initial question revision 1
        q = _make_stdio_payload("q_update", practice_enabled=True)
        q["status"] = "published"
        rev1 = "1" * 32
        rev2 = "2" * 32
        q["practice_revision"] = rev2  # Bank has updated to revision 2
        storage.write_json("questions.json", {"q_update": q})

        attempt_id = "a" * 32
        # Student progress was recorded at revision 1
        storage.write_json("practice_progress.json", {
            "student-1": {
                "q_update": {
                    "practice_revision": rev1,
                    "attempt_id": attempt_id,
                    "last_run_sequence": 2,
                    "has_result": True,
                    "earned_visible_points": 5,
                    "maximum_visible_points": 5,
                    "practice_percentage": 100.0,
                    "score_available": True,
                    "result_summary": [{"id": "v1", "verdict": "AC"}],
                    "updated_at": "2026-11-13T00:00:00Z",
                }
            }
        })

        # Rejects invalid revision format
        status, _ = self.request("POST", "/api/student/practice/questions/q_update/update", cookie=self.student_cookie, payload={
            "expected_attempt_id": attempt_id,
            "old_practice_revision": rev1,
            "new_practice_revision": "not-valid",
        })
        self.assertEqual(status, 422)

        # Rejects stale old_practice_revision
        status, _ = self.request("POST", "/api/student/practice/questions/q_update/update", cookie=self.student_cookie, payload={
            "expected_attempt_id": attempt_id,
            "old_practice_revision": "wrong-rev-32-chars-long!!!!!!!!",
            "new_practice_revision": rev2,
        })
        self.assertEqual(status, 409)

        # Rejects revision mismatch (if client sends revision different from what's in bank)
        status, _ = self.request("POST", "/api/student/practice/questions/q_update/update", cookie=self.student_cookie, payload={
            "expected_attempt_id": attempt_id,
            "old_practice_revision": rev1,
            "new_practice_revision": "3" * 32,
        })
        self.assertEqual(status, 409)

        # Valid update: preserves attempt_id, adopts rev2, invalidates old score
        status, res = self.request("POST", "/api/student/practice/questions/q_update/update", cookie=self.student_cookie, payload={
            "expected_attempt_id": attempt_id,
            "old_practice_revision": rev1,
            "new_practice_revision": rev2,
        })
        self.assertEqual(status, 200)
        self.assertTrue(res["ok"])

        stored = storage.read_json("practice_progress.json")["student-1"]["q_update"]
        self.assertEqual(stored["attempt_id"], attempt_id, "Attempt ID must be preserved on Update")
        self.assertEqual(stored["practice_revision"], rev2, "Must advance to new practice revision")
        self.assertFalse(stored["has_result"], "Previous score must be invalidated")
        self.assertIsNone(stored["practice_percentage"])
        self.assertEqual(stored["result_summary"], [])

    def test_legacy_attempt_reset_route_is_not_available(self):
        q = _make_stdio_payload("q_no_reset_route", practice_enabled=True)
        q.update({"status": "published", "practice_revision": "1" * 32})
        storage.write_json("questions.json", {q["id"]: q})
        progress = {"student-1": {q["id"]: {
            "practice_revision": "1" * 32,
            "attempt_id": "a" * 32,
            "has_result": True,
            "practice_percentage": 80,
        }}}
        storage.write_json("practice_progress.json", progress)

        status, _ = self.request("POST", f"/api/student/practice/questions/{q['id']}/redo",
                                 cookie=self.student_cookie, payload={})

        self.assertEqual(status, 404)
        self.assertEqual(storage.read_json("practice_progress.json"), progress)

    # -------------------------------------------------------------------------
    # 18. Checkpoint 1: In-memory active-run registry and status endpoint
    # -------------------------------------------------------------------------
    def test_active_run_registry_and_status_endpoint(self):
        qid = "q_active_run"
        sid = "student-1"
        attempt_id = "a" * 32
        rev = "1" * 32

        # Initially inactive
        status, res = self.request("GET", f"/api/student/practice/questions/{qid}/run-status", cookie=self.student_cookie)
        self.assertEqual(status, 200)
        self.assertFalse(res["active"])
        self.assertIsNone(res["attempt_id"])
        self.assertIsNone(res["practice_revision"])

        # Reserve active run
        reserved = reserve_active_run(sid, qid, attempt_id, rev, 1)
        self.assertTrue(reserved)

        # Overlapping reservation for same student-question rejected
        overlap = reserve_active_run(sid, qid, "b" * 32, rev, 2)
        self.assertFalse(overlap, "Second reservation for same (student, question) must be rejected")

        # Reservation for DIFFERENT student succeeds (independent)
        other_student = reserve_active_run("student-2", qid, "c" * 32, rev, 1)
        self.assertTrue(other_student)

        # Status endpoint reports active state for student-1
        status, res = self.request("GET", f"/api/student/practice/questions/{qid}/run-status", cookie=self.student_cookie)
        self.assertEqual(status, 200)
        self.assertTrue(res["active"])
        self.assertEqual(res["attempt_id"], attempt_id)
        self.assertEqual(res["practice_revision"], rev)

        # Status endpoint for student-2 reports student-2's attempt
        status, res2 = self.request("GET", f"/api/student/practice/questions/{qid}/run-status", cookie=self.student2_cookie)
        self.assertEqual(status, 200)
        self.assertTrue(res2["active"])
        self.assertEqual(res2["attempt_id"], "c" * 32)

        # Release active run
        release_active_run(sid, qid)
        release_active_run("student-2", qid)

        # Status endpoint now reports inactive
        status, res = self.request("GET", f"/api/student/practice/questions/{qid}/run-status", cookie=self.student_cookie)
        self.assertEqual(status, 200)
        self.assertFalse(res["active"])

        # Verify no JSON writes were made to progress store for active-run state
        progress = storage.read_json("practice_progress.json")
        self.assertNotIn(qid, progress.get(sid, {}))

    def _store_practice_run_question(self, qid="q_run"):
        question = _make_stdio_payload(qid, practice_enabled=True)
        question.update({"status": "published", "practice_revision": "e" * 32, "version": 1})
        storage.write_json("questions.json", {qid: question})
        return question

    def _practice_run_payload(self, question, attempt_id="a" * 32, source="print('ok')"):
        return {
            "question_id": question["id"],
            "expected_practice_revision": question["practice_revision"],
            "attempt_id": attempt_id,
            "source_code": source,
        }

    def test_practice_run_visible_only_scoring_and_confidentiality(self):
        question = self._store_practice_run_question()
        question["tests"].insert(1, {
            "id": "v2", "name": "Visible 2", "stdin": "", "expected_stdout": "never\n",
            "points": 3, "is_visible": True,
        })
        question["tests"][0]["points"] = 2
        question["total_points"] = 10
        storage.write_json("questions.json", {question["id"]: question})
        request_payload = self._practice_run_payload(question)
        before_official = {
            name: storage.read_json(name)
            for name in ("code_runs.json", "code_submissions.json", "code_exams.json", "assignments.json")
        }
        execution = {
            "verdict": "WA", "score": 2, "total_points": 5, "error_category": None,
            "tests": [
                {"id": "v1", "verdict": "AC", "passed": True, "points": 2, "points_earned": 2, "is_visible": True},
                {"id": "v2", "verdict": "WA", "passed": False, "points": 3, "points_earned": 0, "is_visible": True},
                {"id": "h1", "verdict": "AC", "passed": True, "points": 5, "points_earned": 5, "is_visible": False, "expected_stdout": _CANARY_HIDDEN},
            ],
        }
        with patch("app.code_exams.execute_question", return_value=execution) as execute:
            status, result = self.request("POST", "/api/student/practice/run", cookie=self.student_cookie, payload=request_payload)
        self.assertEqual(status, 200, result)
        execute.assert_called_once()
        self.assertTrue(execute.call_args.kwargs["visible_only"])
        passed_question = execute.call_args.args[0]
        self.assertEqual(len(passed_question["tests"]), 3, "server owns the full spec; the execution engine receives an explicit visible_only gate")
        self.assertEqual(result["practice_percentage"], 40.0)
        self.assertEqual(result["earned_visible_points"], 2)
        self.assertEqual(result["maximum_visible_points"], 5)
        encoded = json.dumps(result)
        self.assertNotIn(_CANARY_HIDDEN, encoded)
        self.assertNotIn(_CANARY_REF, encoded)
        self.assertNotIn(_CANARY_NOTE, encoded)
        self.assertEqual([row["id"] for row in result["results"]], ["v1", "v2"])
        progress = storage.read_json("practice_progress.json")["student-1"][question["id"]]
        self.assertEqual(progress["attempt_id"], request_payload["attempt_id"])
        self.assertEqual(progress["last_run_sequence"], 1)
        self.assertNotIn("source_code", progress)
        self.assertNotIn("reference_source", progress)
        self.assertEqual(before_official, {
            name: storage.read_json(name)
            for name in before_official
        })

    def test_practice_run_authorization_eligibility_and_request_allowlist(self):
        question = self._store_practice_run_question("q_run_auth")
        payload = self._practice_run_payload(question)
        with patch("app.code_exams.execute_question") as execute:
            status, _ = self.request("POST", "/api/student/practice/run", payload=payload)
            self.assertEqual(status, 401)
            status, _ = self.request("POST", "/api/student/practice/run", cookie=self.inactive_cookie, payload=payload)
            self.assertEqual(status, 401)
            status, _ = self.request("POST", "/api/student/practice/run", cookie=self.admin_cookie, payload=payload)
            self.assertEqual(status, 403)
            disabled = dict(question, practice_enabled=False)
            storage.write_json("questions.json", {question["id"]: disabled})
            status, result = self.request("POST", "/api/student/practice/run", cookie=self.student_cookie, payload=payload)
            self.assertEqual(status, 404)
            self.assertEqual(result["code"], "PRACTICE_NOT_ELIGIBLE")
            storage.write_json("questions.json", {question["id"]: question})
            forged = dict(payload, tests=question["tests"], reference_source=_CANARY_REF)
            status, result = self.request("POST", "/api/student/practice/run", cookie=self.student_cookie, payload=forged)
            self.assertEqual(status, 422)
            self.assertEqual(result["code"], "INVALID_REQUEST")
            execute.assert_not_called()
        self.assertEqual(storage.read_json("practice_progress.json"), {})

    def test_practice_run_rejections_and_infrastructure_preserve_score(self):
        question = self._store_practice_run_question("q_run_preserve")
        payload = self._practice_run_payload(question)
        status, result = self.request("POST", "/api/student/practice/run", cookie=self.student_cookie,
                                      payload={key: value for key, value in payload.items() if key != "attempt_id"})
        self.assertEqual(status, 409)
        self.assertEqual(result["code"], "ATTEMPT_REQUIRED")
        self.assertEqual(storage.read_json("practice_progress.json"), {})

        attempt = payload["attempt_id"]
        storage.write_json("practice_progress.json", {"student-1": {question["id"]: {
            "practice_revision": question["practice_revision"], "attempt_id": attempt,
            "last_run_sequence": 4, "has_result": True, "earned_visible_points": 2,
            "maximum_visible_points": 5, "practice_percentage": 40.0, "score_available": True,
            "result_summary": [{"id": "v1", "verdict": "WA", "passed": False, "points_earned": 2}],
            "updated_at": "before",
        }}})
        infrastructure = {"verdict": "JUDGE_INFRA_ERROR", "error_category": "JUDGE_INFRA_ERROR", "tests": []}
        with patch("app.code_exams.execute_question", return_value=infrastructure):
            status, result = self.request("POST", "/api/student/practice/run", cookie=self.student_cookie, payload=payload)
        self.assertEqual(status, 503)
        self.assertEqual(result["code"], "JUDGE_INFRA_ERROR")
        retained = storage.read_json("practice_progress.json")["student-1"][question["id"]]
        self.assertEqual(retained["practice_percentage"], 40.0)
        self.assertEqual(retained["last_run_sequence"], 4)

        malformed_runner_result = {"verdict": ["AC"], "error_category": None, "tests": []}
        with patch("app.code_exams.execute_question", return_value=malformed_runner_result):
            status, result = self.request("POST", "/api/student/practice/run", cookie=self.student_cookie, payload=payload)
        self.assertEqual(status, 503)
        self.assertEqual(result["code"], "PROTOCOL_ERROR")
        retained = storage.read_json("practice_progress.json")["student-1"][question["id"]]
        self.assertEqual(retained["practice_percentage"], 40.0)
        self.assertEqual(retained["last_run_sequence"], 4)

        compile_error = {"verdict": "CE", "error_category": None, "tests": [
            {"id": "v1", "verdict": "CE", "passed": False, "points": 5, "points_earned": 0, "is_visible": True}
        ]}
        with patch("app.code_exams.execute_question", return_value=compile_error):
            status, completed = self.request("POST", "/api/student/practice/run", cookie=self.student_cookie, payload=payload)
        self.assertEqual(status, 200)
        self.assertEqual(completed["verdict"], "CE")
        self.assertEqual(completed["practice_percentage"], 0.0)
        replaced = storage.read_json("practice_progress.json")["student-1"][question["id"]]
        self.assertEqual(replaced["last_run_sequence"], 5)
        self.assertEqual(replaced["practice_percentage"], 0.0)

        stale = dict(payload, expected_practice_revision="f" * 32)
        with patch("app.code_exams.execute_question") as execute:
            status, result = self.request("POST", "/api/student/practice/run", cookie=self.student_cookie, payload=stale)
        self.assertEqual(status, 409)
        self.assertEqual(result["code"], "REVISION_MISMATCH")
        execute.assert_not_called()

    def test_practice_run_with_no_visible_points_is_unscored_not_zero_percent(self):
        question = self._store_practice_run_question("q_run_unscored")
        question["tests"] = [question["tests"][1]]
        storage.write_json("questions.json", {question["id"]: question})
        payload = self._practice_run_payload(question)
        with patch("app.code_exams.execute_question", return_value={"verdict": "AC", "tests": [], "error_category": None}):
            status, result = self.request("POST", "/api/student/practice/run", cookie=self.student_cookie, payload=payload)
        self.assertEqual(status, 200)
        self.assertIsNone(result["practice_percentage"])
        self.assertFalse(result["score_available"])
        self.assertEqual(result["maximum_visible_points"], 0)
        stored = storage.read_json("practice_progress.json")["student-1"][question["id"]]
        self.assertTrue(stored["has_result"])
        self.assertIsNone(stored["practice_percentage"])

    def test_practice_run_rejects_overlapping_student_question_execution(self):
        question = self._store_practice_run_question("q_run_overlap")
        payload = self._practice_run_payload(question)
        started = threading.Event()
        finish = threading.Event()

        def slow_execution(*args, **kwargs):
            started.set()
            if not finish.wait(5):
                raise RuntimeError("test execution wait timed out")
            return _mock_exec()

        first_result = []
        with patch("app.code_exams.execute_question", side_effect=slow_execution):
            worker = threading.Thread(target=lambda: first_result.append(
                self.request("POST", "/api/student/practice/run", cookie=self.student_cookie, payload=payload)
            ))
            worker.start()
            self.assertTrue(started.wait(3), "first run did not enter execution")
            status, overlap = self.request("POST", "/api/student/practice/run", cookie=self.student_cookie, payload=payload)
            self.assertEqual(status, 409)
            self.assertEqual(overlap["code"], "RUN_ALREADY_ACTIVE")
            finish.set()
            worker.join(timeout=5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(first_result[0][0], 200)
        progress = storage.read_json("practice_progress.json")["student-1"][question["id"]]
        self.assertEqual(progress["last_run_sequence"], 1)

    def test_practice_run_late_completion_cannot_overwrite_updated_progress(self):
        from app.code_exams import _RUN_SLOTS

        question = self._store_practice_run_question("q_run_stale_finish")
        payload = self._practice_run_payload(question)
        started = threading.Event()
        finish = threading.Event()
        first_result = []

        def slow_execution(*args, **kwargs):
            started.set()
            if not finish.wait(5):
                raise RuntimeError("test execution wait timed out")
            return _mock_exec()

        with patch("app.code_exams.execute_question", side_effect=slow_execution):
            worker = threading.Thread(target=lambda: first_result.append(
                self.request("POST", "/api/student/practice/run", cookie=self.student_cookie, payload=payload)
            ))
            worker.start()
            self.assertTrue(started.wait(3))
            new_revision = "c" * 32
            storage.update_json("questions.json", lambda questions: questions[question["id"]].update({"practice_revision": new_revision}))
            update_question_progress(
                "student-1", question["id"], payload["attempt_id"],
                question["practice_revision"], new_revision,
            )
            finish.set()
            worker.join(timeout=5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(first_result[0][0], 409)
        current = storage.read_json("practice_progress.json")["student-1"][question["id"]]
        self.assertEqual(current["attempt_id"], payload["attempt_id"])
        self.assertEqual(current["practice_revision"], new_revision)
        self.assertFalse(current["has_result"])
        self.assertEqual(current["last_run_sequence"], 0)
        self.assertIsNone(get_active_run("student-1", question["id"]))

        # A later run must release both the shared slot and per-question active reservation.
        self.assertTrue(_RUN_SLOTS.acquire(blocking=False))
        _RUN_SLOTS.release()

    def test_practice_run_busy_shared_capacity_does_not_mutate_progress(self):
        from app.code_exams import MAX_CONCURRENT_RUNS, _RUN_SLOTS

        question = self._store_practice_run_question("q_run_capacity")
        payload = self._practice_run_payload(question)
        held = 0
        try:
            for _ in range(MAX_CONCURRENT_RUNS):
                self.assertTrue(_RUN_SLOTS.acquire(blocking=False))
                held += 1
            status, result = self.request("POST", "/api/student/practice/run", cookie=self.student_cookie, payload=payload)
            self.assertEqual(status, 429)
            self.assertEqual(result["code"], "RUNNER_BUSY")
            self.assertEqual(storage.read_json("practice_progress.json"), {})
        finally:
            for _ in range(held):
                _RUN_SLOTS.release()

    def test_practice_run_completion_after_question_revocation_is_not_saved(self):
        question = self._store_practice_run_question("q_run_revoked")
        payload = self._practice_run_payload(question)
        started = threading.Event()
        finish = threading.Event()
        response = []

        def slow_execution(*args, **kwargs):
            started.set()
            if not finish.wait(5):
                raise RuntimeError("test execution wait timed out")
            return _mock_exec()

        with patch("app.code_exams.execute_question", side_effect=slow_execution):
            worker = threading.Thread(target=lambda: response.append(
                self.request("POST", "/api/student/practice/run", cookie=self.student_cookie, payload=payload)
            ))
            worker.start()
            self.assertTrue(started.wait(3))
            question["practice_enabled"] = False
            storage.write_json("questions.json", {question["id"]: question})
            finish.set()
            worker.join(timeout=5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(response[0][0], 404)
        current = storage.read_json("practice_progress.json")["student-1"][question["id"]]
        self.assertEqual(current["attempt_id"], payload["attempt_id"])
        self.assertFalse(current["has_result"])
        self.assertEqual(current["last_run_sequence"], 0)
        self.assertIsNone(get_active_run("student-1", question["id"]))

    def test_practice_run_completion_after_revision_update_is_not_saved(self):
        question = self._store_practice_run_question("q_run_updated")
        payload = self._practice_run_payload(question)
        new_revision = "f" * 32
        started = threading.Event()
        finish = threading.Event()
        response = []

        def slow_execution(*args, **kwargs):
            started.set()
            if not finish.wait(5):
                raise RuntimeError("test execution wait timed out")
            return _mock_exec()

        with patch("app.code_exams.execute_question", side_effect=slow_execution):
            worker = threading.Thread(target=lambda: response.append(
                self.request("POST", "/api/student/practice/run", cookie=self.student_cookie, payload=payload)
            ))
            worker.start()
            self.assertTrue(started.wait(3))
            question["practice_revision"] = new_revision
            storage.write_json("questions.json", {question["id"]: question})
            update_question_progress("student-1", question["id"], payload["attempt_id"], payload["expected_practice_revision"], new_revision)
            finish.set()
            worker.join(timeout=5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(response[0][0], 409)
        current = storage.read_json("practice_progress.json")["student-1"][question["id"]]
        self.assertEqual(current["practice_revision"], new_revision)
        self.assertEqual(current["attempt_id"], payload["attempt_id"])
        self.assertFalse(current["has_result"])
        self.assertEqual(current["last_run_sequence"], 0)
        self.assertIsNone(get_active_run("student-1", question["id"]))

    @unittest.skipUnless(os.name == "nt", "real execution requires Windows Job Objects")
    def test_practice_run_real_python_runner(self):
        question = self._store_practice_run_question("q_real_python")
        payload = self._practice_run_payload(question, source="print('hello')")
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as workspace_parent:
            with patch.object(practice, "_PRACTICE_WORKSPACE_PARENT", Path(workspace_parent) / "runs"):
                result = practice.run_practice("student-1", payload)
        self.assertEqual(result["verdict"], "AC", result)
        self.assertEqual(result["practice_percentage"], 100.0)
        self.assertEqual([row["id"] for row in result["results"]], ["v1"])
        compile_failure = dict(payload, source_code="if:")
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as workspace_parent:
            with patch.object(practice, "_PRACTICE_WORKSPACE_PARENT", Path(workspace_parent) / "runs"):
                compile_result = practice.run_practice("student-1", compile_failure)
        self.assertEqual(compile_result["verdict"], "CE")
        self.assertEqual(compile_result["practice_percentage"], 0.0)
        self.assertEqual(storage.read_json("practice_progress.json")["student-1"][question["id"]]["practice_percentage"], 0.0)

    @unittest.skipUnless(
        os.name == "nt" and shutil.which("java") and shutil.which("javac"),
        "real Java Reflection execution requires Windows and a configured JDK",
    )
    def test_practice_run_real_java_reflection_runner(self):
        question = _make_reflection_payload("q_real_reflection")
        question["checks"][0].update({"name": "name", "type": "String", "modifier": "private"})
        question.update({"status": "published", "practice_revision": "d" * 32, "version": 1})
        storage.write_json("questions.json", {question["id"]: question})
        payload = {
            "question_id": question["id"],
            "expected_practice_revision": question["practice_revision"],
            "attempt_id": "c" * 32,
            "source_code": "package model; public class Student { private String name; }",
        }
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as workspace_parent:
            with patch.object(practice, "_PRACTICE_WORKSPACE_PARENT", Path(workspace_parent) / "runs"):
                result = practice.run_practice("student-1", payload)
        self.assertEqual(result["verdict"], "AC", result)
        self.assertEqual(result["practice_percentage"], 100.0)
        self.assertEqual([row["id"] for row in result["results"]], ["chk_v"])

    # -------------------------------------------------------------------------
    # 19. Checkpoint 1: Official exam allow_pretest round-trip and regression verification
    # -------------------------------------------------------------------------
    def test_official_exam_allow_pretest_gate_regression(self):
        from app.code_exams import create_code_exam, run_pretest, CodeExamError

        # Create published questions with allow_pretest true and false
        q1 = _make_stdio_payload("q_pt_on", practice_enabled=False)
        q1["allow_pretest"] = True
        q2 = _make_stdio_payload("q_pt_off", practice_enabled=False)
        q2["allow_pretest"] = False

        with patch("app.code_exams.execute_question", return_value=_mock_exec()):
            pub1 = publish_question_candidate(q1, _SAMPLE_STDIO, "admin-1", "127.0.0.1")
            pub2 = publish_question_candidate(q2, _SAMPLE_STDIO, "admin-1", "127.0.0.1")

        # 1. Create exam with allow_pretest=False at exam level
        exam_payload = {
            "title": "Exam Pretest Disabled",
            "question_ids": ["q_pt_on"],
            "allow_pretest": False,
        }
        exam_disabled = create_code_exam(exam_payload, "admin-1", "127.0.0.1")
        self.assertFalse(exam_disabled["allow_pretest"], "Exam level allow_pretest must be False")

        # 2. Create exam with allow_pretest=True at exam level but question with allow_pretest=False
        exam_payload2 = {
            "title": "Exam Pretest Mixed",
            "question_ids": ["q_pt_on", "q_pt_off"],
            "allow_pretest": True,
        }
        exam_mixed = create_code_exam(exam_payload2, "admin-1", "127.0.0.1")
        self.assertTrue(exam_mixed["allow_pretest"])
        q_snapshots = {q["question_id"]: q for q in exam_mixed["questions"]}
        self.assertTrue(q_snapshots["q_pt_on"]["allow_pretest"])
        self.assertFalse(q_snapshots["q_pt_off"]["allow_pretest"])

        # 3. Verify run_pretest gate enforcement:
        # Mock active context for student-1 on exam_disabled -> Pretest is disabled (403)
        with patch("app.code_exams._active_context", return_value=("student-1", {}, exam_disabled)):
            with self.assertRaises(CodeExamError) as ctx:
                run_pretest("student-1", "q_pt_on", "print('test')", "127.0.0.1")
            self.assertEqual(ctx.exception.status, 403)
            self.assertIn("Pretest is disabled", str(ctx.exception))

        # Mock active context for student-1 on exam_mixed for q_pt_off -> 403
        with patch("app.code_exams._active_context", return_value=("student-1", {}, exam_mixed)):
            with self.assertRaises(CodeExamError) as ctx:
                run_pretest("student-1", "q_pt_off", "print('test')", "127.0.0.1")
            self.assertEqual(ctx.exception.status, 403)
            self.assertIn("Pretest is disabled", str(ctx.exception))

        # Mock active context for student-1 on exam_mixed for q_pt_on -> Pretest allowed!
        with patch("app.code_exams._active_context", return_value=("student-1", {}, exam_mixed)), \
             patch("app.code_exams.execute_question", return_value=_mock_exec()), \
             patch("app.code_exams._pretest_reservation", return_value="run-123"), \
             patch("app.code_exams._finish_pretest"), \
             patch("app.code_exams.audit"):
            res = run_pretest("student-1", "q_pt_on", "print('test')", "127.0.0.1")
            self.assertEqual(res["verdict"], "AC")
            self.assertEqual(res["run_id"], "run-123")


if __name__ == "__main__":
    unittest.main()
