from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from app import storage

_TEST_TEMP = tempfile.TemporaryDirectory(prefix="css-proctoring-")
storage.DATA_DIR = Path(_TEST_TEMP.name) / "data"
storage.LOG_DIR = Path(_TEST_TEMP.name) / "logs"
storage.DATA_DIR.mkdir(parents=True, exist_ok=True)
storage.LOG_DIR.mkdir(parents=True, exist_ok=True)

from app import code_exams, proctoring
from app.submissions import accept_submission


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds")


class ProctoringTests(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        _TEST_TEMP.cleanup()

    def setUp(self):
        storage.initialize()
        self.now = datetime.now(timezone.utc)
        for name, value in {
            "settings.json": {
                "exam_state": "started",
                "exam_released": True,
                "exam_release_id": "release-1",
                "submission_policy": "configurable",
                "max_submissions": 1,
                "accepted_submission_extensions": [".zip"],
            },
            "students.json": {"s1": {"full_name": "Student One", "active": True}},
            "assignments.json": {
                "s1": {
                    "release_id": "release-1",
                    "exam_file": "exam.pdf",
                    "started_at": _iso(self.now - timedelta(minutes=5)),
                    "ends_at": _iso(self.now + timedelta(minutes=55)),
                    "status": "in_progress",
                }
            },
            "sessions.json": {
                "token-key": {
                    "user_id": "s1",
                    "role": "student",
                    "last_seen": _iso(self.now),
                }
            },
            "code_exams.json": {},
            "code_submissions.json": {},
        }.items():
            storage.write_json(name, value)

    def _assignment(self) -> dict:
        return storage.read_json("assignments.json")["s1"]

    def test_three_warnings_then_fourth_terminates_with_zero(self):
        for expected in range(1, proctoring.MAX_WARNINGS + 1):
            state = proctoring.register_violation("s1", "tab_hidden", "127.0.0.1")
            self.assertFalse(state["terminated"], state)
            self.assertTrue(state["warning_pending"], state)
            self.assertEqual(state["violation_count"], expected)

        state = proctoring.register_violation("s1", "tab_hidden", "127.0.0.1")
        self.assertTrue(state["terminated"], state)
        self.assertEqual(state["violation_count"], proctoring.MAX_WARNINGS + 1)
        self.assertEqual(state["final_score"], 0)
        assignment = self._assignment()
        self.assertTrue(assignment["terminated_by_proctoring"])
        self.assertTrue(assignment["forced_submit"])
        self.assertEqual(assignment["final_score"], 0)
        self.assertEqual(assignment["proctoring_termination_reason"], "violation_limit")
        self.assertEqual(assignment["status"], "submitted")

    def test_acknowledgement_clears_pending_warning(self):
        proctoring.register_violation("s1", "window_blur", "127.0.0.1")
        state = proctoring.acknowledge_warning("s1", "127.0.0.1")
        self.assertFalse(state["terminated"])
        self.assertFalse(state["warning_pending"])
        self.assertEqual(state["violation_count"], 1)
        self.assertNotIn("proctoring_pending_since", self._assignment())

    def test_expired_warning_terminates_when_state_is_checked(self):
        storage.update_json(
            "assignments.json",
            lambda assignments: assignments["s1"].update(
                {
                    "proctoring_violation_count": 1,
                    "proctoring_pending_since": _iso(
                        self.now - timedelta(seconds=proctoring.RETURN_GRACE_SECONDS + 1)
                    ),
                }
            ),
        )
        state = proctoring.state_for("s1", ip="127.0.0.1")
        self.assertTrue(state["terminated"], state)
        self.assertEqual(state["termination_reason"], "return_timeout")
        self.assertEqual(state["final_score"], 0)
        self.assertEqual(self._assignment()["status"], "submitted")

    def test_watchdog_terminates_silent_heartbeat(self):
        storage.write_json(
            "sessions.json",
            {
                "token-key": {
                    "user_id": "s1",
                    "role": "student",
                    "last_seen": _iso(
                        self.now - timedelta(seconds=proctoring.RETURN_GRACE_SECONDS + 5)
                    ),
                }
            },
        )
        terminated = proctoring.sweep_abandoned(
            now=self.now, ignore_startup_grace=True
        )
        self.assertEqual(terminated, 1)
        assignment = self._assignment()
        self.assertTrue(assignment["terminated_by_proctoring"])
        self.assertEqual(assignment["proctoring_termination_reason"], "disconnect_timeout")
        self.assertEqual(assignment["final_score"], 0)

    def test_watchdog_keeps_student_with_fresh_heartbeat(self):
        terminated = proctoring.sweep_abandoned(
            now=self.now, ignore_startup_grace=True
        )
        self.assertEqual(terminated, 0)
        self.assertFalse(self._assignment().get("terminated_by_proctoring", False))

    def test_terminated_student_cannot_submit_zip_again(self):
        storage.update_json(
            "assignments.json",
            lambda assignments: assignments["s1"].update(
                {"status": "submitted", "terminated_by_proctoring": True}
            ),
        )
        with self.assertRaises(ValueError):
            accept_submission("s1", "answer.zip", b"", "127.0.0.1")

    def test_admin_code_results_force_zero_for_terminated_student(self):
        storage.write_json(
            "code_exams.json",
            {
                "exam-1": {
                    "id": "exam-1",
                    "release_id": "release-1",
                    "status": "started",
                    "title": "Code exam",
                    "questions": [
                        {
                            "question_id": "q1",
                            "title": "Question 1",
                            "total_points": 10,
                        }
                    ],
                }
            },
        )
        storage.write_json(
            "code_submissions.json",
            {
                "s1": [
                    {
                        "id": "submission-1",
                        "exam_id": "exam-1",
                        "release_id": "release-1",
                        "question_id": "q1",
                        "status": "graded",
                        "score": 10,
                        "total_points": 10,
                        "submitted_at": _iso(self.now),
                    }
                ]
            },
        )
        storage.update_json(
            "assignments.json",
            lambda assignments: assignments["s1"].update(
                {"status": "submitted", "terminated_by_proctoring": True, "final_score": 0}
            ),
        )
        result = code_exams.get_admin_code_results("exam-1")
        matrix = result["matrix"][0]
        self.assertTrue(matrix["proctoring_terminated"])
        self.assertEqual(matrix["total_score"], 0)
        self.assertEqual(matrix["cells"][0]["score"], 0)

    def test_student_code_exam_hides_non_zero_score_after_termination(self):
        storage.write_json(
            "code_exams.json",
            {
                "exam-1": {
                    "id": "exam-1",
                    "release_id": "release-1",
                    "status": "started",
                    "title": "Code exam",
                    "show_final_score_immediately": True,
                    "questions": [
                        {
                            "question_id": "q1",
                            "title": "Question 1",
                            "total_points": 10,
                        }
                    ],
                }
            },
        )
        storage.write_json(
            "code_submissions.json",
            {
                "s1": [
                    {
                        "id": "submission-1",
                        "exam_id": "exam-1",
                        "release_id": "release-1",
                        "question_id": "q1",
                        "status": "graded",
                        "score": 10,
                        "total_points": 10,
                        "submitted_at": _iso(self.now),
                    }
                ]
            },
        )
        storage.update_json(
            "assignments.json",
            lambda assignments: assignments["s1"].update(
                {
                    "status": "submitted",
                    "terminated_by_proctoring": True,
                    "forced_submit": True,
                    "code_exam_id": "exam-1",
                }
            ),
        )
        result = code_exams.get_student_code_exam("s1")
        self.assertTrue(result["proctoring_terminated"])
        self.assertTrue(result["read_only"])
        self.assertEqual(result["exam_score"], 0)
        self.assertEqual(result["progress"][0]["score"], 0)


if __name__ == "__main__":
    unittest.main()
