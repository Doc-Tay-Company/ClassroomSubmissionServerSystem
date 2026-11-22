import io
import hashlib
import os
import unittest
from datetime import datetime, timedelta, timezone
import zipfile
from types import SimpleNamespace
from unittest.mock import patch
from app import main
from app.config import SESSION_COOKIE
from app.accounts import parse_accounts
from app.http import inline_filename_header
from app.security import hash_password, verify_password, check_origin, SecurityError
from app.submissions import validate_zip

class CoreTests(unittest.TestCase):
    def test_account_parser_trims_spaces_and_flags_duplicates(self):
        rows, errors = parse_accounts(" 21010001 | 01/02/2003 | Nguyen Van A  \n21010001|01/02/2003|Duplicate\n\n# comment")
        self.assertEqual(rows, [{"student_id": "21010001", "dob": "01/02/2003", "full_name": "Nguyen Van A"}])
        self.assertEqual(len(errors), 1)
        self.assertIn("lặp", errors[0]["message"])

    def test_password_hash(self):
        encoded = hash_password("01/02/2003")
        self.assertTrue(encoded.startswith("scrypt$"))
        self.assertTrue(verify_password("01/02/2003", encoded))
        self.assertFalse(verify_password("02/01/2003", encoded))


    def test_origin_accepts_same_origin_on_custom_port(self):
        request = SimpleNamespace(headers={"Origin": "http://localhost:8080", "Host": "localhost:8080"})
        check_origin(request)

    def test_origin_accepts_host_case_normalization(self):
        request = SimpleNamespace(headers={"Origin": "http://LOCALHOST:8080", "Host": "localhost:8080"})
        check_origin(request)

    def test_origin_rejects_different_host(self):
        request = SimpleNamespace(headers={"Origin": "http://evil.example:8080", "Host": "localhost:8080"})
        with self.assertRaises(SecurityError):
            check_origin(request)

    def test_origin_rejects_different_port(self):
        request = SimpleNamespace(headers={"Origin": "http://localhost:8000", "Host": "localhost:8080"})
        with self.assertRaises(SecurityError):
            check_origin(request)

    def test_origin_accepts_ipv6_normalization(self):
        request = SimpleNamespace(headers={"Origin": "http://[0:0:0:0:0:0:0:1]:8080", "Host": "[::1]:8080"})
        check_origin(request)

    def test_origin_rejects_different_scheme_when_request_scheme_is_known(self):
        request = SimpleNamespace(
            headers={"Origin": "https://localhost:8080", "Host": "localhost:8080"},
            scheme="http",
        )
        with self.assertRaises(SecurityError):
            check_origin(request)

    def test_origin_accepts_trailing_dot_in_host(self):
        request = SimpleNamespace(headers={"Origin": "http://localhost:8080", "Host": "localhost.:8080"})
        check_origin(request)

    def test_origin_error_identifies_received_values(self):
        request = SimpleNamespace(headers={"Origin": "null", "Host": "localhost:8080"})
        with self.assertRaisesRegex(SecurityError, r"Origin=null, Host=localhost:8080"):
            check_origin(request)

    def test_origin_null_accepts_verified_loopback_browser_request(self):
        request = SimpleNamespace(
            headers={
                "Origin": "null",
                "Host": "127.0.0.1:8080",
                "Sec-Fetch-Site": "same-origin",
            }
        )
        check_origin(request)

    def test_origin_null_rejects_file_like_request(self):
        request = SimpleNamespace(
            headers={"Origin": "null", "Host": "127.0.0.1:8080", "Sec-Fetch-Site": "none"}
        )
        with self.assertRaises(SecurityError):
            check_origin(request)

    def test_valid_zip(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("Main.java", "class Main {}")
        self.assertEqual(validate_zip(buffer.getvalue()), (True, "ZIP hợp lệ."))

    def test_invalid_zip(self):
        valid, message = validate_zip(b"not a zip")
        self.assertFalse(valid)
        self.assertIn("chữ ký ZIP", message)

    def test_inline_exam_filename_header_is_ascii_safe(self):
        header = inline_filename_header("Đề thi cuối kỳ.pdf")
        self.assertTrue(header.startswith('inline; filename="'))
        self.assertIn("filename*=UTF-8''", header)
        self.assertNotRegex(header, r"[\r\n]")

    def test_student_telemetry_uses_hashed_session_key_and_reaches_monitor(self):
        token = "student-session-token"
        token_key = hashlib.sha256(token.encode("utf-8")).hexdigest()
        state = {
            "sessions.json": {
                token_key: {
                    "user_id": "21010001",
                    "role": "student",
                    "last_seen": main.utc_now(),
                }
            },
            "students.json": {"21010001": {"full_name": "Test Student"}},
            "exams.json": {},
            "settings.json": {"exam_state": "started", "exam_released": True, "exam_release_id": "release-1"},
            "assignments.json": {"21010001": {"release_id": "release-1", "started_at": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(), "ends_at": (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat(), "status": "in_progress"}},
            "submissions.json": {},
            "code_submissions.json": {},
            "exam_monitoring.json": {"attempts": {}},
        }
        request = SimpleNamespace(
            path="/api/student/telemetry",
            form={
                "visibility": "hidden",
                "focused": "false",
                "tab_count": "2",
                "browser": "Test Browser",
            },
            cookies={SESSION_COOKIE: token},
        )
        handler = object.__new__(main.Handler)
        handler._parse_body = lambda: (b"", request)
        handler._auth = lambda _request, _role: {"user_id": "21010001", "token": token, "token_key": token_key}
        handler._json = lambda payload, status=200, headers=None: payload

        with patch("app.main.read_json", side_effect=lambda name: state[name]), patch(
            "app.exam_monitoring.read_json", side_effect=lambda name: state[name]
        ), patch(
            "app.main.write_json", side_effect=lambda name, value: state.update({name: value})
        ):
            response = handler.do_POST()
            snapshot = main.monitoring_snapshot()

        self.assertEqual(response, {"ok": True})
        self.assertEqual(state["sessions.json"][token_key]["telemetry"]["tab_count"], 2)
        self.assertEqual(state["sessions.json"][token_key]["telemetry"]["release_id"], "release-1")
        self.assertCountEqual(
            snapshot["students"][0]["alerts"],
            ["tab_hidden", "window_unfocused", "multiple_tabs"],
        )



    def test_student_status_exposes_backend_active_attempt_without_changing_existing_fields(self):
        now = datetime.now(timezone.utc)
        state = {
            "settings.json": {"exam_state": "started", "exam_released": True, "exam_release_id": "release-1"},
            "assignments.json": {"student-1": {"release_id": "release-1", "started_at": (now - timedelta(minutes=1)).isoformat(), "ends_at": (now + timedelta(minutes=5)).isoformat(), "status": "in_progress"}},
            "notifications.json": [],
            "exam_monitoring.json": {"attempts": {}},
        }
        request = SimpleNamespace(path="/api/student/status", query={})
        handler = object.__new__(main.Handler)
        handler._request = lambda: request
        handler._auth = lambda _request, _role: {"user_id": "student-1"}
        handler._json = lambda payload, status=200, headers=None: payload

        with patch("app.main.read_json", side_effect=lambda name, *args: state.get(name, args[0] if args else {})), patch(
            "app.main.general_exams.published_for_students", return_value=[]
        ):
            response = handler.do_GET()

        self.assertTrue(response["active_exam_attempt"])
        self.assertTrue(response["practice_locked"])
        self.assertTrue(response["assigned"])
        self.assertTrue(response["started"])
        self.assertEqual(response["release_id"], "release-1")

    def test_active_exam_attempt_requires_current_started_assignment_and_deadline(self):
        now = datetime.now(timezone.utc)
        settings = {"exam_state": "started", "exam_released": True, "exam_release_id": "release-1"}
        active = {
            "release_id": "release-1",
            "started_at": (now - timedelta(minutes=1)).isoformat(),
            "ends_at": (now + timedelta(minutes=5)).isoformat(),
            "status": "in_progress",
        }
        self.assertTrue(main.is_active_exam_attempt("student-1", settings, active, now))
        cases = [
            ({**settings, "exam_state": "distributed"}, active),
            ({**settings, "exam_released": False}, active),
            (settings, {}),
            (settings, {**active, "release_id": "old-release"}),
            (settings, {**active, "started_at": None}),
            (settings, {**active, "status": "assigned"}),
            (settings, {**active, "status": "submitted"}),
            (settings, {**active, "status": "ended"}),
            (settings, {**active, "status": "expired"}),
            (settings, {**active, "forced_submit": True}),
            (settings, {**active, "ends_at": (now - timedelta(seconds=1)).isoformat()}),
            (settings, {**active, "started_at": (now + timedelta(seconds=1)).isoformat()}),
            (settings, {**active, "ends_at": "invalid"}),
        ]
        for candidate_settings, candidate_assignment in cases:
            with self.subTest(settings=candidate_settings, assignment=candidate_assignment):
                self.assertFalse(main.is_active_exam_attempt("student-1", candidate_settings, candidate_assignment, now))

    def test_inactive_telemetry_is_ignored_without_overwriting_session_snapshot(self):
        token = "student-session-token"
        token_key = hashlib.sha256(token.encode("utf-8")).hexdigest()
        old_snapshot = {"visibility": "hidden", "focused": False, "tab_count": 2, "browser": "old", "updated_at": main.utc_now()}
        state = {
            "sessions.json": {token_key: {"user_id": "student-1", "role": "student", "last_seen": main.utc_now(), "telemetry": old_snapshot}},
            "settings.json": {"exam_state": "started", "exam_released": True, "exam_release_id": "release-1"},
            "assignments.json": {"student-1": {"release_id": "release-1", "status": "assigned"}},
        }
        request = SimpleNamespace(
            path="/api/student/telemetry",
            form={"visibility": "visible", "focused": "true", "tab_count": "1", "browser": "new"},
            cookies={SESSION_COOKIE: token},
        )
        handler = object.__new__(main.Handler)
        handler._parse_body = lambda: (b"", request)
        handler._auth = lambda _request, _role: {"user_id": "student-1", "token": token, "token_key": token_key}
        handler._json = lambda payload, status=200, headers=None: payload

        with patch("app.main.read_json", side_effect=lambda name: state[name]), patch(
            "app.main.write_json", side_effect=lambda name, value: state.update({name: value})
        ) as write_json:
            response = handler.do_POST()

        self.assertEqual(response, {"ok": True})
        self.assertEqual(state["sessions.json"][token_key]["telemetry"], old_snapshot)
        write_json.assert_not_called()

    def test_monitor_hides_stale_telemetry_when_attempt_is_inactive_but_keeps_presence(self):
        token_key = "hashed-session"
        state = {
            "students.json": {"student-1": {"full_name": "Test Student"}},
            "exams.json": {},
            "sessions.json": {token_key: {"user_id": "student-1", "role": "student", "last_seen": main.utc_now(), "telemetry": {"visibility": "hidden", "focused": False, "tab_count": 2, "release_id": "old-release"}}},
            "assignments.json": {"student-1": {"release_id": "old-release", "status": "ended", "started_at": main.utc_now(), "ends_at": main.utc_now()}},
            "submissions.json": {},
            "code_submissions.json": {},
            "exam_monitoring.json": {"attempts": {}},
            "settings.json": {"exam_state": "ended", "exam_released": False, "exam_release_id": None},
        }
        with patch("app.main.read_json", side_effect=lambda name: state[name]), patch(
            "app.exam_monitoring.read_json", side_effect=lambda name: state[name]
        ):
            snapshot = main.monitoring_snapshot()

        student = snapshot["students"][0]
        self.assertTrue(student["logged_in"])
        self.assertFalse(student["active_exam_attempt"])
        self.assertEqual(student["telemetry"], {})
        self.assertEqual(student["alerts"], [])

if __name__ == "__main__":
    unittest.main()
