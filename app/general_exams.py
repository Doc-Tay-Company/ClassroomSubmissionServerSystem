"""General exam model stored in data/exams.json.

An exam is a container of assessment items (currently ``code`` and ``zip``). It owns
the lifecycle draft -> distributed -> started -> ended and delegates the runtime to the
existing release machinery: settings.json / assignments.json describe the single running
exam, code_exams.json keeps the immutable code question snapshots, and submissions stay
keyed by release_id. Legacy releases and code exams created before exams.json existed are
wrapped lazily (see ``reconcile``) without moving or rewriting their data.
"""
from __future__ import annotations

import copy
import random
import uuid
from collections.abc import Mapping

from .code_exams import (
    CodeExamError,
    attach_code_exam_to_release,
    build_results_matrix,
    create_code_exam,
    create_paper_code_exam,
    discard_code_exam,
    get_code_exam,
    public_question,
    regrade_submission,
    release_student_exam_scores,
    transition_code_exam,
)
from .exams import (
    compute_assignments,
    eligible_students,
    end_exam_session,
    list_exam_files,
    remaining_seconds,
    start_exam_session,
)
from .security import hash_password
from .papers import PaperError, resolve_paper_reference
from .storage import audit, read_json, transaction, utc_now, write_json

STATUSES = ("draft", "distributed", "started", "ended")
TAGS = ("", "midterm", "final")
ITEM_TYPES = ("code", "zip")
DISTRIBUTION_MODES = ("random", "selected", "parity", "custom")


class ExamError(Exception):
    def __init__(self, detail: str, status: int = 400, fields: list | None = None, extra: dict | None = None):
        super().__init__(detail)
        self.detail = detail
        self.status = status
        self.fields = fields
        self.extra = extra


def _new_id() -> str:
    return uuid.uuid4().hex


def _int(value, label: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ExamError(f"{label} không hợp lệ.")
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        raise ExamError(f"{label} không hợp lệ.")
    if not minimum <= number <= maximum:
        raise ExamError(f"{label} phải từ {minimum} đến {maximum}.")
    return number


def _bool(value, label: str) -> bool:
    if not isinstance(value, bool):
        raise ExamError(f"{label} phải là true hoặc false.")
    return value


def _string_list(value, label: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ExamError(f"{label} phải là danh sách chuỗi.")
    return list(dict.fromkeys(item.strip() for item in value if item.strip()))


# ---------------------------------------------------------------- normalization

def _default_config() -> dict:
    settings = read_json("settings.json")
    return {
        "duration_minutes": int(settings.get("exam_duration_minutes", 90)),
        "submission_policy": settings.get("submission_policy", "configurable"),
        "max_submissions": int(settings.get("max_submissions", 1)),
        "overwrite_previous": bool(settings.get("overwrite_previous", True)),
        "accepted_submission_extensions": list(settings.get("accepted_submission_extensions") or [".zip"]),
        "password_enabled": False,
        "password_hash": None,
        "participants": [],
    }


def _normalize_config(raw, base: dict) -> dict:
    if raw is None:
        raw = {}
    if not isinstance(raw, Mapping):
        raise ExamError("config phải là một object.")
    config = copy.deepcopy(base)
    if "duration_minutes" in raw:
        config["duration_minutes"] = _int(raw["duration_minutes"], "Thời lượng", 1, 1440)
    if "submission_policy" in raw:
        if raw["submission_policy"] not in {"once", "configurable"}:
            raise ExamError("Chính sách nộp không hợp lệ.")
        config["submission_policy"] = raw["submission_policy"]
    if "max_submissions" in raw:
        config["max_submissions"] = _int(raw["max_submissions"], "Số lần nộp", 1, 20)
    if "overwrite_previous" in raw:
        config["overwrite_previous"] = _bool(raw["overwrite_previous"], "overwrite_previous")
    if "accepted_submission_extensions" in raw:
        values = raw["accepted_submission_extensions"]
        if isinstance(values, str):
            values = values.replace(",", " ").split()
        values = _string_list(values, "Loại file được chấp nhận")
        extensions = sorted({v.lower() if v.startswith(".") else f".{v.lower()}" for v in values})
        if not extensions or any(len(v) > 10 for v in extensions):
            raise ExamError("Danh sách loại file nộp không hợp lệ.")
        config["accepted_submission_extensions"] = extensions
    if "password_enabled" in raw:
        config["password_enabled"] = _bool(raw["password_enabled"], "password_enabled")
    password = raw.get("password")
    if password is not None:
        if not isinstance(password, str) or len(password) > 200:
            raise ExamError("Mật khẩu đề thi không hợp lệ.")
        if password.strip():
            config["password_hash"] = hash_password(password)
    if not config["password_enabled"]:
        config["password_hash"] = None
    if "participants" in raw:
        participants = _string_list(raw["participants"], "Danh sách dự thi")
        if len(participants) > 10000 or any(len(sid) > 80 or not sid.isalnum() for sid in participants):
            raise ExamError("Danh sách MSSV dự thi không hợp lệ.")
        config["participants"] = participants
    return config


def _normalize_zip_item(entry: Mapping, item: dict) -> None:
    mode = entry.get("distribution_mode", "random")
    if mode not in DISTRIBUTION_MODES:
        raise ExamError("Chế độ phân phối không hợp lệ.")
    raw = entry.get("distribution_config", {})
    if not isinstance(raw, Mapping):
        raise ExamError("distribution_config phải là một object.")
    files = _string_list(raw.get("exam_files", []), "Danh sách file đề")
    if mode in {"random", "selected"}:
        config = {"exam_files": files}
    elif mode == "parity":
        config = {"even_exam": str(raw.get("even_exam", "")), "odd_exam": str(raw.get("odd_exam", ""))}
    else:
        rules = raw.get("last_digit_map", {})
        if not isinstance(rules, Mapping):
            raise ExamError("last_digit_map phải là một object.")
        config = {
            "last_digit_map": {str(k): str(v) for k, v in rules.items()},
            "custom_modulus": _int(raw.get("custom_modulus", 10), "Số chia", 1, 10),
            "exam_files": files,
        }
    item.update({"distribution_mode": mode, "distribution_config": config})


def _normalize_code_item(entry: Mapping, item: dict) -> None:
    distribution = entry.get("distribution")
    question_ids = _string_list(entry.get("question_ids", []), "Danh sách câu hỏi")
    if distribution is None:
        item["question_ids"] = question_ids
        item.pop("distribution", None)
    else:
        if not isinstance(distribution, Mapping):
            raise ExamError("distribution phải là một object.")
        if question_ids:
            raise ExamError("Không thể kết hợp question_ids với phân phối Paper.")
        mode = distribution.get("mode")
        if mode not in {"common", "random"}:
            raise ExamError("Paper distribution mode phải là common hoặc random.")
        raw_refs = distribution.get("paper_versions", distribution.get("papers"))
        if not isinstance(raw_refs, list) or not raw_refs:
            raise ExamError("paper_versions phải chứa ít nhất một Paper version.")
        refs = []
        seen = set()
        for ref in raw_refs:
            if not isinstance(ref, Mapping):
                raise ExamError("Mỗi Paper version phải là một object.")
            paper_id = ref.get("paper_id")
            version_id = ref.get("paper_version_id")
            if not isinstance(paper_id, str) or not paper_id or len(paper_id) > 80:
                raise ExamError("paper_id không hợp lệ.")
            if version_id is not None and (not isinstance(version_id, str) or not version_id or len(version_id) > 160):
                raise ExamError("paper_version_id không hợp lệ.")
            key = (paper_id, version_id) if version_id is not None else (paper_id, "@paper")
            if key in seen:
                raise ExamError("Một Paper version không thể xuất hiện hai lần trong pool.")
            seen.add(key)
            refs.append({"paper_id": paper_id, **({"paper_version_id": version_id} if version_id is not None else {})})
        if mode == "common" and len(refs) != 1:
            raise ExamError("COMMON phải chọn chính xác một Paper version.")
        item["question_ids"] = []
        item["distribution"] = {"mode": mode, "paper_versions": refs}
    cooldown = entry.get("pretest_cooldown_seconds", 2)
    if isinstance(cooldown, bool) or not isinstance(cooldown, (int, float)) or not 0 <= cooldown <= 3600:
        raise ExamError("Thời gian chờ giữa các lần chạy thử phải từ 0 đến 3600 giây.")
    item.update(
        {
            "question_ids": question_ids,
            "show_final_score_immediately": _bool(entry.get("show_final_score_immediately", False), "show_final_score_immediately"),
            "allow_pretest": _bool(entry.get("allow_pretest", True), "allow_pretest"),
            "max_pretest_runs": _int(entry.get("max_pretest_runs", 20), "Số lần chạy thử tối đa", 1, 1000),
            "pretest_cooldown_seconds": float(cooldown),
        }
    )


def _normalize_items(raw, base_items: list[dict]) -> list[dict]:
    if not isinstance(raw, list):
        raise ExamError("items phải là một danh sách.")
    if len(raw) > 1:
        raise ExamError("Mỗi kỳ thi chỉ được có một loại: bài nộp file hoặc bài code.", 400, ["items"])
    previous = {item["item_id"]: item for item in base_items}
    seen: set[str] = set()
    items = []
    for entry in raw:
        if not isinstance(entry, Mapping):
            raise ExamError("Mỗi bài trong kỳ thi phải là một object.")
        item_type = entry.get("type")
        if item_type not in ITEM_TYPES:
            raise ExamError("Loại bài không được hỗ trợ.")
        if item_type in seen:
            raise ExamError("Hiện mỗi kỳ thi chỉ có tối đa một bài cho mỗi loại (code, ZIP).")
        seen.add(item_type)
        prev = previous.get(entry.get("item_id"))
        prev = prev if prev and prev["type"] == item_type else None
        item = {"item_id": prev["item_id"] if prev else _new_id(), "type": item_type}
        if item_type == "code":
            _normalize_code_item(entry, item)
            if prev and prev.get("code_exam_id"):
                item["code_exam_id"] = prev["code_exam_id"]
            if prev and prev.get("paper_code_exam_ids"):
                item["paper_code_exam_ids"] = copy.deepcopy(prev["paper_code_exam_ids"])
        else:
            _normalize_zip_item(entry, item)
        items.append(item)
    return items


def _normalize(payload, base: dict | None) -> dict:
    if not isinstance(payload, Mapping):
        raise ExamError("Dữ liệu kỳ thi phải là một object JSON.")
    title = payload.get("title", base["title"] if base else None)
    if not isinstance(title, str) or not title.strip() or len(title.strip()) > 200:
        raise ExamError("Tên kỳ thi phải có từ 1 đến 200 ký tự.")
    tag = payload.get("tag", base["tag"] if base else "")
    tag = "" if tag is None else tag
    if tag not in TAGS:
        raise ExamError("Nhãn kỳ thi chỉ có thể là Giữa kỳ hoặc Cuối kỳ.")
    config = _normalize_config(payload.get("config"), base["config"] if base else _default_config())
    items = _normalize_items(payload["items"], base["items"] if base else []) if "items" in payload else (base["items"] if base else [])
    return {"title": title.strip(), "tag": tag, "config": config, "items": items}


# ---------------------------------------------------------------- storage helpers

def _item(exam: dict, item_type: str) -> dict | None:
    return next((item for item in exam.get("items", []) if item["type"] == item_type), None)


def _load() -> dict:
    return read_json("exams.json")


def _must(exams: dict, exam_id: str) -> dict:
    exam = exams.get(exam_id) if isinstance(exam_id, str) else None
    if not exam or exam.get("deleted_at"):
        raise ExamError("Không tìm thấy kỳ thi.", 404)
    return exam


def _touch(exam: dict) -> None:
    exam["updated_at"] = utc_now()
    exam["revision"] = int(exam.get("revision", 1)) + 1


def _drop_code_snapshot(exam: dict) -> None:
    for item in exam.get("items", []):
        if item["type"] == "code":
            code_ids = set(item.get("paper_code_exam_ids", {}).values())
            if item.get("code_exam_id"):
                code_ids.add(item["code_exam_id"])
            for code_id in code_ids:
                discard_code_exam(code_id)
            item.pop("code_exam_id", None)
            item.pop("paper_code_exam_ids", None)


def _code_exam_ids(code_item: dict | None) -> set[str]:
    if not code_item:
        return set()
    ids = set(code_item.get("paper_code_exam_ids", {}).values())
    if code_item.get("code_exam_id"):
        ids.add(code_item["code_exam_id"])
    return ids


def _has_release_activity(release_id: str) -> bool:
    """Return True when persisted records show a Student has started this release."""
    settings = read_json("settings.json")
    if settings.get("exam_release_id") == release_id and settings.get("exam_state") in {"started", "ended"}:
        return True

    for assignment in read_json("assignments.json").values():
        if assignment.get("release_id") != release_id:
            continue
        if assignment.get("started_at"):
            return True
        if assignment.get("status", "assigned") not in {"", "assigned", "draft"}:
            return True

    for code_exam in read_json("code_exams.json").values():
        if code_exam.get("release_id") == release_id and (
            code_exam.get("started_at") or code_exam.get("ended_at")
            or code_exam.get("status") not in {"draft", "distributed"}
        ):
            return True

    def contains_release_record(value) -> bool:
        if isinstance(value, Mapping):
            if value.get("release_id") == release_id:
                return True
            return any(contains_release_record(item) for item in value.values())
        if isinstance(value, list):
            return any(contains_release_record(item) for item in value)
        return False

    return any(contains_release_record(read_json(name)) for name in (
        "code_submissions.json", "code_runs.json", "submissions.json",
    ))


def _synchronize_prestart_assignments(old_release_id: str, release: dict, exam: dict) -> None:
    """Replace only unapplied assignment records with the newly built release plan."""
    assignments = read_json("assignments.json")
    code_item = _item(exam, "code")
    changed = False
    for student_id, assignment in list(assignments.items()):
        if assignment.get("release_id") != old_release_id:
            continue
        if student_id not in release.get("assignments", {}):
            del assignments[student_id]
            changed = True
            continue
        assignment.update({
            "release_id": release["release_id"],
            "exam_file": release["assignments"][student_id],
            "assigned_at": release["released_at"],
            "started_at": None,
            "ends_at": None,
            "status": "assigned",
        })
        for key in ("paper_id", "paper_version_id", "code_exam_id"):
            assignment.pop(key, None)
        paper_assignment = release.get("paper_assignments", {}).get(student_id)
        if paper_assignment:
            assignment.update({
                "paper_id": paper_assignment["paper_id"],
                **({"paper_version_id": paper_assignment["paper_version_id"]} if paper_assignment.get("paper_version_id") is not None else {}),
                "code_exam_id": paper_assignment["code_exam_id"],
            })
        elif code_item and code_item.get("code_exam_id"):
            assignment["code_exam_id"] = code_item["code_exam_id"]
        assignments[student_id] = assignment
        changed = True
    if changed:
        write_json("assignments.json", assignments)

    settings = read_json("settings.json")
    if settings.get("exam_release_id") == old_release_id and settings.get("exam_state") == "distributed":
        settings.update({
            "exam_release_id": release["release_id"],
            "exam_release_at": release["released_at"],
            "exam_released": False,
        })
        write_json("settings.json", settings)


def _clear_applied_release(release_id: str) -> None:
    settings = read_json("settings.json")
    if settings.get("exam_release_id") == release_id and settings.get("exam_state") == "distributed":
        settings.update({"exam_state": "idle", "exam_released": False, "exam_release_id": None, "exam_release_at": None})
        write_json("settings.json", settings)
    assignments = read_json("assignments.json")
    remaining = {sid: item for sid, item in assignments.items() if item.get("release_id") != release_id}
    if len(remaining) != len(assignments):
        write_json("assignments.json", remaining)


# ---------------------------------------------------------------- legacy reconciliation

def _legacy_exam(exam_id: str, title: str, config: dict, items: list[dict], status: str, release: dict | None, created_by, created_at) -> dict:
    now = utc_now()
    return {
        "id": exam_id,
        "title": title,
        "tag": "",
        "status": status,
        "created_by": created_by,
        "created_at": created_at or now,
        "updated_at": now,
        "config": config,
        "items": items,
        "release": release,
        "legacy": True,
    }


def _code_item_from_snapshot(code_exam: dict) -> dict:
    if code_exam.get("paper_ref"):
        return {
            "item_id": _new_id(),
            "type": "code",
            "question_ids": [],
            "distribution": {"mode": "common", "paper_versions": [dict(code_exam["paper_ref"])]},
            "show_final_score_immediately": code_exam.get("show_final_score_immediately", False),
            "allow_pretest": code_exam.get("allow_pretest", True),
            "max_pretest_runs": code_exam.get("max_pretest_runs", 20),
            "pretest_cooldown_seconds": code_exam.get("pretest_cooldown_seconds", 2),
            "paper_code_exam_ids": {_paper_ref_key(code_exam["paper_ref"]): code_exam["id"]},
        }
    return {
        "item_id": _new_id(),
        "type": "code",
        "question_ids": [question["question_id"] for question in code_exam.get("questions", [])],
        "show_final_score_immediately": bool(code_exam.get("show_final_score_immediately", False)),
        "allow_pretest": bool(code_exam.get("allow_pretest", True)),
        "max_pretest_runs": int(code_exam.get("max_pretest_runs", 20)),
        "pretest_cooldown_seconds": float(code_exam.get("pretest_cooldown_seconds", 2)),
        "code_exam_id": code_exam["id"],
    }


def reconcile() -> None:
    """Wrap legacy data, align states, and remove uncommitted Paper snapshots.

    Idempotent. Old question-based data stays untouched. Paper code-exam records
    whose owning release never reached exams.json are discarded as interrupted
    release-build artifacts.
    """
    with transaction():
        exams = _load()
        code_exams = read_json("code_exams.json")
        settings = read_json("settings.json")
        assignments = read_json("assignments.json")
        changed = False
        linked_code = {
            code_id
            for exam in exams.values()
            for item in exam.get("items", [])
            if item["type"] == "code"
            for code_id in _code_exam_ids(item)
        }
        linked_releases = {exam["release"]["release_id"] for exam in exams.values() if exam.get("release")}
        active_release = settings.get("exam_release_id")
        active_state = settings.get("exam_state")

        if active_release and active_state in {"distributed", "started"} and active_release not in linked_releases:
            code_exam = next((c for c in code_exams.values() if c.get("release_id") == active_release and c["id"] not in linked_code), None)
            released = [a for a in assignments.values() if a.get("release_id") == active_release]
            files = sorted({a["exam_file"] for a in released if a.get("exam_file")})
            items = []
            if files:
                items.append(
                    {
                        "item_id": _new_id(),
                        "type": "zip",
                        "distribution_mode": settings.get("distribution_mode", "random"),
                        "distribution_config": copy.deepcopy(settings.get("distribution_config") or {"exam_files": files}),
                    }
                )
            if code_exam:
                items.append(_code_item_from_snapshot(code_exam))
                linked_code.add(code_exam["id"])
            config = _default_config()
            config.update(
                {
                    "duration_minutes": int(settings.get("exam_duration_minutes", 90)),
                    "submission_policy": settings.get("submission_policy", "configurable"),
                    "max_submissions": int(settings.get("max_submissions", 1)),
                    "overwrite_previous": bool(settings.get("overwrite_previous", True)),
                    "accepted_submission_extensions": list(settings.get("accepted_submission_extensions") or [".zip"]),
                    "password_enabled": bool(settings.get("exam_password_enabled")),
                    "password_hash": settings.get("exam_password_hash"),
                    "participants": list(settings.get("exam_participants") or []),
                }
            )
            exam_id = code_exam["id"] if code_exam else active_release
            title = code_exam["title"] if code_exam else "Kỳ thi nhập từ cấu hình cũ"
            exams[exam_id] = _legacy_exam(
                exam_id,
                title,
                config,
                items,
                active_state,
                {"release_id": active_release, "released_at": settings.get("exam_release_at"), "applied": True, "assigned_count": len(released)},
                code_exam.get("created_by") if code_exam else None,
                code_exam.get("created_at") if code_exam else settings.get("exam_release_at"),
            )
            if settings.get("exam_started_at") and active_state == "started":
                exams[exam_id]["started_at"] = settings["exam_started_at"]
            changed = True

        # Paper code-exam records are created while a release is being built,
        # before exams.json can commit the release that owns them. If the
        # process stopped in that gap, discard those uncommitted records on
        # startup instead of reconciling them as historical standalone exams.
        for code_exam in list(code_exams.values()):
            if code_exam["id"] in linked_code:
                continue
            if code_exam.get("general_exam_id"):
                discard_code_exam(code_exam["id"])
                continue
            status = code_exam.get("status", "draft")
            release_id = code_exam.get("release_id")
            stale = release_id != active_release or active_state not in {"distributed", "started"}
            if status in {"distributed", "started"} and stale:
                status = "ended" if status == "started" else "draft"
            config = _default_config()
            config.update(
                {
                    "submission_policy": code_exam.get("submission_policy", config["submission_policy"]),
                    "max_submissions": int(code_exam.get("max_submissions", config["max_submissions"])),
                }
            )
            release = None
            if status != "draft" and release_id:
                release = {"release_id": release_id, "released_at": code_exam.get("distributed_at"), "applied": True, "assigned_count": 0}
            exam = _legacy_exam(
                code_exam["id"], code_exam.get("title", "Đề thi code"), config, [_code_item_from_snapshot(code_exam)],
                status, release, code_exam.get("created_by"), code_exam.get("created_at"),
            )
            for key in ("started_at", "ended_at"):
                if code_exam.get(key):
                    exam[key] = code_exam[key]
            exams[code_exam["id"]] = exam
            changed = True

        for exam in exams.values():
            release = exam.get("release")
            if not release or exam["status"] not in {"distributed", "started"}:
                continue
            if release["release_id"] == active_release and active_state in {"distributed", "started"}:
                if not release.get("applied"):
                    release["applied"] = True
                    changed = True
                if exam["status"] != active_state:
                    exam["status"] = active_state
                    if active_state == "started":
                        exam.setdefault("started_at", settings.get("exam_started_at") or utc_now())
                    _touch(exam)
                    changed = True
            elif release.get("applied"):
                exam["status"] = "ended"
                exam.setdefault("ended_at", utc_now())
                _touch(exam)
                changed = True
        if changed:
            write_json("exams.json", exams)


# ---------------------------------------------------------------- serialization

def _remaining(exam: dict, assignments: dict) -> int | None:
    release = exam.get("release")
    if exam["status"] != "started" or not release:
        return None
    values = [
        remaining_seconds(item)
        for item in assignments.values()
        if item.get("release_id") == release["release_id"] and item.get("started_at") and item.get("status") == "in_progress"
    ]
    return max(values) if values else None


def _public(exam: dict, assignments: dict | None = None) -> dict:
    result = copy.deepcopy(exam)
    result.setdefault("revision", 1)
    config = result["config"]
    config["has_password"] = bool(config.get("password_hash"))
    config.pop("password_hash", None)
    release = result.get("release")
    if release:
        visible_release_keys = (
            "release_id", "released_at", "applied", "assigned_count",
            "distribution_mode", "paper_pool", "paper_distribution_summary",
        )
        result["release"] = {key: release[key] for key in visible_release_keys if key in release}
    result["remaining_seconds"] = _remaining(exam, assignments if assignments is not None else read_json("assignments.json"))
    return result


def list_exams() -> list[dict]:
    reconcile()
    assignments = read_json("assignments.json")
    visible = [exam for exam in _load().values() if not exam.get("deleted_at")]
    visible.sort(key=lambda exam: exam.get("updated_at", ""), reverse=True)
    visible.sort(key=lambda exam: 0 if exam["status"] == "started" else 1)
    return [_public(exam, assignments) for exam in visible]


def get_exam(exam_id: str) -> dict:
    reconcile()
    return _public(_must(_load(), exam_id))


def list_result_exams() -> list[dict]:
    exams = [exam for exam in _load().values() if not exam.get("deleted_at") and _item(exam, "code")]
    exams.sort(key=lambda exam: exam.get("updated_at", ""), reverse=True)
    return [{"id": exam["id"], "title": exam["title"], "status": exam["status"]} for exam in exams]


def _result_exam(exam_id: str) -> dict:
    exam = _must(_load(), exam_id)
    if not _item(exam, "code"):
        raise ExamError("This exam has no code assessment.", 409)
    return exam


def get_exam_results(exam_id: str, *, student_id: str | None = None, question_id: str | None = None) -> dict:
    exam = _result_exam(exam_id)
    release_id = (exam.get("release") or {}).get("release_id")
    submissions = read_json("code_submissions.json")
    if not isinstance(submissions, dict) or any(
        not isinstance(records, list) or any(not isinstance(record, dict) for record in records)
        for records in submissions.values()
    ):
        raise ExamError("Invalid code_submissions.json: expected student-keyed submission lists.", 409)
    rows = [
        {**copy.deepcopy(record), "student_id": owner}
        for owner, records in submissions.items() for record in records
        if release_id and record.get("release_id") == release_id
    ]
    rows.sort(key=lambda record: (record.get("submitted_at", ""), record["student_id"], record.get("attempt", 0)))
    code_item = _item(exam, "code")
    snapshot_ids = _code_exam_ids(code_item) | {record.get("exam_id") for record in rows if record.get("exam_id")}
    stored_snapshots = read_json("code_exams.json")
    question_sets = {}
    questions = {}
    warnings = []
    for snapshot_id in sorted(snapshot_ids):
        snapshot = stored_snapshots.get(snapshot_id)
        frozen = ((snapshot.get("paper_snapshot") or {}).get("questions") or snapshot.get("questions")) if snapshot else None
        if not snapshot or snapshot.get("release_id") != release_id or not frozen:
            warnings.append(f"Released grading snapshot {snapshot_id} is unavailable. Stored submissions remain visible; affected totals cannot be verified.")
            continue
        summaries = [{
            "question_id": question.get("question_id", question.get("id")),
            "title": question.get("title", ""), "total_points": question["total_points"],
            "language": question.get("language"), "grading_mode": question.get("grading_mode"),
        } for question in frozen]
        question_sets[snapshot_id] = summaries
        for question in summaries:
            questions.setdefault(question["question_id"], question)
    bank = read_json("questions.json")
    for record in rows:
        qid = record["question_id"]
        questions.setdefault(qid, {
            "question_id": qid, "title": bank.get(qid, {}).get("title", qid),
            "total_points": record.get("total_points", 0),
            "language": record.get("language"), "grading_mode": record.get("grading_mode"),
        })
    grouped = {}
    for record in rows:
        grouped.setdefault(record["student_id"], []).append({**record, "exam_id": exam_id})
    matrix = []
    assignments = (exam.get("release") or {}).get("paper_assignments", {})
    for owner, records in grouped.items():
        if student_id is not None and owner != student_id:
            continue
        assigned_id = (assignments.get(owner) or {}).get("code_exam_id")
        owner_ids = {record["exam_id"] for record in rows if record["student_id"] == owner and record.get("exam_id")}
        if assigned_id:
            owner_ids.add(assigned_id)
        expected = {}
        for snapshot_id in sorted(owner_ids):
            for question in question_sets.get(snapshot_id, []):
                expected.setdefault(question["question_id"], question)
        for record in records:
            expected.setdefault(record["question_id"], questions[record["question_id"]])
        context = {"id": exam_id, "release_id": release_id, "questions": list(expected.values())}
        entry = build_results_matrix(context, {owner: records}, None)[0]
        complete_metadata = bool(owner_ids) and all(snapshot_id in question_sets for snapshot_id in owner_ids)
        if not complete_metadata:
            entry["total_score"] = entry["total_points"] = None
        cells = {cell["question_id"]: cell for cell in entry["cells"]}
        entry["cells"] = [cells.get(qid, {"question_id": qid, "status": "not_assigned" if complete_metadata else "unknown"}) for qid in questions]
        matrix.append(entry)
    matrix.sort(key=lambda entry: entry["student_id"])
    return {
        "exam_id": exam_id, "release_id": release_id, "title": exam["title"], "status": exam["status"],
        "questions": list(questions.values()), "matrix": matrix, "warnings": warnings,
        "submissions": [record for record in rows
                        if (student_id is None or record["student_id"] == student_id)
                        and (question_id is None or record.get("question_id") == question_id)],
    }


def regrade_exam_submission(exam_id: str, submission_id: str, actor: str, ip: str, *, use_latest_spec: bool = False) -> dict:
    exam = _result_exam(exam_id)
    if exam["status"] != "ended":
        raise ExamError("Only ended exams can be regraded.", 409)
    result = get_exam_results(exam_id)
    record = next((record for record in result["submissions"] if record.get("id") == submission_id), None)
    if record is None:
        raise ExamError("Submission was not found for this exam release.", 404)
    return regrade_submission(record["exam_id"], submission_id, actor, ip, use_latest_spec=use_latest_spec, lifecycle_status=exam["status"])


def regrade_exam_student(exam_id: str, student_id: str, actor: str, ip: str, *, question_id: str | None = None, use_latest_spec: bool = False) -> dict:
    exam = _result_exam(exam_id)
    if exam["status"] != "ended":
        raise ExamError("Only ended exams can be regraded.", 409)
    result = get_exam_results(exam_id, student_id=student_id)
    if not result["submissions"]:
        raise ExamError("This student has no submissions for this exam release.", 404)
    qids = [cell["question_id"] for entry in result["matrix"] for cell in entry["cells"]
            if cell["status"] not in {"not_assigned", "unknown"}]
    if question_id is not None:
        if question_id not in qids:
            raise ExamError("Question is not part of this exam release.", 404)
        qids = [question_id]
    regraded, failed, skipped = [], [], []
    for qid in qids:
        completed = [record for record in result["submissions"] if record.get("question_id") == qid and record.get("status") in {"graded", "error"}]
        if not completed:
            skipped.append({"question_id": qid, "reason": "No completed submission."})
            continue
        target = completed[-1]
        try:
            updated = regrade_submission(target["exam_id"], target["id"], actor, ip, use_latest_spec=use_latest_spec, lifecycle_status=exam["status"])
            regraded.append({"question_id": qid, "submission_id": target["id"], "verdict": updated.get("verdict"), "score": updated.get("score")})
        except CodeExamError as exc:
            failed.append({"question_id": qid, "submission_id": target["id"], "error": str(exc), "status": exc.status})
    if regraded:
        release_student_exam_scores(result["release_id"])
    audit("exam.bulk_regrade", actor, ip, {"exam_id": exam_id, "student_id": student_id, "regraded": len(regraded), "failed": len(failed)})
    return {"exam_id": exam_id, "student_id": student_id, "regraded": regraded, "failed": failed, "skipped": skipped}


def preview_exam(exam_id: str) -> dict:
    """Read-only, student-facing view of the code questions (hidden checks stripped)."""
    reconcile()
    exam = _must(_load(), exam_id)
    code_item = _item(exam, "code")
    if not code_item:
        raise ExamError("Kỳ thi này không có bài code để xem trước.", 409)
    if code_item.get("distribution"):
        paper_previews = []
        for ref in code_item["distribution"].get("paper_versions", []):
            version = None
            release = exam.get("release")
            if release:
                snapshot_ids = code_item.get("paper_code_exam_ids", {})
                code_exam_id = snapshot_ids.get(_paper_ref_key(ref))
                if not code_exam_id and code_item.get("code_exam_id") and ref.get("paper_version_id"):
                    code_exam_id = code_item["code_exam_id"]
                snapshot = get_code_exam(code_exam_id) if code_exam_id else None
                if snapshot:
                    expected_ref = {"paper_id": ref["paper_id"], **({"paper_version_id": ref["paper_version_id"]} if ref.get("paper_version_id") is not None else {})}
                    if snapshot.get("release_id") != release.get("release_id") or snapshot.get("paper_ref") != expected_ref:
                        raise ExamError("The release Paper snapshot is missing or mismatched.", 409)
                    version = {
                        "title": (snapshot.get("paper_snapshot") or {}).get("title", snapshot.get("title", "")),
                        "questions": snapshot.get("questions", []),
                    }
                elif not ref.get("paper_version_id"):
                    raise ExamError("The release Paper snapshot is unavailable.", 409)
            if version is None:
                try:
                    _, version = resolve_paper_reference(ref)
                except PaperError as exc:
                    raise ExamError(str(exc), exc.status) from exc
            paper_previews.append({
                "paper_id": ref["paper_id"],
                **({"paper_version_id": ref["paper_version_id"]} if ref.get("paper_version_id") is not None else {}),
                "title": version.get("title", ""),
                "questions": [
                    {**public_question(question), "total_points": question.get("total_points", 0)}
                    for question in version["questions"]
                ],
            })
        return {
            "exam_id": exam_id,
            "title": exam["title"],
            "distribution_mode": code_item["distribution"]["mode"],
            "paper_versions": paper_previews,
        }
    snapshot = get_code_exam(code_item["code_exam_id"]) if code_item.get("code_exam_id") else None
    if snapshot and exam["status"] != "draft":
        source = {question["question_id"]: question for question in snapshot.get("questions", [])}
    else:
        bank = read_json("questions.json")
        source = {question_id: {**bank[question_id], "question_id": question_id} for question_id in code_item["question_ids"] if question_id in bank}
    questions, missing = [], []
    for index, question_id in enumerate(code_item["question_ids"]):
        question = source.get(question_id)
        if not question:
            missing.append(question_id)
            continue
        entry = public_question({**question, "order": index})
        entry["total_points"] = question.get("total_points", 0)
        questions.append(entry)
    return {"exam_id": exam_id, "title": exam["title"], "questions": questions, "missing": missing}


def published_for_students(student_id: str | None = None) -> list[dict]:
    return [
        {"id": exam["id"], "title": exam["title"], "tag": exam.get("tag", "")}
        for exam in _load().values()
        if exam.get("status") == "distributed" and not exam.get("deleted_at")
        and (student_id is None or not exam["config"]["participants"] or student_id in exam["config"]["participants"])
    ]


def assignment_exam(assignment: dict | None) -> dict | None:
    """Return a short exam summary matching a student's current assignment.

    Newer exams are linked by release_id in exams.json; legacy code exams are
    linked through the snapshot id stored on the assignment.
    """
    if not assignment:
        return None
    release_id = assignment.get("release_id")
    if release_id:
        for exam in _load().values():
            if exam.get("deleted_at"):
                continue
            release = exam.get("release") or {}
            if release.get("release_id") == release_id:
                return {"id": exam["id"], "title": exam["title"], "tag": exam.get("tag", "")}
    code_exam_id = assignment.get("code_exam_id")
    code_exam = read_json("code_exams.json").get(code_exam_id) if isinstance(code_exam_id, str) else None
    if code_exam and not code_exam.get("deleted_at"):
        return {"id": code_exam["id"], "title": code_exam.get("title", ""), "tag": ""}
    return None


# ---------------------------------------------------------------- commands

def create_exam(payload, actor: str, ip: str) -> dict:
    fields = _normalize(payload, None)
    code_item = _item({"items": fields["items"]}, "code")
    if code_item and code_item.get("distribution"):
        _check_code_papers(code_item)
    now = utc_now()
    exam = {
        "id": _new_id(),
        "revision": 1,
        "title": fields["title"],
        "tag": fields["tag"],
        "status": "draft",
        "created_by": actor,
        "created_at": now,
        "updated_at": now,
        "config": fields["config"],
        "items": fields["items"],
        "release": None,
    }
    with transaction():
        exams = _load()
        exams[exam["id"]] = exam
        write_json("exams.json", exams)
    audit("exam.created", actor, ip, {"exam_id": exam["id"]})
    return _public(exam)


def _validate_publishable(exam: dict) -> None:
    problems: list[tuple[str, str]] = []
    config = exam["config"]
    if not str(exam.get("title", "")).strip():
        problems.append(("title", "tên kỳ thi"))
    if not config.get("participants"):
        problems.append(("participants", "danh sách sinh viên dự thi"))
    if not config.get("accepted_submission_extensions"):
        problems.append(("ext", "loại file được chấp nhận"))
    if config["password_enabled"] and not config.get("password_hash"):
        problems.append(("password", "mật khẩu đề thi (đang bật yêu cầu mật khẩu)"))
    code_item = _item(exam, "code")
    if len(exam["items"]) != 1 or exam["items"][0].get("type") not in ITEM_TYPES:
        problems.append(("items", "chọn đúng một loại bài thi: bài nộp file hoặc bài code"))
    elif code_item and not code_item.get("distribution") and not code_item["question_ids"]:
        problems.append(("code", "Paper version hoặc câu hỏi cho bài code"))
    if problems:
        raise ExamError("Chưa thể phát đề. Còn thiếu: " + "; ".join(label for _, label in problems) + ".", 400, [key for key, _ in problems])


SUPPORTED_CODE_KINDS = {("java", "reflection"), ("java", "stdio"), ("python", "stdio")}


def _check_code_questions(code_item: dict) -> None:
    """Reject publishing when any selected question is missing, not Published, unsupported or duplicated.

    Runs before any snapshot is created, so a rejection leaves no partial data behind.
    """
    bank = read_json("questions.json")
    invalid: list[dict] = []
    seen: set[str] = set()
    for position, question_id in enumerate(code_item.get("question_ids", []), start=1):
        question = bank.get(question_id)
        reason = code = None
        if question_id in seen:
            reason, code = "Câu hỏi bị chọn trùng trong đề.", "duplicate"
        elif not question:
            reason, code = "Câu hỏi không còn trong Ngân hàng câu hỏi.", "missing"
        elif question.get("status") == "archived":
            reason, code = "Câu hỏi đã được lưu trữ.", "archived"
        elif question.get("status") != "published":
            reason, code = "Câu hỏi đang ở trạng thái Nháp. Hãy xác thực và xuất bản lại.", "draft"
        elif (question.get("language"), question.get("grading_mode")) not in SUPPORTED_CODE_KINDS:
            reason, code = "Loại câu hỏi chưa được hỗ trợ trong đề nhiều câu.", "unsupported"
        seen.add(question_id)
        if reason:
            invalid.append(
                {
                    "question_id": question_id,
                    "position": position,
                    "title": (question or {}).get("title", ""),
                    "status": (question or {}).get("status"),
                    "code": code,
                    "reason": reason,
                }
            )
    if invalid:
        raise ExamError(
            f"Không thể phát đề: có {len(invalid)} câu hỏi không hợp lệ. Kỳ thi vẫn ở trạng thái Nháp.",
            409,
            ["code"],
            {"invalid_questions": invalid},
        )


def _paper_ref_key(ref: Mapping) -> str:
    return f"{ref['paper_id']}::{ref.get('paper_version_id', '@paper')}"


def _check_code_papers(code_item: dict) -> list[dict]:
    distribution = code_item.get("distribution") or {}
    refs = distribution.get("paper_versions", [])
    if distribution.get("mode") not in {"common", "random"} or not refs:
        raise ExamError("Cấu hình phân phối Paper không hợp lệ.", 422, ["code"])
    if distribution["mode"] == "common" and len(refs) != 1:
        raise ExamError("COMMON phải chọn chính xác một Paper version.", 422, ["code"])
    validated = []
    for ref in refs:
        try:
            canonical, version = resolve_paper_reference(ref, require_published=True)
        except PaperError as exc:
            raise ExamError(str(exc), exc.status, ["code"], {"paper_ref": dict(ref)}) from exc
        validated.append({**canonical, "version": version})
    return validated


def _choose_random_paper(refs: list[dict]) -> dict:
    """Choose a complete paper version once while constructing the release."""
    return random.SystemRandom().choice(refs)


def _build_release(exam: dict, actor: str, ip: str) -> dict:
    """Validate a release and persist its immutable assignment selection map."""
    _validate_publishable(exam)
    config = exam["config"]
    zip_item = _item(exam, "zip")
    code_item = _item(exam, "code")
    validated_papers = []
    if code_item:
        if code_item.get("distribution"):
            validated_papers = _check_code_papers(code_item)
        else:
            _check_code_questions(code_item)
    students = read_json("students.json")
    participants = config["participants"]
    missing = [sid for sid in participants if sid not in students]
    eligible = eligible_students(participants, {**students, **{sid: {"active": True} for sid in missing}})
    if not eligible:
        raise ExamError("Không có tài khoản sinh viên đang hoạt động để phát đề.")
    files = [entry["name"] for entry in list_exam_files()]
    try:
        if zip_item:
            assignments = compute_assignments(zip_item["distribution_mode"], dict(zip_item["distribution_config"]), files, eligible, False)
        else:
            assignments = compute_assignments("selected", {}, files, eligible, True)
    except ValueError as exc:
        raise ExamError(str(exc)) from exc

    release_id = _new_id()
    new_code_id = None
    created_code_ids = []
    paper_assignments = {}
    paper_code_exam_ids = {}
    if code_item:
        if validated_papers:
            try:
                for ref in validated_papers:
                    snapshot = create_paper_code_exam(
                        {
                            "title": exam["title"],
                            "paper_ref": {
                                "paper_id": ref["paper_id"],
                                **({"paper_version_id": ref["paper_version_id"]} if ref.get("paper_version_id") is not None else {}),
                            },
                            "submission_policy": config["submission_policy"],
                            "max_submissions": config["max_submissions"],
                            "show_final_score_immediately": code_item["show_final_score_immediately"],
                            "allow_pretest": code_item["allow_pretest"],
                            "max_pretest_runs": code_item["max_pretest_runs"],
                            "pretest_cooldown_seconds": code_item["pretest_cooldown_seconds"],
                        },
                        general_exam_id=exam["id"],
                        actor=actor,
                        ip=ip,
                    )
                    code_exam_id = snapshot["id"]
                    created_code_ids.append(code_exam_id)
                    attach_code_exam_to_release(code_exam_id, release_id)
                    paper_code_exam_ids[_paper_ref_key(ref)] = code_exam_id
                code_item["paper_code_exam_ids"] = paper_code_exam_ids
                refs = [
                    {"paper_id": ref["paper_id"], **({"paper_version_id": ref["paper_version_id"]} if ref.get("paper_version_id") is not None else {})}
                    for ref in validated_papers
                ]
                for sid in assignments:
                    selected = refs[0] if code_item["distribution"]["mode"] == "common" else _choose_random_paper(refs)
                    paper_assignments[sid] = {
                        **selected,
                        "code_exam_id": paper_code_exam_ids[_paper_ref_key(selected)],
                    }
            except (CodeExamError, PaperError) as exc:
                for created_id in created_code_ids:
                    discard_code_exam(created_id)
                raise ExamError(str(exc), getattr(exc, "status", 409)) from exc
            except Exception:
                for created_id in created_code_ids:
                    discard_code_exam(created_id)
                raise
        else:
            try:
                snapshot = create_code_exam(
                    {
                        "title": exam["title"],
                        "question_ids": code_item["question_ids"],
                        "submission_policy": config["submission_policy"],
                        "max_submissions": config["max_submissions"],
                        "show_final_score_immediately": code_item["show_final_score_immediately"],
                        "allow_pretest": code_item["allow_pretest"],
                        "max_pretest_runs": code_item["max_pretest_runs"],
                        "pretest_cooldown_seconds": code_item["pretest_cooldown_seconds"],
                    },
                    actor,
                    ip,
                )
                new_code_id = snapshot["id"]
                attach_code_exam_to_release(new_code_id, release_id)
            except CodeExamError as exc:
                discard_code_exam(new_code_id)
                raise ExamError(str(exc), exc.status) from exc
            code_item["code_exam_id"] = new_code_id

    if missing:
        students = read_json("students.json")
        for sid in missing:
            students.setdefault(
                sid,
                {"student_id": sid, "full_name": "Chưa cập nhật", "password_hash": hash_password(sid), "active": True, "created_at": utc_now(), "last_ip": None, "last_seen": None, "must_change_password": True},
            )
        write_json("students.json", students)

    summary: dict[str, int] = {}
    for filename in assignments.values():
        if filename:
            summary[filename] = summary.get(filename, 0) + 1
    release = {
        "release_id": release_id,
        "released_at": utc_now(),
        "applied": False,
        "assigned_count": len(assignments),
        "assignments": assignments,
        "distribution_summary": summary,
    }
    if validated_papers:
        counts = {}
        for selected in paper_assignments.values():
            key = selected.get("paper_version_id", selected["paper_id"])
            counts[key] = counts.get(key, 0) + 1
        release.update({
            "distribution_mode": code_item["distribution"]["mode"],
            "paper_pool": [
                {"paper_id": ref["paper_id"], **({"paper_version_id": ref["paper_version_id"]} if ref.get("paper_version_id") is not None else {})}
                for ref in validated_papers
            ],
            "paper_assignments": paper_assignments,
            "paper_distribution_summary": counts,
        })
    return release


def _check_new_code_questions(old_item: dict | None, new_item: dict | None) -> None:
    """Questions already in the exam may stay (with warnings); newly added ones must be Published and supported."""
    if not new_item:
        return
    new_distribution = new_item.get("distribution")
    if new_distribution:
        old_refs = {
            (ref["paper_id"], ref.get("paper_version_id"))
            for ref in ((old_item or {}).get("distribution") or {}).get("paper_versions", [])
        }
        for ref in new_distribution.get("paper_versions", []):
            if (ref["paper_id"], ref.get("paper_version_id")) in old_refs:
                continue
            _check_code_papers({"distribution": {"mode": "common", "paper_versions": [ref]}})
        return
    previous = set(old_item["question_ids"]) if old_item else set()
    bank = read_json("questions.json")
    for question_id in new_item["question_ids"]:
        if question_id in previous:
            continue
        question = bank.get(question_id)
        if not question or question.get("status") != "published":
            raise ExamError("Chỉ có thể thêm câu hỏi đã xuất bản vào đề thi.", 409, ["code"])
        if (question.get("language"), question.get("grading_mode")) not in SUPPORTED_CODE_KINDS:
            raise ExamError("Loại câu hỏi này chưa được hỗ trợ trong đề nhiều câu.", 409, ["code"])


def update_exam(exam_id: str, payload, actor: str, ip: str) -> dict:
    with transaction():
        reconcile()
        exams = _load()
        exam = _must(exams, exam_id)
        expected_revision = payload.get("expected_revision") if isinstance(payload, Mapping) else None
        if isinstance(expected_revision, bool) or not isinstance(expected_revision, int):
            raise ExamError("expected_revision is required", 422, ["expected_revision"])
        current_revision = int(exam.get("revision", 1))
        if expected_revision != current_revision:
            raise ExamError("This exam changed since it was opened. Reload before saving.", 409, ["revision"], {
                "expected_revision": expected_revision, "current_revision": current_revision,
            })
        if exam["status"] not in {"draft", "distributed"}:
            raise ExamError("Không thể chỉnh sửa kỳ thi đang diễn ra hoặc đã kết thúc.", 409)
        fields = _normalize(payload, exam)
        _check_new_code_questions(_item(exam, "code"), _item({"items": fields["items"]}, "code"))
        updated = {**copy.deepcopy(exam), **fields}
        if exam["status"] == "distributed":
            old_code = _item(exam, "code")
            release_id = exam["release"].get("release_id")
            if exam.get("started_at") or exam.get("ended_at") or _has_release_activity(release_id):
                raise ExamError("Student activity exists for this release; its configuration and historical data cannot be changed.", 409)
            old_code_ids = _code_exam_ids(old_code)
            updated["release"] = _build_release(updated, actor, ip)
            new_code = _item(updated, "code")
        _touch(updated)
        exams[exam_id] = updated
        write_json("exams.json", exams)
        if exam["status"] == "distributed":
            _synchronize_prestart_assignments(release_id, updated["release"], updated)
            for old_code_id in old_code_ids - _code_exam_ids(new_code):
                discard_code_exam(old_code_id)
    audit("exam.updated", actor, ip, {"exam_id": exam_id, "status": updated["status"]})
    return _public(updated)


def publish_exam(exam_id: str, actor: str, ip: str) -> dict:
    with transaction():
        reconcile()
        exams = _load()
        exam = _must(exams, exam_id)
        if exam["status"] == "distributed" and exam.get("release"):
            return _public(exam)
        if exam["status"] != "draft":
            raise ExamError("Chỉ có thể phát đề cho kỳ thi ở trạng thái Nháp.", 409)
        updated = copy.deepcopy(exam)
        code_item = _item(updated, "code")
        old_code_ids = _code_exam_ids(code_item)
        if code_item:
            code_item.pop("code_exam_id", None)
            code_item.pop("paper_code_exam_ids", None)
        updated["release"] = _build_release(updated, actor, ip)
        new_code = _item(updated, "code")
        for old_code_id in old_code_ids - _code_exam_ids(new_code):
            discard_code_exam(old_code_id)
        updated["status"] = "distributed"
        _touch(updated)
        exams[exam_id] = updated
        write_json("exams.json", exams)
    audit("exam.published", actor, ip, {"exam_id": exam_id, "release_id": updated["release"]["release_id"]})
    return _public(updated)


def revoke_exam(exam_id: str, actor: str, ip: str) -> dict:
    with transaction():
        reconcile()
        exams = _load()
        exam = _must(exams, exam_id)
        if exam["status"] != "distributed":
            raise ExamError("Chỉ có thể thu hồi kỳ thi đã phát đề và chưa bắt đầu.", 409)
        release = exam["release"]
        if release.get("applied"):
            _clear_applied_release(release["release_id"])
        _drop_code_snapshot(exam)
        exam.update({"status": "draft", "release": None})
        _touch(exam)
        write_json("exams.json", exams)
    audit("exam.revoked", actor, ip, {"exam_id": exam_id})
    return _public(exam)


def _apply_release(exam: dict, settings: dict) -> None:
    release = exam["release"]
    config = exam["config"]
    release_id = release["release_id"]
    files = {entry["name"] for entry in list_exam_files()}
    students = read_json("students.json")
    sessions = read_json("sessions.json")
    old_assignments = read_json("assignments.json")
    code_item = _item(exam, "code")
    zip_item = _item(exam, "zip")
    persisted = {}
    for sid, filename in release["assignments"].items():
        student = students.get(sid)
        if not student or not student.get("active", True):
            continue
        if filename and filename not in files:
            raise ExamError(f"File đề '{filename}' không còn tồn tại. Hãy thu hồi và phát đề lại.", 409)
        previous = old_assignments.get(sid, {})
        previous = previous if previous.get("release_id") == release_id else {}
        item = {
            "exam_file": filename,
            "release_id": release_id,
            "assigned_at": release["released_at"],
            "started_at": previous.get("started_at"),
            "ends_at": previous.get("ends_at"),
            "status": previous.get("status", "assigned"),
            "ip_at_assignment": previous.get("ip_at_assignment") or next((s.get("ip") for s in sessions.values() if s.get("user_id") == sid and s.get("role") == "student"), None),
        }
        if code_item and code_item.get("code_exam_id"):
            item["code_exam_id"] = code_item["code_exam_id"]
        paper_assignment = release.get("paper_assignments", {}).get(sid)
        if paper_assignment:
            expected_ref = {
                "paper_id": paper_assignment.get("paper_id"),
                **({"paper_version_id": paper_assignment["paper_version_id"]} if paper_assignment.get("paper_version_id") is not None else {}),
            }
            code_exam = get_code_exam(paper_assignment.get("code_exam_id"))
            if (
                not code_exam
                or code_exam.get("release_id") != release_id
                or code_exam.get("paper_ref") != expected_ref
            ):
                raise ExamError("Paper assignment snapshot is missing or mismatched.", 409)
            item.update({**expected_ref, "code_exam_id": paper_assignment["code_exam_id"]})
        elif code_item and code_item.get("distribution"):
            raise ExamError("Paper assignment is missing from the persisted release.", 409)
        persisted[sid] = item
    if not persisted:
        raise ExamError("Không còn sinh viên hợp lệ để bắt đầu kỳ thi.", 409)
    started_at = (
        settings.get("exam_started_at")
        if settings.get("exam_release_id") == release_id and settings.get("exam_started_at")
        else utc_now()
    )
    settings.update(
        {
            "exam_duration_minutes": config["duration_minutes"],
            "submission_policy": config["submission_policy"],
            "max_submissions": config["max_submissions"],
            "overwrite_previous": config["overwrite_previous"],
            "accepted_submission_extensions": config["accepted_submission_extensions"],
            "exam_password_enabled": config["password_enabled"],
            "exam_password_hash": config.get("password_hash") if config["password_enabled"] else None,
            "exam_participants": config["participants"],
            "distribution_mode": zip_item["distribution_mode"] if zip_item else "selected",
            "distribution_config": zip_item["distribution_config"] if zip_item else {},
            "exam_state": "started",
            "exam_released": True,
            "exam_release_id": release_id,
            "exam_release_at": release["released_at"],
            "exam_started_at": started_at,
        }
    )
    write_json("assignments.json", persisted)
    write_json("settings.json", settings)
    transition_code_exam(release_id, "started")
    release["applied"] = True


def start_exam(exam_id: str, actor: str, ip: str) -> dict:
    # The shared lock makes the "no other exam is running" check and the state change atomic.
    with transaction():
        reconcile()
        exams = _load()
        exam = _must(exams, exam_id)
        if exam["status"] != "distributed":
            raise ExamError("Chỉ có thể bắt đầu kỳ thi đã phát đề.", 409)
        settings = read_json("settings.json")
        if settings.get("exam_state") == "started" or settings.get("exam_released"):
            raise ExamError("Đang có một kỳ thi diễn ra. Hãy kết thúc kỳ thi đó trước khi bắt đầu kỳ thi khác.", 409)
        release = exam["release"]
        if (
            release.get("applied")
            and settings.get("exam_state") == "distributed"
            and settings.get("exam_release_id") == release.get("release_id")
            and isinstance(release.get("assignments"), Mapping)
        ):
            # A published, not-started release may already have preparatory assignments.
            # Re-apply the persisted release map at explicit Start so synced Paper choices
            # and any other current Exam configuration become authoritative together.
            _apply_release(exam, settings)
        elif release.get("applied"):
            try:
                start_exam_session()
            except ValueError as exc:
                raise ExamError(str(exc), 409) from exc
        else:
            if settings.get("exam_state") == "distributed" and settings.get("exam_release_id") not in {None, release.get("release_id")}:
                raise ExamError("Đang có đề phát theo luồng cũ chưa bắt đầu. Hãy thu hồi hoặc bắt đầu kỳ thi đó trước.", 409)
            _apply_release(exam, settings)
        exam.update({"status": "started", "started_at": utc_now()})
        _touch(exam)
        write_json("exams.json", exams)
    audit("exam.started_by_admin", actor, ip, {"exam_id": exam_id, "release_id": release["release_id"]})
    return _public(exam)


def end_exam(exam_id: str, actor: str, ip: str) -> dict:
    with transaction():
        reconcile()
        exams = _load()
        exam = _must(exams, exam_id)
        if exam["status"] != "started":
            raise ExamError("Chỉ có thể kết thúc kỳ thi đang diễn ra.", 409)
        try:
            ended = end_exam_session()
        except ValueError as exc:
            raise ExamError(str(exc), 409) from exc
        release_student_exam_scores(ended["release_id"])
        exam.update({"status": "ended", "ended_at": ended["ended_at"]})
        _touch(exam)
        write_json("exams.json", exams)
    audit("exam.ended_by_admin", actor, ip, {"exam_id": exam_id, "release_id": ended["release_id"]})
    return _public(exam)


def delete_exam(exam_id: str, actor: str, ip: str) -> dict:
    """Delete an exam.

    Drafts and distributed exams are removed together with their unused code snapshot.
    Ended exams are hidden but kept, so submissions, grading records and code results
    stay available.
    """
    with transaction():
        reconcile()
        exams = _load()
        exam = _must(exams, exam_id)
        if exam["status"] == "started":
            raise ExamError("Không thể xóa kỳ thi đang diễn ra.", 409)
        retained = exam["status"] == "ended"
        if retained:
            exam.update({"deleted_at": utc_now(), "deleted_by": actor})
        else:
            release = exam.get("release")
            if release and release.get("applied"):
                _clear_applied_release(release["release_id"])
            _drop_code_snapshot(exam)
            del exams[exam_id]
        write_json("exams.json", exams)
    audit("exam.deleted", actor, ip, {"exam_id": exam_id, "retained_data": retained})
    return {"retained_data": retained}


def copy_exam(exam_id: str, actor: str, ip: str) -> dict:
    with transaction():
        reconcile()
        exams = _load()
        source = _must(exams, exam_id)
        now = utc_now()
        items = copy.deepcopy(source["items"])
        for item in items:
            item["item_id"] = _new_id()
            item.pop("code_exam_id", None)
            item.pop("paper_code_exam_ids", None)
        title = f"{source['title']} (bản sao)"
        clone = {
            "id": _new_id(),
            "title": title[:200],
            "tag": source.get("tag", ""),
            "status": "draft",
            "created_by": actor,
            "created_at": now,
            "updated_at": now,
            "config": copy.deepcopy(source["config"]),
            "items": items,
            "release": None,
        }
        exams[clone["id"]] = clone
        write_json("exams.json", exams)
    audit("exam.copied", actor, ip, {"source_exam_id": exam_id, "exam_id": clone["id"]})
    return _public(clone)
