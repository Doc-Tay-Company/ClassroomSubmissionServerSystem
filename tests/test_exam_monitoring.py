import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app import exam_monitoring, main, storage


class ExamMonitoringTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="css-exam-monitoring-")
        self.data_dir = Path(self.temp.name) / "data"
        self.data_dir.mkdir()
        self.data_patch = patch.object(storage, "DATA_DIR", self.data_dir)
        self.data_patch.start()
        self.student = "student-1"
        self.release = "release-1"
        now = datetime.now(timezone.utc)
        self.settings = {"exam_state": "started", "exam_released": True, "exam_release_id": self.release}
        self.assignment = {
            "release_id": self.release,
            "status": "in_progress",
            "started_at": (now - timedelta(minutes=1)).isoformat(),
            "ends_at": (now + timedelta(minutes=10)).isoformat(),
        }
        storage.write_json("settings.json", self.settings)
        storage.write_json("assignments.json", {self.student: self.assignment})

    def tearDown(self):
        self.data_patch.stop()
        self.temp.cleanup()

    def test_events_are_independent_idempotent_and_attempt_scoped(self):
        blur, created = exam_monitoring.record_event(self.student, self.release, "event-blur-001", "window_blur")
        hidden, hidden_created = exam_monitoring.record_event(self.student, self.release, "event-hidden-01", "document_hidden")
        retried, retry_created = exam_monitoring.record_event(self.student, self.release, "event-blur-001", "window_blur")
        self.assertTrue(created)
        self.assertTrue(hidden_created)
        self.assertFalse(retry_created)
        self.assertEqual(blur["seq"], 1)
        self.assertEqual(hidden["seq"], 2)
        self.assertEqual(retried["seq"], 1)
        self.assertEqual(exam_monitoring.attempt_summary(self.student, self.release), {
            "event_counters": {**exam_monitoring.DEFAULT_COUNTERS, "window_blur": 1, "document_hidden": 1}, "latest_event_seq": 2,
        })
        self.assertEqual(exam_monitoring.attempt_summary("student-2", self.release)["latest_event_seq"], 0)
        self.assertEqual(exam_monitoring.attempt_summary(self.student, "release-2")["latest_event_seq"], 0)

    def test_concurrent_writes_preserve_each_event_counter_and_sequence(self):
        count = 48
        barrier = threading.Barrier(count)

        def write(index):
            barrier.wait()
            return exam_monitoring.record_event(self.student, self.release, f"parallel-{index:04d}", "window_blur")[0]

        with ThreadPoolExecutor(max_workers=count) as pool:
            written = list(pool.map(write, range(count)))
        summary = exam_monitoring.attempt_summary(self.student, self.release)
        self.assertEqual(summary["latest_event_seq"], count)
        self.assertEqual(summary["event_counters"]["window_blur"], count)
        self.assertEqual(len({event["seq"] for event in written}), count)
        self.assertEqual(len({event["event_id"] for event in written}), count)

    def test_paged_history_returns_only_events_after_cursor(self):
        for index in range(5):
            exam_monitoring.record_event(self.student, self.release, f"page-event-{index:02d}", "document_hidden")
        first = exam_monitoring.events_after(self.student, self.release, 0, 2)
        second = exam_monitoring.events_after(self.student, self.release, first["next_after_seq"], 2)
        self.assertEqual([event["seq"] for event in first["events"]], [1, 2])
        self.assertTrue(first["has_more"])
        self.assertEqual([event["seq"] for event in second["events"]], [3, 4])
        self.assertEqual(second["events"][0]["seq"], 3)

    def _handler(self, path, payload=None, query=None, user_id=None, role="student"):
        request = SimpleNamespace(path=path, query=query or {}, json_body=payload, form={}, cookies={})
        handler = object.__new__(main.Handler)
        handler._parse_body = lambda: (json.dumps(payload or {}).encode(), request)
        handler._request = lambda: request
        handler._auth = lambda _request, wanted=None: {"user_id": user_id or self.student, "role": role}
        handler._json = lambda value, status=200, headers=None: value
        return handler

    def test_student_event_endpoint_uses_authenticated_identity_and_is_idempotent(self):
        payload = {
            "event_id": "endpoint-event-01", "event_type": "window_blur",
            "student_id": "other-student", "release_id": self.release,
            "client_occurred_at": "2026-06-01T10:00:00Z",
        }
        handler = self._handler("/api/student/telemetry/event", payload)
        with patch("app.main.read_json", wraps=storage.read_json):
            result = handler.do_POST()
            duplicate = handler.do_POST()
        self.assertTrue(result["recorded"])
        self.assertFalse(duplicate["recorded"])
        event = exam_monitoring.events_after(self.student, self.release, 0)["events"][0]
        self.assertEqual(event["student_id"], self.student)
        self.assertEqual(event["release_id"], self.release)

    def test_inactive_attempt_is_not_persisted(self):
        ended = dict(self.assignment, status="ended")
        storage.write_json("assignments.json", {self.student: ended})
        handler = self._handler("/api/student/telemetry/event", {"event_id": "inactive-event-01", "event_type": "window_blur", "release_id": self.release})
        with patch("app.main.read_json", wraps=storage.read_json):
            response = handler.do_POST()
        self.assertFalse(response["recorded"])
        self.assertEqual(exam_monitoring.attempt_summary(self.student, self.release)["latest_event_seq"], 0)

    def test_client_release_identity_mismatch_is_not_reinterpreted_as_current_attempt(self):
        handler = self._handler("/api/student/telemetry/event", {
            "event_id": "wrong-release-01", "event_type": "window_blur", "release_id": "release-from-another-tab",
        })
        with patch("app.main.read_json", wraps=storage.read_json):
            response = handler.do_POST()
        self.assertEqual(response["reason"], "attempt_mismatch")
        self.assertEqual(exam_monitoring.attempt_summary(self.student, self.release)["latest_event_seq"], 0)

    def test_teacher_history_route_requires_query_identity_and_returns_incremental_page(self):
        exam_monitoring.record_event(self.student, self.release, "teacher-view-01", "document_hidden")
        query = {"student_id": [self.student], "release_id": [self.release], "after_seq": ["0"], "limit": ["10"]}
        handler = self._handler("/api/admin/monitor/events", query=query, role="admin")
        with patch("app.main.read_json", wraps=storage.read_json):
            response = handler.do_GET()
        self.assertEqual([event["seq"] for event in response["events"]], [1])
        self.assertEqual(response["latest_event_seq"], 1)

    def test_normal_browser_snapshot_does_not_clear_historical_monitor_warning(self):
        exam_monitoring.record_event(self.student, self.release, "history-warning-01", "window_blur")
        storage.write_json("students.json", {self.student: {"full_name": "Test Student"}})
        storage.write_json("sessions.json", {"session-hash": {
            "user_id": self.student, "role": "student", "last_seen": storage.utc_now(),
            "telemetry": {"visibility": "visible", "focused": True, "tab_count": 1, "release_id": self.release},
        }})
        storage.write_json("submissions.json", {})
        storage.write_json("code_submissions.json", {})
        snapshot = main.monitoring_snapshot()
        row = snapshot["students"][0]
        self.assertTrue(row["active_exam_attempt"])
        self.assertTrue(row["telemetry"]["focused"])
        self.assertEqual(row["event_counters"]["window_blur"], 1)
        self.assertEqual(row["latest_event_seq"], 1)
        self.assertIn("recorded_window_blur", row["alerts"])

    def test_event_payload_limits_and_auth_errors_do_not_write_history(self):
        oversized = self._handler("/api/student/telemetry/event", {
            "event_id": "oversized-001", "event_type": "window_blur", "extra": "x" * 5000,
        })
        oversized._handle_error = lambda error: {"status": error.status, "detail": error.detail}
        self.assertEqual(oversized.do_POST()["status"], 413)

        invalid = self._handler("/api/student/telemetry/event", {
            "event_id": "invalid-type-01", "event_type": "unsupported_event", "release_id": self.release,
        })
        invalid._handle_error = lambda error: {"status": error.status, "detail": error.detail}
        with patch("app.main.read_json", wraps=storage.read_json):
            self.assertEqual(invalid.do_POST()["status"], 400)

        unauthenticated = self._handler("/api/student/telemetry/event", {
            "event_id": "unauthenticated-1", "event_type": "window_blur",
        })
        unauthenticated._auth = lambda *_args: (_ for _ in ()).throw(main.ClientError(401, "Authentication required"))
        unauthenticated._handle_error = lambda error: {"status": error.status}
        self.assertEqual(unauthenticated.do_POST()["status"], 401)
        self.assertEqual(exam_monitoring.attempt_summary(self.student, self.release)["latest_event_seq"], 0)


if __name__ == "__main__":
    unittest.main()
