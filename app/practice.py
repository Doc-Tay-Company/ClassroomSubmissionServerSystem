"""Student Practice Question Library core logic and safe public projections."""
from __future__ import annotations

import hashlib
import json
import math
import re
import threading
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

from .config import BASE_DIR
from .exams import is_active_exam_attempt
from .storage import read_json, transaction, update_json, utc_now

_PRACTICE_WORKSPACE_PARENT = BASE_DIR / ".practice-run-workspaces"


class PracticeError(ValueError):
    """Practice request is invalid or refers to unavailable practice data."""

    def __init__(self, message: str, status: int = 400, code: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code


def require_practice_access(student_id: str) -> None:
    """Caller holds transaction() through admission/mutation, never through execution."""
    if is_active_exam_attempt(student_id):
        raise PracticeError("Bạn đang tham gia một kỳ thi chính thức. Practice tạm thời bị khóa.", 403, "PRACTICE_LOCKED")


def is_valid_revision(revision: Any) -> bool:
    """Return True if revision is a valid 32-char hexadecimal UUID string."""
    if not isinstance(revision, str) or len(revision) != 32:
        return False
    try:
        int(revision, 16)
        return True
    except ValueError:
        return False


def is_practice_eligible(question: Mapping | None) -> bool:
    """A question is eligible for student practice iff published, enabled, and has a valid revision."""
    if not isinstance(question, Mapping):
        return False
    if question.get("status") != "published":
        return False
    if question.get("practice_enabled") is not True:
        return False
    return is_valid_revision(question.get("practice_revision"))


def practice_public_projection(question: Mapping) -> dict:
    """Project a question safely for student practice.

    Strict allowlist: only student-facing metadata and visible test cases are exposed.
    Private fields (reference_source, sample_source, validation, hidden checks/tests,
    source, usage_count, and any unknown fields) are excluded unconditionally.
    """
    if not is_practice_eligible(question):
        raise PracticeError("Câu hỏi không khả dụng cho luyện tập.", 404, "PRACTICE_NOT_ELIGIBLE")

    qid = str(question.get("id") or question.get("question_id") or "")
    grading_mode = str(question.get("grading_mode", "stdio"))

    result: dict[str, Any] = {
        "question_id": qid,
        "title": str(question.get("title", "")),
        "statement": str(question.get("statement", "")),
        "language": str(question.get("language", "")),
        "grading_mode": grading_mode,
        "category": str(question.get("category", "")),
        "tags": [str(t) for t in question.get("tags", []) if isinstance(t, str)],
        "difficulty": str(question.get("difficulty", "")),
        "starter_code": str(question.get("starter_code", "")),
        "time_limit_seconds": float(question.get("time_limit_seconds", 5.0)),
        "memory_limit_mb": float(question.get("memory_limit_mb", 256.0)),
        "max_output_bytes": int(question.get("max_output_bytes", 65536)),
        "version": int(question.get("version", 1)),
        "practice_revision": str(question.get("practice_revision")),
    }

    for key in ("target_class", "target_package", "target_file"):
        if key in question and question[key] is not None:
            result[key] = str(question[key])

    if grading_mode == "reflection":
        raw_checks = question.get("checks", [])
        visible_checks = []
        if isinstance(raw_checks, list):
            for item in raw_checks:
                if isinstance(item, Mapping) and item.get("is_visible") is True:
                    check_proj = {
                        "id": str(item.get("id", "")),
                        "name": str(item.get("name", "")),
                        "description": str(item.get("description", "")),
                        "points": float(item.get("points", 0)),
                        "is_visible": True,
                    }
                    visible_checks.append(check_proj)
        result["checks"] = visible_checks
        result["visible_points"] = sum(c["points"] for c in visible_checks)
    else:
        raw_tests = question.get("tests", [])
        visible_tests = []
        if isinstance(raw_tests, list):
            for item in raw_tests:
                if isinstance(item, Mapping) and item.get("is_visible") is True:
                    stdin_val = str(item.get("stdin", item.get("input", "")))
                    stdout_val = str(item.get("expected_stdout", item.get("expected_output", "")))
                    test_proj = {
                        "id": str(item.get("id", "")),
                        "name": str(item.get("name", "")),
                        "stdin": stdin_val,
                        "expected_stdout": stdout_val,
                        "input": stdin_val,
                        "expected_output": stdout_val,
                        "points": float(item.get("points", 0)),
                        "is_visible": True,
                    }
                    visible_tests.append(test_proj)
        result["tests"] = visible_tests
        result["visible_points"] = sum(t["points"] for t in visible_tests)

    return result


def get_practice_catalog(questions_data: Mapping[str, Mapping] | None = None) -> list[dict]:
    """Return compact metadata for all practice-eligible questions."""
    data = read_json("questions.json") if questions_data is None else questions_data
    if not isinstance(data, Mapping):
        return []

    eligible = []
    for qid, q in data.items():
        if isinstance(q, Mapping) and is_practice_eligible(q):
            eligible.append({
                "question_id": str(q.get("id") or qid),
                "title": str(q.get("title", "")),
                "language": str(q.get("language", "")),
                "grading_mode": str(q.get("grading_mode", "")),
                "difficulty": str(q.get("difficulty", "")),
                "category": str(q.get("category", "")),
                "version": int(q.get("version", 1)),
                "practice_revision": str(q.get("practice_revision")),
            })

    eligible.sort(key=lambda item: (item["title"].lower(), item["question_id"]))
    return eligible


def compute_catalog_token(questions_data: Mapping[str, Mapping] | None = None) -> str:
    """Compute SHA-256 digest of sorted (question_id, practice_revision) pairs for all eligible questions."""
    data = read_json("questions.json") if questions_data is None else questions_data
    if not isinstance(data, Mapping):
        pairs: list[list[str]] = []
    else:
        pairs = sorted([
            [str(q.get("id") or qid), str(q.get("practice_revision"))]
            for qid, q in data.items()
            if isinstance(q, Mapping) and is_practice_eligible(q)
        ])
    canonical = json.dumps(pairs, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Phase 2 Checkpoint 1 — Current Progress Contract
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# In-memory active-run registry (process-local, no JSON writes for in-flight)
# ---------------------------------------------------------------------------
_ACTIVE_RUNS_LOCK = threading.Lock()
_ACTIVE_RUNS: dict[tuple[str, str], dict] = {}  # (student_id, question_id) -> entry


def get_active_run(student_id: str, question_id: str) -> dict | None:
    """Return the active-run entry for (student_id, question_id) or None."""
    with _ACTIVE_RUNS_LOCK:
        return dict(_ACTIVE_RUNS[(student_id, question_id)]) if (student_id, question_id) in _ACTIVE_RUNS else None


def reserve_active_run(
    student_id: str,
    question_id: str,
    attempt_id: str,
    practice_revision: str,
    run_sequence: int,
) -> bool:
    """Atomically reserve an active-run slot.  Returns False if already occupied."""
    with _ACTIVE_RUNS_LOCK:
        key = (student_id, question_id)
        if key in _ACTIVE_RUNS:
            return False
        _ACTIVE_RUNS[key] = {
            "attempt_id": attempt_id,
            "practice_revision": practice_revision,
            "run_sequence": run_sequence,
        }
        return True


def release_active_run(student_id: str, question_id: str) -> None:
    """Release the active-run slot (safe to call even when not reserved)."""
    with _ACTIVE_RUNS_LOCK:
        _ACTIVE_RUNS.pop((student_id, question_id), None)


# ---------------------------------------------------------------------------
# Progress schema helpers
# ---------------------------------------------------------------------------

def _empty_progress_record(attempt_id: str, practice_revision: str) -> dict:
    return {
        "practice_revision": practice_revision,
        "attempt_id": attempt_id,
        "last_run_sequence": 0,
        "has_result": False,
        "earned_visible_points": None,
        "maximum_visible_points": None,
        "practice_percentage": None,
        "score_available": False,
        "result_summary": [],
        "run_diagnostic": None,
        "updated_at": utc_now(),
    }


def compute_practice_percentage(earned: Any, maximum: Any) -> float | None:
    """Return float percentage (0–100) or None if not scoreable."""
    if not isinstance(maximum, (int, float)) or maximum <= 0:
        return None
    if not isinstance(earned, (int, float)):
        return None
    return round((earned / maximum) * 100, 2)


def classify_practice_percentage(percentage: float | None) -> str | None:
    """Classify practice percentage according to Owner-approved color rules:
    - 100%: 'green'
    - > 50% and < 100%: 'orange'
    - Exactly 50%: 'orange' (Owner-approved: 50% is light orange)
    - < 50%: 'red'
    - None (or invalid denominator): None (no color, unscored)
    """
    if percentage is None:
        return None
    if percentage >= 100.0:
        return "green"
    if percentage >= 50.0:
        return "orange"
    return "red"


_FEEDBACK_PATH = re.compile(r'(?:[A-Za-z]:[\\/]|/|\\\\)[^\s:<>"|]+')
_RELATIVE_FILE_PATH = re.compile(
    r'(?<![\w])(?:[\w.-]+[\\/])+[\w.-]+\.(?:py|java|class)(?::\d+)?',
    re.IGNORECASE,
)
_TRACEBACK_HEADER = re.compile(r"(?m)^\s*Traceback \(most recent call last\):\s*$")
_PYTHON_FRAME = re.compile(r'(?m)^\s*File "[^"]+", line \d+.*$')
_JAVA_FRAME = re.compile(r"(?m)^\s*at [\w.$<>]+\([^\r\n)]*\)\s*$")
_FEEDBACK_OUTPUT_MAX_BYTES = 8192
_FEEDBACK_DIAGNOSTIC_MAX_BYTES = 2048


def _safe_feedback_text(value: Any, max_bytes: int, *, diagnostic: bool = False) -> str | None:
    """Bound student feedback and redact host paths/stack frames before exposure."""
    if not isinstance(value, str):
        return None
    text = _FEEDBACK_PATH.sub("[path]", value)
    text = _RELATIVE_FILE_PATH.sub("[path]", text)
    if diagnostic:
        text = _TRACEBACK_HEADER.sub("", text)
        text = _PYTHON_FRAME.sub("", text)
        text = _JAVA_FRAME.sub("", text)
        text = "\n".join(line for line in text.splitlines() if line.strip())
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) > max_bytes:
        text = encoded[:max_bytes].decode("utf-8", errors="ignore") + "…"
    return text


def _feedback_value(value: Any) -> str | None:
    """Render safe JSON-shaped Reflection values as bounded display text."""
    if isinstance(value, str):
        text = value
    elif value is None or isinstance(value, (bool, int, float, list, dict)):
        try:
            text = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        except (TypeError, ValueError):
            return None
    else:
        return None
    return _safe_feedback_text(text, _FEEDBACK_OUTPUT_MAX_BYTES)


def _visible_result_ids(question: Mapping | None) -> set[str]:
    if not isinstance(question, Mapping):
        return set()
    field = "checks" if question.get("grading_mode") == "reflection" else "tests"
    items = question.get(field)
    if not isinstance(items, list):
        return set()
    return {
        item["id"] for item in items
        if isinstance(item, Mapping)
        and item.get("is_visible") is True
        and isinstance(item.get("id"), str)
    }


def _safe_progress_summary(record: dict, visible_result_ids: set[str]) -> dict:
    """Strip internal fields for the client-facing progress projection."""
    raw_results = record.get("result_summary")
    safe_results = []
    if isinstance(raw_results, list):
        for raw in raw_results:
            if not isinstance(raw, Mapping):
                continue
            result_id = raw.get("id")
            verdict = raw.get("verdict")
            passed = raw.get("passed")
            if (
                not isinstance(result_id, str)
                or not result_id
                or len(result_id) > 200
                or not isinstance(verdict, str)
                or verdict not in {"AC", "WA", "CE", "TLE", "MLE", "RE", "OLE"}
                or not isinstance(passed, bool)
                or result_id not in visible_result_ids
            ):
                continue
            safe_row = {"id": result_id, "verdict": verdict, "passed": passed}
            points_max = raw.get("points")
            if points_max is not None:
                if isinstance(points_max, bool) or not isinstance(points_max, (int, float)) or not math.isfinite(points_max) or points_max < 0:
                    continue
                safe_row["points"] = points_max
            points = raw.get("points_earned")
            if points is not None:
                if (
                    isinstance(points, bool)
                    or not isinstance(points, (int, float))
                    or not math.isfinite(points)
                    or points < 0
                ):
                    continue
                safe_row["points_earned"] = points
            for field in ("expected_output", "actual_output", "expected", "actual"):
                text = _safe_feedback_text(raw.get(field), _FEEDBACK_OUTPUT_MAX_BYTES)
                if text is not None:
                    safe_row[field] = text
            diagnostic = _safe_feedback_text(
                raw.get("diagnostic"), _FEEDBACK_DIAGNOSTIC_MAX_BYTES, diagnostic=True
            )
            if diagnostic:
                safe_row["diagnostic"] = diagnostic
            safe_results.append(safe_row)
    run_diagnostic = _safe_feedback_text(
        record.get("run_diagnostic"), _FEEDBACK_DIAGNOSTIC_MAX_BYTES, diagnostic=True
    )
    return {
        "practice_revision": record.get("practice_revision"),
        "attempt_id": record.get("attempt_id"),
        "has_result": bool(record.get("has_result")),
        "earned_visible_points": record.get("earned_visible_points"),
        "maximum_visible_points": record.get("maximum_visible_points"),
        "practice_percentage": record.get("practice_percentage"),
        "score_available": bool(record.get("score_available")),
        "result_summary": safe_results,
        "run_diagnostic": run_diagnostic,
        "updated_at": record.get("updated_at"),
    }


# ---------------------------------------------------------------------------
# Progress CRUD helpers
# ---------------------------------------------------------------------------

def get_student_progress(student_id: str) -> dict[str, dict]:
    """Return this student's progress dict keyed by question_id (deep copy)."""
    all_progress = read_json("practice_progress.json")
    student_data = all_progress.get(student_id, {})
    if not isinstance(student_data, dict):
        return {}
    return dict(student_data)


def get_progress_with_availability(
    student_id: str,
    questions_data: Mapping[str, Mapping] | None = None,
) -> list[dict]:
    """Return the caller's current progress union with the eligible catalog.

    Each item contains:
      - question_id, title, language, grading_mode, difficulty, category, version,
        practice_revision — from the Question Bank (available) or progress snapshot
      - available: True if currently eligible
      - progress: safe result summary or None if no attempt
    """
    data = read_json("questions.json") if questions_data is None else questions_data
    student_progress = get_student_progress(student_id)

    # Build a lookup of eligible questions
    eligible: dict[str, dict] = {}
    if isinstance(data, Mapping):
        for qid, q in data.items():
            if isinstance(q, Mapping) and is_practice_eligible(q):
                eligible[str(q.get("id") or qid)] = q

    result: list[dict] = []
    seen: set[str] = set()

    # 1. All eligible catalog questions (available=True)
    for qid, q in eligible.items():
        seen.add(qid)
        progress_record = student_progress.get(qid)
        result.append({
            "question_id": qid,
            "title": str(q.get("title", "")),
            "language": str(q.get("language", "")),
            "grading_mode": str(q.get("grading_mode", "")),
            "difficulty": str(q.get("difficulty", "")),
            "category": str(q.get("category", "")),
            "version": int(q.get("version", 1)),
            "practice_revision": str(q.get("practice_revision")),
            "available": True,
            "progress": _safe_progress_summary(progress_record, _visible_result_ids(q)) if progress_record else None,
        })

    # 2. Progress entries whose question is now unavailable (available=False)
    for qid, progress_record in student_progress.items():
        if qid in seen:
            continue
        # Question no longer eligible — expose safe display info only
        # Try to get minimal display data from bank (may be archived/draft/deleted)
        bank_q = data.get(qid) if isinstance(data, Mapping) else None
        result.append({
            "question_id": qid,
            "title": str(bank_q.get("title", "")) if isinstance(bank_q, Mapping) else "",
            "language": str(bank_q.get("language", "")) if isinstance(bank_q, Mapping) else "",
            "grading_mode": str(bank_q.get("grading_mode", "")) if isinstance(bank_q, Mapping) else "",
            "difficulty": str(bank_q.get("difficulty", "")) if isinstance(bank_q, Mapping) else "",
            "category": str(bank_q.get("category", "")) if isinstance(bank_q, Mapping) else "",
            "version": int(bank_q.get("version", 1)) if isinstance(bank_q, Mapping) else 0,
            "practice_revision": str(progress_record.get("practice_revision", "")),
            "available": False,
            "progress": _safe_progress_summary(progress_record, _visible_result_ids(bank_q)),
        })

    result.sort(key=lambda item: (item["title"].lower(), item["question_id"]))
    return result


def delete_student_question_progress(student_id: str, question_id: str) -> None:
    """Atomically remove one Student–Question progress record. 404 if absent."""
    def _mutate(all_progress: dict) -> None:
        student_dict = all_progress.get(student_id, {})
        if question_id not in student_dict:
            raise PracticeError("Progress record not found.", 404, "PROGRESS_NOT_FOUND")
        del student_dict[question_id]
        if student_dict:
            all_progress[student_id] = student_dict
        else:
            all_progress.pop(student_id, None)

    with transaction():
        require_practice_access(student_id)
        update_json("practice_progress.json", _mutate)


def update_question_progress(
    student_id: str,
    question_id: str,
    expected_attempt_id: Any,
    old_practice_revision: Any,
    new_practice_revision: Any,
) -> None:
    """Advance revision and invalidate the old score under the shared storage lock."""
    if not is_valid_revision(new_practice_revision):
        raise PracticeError("new_practice_revision must be a 32-character hexadecimal ID", 422, "INVALID_REVISION")

    with transaction():
        require_practice_access(student_id)
        data = read_json("questions.json")
        q = data.get(question_id) if isinstance(data, Mapping) else None
        if not is_practice_eligible(q):
            raise PracticeError("Question is not currently available for practice.", 404, "PRACTICE_NOT_ELIGIBLE")
        current_revision = str(q.get("practice_revision"))
        if current_revision != new_practice_revision:
            raise PracticeError(
                "new_practice_revision does not match the current Question Bank revision.",
                409,
                "REVISION_MISMATCH",
            )

        def _mutate(all_progress: dict) -> None:
            student_dict = all_progress.get(student_id, {})
            existing = student_dict.get(question_id)
            if existing is None:
                raise PracticeError("Progress record not found.", 404, "PROGRESS_NOT_FOUND")
            if existing.get("attempt_id") != expected_attempt_id:
                raise PracticeError("attempt_id is stale.", 409, "PROGRESS_STALE")
            if existing.get("practice_revision") != old_practice_revision:
                raise PracticeError("practice_revision is stale.", 409, "PROGRESS_STALE")
            student_dict[question_id] = _empty_progress_record(str(existing["attempt_id"]), current_revision)
            all_progress[student_id] = student_dict

        update_json("practice_progress.json", _mutate)


def run_practice(student_id: str, payload: Mapping) -> dict:
    """Run only the current eligible question's public tests for one attempt.

    Source/specification are never persisted. Progress changes only after the
    runner returns a structurally valid student outcome and the attempt/revision
    still match the current Question Bank state.
    """
    from .code_exams import (
        MAX_SOURCE_BYTES,
        _RUN_SLOTS,
        _validate_source,
        execute_question,
    )
    from .grading import GradingError, grade_reflection, grade_stdio, sum_configured_points

    if not isinstance(payload, Mapping):
        raise PracticeError("Request body must be an object.", 422, "INVALID_REQUEST")
    question_id = payload.get("question_id")
    revision = payload.get("expected_practice_revision")
    attempt_id = payload.get("attempt_id")
    source_code = payload.get("source_code")
    if not isinstance(question_id, str) or not question_id or len(question_id) > 200:
        raise PracticeError("question_id is required.", 422, "INVALID_REQUEST")
    if not is_valid_revision(revision):
        raise PracticeError("expected_practice_revision is invalid.", 422, "INVALID_REVISION")
    if not is_valid_revision(attempt_id):
        raise PracticeError("A current attempt is required. Edit the code before the first Run Test.", 409, "ATTEMPT_REQUIRED")
    if not isinstance(source_code, str):
        raise PracticeError("source_code must be a string.", 422, "INVALID_SOURCE")
    try:
        source_size = len(source_code.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise PracticeError("source_code must be valid UTF-8 text.", 422, "INVALID_SOURCE") from exc
    if source_size == 0:
        raise PracticeError("source_code must not be empty.", 422, "INVALID_SOURCE")
    if source_size > MAX_SOURCE_BYTES:
        raise PracticeError("source_code exceeds the 1 MiB limit.", 413, "SOURCE_TOO_LARGE")
    try:
        _validate_source(source_code)
    except Exception as exc:
        raise PracticeError("source_code is invalid.", 422, "INVALID_SOURCE") from exc

    if not _RUN_SLOTS.acquire(blocking=False):
        raise PracticeError("Code execution is busy. Try again shortly.", 429, "RUNNER_BUSY")

    reserved = False
    question = None
    run_sequence = None
    try:
        with transaction():
            require_practice_access(student_id)
            questions = read_json("questions.json")
            question = questions.get(question_id) if isinstance(questions, Mapping) else None
            if not is_practice_eligible(question):
                raise PracticeError("Question is not currently available for practice.", 404, "PRACTICE_NOT_ELIGIBLE")
            current_revision = str(question.get("practice_revision"))
            if current_revision != revision:
                raise PracticeError("Question has changed. Update it before running.", 409, "REVISION_MISMATCH")

            def admit(all_progress: dict) -> None:
                nonlocal reserved, run_sequence
                if not isinstance(all_progress, dict):
                    raise PracticeError("Practice progress storage is invalid.", 503, "PROGRESS_STORAGE_INVALID")
                student_progress = all_progress.get(student_id)
                if student_progress is None:
                    student_progress = {}
                if not isinstance(student_progress, dict):
                    raise PracticeError("Practice progress storage is invalid.", 503, "PROGRESS_STORAGE_INVALID")
                current = student_progress.get(question_id)
                if current is None:
                    current = _empty_progress_record(attempt_id, current_revision)
                    current_sequence = 0
                else:
                    if not isinstance(current, Mapping):
                        raise PracticeError("Practice progress record is invalid.", 503, "PROGRESS_STORAGE_INVALID")
                    if current.get("attempt_id") != attempt_id:
                        raise PracticeError("This tab has a stale attempt. Refresh the Library before running.", 409, "PROGRESS_STALE")
                    if current.get("practice_revision") != current_revision:
                        raise PracticeError("Update this question before running.", 409, "PROGRESS_STALE")
                    current_sequence = current.get("last_run_sequence", 0)
                    if isinstance(current_sequence, bool) or not isinstance(current_sequence, int) or current_sequence < 0:
                        raise PracticeError("Practice progress sequence is invalid.", 503, "PROGRESS_STORAGE_INVALID")
                run_sequence = current_sequence + 1
                if not reserve_active_run(student_id, question_id, attempt_id, current_revision, run_sequence):
                    raise PracticeError("A Practice Run is already active for this question.", 409, "RUN_ALREADY_ACTIVE")
                reserved = True
                if question_id not in student_progress:
                    student_progress[question_id] = current
                    all_progress[student_id] = student_progress

            update_json("practice_progress.json", admit)
            question = deepcopy(question)

        try:
            execution = execute_question(
                question,
                source_code,
                visible_only=True,
                workspace_parent=_PRACTICE_WORKSPACE_PARENT,
            )
        except Exception as exc:
            raise PracticeError("The execution service failed. Your previous Practice result was retained.", 503, "JUDGE_INFRA_ERROR") from exc
        if not isinstance(execution, Mapping):
            raise PracticeError("The execution service returned an invalid result. Your previous Practice result was retained.", 503, "PROTOCOL_ERROR")

        verdict = execution.get("verdict")
        infrastructure = {"INVALID_REQUEST", "JDK_NOT_FOUND", "JUDGE_INFRA_ERROR", "PROTOCOL_ERROR"}
        student_verdicts = {"AC", "WA", "CE", "TLE", "MLE", "RE", "OLE"}
        error_category = execution.get("error_category")
        if error_category is not None and (not isinstance(error_category, str) or error_category not in infrastructure):
            raise PracticeError("The execution service returned an invalid result. Your previous Practice result was retained.", 503, "PROTOCOL_ERROR")
        if error_category in infrastructure or (isinstance(verdict, str) and verdict in infrastructure):
            raise PracticeError("The execution service failed. Your previous Practice result was retained.", 503, str(error_category or verdict))
        if not isinstance(verdict, str) or verdict not in student_verdicts:
            raise PracticeError("The execution service returned an invalid result. Your previous Practice result was retained.", 503, "PROTOCOL_ERROR")

        reflection = question.get("grading_mode") == "reflection"
        field = "checks" if reflection else "tests"
        configured_items = question.get(field)
        if not isinstance(configured_items, list):
            raise PracticeError("The question specification is invalid. Your previous Practice result was retained.", 503, "QUESTION_SPEC_INVALID")
        public_items = [item for item in configured_items if isinstance(item, Mapping) and item.get("is_visible") is True]
        maximum = sum_configured_points(public_items, item_name="check" if reflection else "test")
        try:
            result_key = "checks" if reflection else "tests"
            raw_rows = execution.get(result_key)
            if not isinstance(raw_rows, list):
                raise GradingError("Runner result rows are missing", "PROTOCOL_ERROR")
            visible_ids = {item.get("id") for item in public_items}
            visible_rows = [row for row in raw_rows if isinstance(row, Mapping) and row.get("id") in visible_ids]
            grading_execution = dict(execution)
            grading_execution[result_key] = visible_rows
            score = (
                grade_reflection(public_items, grading_execution, maximum, verdict=verdict)
                if reflection
                else grade_stdio(public_items, visible_rows, maximum, verdict=verdict)
            )
        except (GradingError, ValueError, TypeError) as exc:
            category = getattr(exc, "category", "PROTOCOL_ERROR")
            raise PracticeError("The execution service returned an invalid result. Your previous Practice result was retained.", 503, category) from exc

        percentage = compute_practice_percentage(score.score, score.total_points)
        score_available = percentage is not None
        raw_rows_by_id = {
            row.get("id"): row for row in visible_rows
            if isinstance(row, Mapping) and isinstance(row.get("id"), str)
        }
        specs_by_id = {
            item.get("id"): item for item in public_items
            if isinstance(item.get("id"), str)
        }
        compile_result = execution.get("compile_result")
        diagnostic_candidates = []
        if verdict == "CE" and isinstance(compile_result, Mapping):
            diagnostic_candidates.extend((compile_result.get("stderr"), compile_result.get("stdout"), compile_result.get("error")))
        diagnostic_candidates.append(execution.get("error"))
        run_diagnostic = next((
            safe for candidate in diagnostic_candidates
            if (safe := _safe_feedback_text(candidate, _FEEDBACK_DIAGNOSTIC_MAX_BYTES, diagnostic=True))
        ), None)
        results = []
        for row in score.results:
            passed = row.get("passed") is True
            row_verdict = verdict if verdict in {"CE", "TLE", "MLE", "RE", "OLE"} else ("AC" if passed else "WA")
            spec = specs_by_id[row["id"]]
            raw = raw_rows_by_id.get(row["id"], {})
            safe_row = {
                "id": row["id"],
                "verdict": row_verdict,
                "passed": passed,
                "points": spec.get("points"),
                "points_earned": row["points_earned"],
            }
            if reflection:
                for field in ("expected", "actual"):
                    text = _feedback_value(row.get(field))
                    if text is not None:
                        safe_row[field] = text
                diagnostic_source = row.get("error")
            else:
                expected = spec.get("expected_stdout", spec.get("expected_output"))
                actual = raw.get("actual_stdout")
                if isinstance(expected, str):
                    safe_row["expected_output"] = _safe_feedback_text(expected, _FEEDBACK_OUTPUT_MAX_BYTES)
                if isinstance(actual, str):
                    safe_row["actual_output"] = _safe_feedback_text(actual, _FEEDBACK_OUTPUT_MAX_BYTES)
                diagnostic_source = raw.get("error") or raw.get("stderr")
            diagnostic = _safe_feedback_text(
                diagnostic_source, _FEEDBACK_DIAGNOSTIC_MAX_BYTES, diagnostic=True
            ) or run_diagnostic
            if diagnostic:
                safe_row["diagnostic"] = diagnostic
            results.append(safe_row)

        def commit(all_progress: dict) -> None:
            if not isinstance(all_progress, dict):
                raise PracticeError("Practice progress storage is invalid.", 503, "PROGRESS_STORAGE_INVALID")
            current_questions = read_json("questions.json")
            live_question = current_questions.get(question_id) if isinstance(current_questions, Mapping) else None
            if not is_practice_eligible(live_question):
                raise PracticeError("Question is no longer available. The result was not saved.", 404, "PRACTICE_NOT_ELIGIBLE")
            if live_question.get("practice_revision") != current_revision:
                raise PracticeError("Question changed during execution. The result was not saved.", 409, "REVISION_MISMATCH")
            student_progress = all_progress.get(student_id)
            current = student_progress.get(question_id) if isinstance(student_progress, dict) else None
            if not isinstance(current, dict) or current.get("attempt_id") != attempt_id or current.get("practice_revision") != current_revision:
                raise PracticeError("Attempt changed during execution. The result was not saved.", 409, "PROGRESS_STALE")
            if current.get("last_run_sequence", 0) >= run_sequence:
                raise PracticeError("A newer Practice result already exists.", 409, "RUN_STALE")
            current.update({
                "last_run_sequence": run_sequence,
                "has_result": True,
                "earned_visible_points": score.score,
                "maximum_visible_points": score.total_points,
                "practice_percentage": percentage,
                "score_available": score_available,
                "result_summary": results,
                "run_diagnostic": run_diagnostic,
                "updated_at": utc_now(),
            })

        with transaction():
            update_json("practice_progress.json", commit)

        return {
            "ok": True,
            "question_id": question_id,
            "practice_revision": current_revision,
            "attempt_id": attempt_id,
            "run_sequence": run_sequence,
            "completed": True,
            "verdict": verdict,
            "earned_visible_points": score.score,
            "maximum_visible_points": score.total_points,
            "practice_percentage": percentage,
            "score_available": score_available,
            "results": results,
            "run_diagnostic": run_diagnostic,
        }
    finally:
        if reserved:
            release_active_run(student_id, question_id)
        _RUN_SLOTS.release()
