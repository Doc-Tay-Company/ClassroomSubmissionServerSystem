"""Small JSON/JSONL persistence layer with atomic replacement and a process lock."""
from __future__ import annotations
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from .config import DATA_DIR, LOG_DIR

_LOCK = threading.RLock()
DEFAULTS = {
    "students.json": {},
    "admins.json": {},
    "settings.json": {
        "exam_duration_minutes": 90,
        "submission_policy": "configurable",
        "max_submissions": 1,
        "accepted_submission_extensions": [".zip"],
        "overwrite_previous": True,
        "exam_password_enabled": False,
        "exam_password_hash": None,
        "distribution_mode": "random",
        "distribution_config": {},
        "exam_released": False,
        "exam_state": "idle",
        "exam_release_id": None,
        "exam_release_at": None,
        "exam_participants": [],
        "max_upload_bytes": 52428800,
        "allow_late_submission": False
    },
    "assignments.json": {},
    "submissions.json": {},
    "questions.json": {},
    "code_exams.json": {},
    "code_submissions.json": {},
    "code_runs.json": [],
    "sessions.json": {},
    "login_attempts.json": {},
    "machines.json": {}
    ,"notifications.json": []
}

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def _path(name: str) -> Path:
    if name.endswith(".jsonl"):
        return LOG_DIR / name
    return DATA_DIR / name

def initialize() -> None:
    with _LOCK:
        for name, default in DEFAULTS.items():
            p = _path(name)
            if not p.exists():
                atomic_write(p, default)
            elif name == "settings.json":
                with p.open("r", encoding="utf-8") as f:
                    current = json.load(f)
                missing = {key: value for key, value in default.items() if key not in current}
                if "exam_state" not in current:
                    current["exam_state"] = "started" if current.get("exam_released") else "idle"
                    missing.pop("exam_state", None)
                if missing:
                    current.update(missing)
                    atomic_write(p, current)
        (LOG_DIR / "audit.jsonl").touch(exist_ok=True)

def atomic_write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    payload = json.dumps(value, ensure_ascii=False, indent=2)
    with tmp.open("w", encoding="utf-8", newline="\n") as f:
        f.write(payload)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)

def read_json(name: str, default: Any = None) -> Any:
    with _LOCK:
        p = _path(name)
        if not p.exists():
            if default is not None:
                return default
            return DEFAULTS.get(name, {})
        try:
            with p.open("r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            raise RuntimeError(f"Không thể đọc {p.name}; không tự ghi đè dữ liệu lỗi: {exc}") from exc

def write_json(name: str, value: Any) -> None:
    with _LOCK:
        atomic_write(_path(name), value)

def update_json(name: str, mutator):
    with _LOCK:
        value = read_json(name)
        result = mutator(value)
        write_json(name, value)
        return result

def audit(event: str, actor: str | None, ip: str | None, details: dict | None = None) -> None:
    record = {"occurred_at": utc_now(), "event": event, "actor": actor, "ip": ip, "details": details or {}}
    p = _path("audit.jsonl")
    with _LOCK:
        with p.open("a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
            f.flush()
            os.fsync(f.fileno())
