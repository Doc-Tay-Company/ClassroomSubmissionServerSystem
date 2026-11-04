import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app import storage


class StorageInitializationTests(unittest.TestCase):
    def test_runtime_json_files_are_created_with_defaults_without_overwriting_local_data(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            log_dir = Path(temp_dir) / "logs"
            data_dir.mkdir()
            log_dir.mkdir()
            local_admins = {"local-admin": {"active": True}}
            (data_dir / "admins.json").write_text(
                json.dumps(local_admins), encoding="utf-8"
            )

            with patch.object(storage, "DATA_DIR", data_dir), patch.object(
                storage, "LOG_DIR", log_dir
            ):
                storage.initialize()

                for name in (
                    "students.json",
                    "admins.json",
                    "settings.json",
                    "assignments.json",
                    "submissions.json",
                    "questions.json",
                    "code_exams.json",
                    "code_submissions.json",
                    "code_runs.json",
                    "sessions.json",
                    "login_attempts.json",
                    "machines.json",
                    "notifications.json",
                ):
                    with self.subTest(name=name):
                        self.assertTrue((data_dir / name).is_file())
                        with (data_dir / name).open(encoding="utf-8") as file:
                            json.load(file)

                self.assertEqual(storage.read_json("admins.json"), local_admins)
