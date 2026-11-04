"""Question bank validation and persistence for code grading."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import json
import re
import uuid
from typing import Mapping

from .grading import GradingError, sum_configured_points
from .storage import audit, read_json, update_json, utc_now
from .windows_job import MIN_JAVA_JOB_MEMORY_MB


class QuestionError(ValueError):
    """A question request is invalid or conflicts with stored data."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
_MAX_SOURCE_BYTES = 1024 * 1024


def _positive_number(value, field: str, *, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise QuestionError(f"{field} must be a finite number")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise QuestionError(f"{field} must be a finite number") from exc
    if not minimum <= number <= maximum:
        raise QuestionError(f"{field} must be between {minimum:g} and {maximum:g}")
    return number


def _validate_question(payload: Mapping, *, question_id: str, actor: str) -> dict:
    if not isinstance(payload, Mapping):
        raise QuestionError("Question must be a JSON object")
    try:
        question = json.loads(json.dumps(dict(payload), ensure_ascii=False, allow_nan=False))
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise QuestionError("Question must contain valid JSON values") from exc

    title = question.get("title")
    statement = question.get("statement", "")
    if not isinstance(title, str) or not title.strip() or len(title) > 200:
        raise QuestionError("title must contain 1 to 200 characters")
    if not isinstance(statement, str) or len(statement) > 100_000:
        raise QuestionError("statement must be a string of at most 100000 characters")

    language = question.get("language")
    grading_mode = question.get("grading_mode")
    if (language, grading_mode) not in {
        ("java", "reflection"),
        ("java", "stdio"),
        ("python", "stdio"),
    }:
        raise QuestionError("language/grading_mode must be java/reflection, java/stdio, or python/stdio")

    starter_code = question.get("starter_code", "")
    if not isinstance(starter_code, str) or len(starter_code.encode("utf-8")) > _MAX_SOURCE_BYTES:
        raise QuestionError("starter_code must be UTF-8 text within the source size limit")

    question["time_limit_seconds"] = _positive_number(
        question.get("time_limit_seconds", 2),
        "time_limit_seconds",
        minimum=0.1,
        maximum=60,
    )
    memory_mb = question.get("memory_limit_mb", 256)
    if isinstance(memory_mb, bool) or not isinstance(memory_mb, int) or not 16 <= memory_mb <= 2048:
        raise QuestionError("memory_limit_mb must be an integer between 16 and 2048")
    if language == "java" and memory_mb < MIN_JAVA_JOB_MEMORY_MB:
        raise QuestionError(
            f"Java memory_limit_mb must be at least {MIN_JAVA_JOB_MEMORY_MB}"
        )
    question["memory_limit_mb"] = memory_mb
    output_limit = question.get("max_output_bytes", 64 * 1024)
    if isinstance(output_limit, bool) or not isinstance(output_limit, int) or not 1024 <= output_limit <= 1024 * 1024:
        raise QuestionError("max_output_bytes must be an integer between 1024 and 1048576")
    question["max_output_bytes"] = output_limit
    question["allow_pretest"] = question.get("allow_pretest", True)
    if not isinstance(question["allow_pretest"], bool):
        raise QuestionError("allow_pretest must be a boolean")
    max_pretest_runs = question.get("max_pretest_runs", 20)
    if isinstance(max_pretest_runs, bool) or not isinstance(max_pretest_runs, int) or not 1 <= max_pretest_runs <= 1000:
        raise QuestionError("max_pretest_runs must be an integer between 1 and 1000")
    question["max_pretest_runs"] = max_pretest_runs

    if grading_mode == "reflection":
        target_class = question.get("target_class")
        target_package = question.get("target_package")
        checks = question.get("checks")
        if not isinstance(target_class, str) or not target_class.strip():
            raise QuestionError("Reflection questions require target_class")
        if not isinstance(target_package, str) or not target_package.strip():
            raise QuestionError("Reflection questions require target_package")
        if not isinstance(checks, list) or not checks:
            raise QuestionError("Reflection questions require a non-empty checks array")
        items, item_name = checks, "check"
        for index, item in enumerate(checks):
            if not isinstance(item, Mapping) or not isinstance(item.get("is_visible"), bool):
                raise QuestionError(f"check at index {index} must be an object with boolean is_visible")
    else:
        tests = question.get("tests")
        if not isinstance(tests, list) or not tests:
            raise QuestionError("STDIO questions require a non-empty tests array")
        items, item_name = tests, "test"
        for index, item in enumerate(tests):
            if not isinstance(item, Mapping) or not isinstance(item.get("is_visible"), bool):
                raise QuestionError(f"test at index {index} must be an object with boolean is_visible")
        if language == "java":
            if not isinstance(question.get("target_class"), str) or not question["target_class"].strip():
                raise QuestionError("Java STDIO questions require target_class")
        else:
            question.setdefault("target_file", "solution.py")

    try:
        configured_total = sum_configured_points(items, item_name=item_name)
        declared = Decimal(str(question.get("total_points")))
    except (GradingError, InvalidOperation, TypeError, ValueError) as exc:
        raise QuestionError(str(exc)) from exc
    if not declared.is_finite() or declared < 0 or declared != configured_total:
        raise QuestionError("total_points must equal the sum of configured check/test points")

    question.update(
        {
            "id": question_id,
            "status": "draft",
            "source": {
                "created_by": actor,
                "created_at": utc_now(),
                "updated_at": utc_now(),
            },
            "usage_count": 0,
            "version": 1,
        }
    )
    return question


def create_question(payload: Mapping, actor: str, ip: str) -> dict:
    requested_id = payload.get("id") if isinstance(payload, Mapping) else None
    question_id = requested_id or uuid.uuid4().hex
    if not isinstance(question_id, str) or not _ID_PATTERN.fullmatch(question_id):
        raise QuestionError("id may contain only letters, digits, underscore, and hyphen")
    question = _validate_question(payload, question_id=question_id, actor=actor)

    def insert(questions):
        if question_id in questions:
            raise QuestionError("question id already exists", 409)
        questions[question_id] = question

    update_json("questions.json", insert)
    audit("code.question_created", actor, ip, {"question_id": question_id, "language": question["language"], "grading_mode": question["grading_mode"]})
    return question


def get_question(question_id: str) -> dict | None:
    return read_json("questions.json").get(question_id)


def list_questions() -> list[dict]:
    return list(read_json("questions.json").values())


def update_question(question_id: str, payload: Mapping, actor: str, ip: str) -> dict:
    current = get_question(question_id)
    if not current:
        raise QuestionError("question not found", 404)
    if current.get("status") == "archived":
        raise QuestionError("archived questions cannot be edited", 409)

    updated = _validate_question(payload, question_id=question_id, actor=actor)
    updated.update(
        {
            "status": current.get("status", "draft"),
            "source": {
                **current.get("source", {}),
                "updated_by": actor,
                "updated_at": utc_now(),
            },
            "usage_count": current.get("usage_count", 0),
            "version": int(current.get("version", 1)) + 1,
        }
    )
    save_question(updated)
    audit("code.question_updated", actor, ip, {"question_id": question_id, "version": updated["version"]})
    return updated


def duplicate_question(question_id: str, actor: str, ip: str) -> dict:
    question = get_question(question_id)
    if not question:
        raise QuestionError("question not found", 404)
    duplicate = {
        key: value
        for key, value in question.items()
        if key not in {"id", "status", "source", "usage_count", "version"}
    }
    return create_question(duplicate, actor, ip)


def archive_question(question_id: str, actor: str, ip: str) -> dict:
    question = get_question(question_id)
    if not question:
        raise QuestionError("question not found", 404)
    if question.get("status") == "archived":
        return question
    question["status"] = "archived"
    question.setdefault("source", {}).update(
        {"updated_by": actor, "updated_at": utc_now()}
    )
    save_question(question)
    audit("code.question_archived", actor, ip, {"question_id": question_id})
    return question


def delete_question(question_id: str, actor: str, ip: str) -> None:
    question = get_question(question_id)
    if not question:
        raise QuestionError("question not found", 404)
    code_exam_used = any(
        any(item.get("question_id") == question_id for item in exam.get("questions", []))
        for exam in read_json("code_exams.json").values()
    )
    submission_used = any(
        item.get("question_id") == question_id
        for records in read_json("code_submissions.json").values()
        for item in records
    )
    run_used = any(
        item.get("question_id") == question_id
        for item in read_json("code_runs.json", [])
    )
    if code_exam_used or submission_used or run_used:
        raise QuestionError("question is in use; archive it instead of deleting", 409)

    def remove(questions):
        if question_id not in questions:
            raise QuestionError("question not found", 404)
        del questions[question_id]

    update_json("questions.json", remove)
    audit("code.question_deleted", actor, ip, {"question_id": question_id})


def save_question(question: dict) -> None:
    def replace_question(questions):
        if question["id"] not in questions:
            raise QuestionError("question not found", 404)
        questions[question["id"]] = question

    update_json("questions.json", replace_question)
