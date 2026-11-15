"""Reusable exam paper drafts and immutable published question snapshots."""
from __future__ import annotations

from copy import deepcopy
import json
import re
import uuid
from collections.abc import Mapping

from .code_exams import CodeExamError, _snapshot_question, _validate_code_exam_payload
from .questions import QuestionError, _validate_question
from .storage import audit, read_json, transaction, update_json, utc_now, write_json


_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
_SUPPORTED_CODE_KINDS = {("java", "reflection"), ("java", "stdio"), ("python", "stdio")}
_QUESTION_FILTER_KEYS = {"search", "category", "language", "grading_mode", "difficulty", "tags"}


class PaperError(ValueError):
    """A paper request is invalid or conflicts with its stored state."""

    def __init__(self, message: str, status: int = 400, code: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code


def _copy_json(value, label: str):
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise PaperError(f"{label} must contain valid JSON values", 422) from exc


def _validate_ids(question_ids, *, allow_empty: bool = False) -> list[str]:
    if not isinstance(question_ids, list) or (not allow_empty and not question_ids):
        message = "question_ids must be an array" if allow_empty else "question_ids must be a non-empty array"
        raise PaperError(message, 422)
    if any(not isinstance(qid, str) or not _ID_PATTERN.fullmatch(qid) for qid in question_ids):
        raise PaperError("question_ids contains an invalid question id", 422)
    if len(set(question_ids)) != len(question_ids):
        raise PaperError("A question may appear only once in a paper", 422, "DUPLICATE_QUESTION")
    return list(question_ids)


def _validate_title(value) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 200:
        raise PaperError("title must contain 1 to 200 characters", 422)
    return value.strip()


def _validate_metadata(value) -> dict:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise PaperError("metadata must be a JSON object", 422)
    metadata = _copy_json(dict(value), "metadata")
    if len(json.dumps(metadata, ensure_ascii=False).encode("utf-8")) > 32_768:
        raise PaperError("metadata must be at most 32768 bytes", 422)
    return metadata


def _validate_new_questions(question_ids: list[str]) -> None:
    bank = read_json("questions.json")
    for qid in question_ids:
        question = bank.get(qid)
        if question is None:
            raise PaperError(f"Question '{qid}' was not found", 404, "QUESTION_NOT_FOUND")
        if question.get("status") != "published":
            raise PaperError(f"Question '{qid}' is not published", 409, "QUESTION_NOT_PUBLISHED")
        if (question.get("language"), question.get("grading_mode")) not in _SUPPORTED_CODE_KINDS:
            raise PaperError(f"Question '{qid}' is not eligible for a code paper", 409, "QUESTION_NOT_ELIGIBLE")
        try:
            _validate_question(question, question_id=qid, actor="paper-validation")
        except QuestionError as exc:
            raise PaperError(f"Question '{qid}' is missing valid display or grading fields: {exc}", 422, "QUESTION_NOT_ELIGIBLE") from exc

    try:
        _validate_code_exam_payload({"title": "Paper validation", "question_ids": question_ids})
    except CodeExamError as exc:
        raise PaperError(str(exc), exc.status, "QUESTION_NOT_ELIGIBLE") from exc
    except (KeyError, TypeError, ValueError) as exc:
        raise PaperError(f"A selected question is missing required grading fields: {exc}", 422, "QUESTION_NOT_ELIGIBLE") from exc


def _normalize_question_filters(value) -> dict:
    if value is None:
        value = {}
    if not isinstance(value, Mapping):
        raise PaperError("question_filters must be an object", 422, "INVALID_QUESTION_FILTERS")
    if set(value) - _QUESTION_FILTER_KEYS:
        raise PaperError("question_filters contains an unsupported field", 422, "INVALID_QUESTION_FILTERS")

    result = {}
    for key in ("search", "category", "language", "grading_mode", "difficulty"):
        raw = value.get(key, "")
        if not isinstance(raw, str) or len(raw) > 200:
            raise PaperError(f"question_filters.{key} must be text of at most 200 characters", 422, "INVALID_QUESTION_FILTERS")
        result[key] = raw.strip().casefold()
    if result["language"] not in {"", "java", "python"}:
        raise PaperError("question_filters.language is not supported", 422, "INVALID_QUESTION_FILTERS")
    if result["grading_mode"] not in {"", "reflection", "stdio"}:
        raise PaperError("question_filters.grading_mode is not supported", 422, "INVALID_QUESTION_FILTERS")

    tags = value.get("tags", [])
    if not isinstance(tags, list) or len(tags) > 100 or any(not isinstance(tag, str) or len(tag) > 100 for tag in tags):
        raise PaperError("question_filters.tags must be an array of at most 100 text values", 422, "INVALID_QUESTION_FILTERS")
    result["tags"] = list(dict.fromkeys(tag.strip().casefold() for tag in tags if tag.strip()))
    return result


def _question_tags(question: Mapping) -> list[str]:
    raw = question.get("tags", [])
    if isinstance(raw, str):
        values = raw.split(",")
    elif isinstance(raw, list):
        values = raw
    else:
        values = []
    return [tag.strip().casefold() for tag in values if isinstance(tag, str) and tag.strip()]


def _question_matches_filters(question: Mapping, filters: Mapping) -> bool:
    for key in ("category", "difficulty"):
        requested = filters.get(key, "")
        actual = question.get(key)
        actual = actual.strip().casefold() if isinstance(actual, str) else ""
        if requested and actual != requested:
            return False
    for key in ("language", "grading_mode"):
        requested = filters.get(key, "")
        actual = question.get(key)
        actual = actual.strip().casefold() if isinstance(actual, str) else ""
        if requested and actual != requested:
            return False
    wanted_tags = filters.get("tags", [])
    if wanted_tags and not set(wanted_tags).intersection(_question_tags(question)):
        return False
    search = filters.get("search", "")
    if search:
        haystack = " ".join(
            [str(question.get("title") or ""), str(question.get("id") or ""), *_question_tags(question)]
        ).casefold()
        if search not in haystack:
            return False
    return True


def _is_eligible_question(question_id: str, question: Mapping) -> bool:
    if question.get("status") != "published" or (question.get("language"), question.get("grading_mode")) not in _SUPPORTED_CODE_KINDS:
        return False
    try:
        _validate_question(question, question_id=question_id, actor="paper-pool-validation")
    except (QuestionError, KeyError, TypeError, ValueError):
        return False
    return True


def _filtered_eligible_questions(filters: Mapping) -> dict[str, dict]:
    bank = read_json("questions.json")
    return {
        question_id: question
        for question_id, question in bank.items()
        if isinstance(question, Mapping)
        and _is_eligible_question(question_id, question)
        and _question_matches_filters(question, filters)
    }


def _validate_question_selection(
    question_ids: list[str], question_limit, raw_filters, *, previous_ids: set[str] | None = None,
    require_exact: bool = False,
) -> tuple[int | None, dict, list[str]]:
    filters = _normalize_question_filters(raw_filters)
    if question_limit is not None and (
        isinstance(question_limit, bool) or not isinstance(question_limit, int) or question_limit < 1
    ):
        raise PaperError("question_limit must be an integer of at least 1", 422, "INVALID_QUESTION_LIMIT")
    if require_exact and (question_limit is None or question_limit != len(question_ids)):
        raise PaperError("question_limit must equal the number of selected questions", 422, "QUESTION_LIMIT_MISMATCH")
    if question_limit is not None and question_limit < len(question_ids):
        raise PaperError("question_limit cannot be less than the number of selected questions", 422, "QUESTION_LIMIT_MISMATCH")

    pool = _filtered_eligible_questions(filters)
    previous_ids = previous_ids or set()
    newly_added = [question_id for question_id in question_ids if question_id not in previous_ids]
    grandfathered = [question_id for question_id in question_ids if question_id in previous_ids and question_id not in pool]
    if question_limit is not None and question_limit > len(pool) + len(grandfathered):
        raise PaperError("question_limit exceeds the eligible filtered question pool", 422, "QUESTION_LIMIT_EXCEEDS_POOL")
    if newly_added:
        _validate_new_questions(newly_added)
        if any(question_id not in pool for question_id in newly_added):
            raise PaperError("New questions must match the selected filters", 422, "QUESTION_FILTER_MISMATCH")
    return question_limit, filters, newly_added


def _source_status(question_id: str, snapshot: Mapping | None = None) -> dict:
    question = read_json("questions.json").get(question_id)
    snapshot_source = (snapshot or {}).get("source_ref") or {}
    if question is None:
        return {
            "question_id": question_id,
            "title": snapshot_source.get("title_at_capture") or (snapshot or {}).get("title", ""),
            "status": "deleted",
            "active": False,
            "warning": "Câu hỏi nguồn đã bị xóa; Paper đang dùng snapshot đã lưu.",
        }
    captured_created_at = snapshot_source.get("created_at")
    current_created_at = (question.get("source") or {}).get("created_at")
    if captured_created_at and current_created_at and captured_created_at != current_created_at:
        return {
            "question_id": question_id,
            "title": snapshot_source.get("title_at_capture") or (snapshot or {}).get("title", ""),
            "status": "recreated",
            "active": False,
            "warning": "ID nguồn đã được dùng lại; Paper giữ snapshot của câu hỏi đã bị xóa trước đó.",
        }
    status = question.get("status", "unknown")
    active = status == "published"
    return {
        "question_id": question_id,
        "title": question.get("title", ""),
        "status": status,
        "active": active,
        "warning": None if active else f"Câu hỏi nguồn hiện có trạng thái '{status}'; Paper vẫn giữ snapshot đã lưu.",
    }


def _serialize_version(version: Mapping) -> dict:
    result = deepcopy(dict(version))
    statuses = [_source_status(item["question_id"], item) for item in result.get("questions", [])]
    result["source_status"] = statuses
    result["warnings"] = [item for item in statuses if item["warning"]]
    return result


def _serialize_paper(paper: Mapping) -> dict:
    result = deepcopy(dict(paper))
    if result.get("versions") and result.get("status") != "archived":
        result["status"] = "published"
    for version_id, version in result.get("versions", {}).items():
        result["versions"][version_id] = _serialize_version(version)
    draft = result.get("draft")
    if isinstance(draft, dict):
        statuses = [_source_status(qid) for qid in draft.get("question_ids", [])]
        draft["source_status"] = statuses
        draft["warnings"] = [item for item in statuses if item["warning"]]
    return result


def _get_paper(paper_id: str) -> dict | None:
    return read_json("papers.json").get(paper_id)


def list_papers() -> list[dict]:
    papers = read_json("papers.json")
    result = []
    for paper in papers.values():
        current_id = paper.get("current_version_id")
        current = paper.get("versions", {}).get(current_id, {}) if current_id else {}
        question_ids = (paper.get("draft") or {}).get("question_ids", [])
        source_questions = current.get("questions", []) or [
            {"question_id": qid} for qid in question_ids
        ]
        source_status = [_source_status(item["question_id"], item) for item in source_questions]
        result.append({
            "id": paper["id"],
            "title": paper.get("title", ""),
            "metadata": deepcopy(paper.get("metadata", {})),
            "status": "published" if paper.get("versions") and paper.get("status") != "archived" else paper.get("status", "draft"),
            "has_draft": isinstance(paper.get("draft"), Mapping),
            "revision": paper.get("revision", 1),
            "current_version_id": current_id,
            "version_count": len(paper.get("versions", {})),
            "question_count": len(current.get("questions", [])) or len(question_ids),
            "source_status": source_status,
            "warnings": [item for item in source_status if item["warning"]],
            "updated_at": paper.get("updated_at"),
        })
    return sorted(result, key=lambda item: (item.get("updated_at") or "", item["id"]), reverse=True)


def get_paper(paper_id: str) -> dict:
    paper = _get_paper(paper_id)
    if not paper:
        raise PaperError("Paper was not found", 404, "PAPER_NOT_FOUND")
    return _serialize_paper(paper)


def get_paper_version_snapshot(
    paper_id: str, paper_version_id: str, *, require_published: bool = False
) -> dict:
    """Return the persisted immutable version, optionally requiring an active paper."""
    paper = _get_paper(paper_id)
    if not paper:
        raise PaperError("Paper was not found", 404, "PAPER_NOT_FOUND")
    if require_published and paper.get("status") != "published":
        raise PaperError("Paper is not published", 409, "PAPER_NOT_PUBLISHED")
    version = paper.get("versions", {}).get(paper_version_id)
    if not isinstance(version, Mapping):
        raise PaperError("Paper version was not found", 404, "PAPER_VERSION_NOT_FOUND")
    questions = version.get("questions")
    if not isinstance(questions, list) or not questions:
        raise PaperError("Paper version has no valid question snapshots", 409, "PAPER_VERSION_INVALID")
    seen = set()
    for order, question in enumerate(questions):
        if (
            not isinstance(question, Mapping)
            or not isinstance(question.get("question_id"), str)
            or question.get("order") != order
            or question["question_id"] in seen
            or not isinstance(question.get("total_points"), (int, float))
        ):
            raise PaperError("Paper version contains an invalid question snapshot", 409, "PAPER_VERSION_INVALID")
        seen.add(question["question_id"])
    return deepcopy(dict(version))


def create_paper(payload: Mapping, actor: str, ip: str) -> dict:
    if not isinstance(payload, Mapping):
        raise PaperError("Paper must be a JSON object", 422)
    title = _validate_title(payload.get("title"))
    metadata = _validate_metadata(payload.get("metadata", {}))
    question_ids = _validate_ids(payload.get("question_ids"), allow_empty=True)
    quantity_default = len(question_ids) if question_ids else None
    question_limit, question_filters, _ = _validate_question_selection(
        question_ids, payload.get("question_limit", quantity_default), payload.get("question_filters", {})
    )
    now = utc_now()
    paper_id = uuid.uuid4().hex
    paper = {
        "id": paper_id,
        "schema_version": 1,
        "title": title,
        "metadata": metadata,
        "status": "draft",
        "revision": 1,
        "draft": {
            "title": title,
            "metadata": metadata,
            "question_ids": question_ids,
            "question_limit": question_limit,
            "question_filters": question_filters,
        },
        "current_version_id": None,
        "versions": {},
        "created_by": actor,
        "created_at": now,
        "updated_at": now,
    }

    def insert(papers):
        papers[paper_id] = paper

    with transaction():
        if question_ids:
            _validate_new_questions(question_ids)
        update_json("papers.json", insert)
    audit("paper.created", actor, ip, {"paper_id": paper_id, "question_count": len(question_ids)})
    return get_paper(paper_id)


def _require_revision(paper: Mapping, payload: Mapping) -> None:
    if not isinstance(payload, Mapping):
        raise PaperError("expected_revision is required", 422)
    expected = payload.get("expected_revision")
    current = paper.get("revision", 1)
    if isinstance(expected, bool) or not isinstance(expected, int) or expected != current:
        raise PaperError("Paper has changed; reload before retrying", 409, "PAPER_CHANGED")


def update_paper(paper_id: str, payload: Mapping, actor: str, ip: str) -> dict:
    if not isinstance(payload, Mapping):
        raise PaperError("Paper update must be a JSON object", 422)
    with transaction():
        paper = _get_paper(paper_id)
        if not paper:
            raise PaperError("Paper was not found", 404, "PAPER_NOT_FOUND")
        _require_revision(paper, payload)
        if paper.get("status") == "archived":
            raise PaperError("Archived papers cannot be edited; restore the paper first", 409)
        draft = paper.get("draft") or {
            "title": paper.get("title", ""),
            "metadata": deepcopy(paper.get("metadata", {})),
            "question_ids": [item["question_id"] for item in paper.get("versions", {}).get(paper.get("current_version_id"), {}).get("questions", [])],
            "question_limit": len(paper.get("versions", {}).get(paper.get("current_version_id"), {}).get("questions", [])) or None,
            "question_filters": {},
        }
        title = _validate_title(payload.get("title", draft.get("title")))
        metadata = _validate_metadata(payload.get("metadata", draft.get("metadata", {})))
        question_ids = _validate_ids(payload.get("question_ids", draft.get("question_ids", [])), allow_empty=True)
        previous_ids = set(draft.get("question_ids", []))
        quantity_default = draft.get("question_limit", len(question_ids) if question_ids else None)
        question_limit, question_filters, _ = _validate_question_selection(
            question_ids,
            payload.get("question_limit", quantity_default),
            payload.get("question_filters", draft.get("question_filters", {})),
            previous_ids=previous_ids,
        )

        now = utc_now()
        updated = {
            **paper,
            "title": title,
            "metadata": metadata,
            "status": "published" if paper.get("versions") else "draft",
            "revision": paper.get("revision", 1) + 1,
            "draft": {
                "title": title,
                "metadata": metadata,
                "question_ids": question_ids,
                "question_limit": question_limit,
                "question_filters": question_filters,
            },
            "updated_at": now,
        }
        papers = read_json("papers.json")
        papers[paper_id] = updated
        write_json("papers.json", papers)
    audit("paper.updated", actor, ip, {"paper_id": paper_id, "revision": updated["revision"]})
    return _serialize_paper(updated)


def _make_version(paper: Mapping, draft: Mapping) -> dict:
    question_ids = _validate_ids(draft.get("question_ids"))
    question_limit = draft.get("question_limit", len(question_ids))
    _validate_question_selection(
        question_ids, question_limit, draft.get("question_filters", {}),
        previous_ids=set(question_ids), require_exact=True,
    )
    previous = paper.get("versions", {}).get(paper.get("current_version_id"), {})
    previous_by_id = {item["question_id"]: item for item in previous.get("questions", [])}
    bank = read_json("questions.json")
    active_ids = []
    for qid in question_ids:
        question = bank.get(qid)
        prior = previous_by_id.get(qid)
        captured_created_at = ((prior or {}).get("source_ref") or {}).get("created_at")
        current_created_at = ((question or {}).get("source") or {}).get("created_at")
        same_source = not captured_created_at or not current_created_at or captured_created_at == current_created_at
        if question and question.get("status") == "published" and same_source:
            if (question.get("language"), question.get("grading_mode")) not in _SUPPORTED_CODE_KINDS:
                raise PaperError(f"Question '{qid}' is not eligible for a code paper", 409, "QUESTION_NOT_ELIGIBLE")
            active_ids.append(qid)
        elif qid not in previous_by_id:
            reason = "was not found" if question is None else "is not published"
            raise PaperError(f"Question '{qid}' {reason} and has no saved Paper snapshot", 409, "QUESTION_NOT_ELIGIBLE")

    fresh_by_id = {}
    if active_ids:
        try:
            _validate_new_questions(active_ids)
            _, fresh = _validate_code_exam_payload({"title": draft["title"], "question_ids": active_ids})
        except CodeExamError as exc:
            raise PaperError(str(exc), exc.status, "QUESTION_NOT_ELIGIBLE") from exc
        fresh_by_id = {item["question_id"]: item for item in fresh}

    snapshots = []
    for order, qid in enumerate(question_ids):
        if qid in fresh_by_id:
            snapshot = fresh_by_id[qid]
            source = bank[qid]
            snapshot["source_ref"] = {
                "question_id": qid,
                "title_at_capture": source.get("title", ""),
                "status_at_capture": source.get("status", "unknown"),
                "created_at": (source.get("source") or {}).get("created_at"),
            }
        else:
            snapshot = deepcopy(previous_by_id[qid])
        snapshot["order"] = order
        snapshots.append(snapshot)

    return {
        "id": f"{paper['id']}:v{len(paper.get('versions', {})) + 1}",
        "version": len(paper.get("versions", {})) + 1,
        "published_at": utc_now(),
        "title": draft["title"],
        "metadata": deepcopy(draft.get("metadata", {})),
        "questions": snapshots,
    }


def publish_paper(paper_id: str, payload: Mapping, actor: str, ip: str) -> dict:
    if not isinstance(payload, Mapping):
        raise PaperError("Publish request must be a JSON object", 422)
    with transaction():
        papers = read_json("papers.json")
        paper = papers.get(paper_id)
        if not paper:
            raise PaperError("Paper was not found", 404, "PAPER_NOT_FOUND")
        _require_revision(paper, payload)
        if paper.get("status") == "archived":
            raise PaperError("Archived papers cannot be published", 409)
        draft = paper.get("draft")
        if not isinstance(draft, Mapping):
            raise PaperError("Paper has no draft to publish", 409)
        version = _make_version(paper, draft)
        updated = {
            **paper,
            "title": draft["title"],
            "metadata": deepcopy(draft.get("metadata", {})),
            "status": "published",
            "revision": paper.get("revision", 1) + 1,
            "draft": None,
            "current_version_id": version["id"],
            "versions": {**paper.get("versions", {}), version["id"]: version},
            "updated_at": utc_now(),
        }
        papers[paper_id] = updated
        write_json("papers.json", papers)
    audit("paper.published", actor, ip, {"paper_id": paper_id, "paper_version_id": version["id"]})
    return _serialize_paper(updated)


def preview_paper(paper_id: str, version_id: str | None = None, *, draft_only: bool = False) -> dict:
    paper = _get_paper(paper_id)
    if not paper:
        raise PaperError("Paper was not found", 404, "PAPER_NOT_FOUND")
    if draft_only and version_id is not None:
        raise PaperError("Draft preview cannot request a published version", 422, "INVALID_PREVIEW_TARGET")
    selected_id = version_id
    if selected_id is None and paper.get("status") == "published" and not draft_only:
        selected_id = paper.get("current_version_id")
    if selected_id:
        version = paper.get("versions", {}).get(selected_id)
        if not version:
            raise PaperError("Paper version was not found", 404, "PAPER_VERSION_NOT_FOUND")
        return {"paper_id": paper_id, "status": paper.get("status"), "version": _serialize_version(version)}

    draft = paper.get("draft")
    if not draft:
        raise PaperError("Paper has no draft or published version", 409)
    snapshots = []
    for order, qid in enumerate(draft.get("question_ids", [])):
        question = read_json("questions.json").get(qid)
        if question is None:
            continue
        snapshots.append({**_snapshot_question(question), "question_id": qid, "order": order})
    source_status = [_source_status(qid) for qid in draft.get("question_ids", [])]
    return {
        "paper_id": paper_id,
        "status": paper.get("status"),
        "draft": {"title": draft["title"], "metadata": deepcopy(draft.get("metadata", {})), "questions": snapshots},
        "source_status": source_status,
        "warnings": [item for item in source_status if item["warning"]],
    }


def archive_paper(paper_id: str, payload: Mapping, actor: str, ip: str) -> dict:
    def change(papers):
        paper = papers.get(paper_id)
        if not paper:
            raise PaperError("Paper was not found", 404, "PAPER_NOT_FOUND")
        _require_revision(paper, payload)
        paper["status"] = "archived"
        paper["revision"] = paper.get("revision", 1) + 1
        paper["updated_at"] = utc_now()
        return deepcopy(paper)

    updated = update_json("papers.json", change)
    audit("paper.archived", actor, ip, {"paper_id": paper_id})
    return _serialize_paper(updated)


def restore_paper(paper_id: str, payload: Mapping, actor: str, ip: str) -> dict:
    def change(papers):
        paper = papers.get(paper_id)
        if not paper:
            raise PaperError("Paper was not found", 404, "PAPER_NOT_FOUND")
        _require_revision(paper, payload)
        if paper.get("status") != "archived":
            raise PaperError("Only archived papers can be restored", 409)
        paper["status"] = "draft"
        paper["revision"] = paper.get("revision", 1) + 1
        paper["updated_at"] = utc_now()
        return deepcopy(paper)

    updated = update_json("papers.json", change)
    audit("paper.restored", actor, ip, {"paper_id": paper_id})
    return _serialize_paper(updated)


def _contains_paper_reference(value, paper_id: str) -> bool:
    if isinstance(value, Mapping):
        if value.get("paper_id") == paper_id:
            return True
        return any(_contains_paper_reference(item, paper_id) for item in value.values())
    if isinstance(value, list):
        return any(_contains_paper_reference(item, paper_id) for item in value)
    return False


def delete_paper(paper_id: str, payload: Mapping, actor: str, ip: str) -> None:
    with transaction():
        papers = read_json("papers.json")
        paper = papers.get(paper_id)
        if not paper:
            raise PaperError("Paper was not found", 404, "PAPER_NOT_FOUND")
        _require_revision(paper, payload)
        referenced = any(
            _contains_paper_reference(read_json(name), paper_id)
            for name in ("exams.json", "assignments.json", "code_exams.json")
        )
        if referenced:
            raise PaperError("Paper is referenced by exam history; archive it instead of deleting", 409, "PAPER_IN_USE")
        del papers[paper_id]
        write_json("papers.json", papers)
    audit("paper.deleted", actor, ip, {"paper_id": paper_id})
