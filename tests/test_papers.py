from __future__ import annotations

from http.server import ThreadingHTTPServer
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest

from app import storage


_ORIGINAL_DATA_DIR = storage.DATA_DIR
_ORIGINAL_LOG_DIR = storage.LOG_DIR
_TEMP = tempfile.TemporaryDirectory(prefix="css-papers-")
_ROOT = Path(_TEMP.name)
storage.DATA_DIR = _ROOT / "data"
storage.LOG_DIR = _ROOT / "logs"
storage.DATA_DIR.mkdir(parents=True, exist_ok=True)
storage.LOG_DIR.mkdir(parents=True, exist_ok=True)

from app import main
from app.security import new_session


def _question(
    question_id: str, *, status="published", language="python", grading_mode="stdio",
    category=None, difficulty=None, tags=None,
) -> dict:
    question = {
        "id": question_id,
        "title": f"Question {question_id}",
        "statement": "Read and print one line.",
        "language": language,
        "grading_mode": grading_mode,
        "starter_code": "# implement",
        "time_limit_seconds": 2,
        "memory_limit_mb": 128,
        "max_output_bytes": 4096,
        "total_points": 10,
        "tests": [
            {"id": "visible", "stdin": "a\n", "expected_stdout": "a\n", "points": 6, "is_visible": True},
            {"id": "hidden", "stdin": "secret\n", "expected_stdout": "private-answer\n", "points": 4, "is_visible": False},
        ],
        "reference_source": "private teacher sample",
        "status": status,
        "version": 3,
        "source": {"created_by": "teacher", "created_at": "2026-01-01T00:00:00+00:00"},
    }
    if language == "java":
        question["target_class"] = "Main"
        question["memory_limit_mb"] = 256
    if category is not None:
        question["category"] = category
    if difficulty is not None:
        question["difficulty"] = difficulty
    if tags is not None:
        question["tags"] = tags
    return question


class ExamPaperApiTests(unittest.TestCase):
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
            _TEMP.cleanup()

    def setUp(self):
        main.initialize()
        for name, value in {
            "students.json": {"student-1": {"active": True}},
            "admins.json": {"admin-1": {"active": True}},
            "questions.json": {"q-1": _question("q-1"), "q-2": _question("q-2"), "q-draft": _question("q-draft", status="draft")},
            "papers.json": {},
            "exams.json": {},
            "assignments.json": {},
            "code_exams.json": {},
            "code_submissions.json": {},
            "code_runs.json": [],
            "sessions.json": {},
            "login_attempts.json": {},
        }.items():
            storage.write_json(name, value)
        self.admin_cookie = new_session("admin-1", "admin", "127.0.0.1", "paper-tests")
        self.student_cookie = new_session("student-1", "student", "127.0.0.1", "paper-tests")

    def request(self, method, path, *, cookie=None, payload=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {}
        body = None
        if cookie:
            headers["Cookie"] = f"css_session={cookie}"
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        conn.request(method, path, body=body, headers=headers)
        response = conn.getresponse()
        raw = response.read()
        status = response.status
        conn.close()
        return status, json.loads(raw.decode("utf-8")) if raw else None

    def create_paper(self, question_ids=("q-1", "q-2")):
        status, body = self.request(
            "POST", "/api/admin/papers", cookie=self.admin_cookie,
            payload={"title": "Midterm", "metadata": {"course": "CS"}, "question_ids": list(question_ids)},
        )
        self.assertEqual(status, 201, body)
        return body["paper"]

    def publish(self, paper):
        return self.request(
            "POST", f"/api/admin/papers/{paper['id']}/publish", cookie=self.admin_cookie,
            payload={"expected_revision": paper["revision"]},
        )

    def test_admin_papers_tab_renders_manager(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request(
            "GET", "/admin?section=exam-management&tab=papers",
            headers={"Cookie": f"css_session={self.admin_cookie}"},
        )
        response = conn.getresponse()
        body = response.read().decode("utf-8")
        status = response.status
        conn.close()
        self.assertEqual(status, 200)
        self.assertIn('id="code-papers-view"', body)
        self.assertIn('/static/js/code-papers.js', body)

    def test_admin_authorization_and_create_list_get_preview_update_archive(self):
        status, _ = self.request("GET", "/api/admin/papers")
        self.assertEqual(status, 401)
        status, _ = self.request("GET", "/api/admin/papers", cookie=self.student_cookie)
        self.assertEqual(status, 403)
        denied_payload = {"title": "Denied", "question_ids": ["q-1"]}
        status, _ = self.request("POST", "/api/admin/papers", payload=denied_payload)
        self.assertEqual(status, 401)
        status, _ = self.request("POST", "/api/admin/papers", cookie=self.student_cookie, payload=denied_payload)
        self.assertEqual(status, 403)

        paper = self.create_paper(("q-2", "q-1"))
        self.assertEqual(paper["draft"]["question_ids"], ["q-2", "q-1"])
        status, listing = self.request("GET", "/api/admin/papers", cookie=self.admin_cookie)
        self.assertEqual(status, 200, listing)
        self.assertEqual(listing["papers"][0]["id"], paper["id"])
        self.assertEqual(listing["papers"][0]["metadata"], {"course": "CS"})
        status, detail = self.request("GET", f"/api/admin/papers/{paper['id']}", cookie=self.admin_cookie)
        self.assertEqual(status, 200, detail)
        self.assertEqual(detail["paper"]["draft"]["question_ids"], ["q-2", "q-1"])
        status, preview = self.request("GET", f"/api/admin/papers/{paper['id']}/preview", cookie=self.admin_cookie)
        self.assertEqual(status, 200, preview)
        self.assertEqual([q["question_id"] for q in preview["preview"]["draft"]["questions"]], ["q-2", "q-1"])

        status, updated = self.request(
            "PUT", f"/api/admin/papers/{paper['id']}", cookie=self.admin_cookie,
            payload={"expected_revision": paper["revision"], "title": "Midterm edited", "metadata": {"course": "CS2"}, "question_ids": ["q-1", "q-2"]},
        )
        self.assertEqual(status, 200, updated)
        self.assertEqual(updated["paper"]["title"], "Midterm edited")
        status, stale = self.request(
            "POST", f"/api/admin/papers/{paper['id']}/update", cookie=self.admin_cookie,
            payload={"expected_revision": paper["revision"], "title": "Stale", "question_ids": ["q-1"]},
        )
        self.assertEqual(status, 409, stale)

        status, archived = self.request(
            "POST", f"/api/admin/papers/{paper['id']}/archive", cookie=self.admin_cookie,
            payload={"expected_revision": updated["paper"]["revision"]},
        )
        self.assertEqual(status, 200, archived)
        self.assertEqual(archived["paper"]["status"], "archived")
        self.assertEqual(archived["paper"]["versions"], {})

    def test_selection_rejects_missing_duplicate_unpublished_and_invalid_payload(self):
        bank = storage.read_json("questions.json")
        invalid = _question("q-invalid")
        invalid.pop("tests")
        bank["q-invalid"] = invalid
        storage.write_json("questions.json", bank)
        cases = [
            ({"title": "P", "question_ids": ["missing"]}, 404),
            ({"title": "P", "question_ids": ["q-1", "q-1"]}, 422),
            ({"title": "P", "question_ids": ["q-draft"]}, 409),
            ({"title": "P", "question_ids": ["q-invalid"]}, 422),
        ]
        for payload, expected in cases:
            status, _ = self.request("POST", "/api/admin/papers", cookie=self.admin_cookie, payload=payload)
            self.assertEqual(status, expected, payload)
        self.assertEqual(storage.read_json("papers.json"), {})

    def test_incomplete_draft_preview_publish_and_immutable_republish_lifecycle(self):
        status, created = self.request(
            "POST", "/api/admin/papers", cookie=self.admin_cookie,
            payload={"title": "Lifecycle", "question_ids": [], "question_limit": 2},
        )
        self.assertEqual(status, 201, created)
        paper = created["paper"]
        self.assertEqual(paper["draft"]["question_ids"], [])
        self.assertEqual(paper["draft"]["question_limit"], 2)

        status, preview = self.request("GET", f"/api/admin/papers/{paper['id']}/preview", cookie=self.admin_cookie)
        self.assertEqual(status, 200, preview)
        self.assertEqual(preview["preview"]["draft"]["questions"], [])
        status, detail = self.request("GET", f"/api/admin/papers/{paper['id']}", cookie=self.admin_cookie)
        self.assertEqual(status, 200, detail)
        self.assertEqual(detail["paper"]["versions"], {})
        self.assertIsNone(detail["paper"]["current_version_id"])

        status, incomplete = self.publish(paper)
        self.assertEqual(status, 422, incomplete)
        self.assertEqual(storage.read_json("papers.json")[paper["id"]]["versions"], {})

        status, partial = self.request(
            "PUT", f"/api/admin/papers/{paper['id']}", cookie=self.admin_cookie,
            payload={"expected_revision": paper["revision"], "question_ids": ["q-1"], "question_limit": 2},
        )
        self.assertEqual(status, 200, partial)
        status, insufficient = self.publish(partial["paper"])
        self.assertEqual(status, 422, insufficient)

        status, complete = self.request(
            "PUT", f"/api/admin/papers/{paper['id']}", cookie=self.admin_cookie,
            payload={"expected_revision": partial["paper"]["revision"], "question_ids": ["q-1", "q-2"], "question_limit": 2},
        )
        self.assertEqual(status, 200, complete)
        status, first_publish = self.publish(complete["paper"])
        self.assertEqual(status, 200, first_publish)
        first = first_publish["paper"]
        first_version_id = first["current_version_id"]
        first_version = json.loads(json.dumps(first["versions"][first_version_id]))
        self.assertEqual(first["versions"][first_version_id]["version"], 1)

        status, draft_preview = self.request(
            "GET", f"/api/admin/papers/{paper['id']}/preview?draft=1", cookie=self.admin_cookie,
        )
        self.assertEqual(status, 200, draft_preview)
        self.assertIn("draft", draft_preview["preview"])
        self.assertNotIn("version", draft_preview["preview"])

        status, edited = self.request(
            "PUT", f"/api/admin/papers/{paper['id']}", cookie=self.admin_cookie,
            payload={"expected_revision": first["revision"], "title": "Lifecycle edited", "question_ids": ["q-2", "q-1"], "question_limit": 2},
        )
        self.assertEqual(status, 200, edited)
        self.assertEqual(edited["paper"]["versions"][first_version_id], first_version)
        status, second_publish = self.publish(edited["paper"])
        self.assertEqual(status, 200, second_publish)
        second = second_publish["paper"]
        self.assertEqual(second["versions"][second["current_version_id"]]["version"], 2)
        self.assertEqual(second["versions"][first_version_id], first_version)

    def test_explicit_selection_order_is_stable_through_save_reload_preview_and_publish(self):
        payload = {
            "title": "Stable selection",
            "question_ids": ["q-2", "q-1"],
            "question_limit": 2,
            "question_filters": {},
        }
        status, created = self.request("POST", "/api/admin/papers", cookie=self.admin_cookie, payload=payload)
        self.assertEqual(status, 201, created)
        paper = created["paper"]
        expected_ids = ["q-2", "q-1"]
        self.assertEqual(paper["draft"]["question_ids"], expected_ids)

        status, detail = self.request("GET", f"/api/admin/papers/{paper['id']}", cookie=self.admin_cookie)
        self.assertEqual(status, 200, detail)
        self.assertEqual(detail["paper"]["draft"]["question_ids"], expected_ids)
        status, preview = self.request("GET", f"/api/admin/papers/{paper['id']}/preview", cookie=self.admin_cookie)
        self.assertEqual(status, 200, preview)
        self.assertEqual([item["question_id"] for item in preview["preview"]["draft"]["questions"]], expected_ids)

        status, saved = self.request(
            "PUT", f"/api/admin/papers/{paper['id']}", cookie=self.admin_cookie,
            payload={**payload, "expected_revision": paper["revision"]},
        )
        self.assertEqual(status, 200, saved)
        self.assertEqual(saved["paper"]["draft"]["question_ids"], expected_ids)
        status, reloaded = self.request("GET", f"/api/admin/papers/{paper['id']}", cookie=self.admin_cookie)
        self.assertEqual(status, 200, reloaded)
        self.assertEqual(reloaded["paper"]["draft"]["question_ids"], expected_ids)

        status, published = self.publish(saved["paper"])
        self.assertEqual(status, 200, published)
        record = published["paper"]
        version = record["versions"][record["current_version_id"]]
        self.assertEqual([item["question_id"] for item in version["questions"]], expected_ids)
        status, published_preview = self.request(
            "GET", f"/api/admin/papers/{paper['id']}/preview", cookie=self.admin_cookie,
        )
        self.assertEqual(status, 200, published_preview)
        self.assertEqual(
            [item["question_id"] for item in published_preview["preview"]["version"]["questions"]],
            expected_ids,
        )

    def test_question_filter_metadata_and_combination_semantics(self):
        bank = storage.read_json("questions.json")
        bank.update({
            "q-1": _question("q-1", category="Math", difficulty="Easy", tags=["Loops", "Intro"]),
            "q-2": _question("q-2", category="Math", difficulty="Hard", tags=["loops", "Advanced"]),
            "q-java": _question(
                "q-java", language="java", category="Science", difficulty="Easy", tags=["Arrays", "loops"]
            ),
        })
        storage.write_json("questions.json", bank)

        status, listing = self.request("GET", "/api/admin/questions", cookie=self.admin_cookie)
        self.assertEqual(status, 200, listing)
        metadata_question = next(question for question in listing["questions"] if question["id"] == "q-1")
        self.assertEqual(metadata_question["category"], "Math")
        self.assertEqual(metadata_question["difficulty"], "Easy")
        self.assertEqual(metadata_question["tags"], ["Loops", "Intro"])

        cases = [
            (["q-1", "q-2"], {"category": "MATH"}, 2),
            (["q-java"], {"language": "JAVA"}, 1),
            (["q-1", "q-java"], {"difficulty": "easy"}, 2),
            (["q-1", "q-2"], {"tags": ["intro", "ADVANCED"]}, 2),
            (["q-2"], {
                "category": "math", "language": "python", "grading_mode": "stdio",
                "difficulty": "hard", "tags": ["loops", "advanced"], "search": "q-2",
            }, 1),
        ]
        for index, (question_ids, filters, limit) in enumerate(cases):
            with self.subTest(filters=filters):
                status, created = self.request(
                    "POST", "/api/admin/papers", cookie=self.admin_cookie,
                    payload={
                        "title": f"Filter test {index}", "question_ids": question_ids,
                        "question_limit": limit, "question_filters": filters,
                    },
                )
                self.assertEqual(status, 201, created)
                self.assertEqual(created["paper"]["draft"]["question_limit"], limit)

    def test_question_limit_rejects_invalid_bounds_and_nonmatching_new_questions(self):
        invalid_payloads = [
            {"question_ids": ["q-1"], "question_limit": 0},
            {"question_ids": ["q-1"], "question_limit": True},
            {"question_ids": ["q-1"], "question_limit": "1"},
            {"question_ids": ["q-1", "q-2"], "question_limit": 1},
            {"question_ids": ["q-1"], "question_limit": 1, "question_filters": {"category": "no-matching-category"}},
            {"question_ids": ["q-1", "q-2"], "question_limit": 2, "question_filters": {"category": "math", "difficulty": "easy"}},
            {"question_ids": ["q-1"], "question_limit": 1, "question_filters": {"language": "ruby"}},
            {"question_ids": ["q-1"], "question_limit": 1, "question_filters": {"unknown": "value"}},
        ]
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                status, _ = self.request(
                    "POST", "/api/admin/papers", cookie=self.admin_cookie,
                    payload={"title": "Invalid quantity", **payload},
                )
                self.assertEqual(status, 422, payload)
        self.assertEqual(storage.read_json("papers.json"), {})

    def test_legacy_paper_without_quantity_metadata_remains_readable_and_editable(self):
        paper = self.create_paper(("q-1",))
        records = storage.read_json("papers.json")
        records[paper["id"]]["draft"].pop("question_limit")
        records[paper["id"]]["draft"].pop("question_filters")
        storage.write_json("papers.json", records)

        status, loaded = self.request(
            "GET", f"/api/admin/papers/{paper['id']}", cookie=self.admin_cookie
        )
        self.assertEqual(status, 200, loaded)
        self.assertEqual(loaded["paper"]["draft"]["question_ids"], ["q-1"])
        self.assertNotIn("question_limit", loaded["paper"]["draft"])

        status, updated = self.request(
            "PUT", f"/api/admin/papers/{paper['id']}", cookie=self.admin_cookie,
            payload={"expected_revision": paper["revision"], "title": "Legacy edited", "question_ids": ["q-1"]},
        )
        self.assertEqual(status, 200, updated)
        self.assertEqual(updated["paper"]["draft"]["question_limit"], 1)
        self.assertEqual(updated["paper"]["draft"]["question_filters"]["tags"], [])

    def test_update_rejects_new_unpublished_or_filter_mismatched_questions(self):
        bank = storage.read_json("questions.json")
        bank["q-1"]["category"] = "Math"
        bank["q-2"]["category"] = "Science"
        storage.write_json("questions.json", bank)
        paper_status, paper_body = self.request(
            "POST", "/api/admin/papers", cookie=self.admin_cookie,
            payload={
                "title": "Filtered paper", "question_ids": ["q-1"], "question_limit": 1,
                "question_filters": {"category": "math"},
            },
        )
        self.assertEqual(paper_status, 201, paper_body)
        paper = paper_body["paper"]

        invalid_updates = [
            ({"question_ids": ["q-1", "q-draft"], "question_limit": 2, "question_filters": {}}, 409),
            ({"question_ids": ["q-1", "q-2"], "question_limit": 2, "question_filters": {"category": "math"}}, 422),
        ]
        for fields, expected in invalid_updates:
            with self.subTest(fields=fields):
                status, _ = self.request(
                    "PUT", f"/api/admin/papers/{paper['id']}", cookie=self.admin_cookie,
                    payload={"expected_revision": paper["revision"], **fields},
                )
                self.assertEqual(status, expected)
        stored = storage.read_json("papers.json")[paper["id"]]
        self.assertEqual(stored["revision"], paper["revision"])
        self.assertEqual(stored["draft"]["question_ids"], ["q-1"])

    def test_publish_captures_complete_ordered_snapshot_and_never_mutates_it(self):
        paper = self.create_paper(("q-2", "q-1"))
        status, published = self.publish(paper)
        self.assertEqual(status, 200, published)
        record = published["paper"]
        version_id = record["current_version_id"]
        snapshot = record["versions"][version_id]["questions"]
        self.assertEqual([item["question_id"] for item in snapshot], ["q-2", "q-1"])
        self.assertEqual([item["order"] for item in snapshot], [0, 1])
        self.assertEqual(snapshot[0]["snapshot_version"], 3)
        self.assertEqual(snapshot[0]["tests"][1]["expected_stdout"], "private-answer\n")
        self.assertNotIn("reference_source", snapshot[0])
        self.assertEqual(snapshot[0]["source_ref"]["title_at_capture"], "Question q-2")

        exams = {"exam-old": {"release": {"paper_pool": [{"paper_id": record["id"], "paper_version_id": version_id}]}}}
        assignments = {"student-1": {"paper_id": record["id"], "paper_version_id": version_id}}
        storage.write_json("exams.json", exams)
        storage.write_json("assignments.json", assignments)

        question_bank = storage.read_json("questions.json")
        question_bank["q-1"]["title"] = "Changed current title"
        question_bank["q-1"]["tests"][1]["expected_stdout"] = "changed answer"
        storage.write_json("questions.json", question_bank)
        status, updated = self.request(
            "PUT", f"/api/admin/papers/{record['id']}", cookie=self.admin_cookie,
            payload={"expected_revision": record["revision"], "question_ids": ["q-1", "q-2"], "title": "New draft"},
        )
        self.assertEqual(status, 200, updated)
        persisted = storage.read_json("papers.json")[record["id"]]
        old_snapshot = persisted["versions"][version_id]["questions"][1]
        self.assertEqual(old_snapshot["title"], "Question q-1")
        self.assertEqual(old_snapshot["tests"][1]["expected_stdout"], "private-answer\n")

        status, blocked = self.request(
            "POST", f"/api/admin/papers/{record['id']}/delete", cookie=self.admin_cookie,
            payload={"expected_revision": updated["paper"]["revision"]},
        )
        self.assertEqual(status, 409, blocked)
        self.assertEqual(storage.read_json("papers.json")[record["id"]]["versions"][version_id], persisted["versions"][version_id])

    def test_source_unpublish_and_delete_preserve_snapshot_and_teacher_warnings(self):
        paper = self.create_paper(("q-1",))
        status, published = self.publish(paper)
        self.assertEqual(status, 200, published)
        record = published["paper"]
        version_id = record["current_version_id"]

        questions = storage.read_json("questions.json")
        questions["q-1"]["status"] = "draft"
        storage.write_json("questions.json", questions)
        status, detail = self.request("GET", f"/api/admin/papers/{record['id']}", cookie=self.admin_cookie)
        self.assertEqual(status, 200, detail)
        question_status = detail["paper"]["versions"][version_id]["source_status"][0]
        self.assertEqual(question_status["status"], "draft")
        self.assertTrue(question_status["warning"])

        status, deleted = self.request(
            "POST", "/api/admin/questions/q-1/delete", cookie=self.admin_cookie,
            payload={"expected_version": 3},
        )
        self.assertEqual(status, 200, deleted)
        status, detail = self.request("GET", f"/api/admin/papers/{record['id']}", cookie=self.admin_cookie)
        self.assertEqual(status, 200, detail)
        version = detail["paper"]["versions"][version_id]
        self.assertEqual(version["source_status"][0]["status"], "deleted")
        self.assertTrue(version["warnings"])
        self.assertEqual(version["questions"][0]["tests"][1]["expected_stdout"], "private-answer\n")

        recreated = _question("q-1")
        recreated["title"] = "Replacement question with reused id"
        recreated["version"] = 1
        recreated["source"]["created_at"] = "2026-02-01T00:00:00+00:00"
        questions = storage.read_json("questions.json")
        questions["q-1"] = recreated
        storage.write_json("questions.json", questions)
        status, detail = self.request("GET", f"/api/admin/papers/{record['id']}", cookie=self.admin_cookie)
        self.assertEqual(status, 200, detail)
        self.assertEqual(detail["paper"]["versions"][version_id]["source_status"][0]["status"], "recreated")

        current = detail["paper"]
        status, changed = self.request(
            "PUT", f"/api/admin/papers/{record['id']}", cookie=self.admin_cookie,
            payload={"expected_revision": current["revision"], "title": "After source replacement", "question_ids": ["q-1"]},
        )
        self.assertEqual(status, 200, changed)
        status, republished = self.publish(changed["paper"])
        self.assertEqual(status, 200, republished)
        new_version = republished["paper"]["versions"][republished["paper"]["current_version_id"]]
        self.assertEqual(new_version["questions"][0]["title"], "Question q-1")

        status, preview = self.request("GET", f"/api/admin/papers/{record['id']}/preview?version_id={version_id}", cookie=self.admin_cookie)
        self.assertEqual(status, 200, preview)
        self.assertEqual(preview["preview"]["version"]["questions"][0]["statement"], "Read and print one line.")

    def test_publish_can_reuse_prior_snapshot_after_source_becomes_inactive(self):
        paper = self.create_paper(("q-1",))
        status, published = self.publish(paper)
        self.assertEqual(status, 200, published)
        original = published["paper"]
        questions = storage.read_json("questions.json")
        questions["q-1"]["status"] = "archived"
        storage.write_json("questions.json", questions)

        status, updated = self.request(
            "PUT", f"/api/admin/papers/{original['id']}", cookie=self.admin_cookie,
            payload={"expected_revision": original["revision"], "title": "Metadata-only edit", "question_ids": ["q-1"]},
        )
        self.assertEqual(status, 200, updated)
        status, republished = self.publish(updated["paper"])
        self.assertEqual(status, 200, republished)
        versions = republished["paper"]["versions"]
        self.assertEqual(len(versions), 2)
        self.assertEqual(versions["%s:v2" % original["id"]]["questions"][0]["snapshot_version"], 3)

    def test_delete_unreferenced_paper_and_restore_archived_paper(self):
        paper = self.create_paper(("q-1",))
        status, archived = self.request(
            "POST", f"/api/admin/papers/{paper['id']}/archive", cookie=self.admin_cookie,
            payload={"expected_revision": paper["revision"]},
        )
        self.assertEqual(status, 200, archived)
        status, restored = self.request(
            "POST", f"/api/admin/papers/{paper['id']}/restore", cookie=self.admin_cookie,
            payload={"expected_revision": archived["paper"]["revision"]},
        )
        self.assertEqual(status, 200, restored)
        status, deleted = self.request(
            "POST", f"/api/admin/papers/{paper['id']}/delete", cookie=self.admin_cookie,
            payload={"expected_revision": restored["paper"]["revision"]},
        )
        self.assertEqual(status, 200, deleted)
        self.assertEqual(storage.read_json("papers.json"), {})


if __name__ == "__main__":
    unittest.main()
