from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app import storage


_ORIGINAL_DATA_DIR = storage.DATA_DIR
_ORIGINAL_LOG_DIR = storage.LOG_DIR
_TEMP = tempfile.TemporaryDirectory(prefix="css-paper-distribution-")
_ROOT = Path(_TEMP.name)
storage.DATA_DIR = _ROOT / "data"
storage.LOG_DIR = _ROOT / "logs"
storage.DATA_DIR.mkdir(parents=True, exist_ok=True)
storage.LOG_DIR.mkdir(parents=True, exist_ok=True)

from app import code_exams, exams, general_exams, main, papers


def _question(qid: str, title: str) -> dict:
    return {
        "id": qid,
        "title": title,
        "statement": "Read one line and print it.",
        "language": "python",
        "grading_mode": "stdio",
        "starter_code": "",
        "time_limit_seconds": 2,
        "memory_limit_mb": 128,
        "max_output_bytes": 4096,
        "total_points": 10,
        "tests": [
            {"id": f"{qid}-visible", "stdin": "x\n", "expected_stdout": "x\n", "points": 6, "is_visible": True},
            {"id": f"{qid}-hidden", "stdin": "s\n", "expected_stdout": "secret\n", "points": 4, "is_visible": False},
        ],
        "reference_source": "teacher only",
        "status": "published",
        "version": 1,
        "source": {"created_by": "teacher", "created_at": f"2026-01-01T00:00:0{qid[-1]}+00:00"},
    }


class PaperDistributionTests(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        storage.DATA_DIR = _ORIGINAL_DATA_DIR
        storage.LOG_DIR = _ORIGINAL_LOG_DIR
        _TEMP.cleanup()

    def setUp(self):
        storage.DATA_DIR = _ROOT / "data"
        storage.LOG_DIR = _ROOT / "logs"
        storage.DATA_DIR.mkdir(parents=True, exist_ok=True)
        storage.LOG_DIR.mkdir(parents=True, exist_ok=True)
        main.initialize()
        for name, value in {
            "students.json": {f"student-{i}": {"active": True, "full_name": f"Student {i}"} for i in range(1, 4)},
            "questions.json": {"q-1": _question("q-1", "One"), "q-2": _question("q-2", "Two")},
            "papers.json": {},
            "exams.json": {},
            "assignments.json": {},
            "code_exams.json": {},
            "code_submissions.json": {},
            "code_runs.json": [],
            "sessions.json": {},
        }.items():
            storage.write_json(name, value)
        settings = storage.read_json("settings.json")
        settings.update({"exam_state": "idle", "exam_released": False, "exam_release_id": None, "exam_release_at": None, "exam_started_at": None})
        storage.write_json("settings.json", settings)
        self.paper1 = self._publish_paper("Paper one", ["q-1"])
        self.paper2 = self._publish_paper("Paper two", ["q-2"])

    def _publish_paper(self, title, ids):
        paper = papers.create_paper({"title": title, "question_ids": ids}, "teacher", "127.0.0.1")
        paper = papers.publish_paper(paper["id"], {"expected_revision": paper["revision"]}, "teacher", "127.0.0.1")
        return {"paper_id": paper["id"], "paper_version_id": paper["current_version_id"]}

    def _release(self, mode, refs):
        exam = general_exams.create_exam({
            "title": f"{mode} exam",
            "config": {"participants": ["student1", "student2", "student3"]},
            "items": [{"type": "code", "distribution": {"mode": mode, "paper_versions": refs}}],
        }, "teacher", "127.0.0.1")
        return general_exams.publish_exam(exam["id"], "teacher", "127.0.0.1")

    def _start(self, exam_id):
        general_exams.start_exam(exam_id, "teacher", "127.0.0.1")

    def test_common_assigns_one_exact_ordered_snapshot_and_survives_archive_restart(self):
        # Build a two-question snapshot and preserve its saved order.
        common = self._publish_paper("Ordered", ["q-2", "q-1"])
        release = self._release("common", [common])
        self.assertEqual(release["release"]["distribution_mode"], "common")
        self.assertEqual(set(release["release"]["paper_pool"][0]), {"paper_id", "paper_version_id"})
        general_exams.publish_exam(release["id"], "teacher", "127.0.0.1")  # retry is idempotent
        persisted_release = storage.read_json("exams.json")[release["id"]]["release"]
        self.assertEqual(len(persisted_release["paper_assignments"]), 3)
        self.assertEqual({(a["paper_id"], a["paper_version_id"]) for a in persisted_release["paper_assignments"].values()}, {(common["paper_id"], common["paper_version_id"])})

        paper_record = papers.get_paper(common["paper_id"])
        papers.update_paper(common["paper_id"], {
            "expected_revision": paper_record["revision"], "title": "Edited after release", "question_ids": ["q-1"],
        }, "teacher", "127.0.0.1")

        self._start(release["id"])
        for sid in ("student1", "student2", "student3"):
            exams.start_exam(sid, "", "127.0.0.1")
        assignments = storage.read_json("assignments.json")
        self.assertEqual({(a["paper_id"], a["paper_version_id"]) for a in assignments.values()}, {(common["paper_id"], common["paper_version_id"])})
        first = code_exams.get_student_code_exam("student1")
        self.assertEqual([q["question_id"] for q in first["questions"]], ["q-2", "q-1"])
        self.assertEqual(len(first["questions"][0]["tests"]), 1)
        self.assertNotIn("secret", repr(first["questions"][0]))
        self.assertEqual(first["paper_version_id"], common["paper_version_id"])

        paper = papers.get_paper(common["paper_id"])
        papers.archive_paper(common["paper_id"], {"expected_revision": paper["revision"]}, "teacher", "127.0.0.1")
        question_bank = storage.read_json("questions.json")
        del question_bank["q-2"]
        question_bank["q-1"]["status"] = "draft"
        storage.write_json("questions.json", question_bank)
        main.initialize()  # startup/reconcile must keep the same assignment and version
        second = code_exams.get_student_code_exam("student1")
        self.assertEqual(second["exam_id"], first["exam_id"])
        self.assertEqual([q["question_id"] for q in second["questions"]], ["q-2", "q-1"])
        self.assertEqual(storage.read_json("assignments.json"), assignments)
        with self.assertRaises(papers.PaperError):
            papers.delete_paper(common["paper_id"], {"expected_revision": papers.get_paper(common["paper_id"])["revision"]}, "teacher", "127.0.0.1")

    def test_random_selects_only_pool_members_and_persists_server_choice(self):
        refs = [self.paper1, self.paper2]
        with patch("app.general_exams._choose_random_paper", side_effect=[refs[1], refs[0], refs[1]]) as choose:
            release = self._release("random", refs)
        self.assertEqual(choose.call_count, 3)
        release_record = storage.read_json("exams.json")[release["id"]]["release"]
        selected = release_record["paper_assignments"]
        self.assertEqual(selected["student1"]["paper_id"], refs[1]["paper_id"])
        self.assertEqual(selected["student2"]["paper_id"], refs[0]["paper_id"])
        allowed = {(ref["paper_id"], ref["paper_version_id"]) for ref in refs}
        self.assertTrue(all((a["paper_id"], a["paper_version_id"]) in allowed for a in selected.values()))

        self._start(release["id"])
        for sid in ("student1", "student2", "student3"):
            exams.start_exam(sid, "", "127.0.0.1")
        before = {sid: (a["paper_id"], a["paper_version_id"], a["code_exam_id"]) for sid, a in storage.read_json("assignments.json").items()}
        for sid in before:
            result = code_exams.get_student_code_exam(sid)
            self.assertEqual((result["paper_id"], result["paper_version_id"], result["exam_id"]), before[sid])
            self.assertNotIn("paper_pool", result)
        main.initialize()
        self.assertEqual(
            {sid: (a["paper_id"], a["paper_version_id"], a["code_exam_id"]) for sid, a in storage.read_json("assignments.json").items()},
            before,
        )

    def test_submission_and_regrade_resolve_the_same_paper_version(self):
        release = self._release("common", [self.paper1])
        self._start(release["id"])
        exams.start_exam("student1", "", "127.0.0.1")
        assignment = storage.read_json("assignments.json")["student1"]
        exam = code_exams.get_code_exam(assignment["code_exam_id"])
        question = exam["questions"][0]
        record = code_exams._reserve_submission("student1", exam, question, "print(input())", "hash", "127.0.0.1")
        self.assertEqual(record["paper_id"], self.paper1["paper_id"])
        self.assertEqual(record["paper_version_id"], self.paper1["paper_version_id"])
        self.assertEqual(record["snapshot_version"], question["snapshot_version"])

        code_exams.transition_code_exam(release["release"]["release_id"], "ended")
        submissions = storage.read_json("code_submissions.json")
        submissions["student1"][0].update({"status": "graded", "score": 0, "verdict": "WA"})
        storage.write_json("code_submissions.json", submissions)
        seen = {}

        def execute(snapshot, source):
            seen.update(snapshot)
            return {
                "verdict": "AC", "score": 10, "total_points": 10, "duration_ms": 1,
                "tests": [
                    {"id": "q-1-visible", "passed": True, "points": 6, "points_earned": 6, "is_visible": True},
                    {"id": "q-1-hidden", "passed": True, "points": 4, "points_earned": 4, "is_visible": False},
                ],
            }

        with patch("app.code_exams.execute_question", side_effect=execute):
            code_exams.regrade_submission(exam["id"], record["id"], "teacher", "127.0.0.1")
        self.assertEqual(seen["question_id"], question["question_id"])
        self.assertEqual(seen["snapshot_version"], question["snapshot_version"])
        final = storage.read_json("code_submissions.json")["student1"][0]
        self.assertEqual(final["paper_version_id"], self.paper1["paper_version_id"])

    def test_release_rejects_invalid_paper_references_and_common_multiple_versions(self):
        with self.assertRaises(general_exams.ExamError):
            general_exams.create_exam({
                "title": "Invalid common",
                "config": {"participants": ["student1"]},
                "items": [{"type": "code", "distribution": {"mode": "common", "paper_versions": [self.paper1, self.paper2]}}],
            }, "teacher", "127.0.0.1")

        exam = general_exams.create_exam({
            "title": "Missing version",
            "config": {"participants": ["student1"]},
            "items": [{"type": "code", "distribution": {"mode": "random", "paper_versions": [{"paper_id": self.paper1["paper_id"], "paper_version_id": "missing-version"}]}}],
        }, "teacher", "127.0.0.1")
        with self.assertRaises(general_exams.ExamError):
            general_exams.publish_exam(exam["id"], "teacher", "127.0.0.1")
        self.assertEqual(storage.read_json("code_exams.json"), {})

    def test_reconcile_discards_paper_code_exam_without_committed_release(self):
        orphan = code_exams.create_paper_code_exam({"title": "Interrupted", "paper_ref": self.paper1}, general_exam_id="uncommitted-exam", actor="teacher", ip="127.0.0.1")
        code_exams.attach_code_exam_to_release(orphan["id"], "uncommitted-release")
        general_exams.reconcile()
        self.assertNotIn(orphan["id"], storage.read_json("code_exams.json"))
        self.assertNotIn("uncommitted-exam", storage.read_json("exams.json"))

    def test_legacy_question_release_reconciliation_remains_readable(self):
        storage.write_json("code_exams.json", {
            "legacy-exam": {
                "id": "legacy-exam", "status": "started", "release_id": "legacy-release", "title": "Legacy",
                "questions": [{"question_id": "q-1", "title": "One", "total_points": 10, "version": 1}],
            }
        })
        storage.write_json("settings.json", {**storage.read_json("settings.json"), "exam_state": "started", "exam_released": True, "exam_release_id": "legacy-release"})
        storage.write_json("assignments.json", {"student1": {"release_id": "legacy-release", "code_exam_id": "legacy-exam", "started_at": "2026-11-14T00:00:00+00:00"}})
        general_exams.reconcile()
        self.assertEqual(code_exams.get_code_exam("legacy-exam")["questions"][0]["question_id"], "q-1")
        self.assertNotIn("paper_ref", code_exams.get_code_exam("legacy-exam"))


if __name__ == "__main__":
    unittest.main()
