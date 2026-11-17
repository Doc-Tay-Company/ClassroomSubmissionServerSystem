from __future__ import annotations

import importlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from app import storage
from app.code_exams import (
    publish_question,
    publish_question_candidate,
    update_published_question,
    validate_question_sample,
    execute_question,
)
from app.questions import (
    QuestionError,
    archive_question,
    compute_spec_hash,
    create_question,
    delete_question,
    duplicate_question,
    get_question,
    restore_question,
    revoke_question,
    update_question,
)


def _payload(question_id: str) -> dict:
    return {
        "id": question_id,
        "title": f"Question {question_id}",
        "statement": "Read one line and print it.",
        "language": "python",
        "grading_mode": "stdio",
        "time_limit_seconds": 2,
        "memory_limit_mb": 128,
        "max_output_bytes": 4096,
        "allow_pretest": True,
        "max_pretest_runs": 5,
        "tests": [{
            "id": "visible", "stdin": "hello\n", "expected_stdout": "hello\n",
            "points": 1, "is_visible": True,
        }],
        "total_points": 1,
    }


def _tokens(question: dict) -> dict:
    return {
        "expected_version": question.get("version", 1),
        **({"expected_practice_revision": question["practice_revision"]}
           if "practice_revision" in question else {}),
    }


def _load_main_without_template_dependency():
    jinja = types.ModuleType("jinja2")
    jinja.Environment = lambda **kwargs: object()
    jinja.FileSystemLoader = lambda path: object()
    jinja.select_autoescape = lambda extensions: None
    with patch.dict(sys.modules, {"jinja2": jinja}):
        module = importlib.import_module("app.main")
    sys.modules["app.main"] = module
    return module


class QuestionConcurrencyTests(unittest.TestCase):
    def setUp(self):
        self._old_data = storage.DATA_DIR
        self._old_logs = storage.LOG_DIR
        self._temp = tempfile.TemporaryDirectory(prefix="css-question-concurrency-")
        root = Path(self._temp.name)
        storage.DATA_DIR = root / "data"
        storage.LOG_DIR = root / "logs"
        storage.DATA_DIR.mkdir(parents=True)
        storage.LOG_DIR.mkdir(parents=True)
        storage.initialize()

    def tearDown(self):
        storage.DATA_DIR = self._old_data
        storage.LOG_DIR = self._old_logs
        self._temp.cleanup()

    def assert_conflict_unchanged(self, action, question_id: str):
        before = get_question(question_id)
        with self.assertRaises(QuestionError) as caught:
            action()
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(caught.exception.code, "QUESTION_CHANGED")
        self.assertEqual(get_question(question_id), before)

    def test_draft_update_requires_current_tokens_and_drops_request_metadata(self):
        created = create_question(_payload("draft"), "teacher", "127.0.0.1")
        change = dict(_payload("draft"), title="Updated")
        self.assert_conflict_unchanged(
            lambda: update_question("draft", change, "teacher", "127.0.0.1"), "draft"
        )
        stale = dict(change, expected_version=created["version"] + 2,
                     expected_practice_revision=created["practice_revision"])
        self.assert_conflict_unchanged(
            lambda: update_question("draft", stale, "teacher", "127.0.0.1"), "draft"
        )
        valid = dict(change, **_tokens(created))
        valid["expected_version"] = created["version"]
        updated = update_question("draft", valid, "teacher", "127.0.0.1")
        self.assertEqual(updated["title"], "Updated")
        self.assertNotIn("expected_version", updated)
        self.assertNotIn("expected_practice_revision", updated)
        self.assertEqual(
            compute_spec_hash(dict(created, expected_version=1, expected_practice_revision="ignored")),
            compute_spec_hash(created),
        )

    def test_stdio_import_defaults_and_protects_system_metadata(self):
        payload = dict(_payload("import-python"), target_file="", sample_source="print('x')",
                       status="published", version=99, usage_count=50,
                       source={"created_by": "forged"}, validation={"passed": True},
                       practice_revision="forged")
        created = create_question(payload, "teacher", "127.0.0.1")
        self.assertEqual(created["target_file"], "solution.py")
        self.assertEqual(created["status"], "draft")
        self.assertEqual(created["version"], 1)
        self.assertEqual(created["usage_count"], 0)
        self.assertEqual(created["source"]["created_by"], "teacher")
        self.assertNotIn("sample_source", created)
        self.assertNotIn("validation", created)

        self.assertNotEqual(created["practice_revision"], "forged")

        exported = _payload("exported-id")
        for key in ("id", "status", "source", "usage_count", "version"):
            exported.pop(key, None)
        imported = create_question(exported, "teacher", "127.0.0.1")
        self.assertEqual(imported["target_file"], "solution.py")
        self.assertNotEqual(imported["id"], "exported-id")

    def test_stdio_import_rejects_runner_invalid_fields_without_partial_write(self):
        payload = dict(_payload("invalid-import"), target_file="../main.py")
        with self.assertRaisesRegex(QuestionError, "safe .py filename"):
            create_question(payload, "teacher", "127.0.0.1")
        self.assertNotIn("invalid-import", storage.read_json("questions.json", {}))

        payload = dict(_payload("invalid-test-import"), tests=[{
            "id": "visible", "stdin": 7, "expected_stdout": "hello\n",
            "points": 1, "is_visible": True,
        }])
        with self.assertRaisesRegex(QuestionError, "stdin and expected_stdout must be strings"):
            create_question(payload, "teacher", "127.0.0.1")
        self.assertNotIn("invalid-test-import", storage.read_json("questions.json", {}))

        existing = create_question(_payload("invalid-update"), "teacher", "127.0.0.1")
        before = get_question("invalid-update")
        invalid_update = dict(_payload("invalid-update"), **_tokens(existing))
        invalid_update["tests"] = [{
            "id": "visible", "stdin": None, "expected_stdout": "hello\n",
            "points": 1, "is_visible": True,
        }]
        with self.assertRaisesRegex(QuestionError, "stdin and expected_stdout must be strings"):
            update_question("invalid-update", invalid_update, "teacher", "127.0.0.1")
        self.assertEqual(get_question("invalid-update"), before)

    def test_java_stdio_import_derives_and_validates_target_file(self):
        payload = {
            "id": "import-java", "title": "Java import", "statement": "Print a line.",
            "language": "java", "grading_mode": "stdio", "target_class": "Main",
            "target_package": "sample", "tests": [{
                "id": "visible", "stdin": "", "expected_stdout": "ok\n",
                "is_visible": True,
            }], "total_points": 1,
        }
        created = create_question(payload, "teacher", "127.0.0.1")
        self.assertEqual(created["target_file"], "Main.java")
        self.assertEqual(created["tests"][0]["points"], 1)
        payload["id"] = "bad-java-import"
        payload["target_file"] = "Other.java"
        with self.assertRaisesRegex(QuestionError, "match the target class name"):
            create_question(payload, "teacher", "127.0.0.1")
        self.assertNotIn("bad-java-import", storage.read_json("questions.json", {}))

    def test_r03_comparable_import_preserves_legacy_arrays(self):
        fixture_path = Path(__file__).resolve().parents[1] / "test-data" / "grading-questions" / "R03.json"
        payload = json.loads(fixture_path.read_text(encoding="utf-8"))
        payload["id"] = "r03-import"
        expected = next(check for check in payload["checks"] if check["id"] == "r03-ordering")
        created = create_question(payload, "teacher", "127.0.0.1")
        actual = next(check for check in created["checks"] if check["id"] == "r03-ordering")
        self.assertEqual(actual, expected)
        self.assertEqual(len(actual["instances"]), 3)
        self.assertEqual(actual["comparisons"], [
            {"left": 1, "right": 0, "expected_sign": -1},
            {"left": 2, "right": 0, "expected_sign": -1},
        ])
        self.assertEqual(actual["expected_order"], [1, 2, 0])

        source = """package model;
public class RankedLabel implements Comparable<RankedLabel> {
    private int rank;
    private String label;
    public RankedLabel(int rank, String label) { this.rank = rank; this.label = label; }
    @Override public int compareTo(RankedLabel other) {
        int byRank = Integer.compare(this.rank, other.rank);
        return byRank != 0 ? byRank : this.label.compareTo(other.label);
    }
}
"""
        result = execute_question(created, source)
        self.assertEqual(result["verdict"], "AC", result.get("error"))
        self.assertEqual(result["score"], 100)

    def test_reflection_import_uses_runner_request_validation(self):
        payload = {
            "id": "import-reflection", "title": "Reflection import",
            "language": "java", "grading_mode": "reflection",
            "target_class": "Main", "target_package": "sample",
            "checks": [{
                "id": "method-check", "kind": "method", "method_name": "answer",
                "expected_return_type": "int", "param_types": [],
                "points": 1, "is_visible": True,
            }], "total_points": 1,
        }
        created = create_question(payload, "teacher", "127.0.0.1")
        self.assertEqual(created["status"], "draft")
        self.assertEqual(created["checks"][0]["id"], "method-check")

        payload["id"] = "invalid-reflection-import"
        payload["checks"][0]["kind"] = ""
        with self.assertRaisesRegex(QuestionError, "non-empty kind"):
            create_question(payload, "teacher", "127.0.0.1")
        self.assertNotIn("invalid-reflection-import", storage.read_json("questions.json", {}))

    def test_candidate_publication_requires_tokens_for_existing_draft(self):
        created = create_question(_payload("candidate"), "teacher", "127.0.0.1")
        execution = {"verdict": "AC", "score": 1, "total_points": 1,
                     "duration_ms": 1, "tests": [{"id": "visible", "passed": True}]}
        record = {"passed": True, "spec_hash": compute_spec_hash(created),
                  "sample_sha256": "sample-hash", "validated_at": "now"}
        with patch("app.code_exams._run_candidate", return_value=(execution, record)):
            self.assert_conflict_unchanged(
                lambda: publish_question_candidate(_payload("candidate"), "print('hello')", "teacher", "127.0.0.1"),
                "candidate",
            )
            result = publish_question_candidate(
                dict(_payload("candidate"), **_tokens(created)), "print('hello')", "teacher", "127.0.0.1"
            )
        self.assertTrue(result["published"])
        stored = get_question("candidate")
        self.assertNotIn("expected_version", stored)
        self.assertNotIn("expected_practice_revision", stored)

    def test_published_edit_requires_tokens_and_conflict_is_http_409(self):
        question = create_question(_payload("published"), "teacher", "127.0.0.1")
        question["status"] = "published"
        question["reference_source"] = "print(input())"
        question["validation"] = {
            "passed": True,
            "spec_hash": compute_spec_hash(question),
            "sample_sha256": "sample-hash",
        }
        storage.write_json("questions.json", {"published": question})
        payload = dict(_payload("published"), title="New title")
        execution = {"verdict": "AC", "score": 1, "total_points": 1,
                     "duration_ms": 1, "tests": [{"id": "visible", "passed": True}]}
        record = {"passed": True, "spec_hash": "new-spec", "sample_sha256": "new-sample"}
        with patch("app.code_exams._run_candidate", return_value=(execution, record)):
            self.assert_conflict_unchanged(
                lambda: update_published_question("published", payload, "print(input())", "teacher", "127.0.0.1"),
                "published",
            )
            updated = update_published_question(
                "published", dict(payload, **_tokens(question)), "print(input())", "teacher", "127.0.0.1"
            )
        self.assertTrue(updated["saved"])

        main = _load_main_without_template_dependency()
        handler = object.__new__(main.Handler)
        handler.path = "/api/admin/questions/published/update"
        captured = {}
        handler._json = lambda body, status=200: captured.update(body=body, status=status) or captured
        response = handler._handle_error(QuestionError("stale", 409, "QUESTION_CHANGED"))
        self.assertEqual(response["status"], 409)
        self.assertEqual(response["body"]["code"], "QUESTION_CHANGED")

    def test_sample_validation_requires_tokens_before_persisting(self):
        question = create_question(_payload("validation"), "teacher", "127.0.0.1")
        execution = {"verdict": "AC", "score": 1, "total_points": 1,
                     "duration_ms": 1, "tests": []}
        with patch("app.code_exams.execute_question", return_value=execution), \
             patch("app.code_exams._sample_passes", return_value=(True, None)):
            self.assert_conflict_unchanged(
                lambda: validate_question_sample("validation", "print(input())", {}, "teacher", "127.0.0.1"),
                "validation",
            )
            result = validate_question_sample(
                "validation", "print(input())", _tokens(question), "teacher", "127.0.0.1"
            )
        self.assertTrue(result["validation"]["current"])

    def test_publish_revoke_restore_archive_delete_and_duplicate_require_state(self):
        q = create_question(_payload("life"), "teacher", "127.0.0.1")
        q["validation"] = {"passed": True, "spec_hash": compute_spec_hash(q)}
        storage.write_json("questions.json", {"life": q})
        self.assert_conflict_unchanged(
            lambda: publish_question("life", {}, "teacher", "127.0.0.1"), "life"
        )
        published = publish_question("life", _tokens(q), "teacher", "127.0.0.1")
        self.assertEqual(published["status"], "published")
        self.assert_conflict_unchanged(
            lambda: revoke_question("life", _tokens(q), "teacher", "127.0.0.1"), "life"
        )
        revoked = revoke_question("life", _tokens(published), "teacher", "127.0.0.1")
        archived = archive_question("life", _tokens(revoked), "teacher", "127.0.0.1")
        self.assertEqual(archived["status"], "archived")
        restored = restore_question("life", _tokens(archived), "teacher", "127.0.0.1")
        self.assertEqual(restored["status"], "draft")
        duplicate = duplicate_question("life", _tokens(restored), "teacher", "127.0.0.1")
        self.assertNotEqual(duplicate["id"], "life")
        self.assert_conflict_unchanged(
            lambda: delete_question("life", _tokens(revoked), "teacher", "127.0.0.1"), "life"
        )
        delete_question("life", _tokens(restored), "teacher", "127.0.0.1")
        self.assertIsNone(get_question("life"))

    def test_question_mutations_leave_exam_snapshot_unchanged_and_block_delete(self):
        question = create_question(_payload("snapshotted"), "teacher", "127.0.0.1")
        exam = {
            "exam-1": {
                "id": "exam-1",
                "questions": [{
                    "question_id": "snapshotted",
                    "question": {"title": question["title"], "tests": question["tests"]},
                }],
            }
        }
        storage.write_json("code_exams.json", exam)
        update_question(
            "snapshotted", dict(_payload("snapshotted"), title="Updated bank title", **_tokens(question)),
            "teacher", "127.0.0.1",
        )
        current = get_question("snapshotted")
        archived = archive_question("snapshotted", _tokens(current), "teacher", "127.0.0.1")
        self.assertEqual(archived["status"], "archived")
        self.assertEqual(storage.read_json("code_exams.json"), exam)
        with self.assertRaises(QuestionError):
            delete_question("snapshotted", _tokens(archived), "teacher", "127.0.0.1")
        self.assertIsNotNone(get_question("snapshotted"))

    def test_importing_main_does_not_initialize_storage(self):
        script = r'''
from pathlib import Path
import tempfile
import types
import sys
sys.dont_write_bytecode = True
root = Path.cwd().resolve()
temp = tempfile.TemporaryDirectory(prefix="css-import-bootstrap-")
original_mkdir = Path.mkdir
def guarded_mkdir(self, *args, **kwargs):
    resolved = self.resolve()
    if resolved == root or root in resolved.parents:
        raise AssertionError(f"import attempted project filesystem write: {resolved}")
    return original_mkdir(self, *args, **kwargs)
Path.mkdir = guarded_mkdir
from app import storage
storage.DATA_DIR = Path(temp.name) / "data"
storage.LOG_DIR = Path(temp.name) / "logs"
storage.initialize = lambda: (_ for _ in ()).throw(AssertionError("initialize called during import"))
jinja = types.ModuleType("jinja2")
jinja.Environment = lambda **kwargs: object()
jinja.FileSystemLoader = lambda path: object()
jinja.select_autoescape = lambda extensions: None
sys.modules["jinja2"] = jinja
import app.main
import app.questions
import app.code_exams
'''
        result = subprocess.run(
            [sys.executable, "-c", script], cwd=Path.cwd(), capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
