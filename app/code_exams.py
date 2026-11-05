"""Code-exam snapshots, lifecycle checks, execution, and result persistence."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
import threading
import time
import uuid
from typing import Mapping

from .code_runner import run_stdio
from .grading import GradingError, grade_exam, grade_reflection, grade_stdio
from .java_runner import run_reflection_judge
from .questions import QuestionError, _validate_question, compute_spec_hash, get_question
from .storage import audit, read_json, update_json, utc_now
from .windows_job import DEFAULT_JOB_LIMITS, MIN_JAVA_JOB_MEMORY_MB, JobLimits


class CodeExamError(ValueError):
    """A code-exam action is invalid or blocked by the current lifecycle."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


MAX_SOURCE_BYTES = 1024 * 1024
MAX_PRETEST_HISTORY = 10_000
try:
    MAX_CONCURRENT_RUNS = max(1, min(16, int(os.getenv("CSS_MAX_CONCURRENT_CODE_RUNS", "2"))))
except ValueError:
    MAX_CONCURRENT_RUNS = 2
_RUN_SLOTS = threading.BoundedSemaphore(MAX_CONCURRENT_RUNS)


def _decimal(value, field: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CodeExamError(f"{field} must be a finite non-negative number")
    try:
        number = Decimal(str(value))
    except Exception as exc:
        raise CodeExamError(f"{field} must be a finite non-negative number") from exc
    if not number.is_finite() or number < 0:
        raise CodeExamError(f"{field} must be a finite non-negative number")
    return number


def _positive_int(value, field: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise CodeExamError(f"{field} must be an integer between {minimum} and {maximum}")
    return value


def _validate_code_exam_payload(payload: Mapping) -> tuple[dict, list[dict]]:
    if not isinstance(payload, Mapping):
        raise CodeExamError("Code exam must be a JSON object", 422)

    title = payload.get("title")
    question_ids = payload.get("question_ids")
    if not isinstance(title, str) or not title.strip() or len(title) > 200:
        raise CodeExamError("title must contain 1 to 200 characters", 422)
    if (
        not isinstance(question_ids, list)
        or not question_ids
        or any(not isinstance(value, str) or not value for value in question_ids)
    ):
        raise CodeExamError("question_ids must be a non-empty array of question ids", 422)
    if len(set(question_ids)) != len(question_ids):
        raise CodeExamError("A question may appear only once in a code exam", 422)

    settings = read_json("settings.json")
    policy = payload.get("submission_policy", settings.get("submission_policy", "configurable"))
    if policy not in {"once", "configurable"}:
        raise CodeExamError("submission_policy must be once or configurable", 422)
    max_submissions = _positive_int(
        payload.get("max_submissions", settings.get("max_submissions", 1)),
        "max_submissions",
        1,
        20,
    )
    show_score = payload.get("show_final_score_immediately", False)
    allow_pretest = payload.get("allow_pretest", True)
    if not isinstance(show_score, bool) or not isinstance(allow_pretest, bool):
        raise CodeExamError("show_final_score_immediately and allow_pretest must be booleans", 422)
    cooldown = payload.get("pretest_cooldown_seconds", 2)
    if isinstance(cooldown, bool) or not isinstance(cooldown, (int, float)) or not 0 <= cooldown <= 3600:
        raise CodeExamError("pretest_cooldown_seconds must be between 0 and 3600", 422)
    max_pretest_runs = _positive_int(
        payload.get("max_pretest_runs", 20), "max_pretest_runs", 1, 1000
    )

    snapshots = []
    for order, question_id in enumerate(question_ids):
        question = get_question(question_id)
        if not question:
            raise CodeExamError(f"Question '{question_id}' was not found", 404)
        if question.get("status") != "published":
            raise CodeExamError(f"Question '{question_id}' is not published", 409)
        snapshots.append(
            {
                **_json_copy(question),
                "question_id": question_id,
                "snapshot_version": question.get("version", 1),
                "snapshot_at": utc_now(),
                "order": order,
            }
        )
    try:
        grade_exam(
            [
                {"question_id": item["question_id"], "score": 0, "total_points": item["total_points"]}
                for item in snapshots
            ]
        )
    except (GradingError, KeyError) as exc:
        raise CodeExamError(f"Question snapshots have invalid points: {exc}", 422) from exc

    return (
        {
            "title": title.strip(),
            "show_final_score_immediately": show_score,
            "allow_pretest": allow_pretest,
            "max_pretest_runs": max_pretest_runs,
            "pretest_cooldown_seconds": float(cooldown),
            "submission_policy": policy,
            "max_submissions": max_submissions,
            "questions": snapshots,
        },
        snapshots,
    )


def _json_copy(value):
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise CodeExamError("Request must contain valid JSON values") from exc


def create_code_exam(payload: Mapping, actor: str, ip: str) -> dict:
    exam_data, snapshots = _validate_code_exam_payload(payload)

    exam_id = uuid.uuid4().hex
    now = utc_now()
    exam = {
        "id": exam_id,
        "status": "draft",
        "release_id": None,
        "created_by": actor,
        "created_at": now,
        "updated_at": now,
        **exam_data,
    }

    def insert(exams):
        exams[exam_id] = exam

    update_json("code_exams.json", insert)
    _increment_question_usage(snapshots)
    audit("code.exam_created", actor, ip, {"exam_id": exam_id, "question_count": len(snapshots)})
    return exam


def _increment_question_usage(snapshots: list[dict], *, exclude_question_ids: set[str] | None = None) -> None:
    def record_usage(questions):
        for item in snapshots:
            question = questions.get(item["question_id"])
            if question:
                question["usage_count"] = int(question.get("usage_count", 0)) + 1

    update_json("questions.json", record_usage)


def _update_question_usage_for_exam(exam: dict, snapshots: list[dict]) -> None:
    old_ids = {item["question_id"] for item in exam.get("questions", [])}
    new_ids = {item["question_id"] for item in snapshots}

    def update_usage(questions):
        for question_id in old_ids - new_ids:
            question = questions.get(question_id)
            if question:
                question["usage_count"] = max(0, int(question.get("usage_count", 0)) - 1)
        for question_id in new_ids - old_ids:
            question = questions.get(question_id)
            if question:
                question["usage_count"] = int(question.get("usage_count", 0)) + 1

    update_json("questions.json", update_usage)


def update_draft_code_exam(exam_id: str, payload: Mapping, actor: str, ip: str) -> dict:
    exam = get_code_exam(exam_id)
    if not exam:
        raise CodeExamError("Code exam was not found", 404)
    if exam.get("status") != "draft":
        raise CodeExamError("Only draft code exams can be updated", 409)

    updated_data, snapshots = _validate_code_exam_payload(payload)
    updated = {
        **exam,
        **updated_data,
        "updated_at": utc_now(),
    }

    def replace(exams):
        current = exams.get(exam_id)
        if not current:
            raise CodeExamError("Code exam was not found", 404)
        if current.get("status") != "draft":
            raise CodeExamError("Only draft code exams can be updated", 409)
        exams[exam_id] = updated

    update_json("code_exams.json", replace)
    _update_question_usage_for_exam(exam, snapshots)
    audit(
        "code.exam_updated",
        actor,
        ip,
        {"exam_id": exam_id, "question_ids": [item["question_id"] for item in snapshots]},
    )
    return updated


def list_code_exams() -> list[dict]:
    return list(read_json("code_exams.json").values())


def get_code_exam(exam_id: str) -> dict | None:
    return read_json("code_exams.json").get(exam_id)


def prepare_code_exam_distribution(exam_id: str) -> dict:
    exam = get_code_exam(exam_id)
    if not exam:
        raise CodeExamError("Code exam was not found", 404)
    if exam.get("status") != "draft" or not exam.get("questions"):
        raise CodeExamError("Only a non-empty draft code exam can be distributed", 409)
    return exam


def attach_code_exam_to_release(exam_id: str, release_id: str) -> None:
    def attach(exams):
        exam = exams.get(exam_id)
        if not exam or exam.get("status") != "draft":
            raise CodeExamError("Code exam is no longer available for distribution", 409)
        exam.update({"status": "distributed", "release_id": release_id, "distributed_at": utc_now(), "updated_at": utc_now()})

    update_json("code_exams.json", attach)


def discard_code_exam(exam_id: str | None) -> bool:
    """Remove a never-started code exam snapshot and release its question usage counts."""
    if not exam_id:
        return False
    removed: list[str] = []

    def remove(exams):
        exam = exams.get(exam_id)
        if exam and exam.get("status") in {"draft", "distributed"}:
            removed.extend(question.get("question_id") for question in exam.get("questions", []))
            del exams[exam_id]

    update_json("code_exams.json", remove)
    if not removed:
        return False

    def release_usage(questions):
        for question_id in removed:
            question = questions.get(question_id)
            if question:
                question["usage_count"] = max(0, int(question.get("usage_count", 0)) - 1)

    update_json("questions.json", release_usage)
    return True


def transition_code_exam(release_id: str | None, state: str) -> None:
    if not release_id:
        return

    def transition(exams):
        for exam in exams.values():
            if exam.get("release_id") == release_id:
                if state == "started" and exam.get("status") == "distributed":
                    exam.update({"status": "started", "started_at": utc_now(), "updated_at": utc_now()})
                elif state == "ended" and exam.get("status") in {"distributed", "started"}:
                    exam.update({"status": "ended", "ended_at": utc_now(), "updated_at": utc_now()})

    update_json("code_exams.json", transition)


def _active_context(student_id: str) -> tuple[dict, dict, dict]:
    settings = read_json("settings.json")
    assignments = read_json("assignments.json")
    assignment = assignments.get(student_id)
    if (
        settings.get("exam_state") != "started"
        or not settings.get("exam_released")
        or not assignment
        or assignment.get("release_id") != settings.get("exam_release_id")
    ):
        raise CodeExamError("No active code exam is assigned", 403)
    if assignment.get("status") in {"expired", "ended"}:
        raise CodeExamError("The assigned exam is not accepting code", 403)
    if assignment.get("forced_submit"):
        raise CodeExamError("The assigned exam was force-submitted", 403)
    if not assignment.get("started_at"):
        raise CodeExamError("The assigned exam has not started", 403)
    ends_at = assignment.get("ends_at")
    if not ends_at:
        raise CodeExamError("The assigned exam has no server deadline", 403)
    try:
        deadline = datetime.fromisoformat(ends_at)
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError) as exc:
        raise CodeExamError("The assigned exam deadline is invalid", 503) from exc
    if datetime.now(timezone.utc) >= deadline:
        raise CodeExamError("The server-side exam deadline has passed", 409)

    exam_id = assignment.get("code_exam_id")
    exam = get_code_exam(exam_id) if isinstance(exam_id, str) else None
    if not exam or exam.get("release_id") != assignment.get("release_id") or exam.get("status") != "started":
        raise CodeExamError("No started code exam is attached to this release", 403)
    return settings, assignment, exam


def _question_snapshot(exam: dict, question_id: str) -> dict:
    for question in exam.get("questions", []):
        if question.get("question_id") == question_id:
            return question
    raise CodeExamError("Question is not part of the assigned code exam", 404)


def public_question(question: Mapping) -> dict:
    visible_key = "checks" if question.get("grading_mode") == "reflection" else "tests"
    visible_items = [item for item in question.get(visible_key, []) if item.get("is_visible") is True]
    result = {
        key: question[key]
        for key in (
            "question_id",
            "title",
            "statement",
            "language",
            "grading_mode",
            "category",
            "tags",
            "difficulty",
            "starter_code",
            "time_limit_seconds",
            "memory_limit_mb",
            "max_output_bytes",
            "allow_pretest",
            "target_class",
            "target_package",
            "target_file",
        )
        if key in question
    }
    result[visible_key] = deepcopy(visible_items)
    result["visible_points"] = sum(float(item.get("points", 0)) for item in visible_items)
    result["order"] = question.get("order", 0)
    return result


def get_student_code_exam(student_id: str) -> dict:
    settings = read_json("settings.json")
    assignment = read_json("assignments.json").get(student_id)
    if (
        not assignment
        or not assignment.get("code_exam_id")
        or not assignment.get("started_at")
    ):
        raise CodeExamError("No started code exam is assigned", 403)
    exam = get_code_exam(assignment["code_exam_id"])
    if (
        not exam
        or exam.get("release_id") != assignment.get("release_id")
        or exam.get("status") not in {"started", "ended"}
        or (
            assignment.get("release_id") != settings.get("exam_release_id")
            and not (settings.get("exam_state") == "ended" and exam.get("status") == "ended")
        )
    ):
        raise CodeExamError("No matching code exam is available", 403)

    deadline = assignment.get("ends_at")
    expired = True
    if deadline:
        try:
            parsed_deadline = datetime.fromisoformat(deadline)
            if parsed_deadline.tzinfo is None:
                parsed_deadline = parsed_deadline.replace(tzinfo=timezone.utc)
            expired = datetime.now(timezone.utc) >= parsed_deadline
        except (TypeError, ValueError):
            expired = True
    read_only = (
        settings.get("exam_state") != "started"
        or not settings.get("exam_released")
        or exam.get("status") != "started"
        or assignment.get("status") in {"expired", "ended"}
        or bool(assignment.get("forced_submit"))
        or expired
    )
    reveal = exam.get("show_final_score_immediately", False) or exam.get("status") == "ended"
    student_records = [
        item
        for item in read_json("code_submissions.json").get(student_id, [])
        if item.get("exam_id") == exam["id"] and item.get("release_id") == exam.get("release_id")
    ]
    progress = []
    all_submitted = True
    for question in exam["questions"]:
        records = [item for item in student_records if item.get("question_id") == question["question_id"]]
        latest = records[-1] if records else None
        entry = {
            "question_id": question["question_id"],
            "submitted": latest is not None,
            "submission_count": len(records),
            "status": _public_submission(latest, reveal_score=False)["status"] if latest else "none",
        }
        if latest is None:
            all_submitted = False
        if reveal and latest and latest.get("status") == "graded":
            entry.update({"score": latest.get("score"), "total_points": latest.get("total_points"), "verdict": latest.get("verdict")})
        progress.append(entry)
    result = {
        "exam_id": exam["id"],
        "title": exam["title"],
        "release_id": exam["release_id"],
        "ends_at": assignment["ends_at"],
        "show_final_score_immediately": exam["show_final_score_immediately"],
        "allow_pretest": exam.get("allow_pretest", True),
        "submission_policy": exam.get("submission_policy"),
        "max_submissions": exam.get("max_submissions"),
        "read_only": read_only,
        "total_points": sum(float(item["total_points"]) for item in exam["questions"]),
        "progress": progress,
        "questions": [{**public_question(question), "total_points": question["total_points"]} for question in exam["questions"]],
    }
    if reveal and all_submitted and all("score" in item for item in progress):
        result["exam_score"] = sum(float(item["score"] or 0) for item in progress)
    return result


def _validate_source(source: str) -> str:
    if not isinstance(source, str):
        raise CodeExamError("source_code must be a string")
    try:
        encoded = source.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise CodeExamError("source_code must be valid UTF-8 text") from exc
    if not encoded or len(encoded) > MAX_SOURCE_BYTES:
        raise CodeExamError("source_code must be non-empty and at most 1 MiB")
    return hashlib.sha256(encoded).hexdigest()


def _target_class_name(question: Mapping) -> str:
    target = question.get("target_class", "")
    package = question.get("target_package", "")
    if package and not target.startswith(package + "."):
        return f"{package}.{target}"
    return target


def _job_limits(question: Mapping) -> JobLimits:
    memory_mb = question.get("memory_limit_mb", 256)
    if (
        isinstance(memory_mb, bool)
        or not isinstance(memory_mb, int)
        or not 16 <= memory_mb <= 2048
    ):
        raise ValueError("memory_limit_mb must be an integer between 16 and 2048")
    if question.get("language") == "java" and memory_mb < MIN_JAVA_JOB_MEMORY_MB:
        raise ValueError(
            f"Java memory_limit_mb must be at least {MIN_JAVA_JOB_MEMORY_MB}"
        )
    memory_bytes = memory_mb * 1024 * 1024
    return JobLimits(
        active_process_limit=DEFAULT_JOB_LIMITS.active_process_limit,
        process_memory_limit_bytes=memory_bytes,
        job_memory_limit_bytes=memory_bytes,
    )


def _reflection_judge_checks(checks: list[Mapping]) -> list[dict]:
    """Translate the earlier question-bank check shape to ReflectionJudge's input schema."""
    normalized = []
    for raw in checks:
        check = dict(raw)
        kind = check.get("kind")
        if kind == "field":
            check["name"] = check.get("name", check.get("field_name"))
            check["type"] = check.get("type", check.get("expected_type"))
            modifiers = check.get("modifier", check.get("expected_modifiers", []))
            check["modifier"] = " ".join(modifiers) if isinstance(modifiers, list) else modifiers
            for key in ("field_name", "expected_type", "expected_modifiers"):
                check.pop(key, None)
        elif kind == "constructor":
            check["parameter_types"] = check.get("parameter_types", check.get("param_types", []))
            modifiers = check.get("modifier", check.get("expected_modifiers", []))
            check["modifier"] = " ".join(modifiers) if isinstance(modifiers, list) else modifiers
            check.pop("param_types", None)
            check.pop("expected_modifiers", None)
        elif kind == "method":
            check["name"] = check.get("name", check.get("method_name"))
            check["return_type"] = check.get("return_type", check.get("expected_return_type"))
            check["parameter_types"] = check.get("parameter_types", check.get("param_types", []))
            modifiers = check.get("modifier", check.get("expected_modifiers", []))
            check["modifier"] = " ".join(modifiers) if isinstance(modifiers, list) else modifiers
            for key in ("method_name", "expected_return_type", "param_types", "expected_modifiers"):
                check.pop(key, None)
        elif kind == "implements":
            check["interface"] = check.get("interface", check.get("expected_interface"))
            check.pop("expected_interface", None)
        elif kind == "behavior":
            setup = check.get("setup")
            invoke = check.get("invoke")
            if isinstance(setup, Mapping):
                check["constructor_parameter_types"] = setup.get(
                    "constructor_parameter_types", setup.get("constructor_param_types", [])
                )
                check["constructor_args"] = setup.get("constructor_args", [])
                check["setup"] = []
            if isinstance(invoke, Mapping):
                check["method"] = check.get("method", invoke.get("method"))
                check["parameter_types"] = check.get(
                    "parameter_types", invoke.get("parameter_types", invoke.get("param_types", []))
                )
                check["args"] = check.get("args", invoke.get("args", []))
                check.pop("invoke", None)
            state = check.get("expect_state")
            if isinstance(state, Mapping) and "getter" not in state and "field" not in state:
                getter, value = next(iter(state.items()), ("", None))
                check["expect_state"] = {"getter": getter, "value": value}
        elif kind == "toString":
            check["template"] = check.get("template", check.get("expected_template", ""))
            check.pop("expected_template", None)
            setup = check.get("setup")
            if isinstance(setup, Mapping):
                check["constructor_parameter_types"] = setup.get(
                    "constructor_parameter_types", setup.get("constructor_param_types", [])
                )
                check["constructor_args"] = setup.get("constructor_args", [])
                check["setup"] = []
        elif kind == "comparable" and isinstance(check.get("cases"), list):
            parameter_types = check.get("constructor_parameter_types", check.get("constructor_param_types", []))
            instances = []
            comparisons = []
            for case in check["cases"]:
                left = len(instances)
                instances.append({"constructor_parameter_types": parameter_types, "constructor_args": case.get("a", [])})
                right = len(instances)
                instances.append({"constructor_parameter_types": parameter_types, "constructor_args": case.get("b", [])})
                comparisons.append({"left": left, "right": right, "expected_sign": case.get("expected_sign")})
            check["instances"] = instances
            check["comparisons"] = comparisons
            check.pop("cases", None)
            check.pop("constructor_param_types", None)
        normalized.append(check)
    return normalized


def execute_question(
    question: Mapping, source_code: str, *, visible_only: bool = False
) -> dict:
    limits = _job_limits(question)
    if question["grading_mode"] == "reflection":
        checks = _reflection_judge_checks(question["checks"])
        total_points = question["total_points"]
        if visible_only:
            checks = [check for check in checks if check.get("is_visible") is True]
            visible_total = sum(
                (Decimal(str(check["points"])) for check in checks), Decimal("0")
            )
            total_points = (
                int(visible_total)
                if visible_total == visible_total.to_integral_value()
                else float(visible_total)
            )
        result = run_reflection_judge(
            source_code,
            _target_class_name(question),
            {"checks": checks, "total_points": total_points},
            judge_timeout_seconds=question["time_limit_seconds"],
            max_output_bytes=question["max_output_bytes"],
            job_limits=limits,
        )
    else:
        result = run_stdio(
            source_code,
            question["language"],
            question["tests"],
            target_class=question.get("target_class") if question["language"] == "java" else None,
            target_package=question.get("target_package") if question["language"] == "java" else None,
            target_file=question.get("target_file"),
            timeout_seconds=question["time_limit_seconds"],
            max_output_bytes=question["max_output_bytes"],
            visible_only=visible_only,
            job_limits=limits,
        )
    return result.to_dict()


def _normalized_results(
    question: Mapping, execution: Mapping, *, visible_only: bool, include_points: bool = True
) -> list[dict]:
    reflection = question["grading_mode"] == "reflection"
    source_items = question["checks"] if reflection else question["tests"]
    visibility = {item["id"]: item.get("is_visible") is True for item in source_items}
    result_items = execution.get("checks" if reflection else "tests", [])
    normalized = []
    for raw in result_items:
        item_id = raw.get("id")
        if item_id not in visibility or (visible_only and not visibility[item_id]):
            continue
        passed = raw.get("passed") is True
        row = {
            "id": item_id,
            "is_visible": visibility[item_id],
            "verdict": execution.get("verdict") if execution.get("verdict") in {"CE", "TLE", "MLE", "RE", "OLE"} else ("AC" if passed else "WA"),
            "passed": passed,
            "duration_ms": raw.get("duration_ms", execution.get("duration_ms", 0)),
            "error": raw.get("error"),
        }
        if include_points:
            row["points_earned"] = raw.get("points_earned", 0)
        if reflection:
            row.update({"expected": raw.get("expected"), "actual": raw.get("actual")})
        else:
            row.update(
                {
                    "expected": raw.get("expected_stdout"),
                    "actual": raw.get("actual_stdout"),
                    "stderr": raw.get("stderr", ""),
                }
            )
        normalized.append(row)
    return normalized


def _compiler_summary(execution: Mapping) -> dict | None:
    compile_result = execution.get("compile_result")
    if not isinstance(compile_result, Mapping):
        return None
    return {
        key: compile_result.get(key)
        for key in ("status", "success", "verdict", "stdout", "stderr", "error", "error_category")
        if key in compile_result
    }


def _pretest_reservation(student_id: str, exam: dict, question: dict, source_hash: str) -> str:
    run_id = uuid.uuid4().hex
    started_epoch = time.time()
    max_runs = min(
        int(question.get("max_pretest_runs", 20)),
        int(exam.get("max_pretest_runs", question.get("max_pretest_runs", 20))),
    )
    cooldown = float(exam.get("pretest_cooldown_seconds", 2))
    now_iso = utc_now()

    def reserve(records):
        matching = [
            item
            for item in records
            if item.get("student_id") == student_id
            and item.get("release_id") == exam.get("release_id")
            and item.get("question_id") == question.get("question_id")
        ]
        if len(matching) >= max_runs:
            raise CodeExamError("Pretest limit for this question has been reached", 429)
        if matching and started_epoch - float(matching[-1].get("started_epoch", 0)) < cooldown:
            raise CodeExamError("Please wait before running this question again", 429)
        records.append(
            {
                "run_id": run_id,
                "student_id": student_id,
                "exam_id": exam["id"],
                "release_id": exam["release_id"],
                "question_id": question["question_id"],
                "source_sha256": source_hash,
                "started_at": now_iso,
                "started_epoch": started_epoch,
                "status": "running",
            }
        )
        if len(records) > MAX_PRETEST_HISTORY:
            del records[: len(records) - MAX_PRETEST_HISTORY]

    update_json("code_runs.json", reserve)
    return run_id


def _finish_pretest(run_id: str, execution: Mapping) -> None:
    def finish(records):
        for item in reversed(records):
            if item.get("run_id") == run_id:
                item.update(
                    {
                        "status": "finished",
                        "verdict": execution.get("verdict"),
                        "duration_ms": execution.get("duration_ms"),
                        "finished_at": utc_now(),
                    }
                )
                break

    update_json("code_runs.json", finish)


def run_pretest(student_id: str, question_id: str, source_code: str, ip: str) -> dict:
    source_hash = _validate_source(source_code)
    _, _, exam = _active_context(student_id)
    question = _question_snapshot(exam, question_id)
    if not exam.get("allow_pretest", True) or not question.get("allow_pretest", True):
        raise CodeExamError("Pretest is disabled for this question or exam", 403)
    run_id = _pretest_reservation(student_id, exam, question, source_hash)
    if not _RUN_SLOTS.acquire(blocking=False):
        _finish_pretest(run_id, {"verdict": "JUDGE_INFRA_ERROR", "duration_ms": 0})
        raise CodeExamError("Code execution capacity is busy; retry shortly", 429)
    try:
        execution = execute_question(question, source_code, visible_only=True)
    except Exception as exc:
        execution = {
            "verdict": "JUDGE_INFRA_ERROR",
            "score": 0,
            "total_points": question["total_points"],
            "duration_ms": 0,
            "error": f"{type(exc).__name__}: {exc}",
            "error_category": "JUDGE_INFRA_ERROR",
            "checks": [],
            "tests": [],
        }
    finally:
        _RUN_SLOTS.release()
    _finish_pretest(run_id, execution)
    audit(
        "code.pretest",
        student_id,
        ip,
        {"exam_id": exam["id"], "question_id": question_id, "run_id": run_id, "source_sha256": source_hash, "verdict": execution.get("verdict")},
    )
    return {
        "run_id": run_id,
        "verdict": execution.get("verdict"),
        "duration_ms": execution.get("duration_ms", 0),
        "error": execution.get("error"),
        "error_category": execution.get("error_category"),
        "compile_result": _compiler_summary(execution),
        "results": _normalized_results(question, execution, visible_only=True, include_points=False),
    }


def _reserve_submission(student_id: str, exam: dict, question: dict, source_code: str, source_hash: str, ip: str) -> dict:
    submission_id = uuid.uuid4().hex
    record = {
        "id": submission_id,
        "exam_id": exam["id"],
        "release_id": exam["release_id"],
        "question_id": question["question_id"],
        "language": question["language"],
        "grading_mode": question["grading_mode"],
        "source_code": source_code,
        "source_sha256": source_hash,
        "submitted_at": utc_now(),
        "status": "grading",
        "score": 0,
        "total_points": question["total_points"],
        "results": [],
    }

    def reserve(submissions):
        student_records = submissions.setdefault(student_id, [])
        matching = [
            item
            for item in student_records
            if item.get("release_id") == exam["release_id"]
            and item.get("question_id") == question["question_id"]
        ]
        attempts = len(matching)
        max_allowed = 1 if exam.get("submission_policy") == "once" else int(exam.get("max_submissions", 1))
        if attempts >= max_allowed:
            raise CodeExamError("Submission limit for this question has been reached", 409)
        record["attempt"] = attempts + 1
        student_records.append(record)

    update_json("code_submissions.json", reserve)
    audit(
        "code.submit",
        student_id,
        ip,
        {"submission_id": submission_id, "exam_id": exam["id"], "question_id": question["question_id"], "release_id": exam["release_id"], "source_sha256": source_hash, "attempt": record["attempt"]},
    )
    return record


def _complete_submission(
    student_id: str,
    submission_id: str,
    question: dict,
    execution: Mapping,
    ip: str,
    *,
    audit_actor: str | None = None,
    audit_event: str = "code.graded",
    preserve_history: bool = False,
) -> dict:
    verdict = execution.get("verdict", "JUDGE_INFRA_ERROR")
    infrastructure = verdict in {"INVALID_REQUEST", "JDK_NOT_FOUND", "JUDGE_INFRA_ERROR", "PROTOCOL_ERROR"}
    if verdict not in {"AC", "WA", "CE", "TLE", "MLE", "RE", "OLE", "INVALID_REQUEST", "JDK_NOT_FOUND", "JUDGE_INFRA_ERROR", "PROTOCOL_ERROR"}:
        verdict = "PROTOCOL_ERROR"
        infrastructure = True
        execution = {**dict(execution), "error": "Runner returned an unknown verdict", "error_category": "PROTOCOL_ERROR"}
    score = 0
    if not infrastructure:
        try:
            if question["grading_mode"] == "reflection":
                checked = grade_reflection(
                    question["checks"],
                    {
                        "score": execution.get("score"),
                        "total_points": execution.get("total_points"),
                        "checks": execution.get("checks"),
                    },
                    question["total_points"],
                    verdict=verdict,
                )
            else:
                checked = grade_stdio(
                    question["tests"],
                    execution.get("tests"),
                    question["total_points"],
                    verdict=verdict,
                )
            score = checked.score
            if _decimal(execution.get("total_points"), "reported total_points") != _decimal(question["total_points"], "total_points"):
                raise GradingError("Runner total_points do not match the question snapshot", "JUDGE_INFRA_ERROR")
            if _decimal(execution.get("score"), "reported score") != _decimal(score, "normalized score"):
                raise GradingError("Runner score does not match validated result points", "JUDGE_INFRA_ERROR")
            if verdict in {"AC", "WA"}:
                verdict = "AC" if all(item.get("passed") is True for item in checked.results) else "WA"
            execution = {
                **dict(execution),
                "checks" if question["grading_mode"] == "reflection" else "tests": checked.results,
                "score": score,
                "total_points": checked.total_points,
            }
        except CodeExamError as exc:
            verdict = "JUDGE_INFRA_ERROR"
            infrastructure = True
            execution = {**dict(execution), "error": str(exc), "error_category": "JUDGE_INFRA_ERROR"}
        except GradingError as exc:
            verdict = exc.category
            infrastructure = True
            execution = {**dict(execution), "error": str(exc), "error_category": exc.category}
    results = _normalized_results(question, execution, visible_only=False)
    updated = None
    regrade_failure = None

    def complete(submissions):
        nonlocal updated, regrade_failure
        for item in submissions.get(student_id, []):
            if item.get("id") == submission_id:
                if preserve_history and infrastructure:
                    updated = deepcopy(item)
                    regrade_failure = {
                        "error_category": execution.get("error_category") or verdict,
                        "question_id": question["question_id"],
                    }
                    break
                if preserve_history and item.get("status") in {"graded", "error"}:
                    history_fields = (
                        "graded_at",
                        "grading_spec_version",
                        "verdict",
                        "score",
                        "total_points",
                        "duration_ms",
                        "error",
                        "error_category",
                        "compile_result",
                        "results",
                    )
                    history = item.setdefault("grading_history", [])
                    history.append(
                        {
                            key: deepcopy(item.get(key))
                            for key in history_fields
                            if key in item
                        }
                    )
                    del history[:-100]
                item.update(
                    {
                        "status": "error" if infrastructure else "graded",
                        "verdict": verdict,
                        "score": 0 if infrastructure else score,
                        "total_points": question["total_points"],
                        "duration_ms": execution.get("duration_ms", 0),
                        "error": execution.get("error"),
                        "error_category": execution.get("error_category"),
                        "compile_result": _compiler_summary(execution),
                        "results": results,
                        "graded_at": utc_now(),
                        "grading_spec_version": question.get(
                            "snapshot_version", question.get("version", 1)
                        ),
                    }
                )
                updated = deepcopy(item)
                break

    update_json("code_submissions.json", complete)
    if updated is None:
        raise CodeExamError("Submission reservation was lost", 503)
    if regrade_failure:
        audit(
            "code.regrade_failed",
            audit_actor or student_id,
            ip,
            {
                "submission_id": submission_id,
                **regrade_failure,
            },
        )
        raise CodeExamError(
            "Regrading failed because the judge is unavailable; the previous result was retained",
            503,
        )
    audit(
        audit_event,
        audit_actor or student_id,
        ip,
        {"submission_id": submission_id, "question_id": question["question_id"], "verdict": verdict, "score": updated["score"], "total_points": updated["total_points"], "error_category": execution.get("error_category")},
    )
    return _refresh_exam_score(student_id, updated)


def _refresh_exam_score(student_id: str, submission: dict) -> dict:
    exam = get_code_exam(submission.get("exam_id"))
    if not exam:
        return submission
    student_records = read_json("code_submissions.json").get(student_id, [])
    latest_graded = {}
    for item in student_records:
        if item.get("exam_id") == exam.get("id") and item.get("status") == "graded":
            latest_graded[item.get("question_id")] = item
    question_scores = []
    all_questions_submitted = True
    for question in exam.get("questions", []):
        question_id = question["question_id"]
        latest = latest_graded.get(question_id)
        if latest is None:
            all_questions_submitted = False
        question_scores.append(
            {
                "question_id": question_id,
                "score": latest.get("score", 0) if latest else 0,
                "total_points": question["total_points"],
            }
        )
    try:
        exam_score = grade_exam(question_scores)
    except GradingError as exc:
        raise CodeExamError(f"Could not aggregate the code exam score: {exc}", 503) from exc
    submission.update(
        {
            "exam_score": exam_score.score,
            "exam_total_points": exam_score.total_points,
            "all_questions_submitted": all_questions_submitted,
            "exam_ended": exam.get("status") == "ended",
        }
    )

    def persist(submissions):
        for item in submissions.get(student_id, []):
            if item.get("id") == submission.get("id"):
                item.update(
                    {
                        "exam_score": submission["exam_score"],
                        "exam_total_points": submission["exam_total_points"],
                        "all_questions_submitted": all_questions_submitted,
                        "exam_ended": submission["exam_ended"],
                    }
                )
                break

    update_json("code_submissions.json", persist)
    if all_questions_submitted:
        def finish_code_only_assignment(assignments):
            assignment = assignments.get(student_id)
            if (
                assignment
                and assignment.get("release_id") == exam.get("release_id")
                and assignment.get("exam_file") is None
                and assignment.get("status") == "in_progress"
                and not assignment.get("forced_submit")
            ):
                assignment.update({"status": "submitted", "submitted_at": utc_now()})

        update_json("assignments.json", finish_code_only_assignment)
    return submission


def _public_submission(
    record: Mapping, *, reveal_score: bool, reveal_exam_score: bool = False
) -> dict:
    result = {
        "submission_id": record.get("id"),
        "exam_id": record.get("exam_id"),
        "question_id": record.get("question_id"),
        "status": "submitted" if record.get("status") in {"grading", "graded", "error"} else record.get("status"),
        "submitted_at": record.get("submitted_at"),
    }
    if reveal_score and record.get("status") == "graded":
        result.update(
            {
                "verdict": record.get("verdict"),
                "score": record.get("score"),
                "total_points": record.get("total_points"),
                "duration_ms": record.get("duration_ms"),
                "error": record.get("error"),
                "results": [item for item in record.get("results", []) if item.get("is_visible") is True],
            }
        )
        compile_result = record.get("compile_result")
        if compile_result:
            result["compile_result"] = compile_result
        if reveal_exam_score:
            result["exam_score"] = record.get("exam_score", 0)
            result["exam_total_points"] = record.get("exam_total_points", 0)
    elif record.get("status") == "error":
        result["error"] = record.get("error")
        result["error_category"] = record.get("error_category")
    return result


def submit_code(student_id: str, question_id: str, source_code: str, ip: str) -> tuple[dict, bool]:
    source_hash = _validate_source(source_code)
    _, _, exam = _active_context(student_id)
    question = _question_snapshot(exam, question_id)
    if not _RUN_SLOTS.acquire(blocking=False):
        raise CodeExamError("Code execution capacity is busy; retry shortly", 429)
    try:
        record = _reserve_submission(student_id, exam, question, source_code, source_hash, ip)
    except Exception:
        _RUN_SLOTS.release()
        raise
    try:
        execution = execute_question(question, source_code)
    except Exception as exc:
        execution = {
            "verdict": "JUDGE_INFRA_ERROR",
            "score": 0,
            "total_points": question["total_points"],
            "duration_ms": 0,
            "error": f"{type(exc).__name__}: {exc}",
            "error_category": "JUDGE_INFRA_ERROR",
            "checks": [],
            "tests": [],
        }
    finally:
        _RUN_SLOTS.release()

    completed = _complete_submission(student_id, record["id"], question, execution, ip)
    reveal = exam.get("show_final_score_immediately", False)
    reveal_exam = reveal and completed.get("all_questions_submitted")
    return _public_submission(completed, reveal_score=reveal, reveal_exam_score=reveal_exam), completed["status"] != "error"


def get_student_submission(student_id: str, question_id: str) -> dict:
    assignment = read_json("assignments.json").get(student_id)
    if not assignment or not assignment.get("code_exam_id"):
        raise CodeExamError("No code exam is assigned", 404)
    exam = get_code_exam(assignment["code_exam_id"])
    if not exam or exam.get("release_id") != assignment.get("release_id"):
        raise CodeExamError("No matching code exam was found", 404)
    _question_snapshot(exam, question_id)
    matching = [
        item
        for item in read_json("code_submissions.json").get(student_id, [])
        if item.get("release_id") == assignment.get("release_id") and item.get("question_id") == question_id
    ]
    if not matching:
        raise CodeExamError("No submission was found for this question", 404)
    latest = matching[-1]
    reveal = exam.get("show_final_score_immediately", False) or exam.get("status") == "ended"
    reveal_exam = reveal and (
        latest.get("all_questions_submitted") or exam.get("status") == "ended"
    )
    return _public_submission(latest, reveal_score=reveal, reveal_exam_score=reveal_exam)


def release_student_exam_scores(release_id: str) -> None:
    exams = read_json("code_exams.json")
    exam = next(
        (item for item in exams.values() if item.get("release_id") == release_id),
        None,
    )
    if not exam:
        return

    def update_scores(submissions):
        for records in submissions.values():
            latest_by_question = {}
            for item in records:
                if (
                    item.get("exam_id") == exam.get("id")
                    and item.get("release_id") == release_id
                    and item.get("status") == "graded"
                ):
                    latest_by_question[item.get("question_id")] = item
            for record in records:
                if record.get("exam_id") != exam.get("id") or record.get("release_id") != release_id:
                    continue
                question_scores = []
                all_submitted = True
                for question in exam.get("questions", []):
                    latest = latest_by_question.get(question["question_id"])
                    if latest is None:
                        all_submitted = False
                    question_scores.append(
                        {
                            "question_id": question["question_id"],
                            "score": latest.get("score", 0) if latest else 0,
                            "total_points": question["total_points"],
                        }
                    )
                try:
                    total = grade_exam(question_scores)
                except GradingError as exc:
                    raise CodeExamError(f"Could not aggregate the code exam score: {exc}", 503) from exc
                record.update(
                    {
                        "exam_score": total.score,
                        "exam_total_points": total.total_points,
                        "all_questions_submitted": all_submitted,
                        "exam_ended": True,
                    }
                )

    update_json("code_submissions.json", update_scores)


def get_admin_code_results(
    exam_id: str, *, student_id: str | None = None, question_id: str | None = None
) -> dict:
    if not isinstance(exam_id, str) or not exam_id:
        raise CodeExamError("exam_id is required")
    exam = get_code_exam(exam_id)
    if not exam:
        raise CodeExamError("Code exam was not found", 404)
    submissions = read_json("code_submissions.json")
    rows = []
    for owner_id, records in submissions.items():
        if student_id is not None and owner_id != student_id:
            continue
        for record in records:
            if record.get("exam_id") != exam_id or record.get("release_id") != exam.get("release_id"):
                continue
            if question_id is not None and record.get("question_id") != question_id:
                continue
            rows.append({"student_id": owner_id, **deepcopy(record)})
    rows.sort(key=lambda item: (item.get("submitted_at", ""), item["student_id"], item.get("attempt", 0)))
    return {
        "exam_id": exam_id,
        "release_id": exam.get("release_id"),
        "status": exam.get("status"),
        "title": exam.get("title"),
        "questions": [
            {"question_id": q["question_id"], "title": q.get("title", ""), "total_points": q["total_points"], "language": q.get("language"), "grading_mode": q.get("grading_mode")}
            for q in exam.get("questions", [])
        ],
        "matrix": _results_matrix(exam, submissions, student_id),
        "submissions": rows,
    }


def _results_matrix(exam: dict, submissions: Mapping, only_student: str | None) -> list[dict]:
    """One row per student, one cell per question in exam order; scores follow the latest graded submission."""
    names = {sid: item.get("full_name", "") for sid, item in read_json("students.json").items()}
    matrix = []
    for owner_id, records in submissions.items():
        if only_student is not None and owner_id != only_student:
            continue
        mine = [r for r in records if r.get("exam_id") == exam["id"] and r.get("release_id") == exam.get("release_id")]
        if not mine:
            continue
        cells, scores = [], []
        for question in exam.get("questions", []):
            qid = question["question_id"]
            attempts = [r for r in mine if r.get("question_id") == qid]
            graded = [r for r in attempts if r.get("status") == "graded"]
            latest = attempts[-1] if attempts else None
            score = graded[-1].get("score", 0) if graded else 0
            scores.append({"question_id": qid, "score": score, "total_points": question["total_points"]})
            cells.append(
                {
                    "question_id": qid,
                    "attempts": len(attempts),
                    "status": latest.get("status") if latest else "none",
                    "verdict": latest.get("verdict") if latest else None,
                    "score": score,
                    "total_points": question["total_points"],
                    "submission_id": latest.get("id") if latest else None,
                    "regraded": any(r.get("grading_history") for r in attempts),
                }
            )
        try:
            total = grade_exam(scores)
            total_score, total_points = total.score, total.total_points
        except GradingError:
            total_score, total_points = None, None
        matrix.append({"student_id": owner_id, "full_name": names.get(owner_id, ""), "cells": cells, "total_score": total_score, "total_points": total_points})
    matrix.sort(key=lambda item: item["student_id"])
    return matrix


def regrade_student_exam(
    exam_id: str,
    student_id: str,
    actor: str,
    ip: str,
    *,
    question_id: str | None = None,
    use_latest_spec: bool = False,
) -> dict:
    """Regrade the latest completed submission of each question (or one question) for one student."""
    exam = get_code_exam(exam_id)
    if not exam:
        raise CodeExamError("Code exam was not found", 404)
    if exam.get("status") != "ended":
        raise CodeExamError("Only ended code exams can be regraded", 409)
    if not isinstance(student_id, str) or not student_id:
        raise CodeExamError("student_id is required")
    question_ids = [q["question_id"] for q in exam.get("questions", [])]
    if question_id is not None:
        if question_id not in question_ids:
            raise CodeExamError("Question is not part of this code exam", 404)
        question_ids = [question_id]
    records = [
        item
        for item in read_json("code_submissions.json").get(student_id, [])
        if item.get("exam_id") == exam_id and item.get("release_id") == exam.get("release_id")
    ]
    if not records:
        raise CodeExamError("This student has no submissions for this code exam", 404)
    regraded, failed, skipped = [], [], []
    for qid in question_ids:
        done = [item for item in records if item.get("question_id") == qid and item.get("status") in {"graded", "error"}]
        if not done:
            skipped.append({"question_id": qid, "reason": "Chưa có bài nộp đã chấm."})
            continue
        target = done[-1]
        try:
            updated = regrade_submission(exam_id, target["id"], actor, ip, use_latest_spec=use_latest_spec)
            regraded.append({"question_id": qid, "submission_id": target["id"], "verdict": updated.get("verdict"), "score": updated.get("score")})
        except CodeExamError as exc:
            failed.append({"question_id": qid, "submission_id": target["id"], "error": str(exc), "status": exc.status})
    if regraded:
        release_student_exam_scores(exam["release_id"])
    audit(
        "code.bulk_regrade",
        actor,
        ip,
        {
            "exam_id": exam_id,
            "student_id": student_id,
            "scope": "question" if question_id else "exam",
            "regraded": len(regraded),
            "failed": len(failed),
            "skipped": len(skipped),
            "use_latest_spec": use_latest_spec,
        },
    )
    return {"exam_id": exam_id, "student_id": student_id, "regraded": regraded, "failed": failed, "skipped": skipped}


def regrade_submission(
    exam_id: str,
    submission_id: str,
    actor: str,
    ip: str,
    *,
    use_latest_spec: bool = False,
) -> dict:
    exam = get_code_exam(exam_id)
    if not exam:
        raise CodeExamError("Code exam was not found", 404)
    if exam.get("status") != "ended":
        raise CodeExamError("Only ended code exams can be regraded", 409)

    owner_id = None
    record = None
    for student_id, records in read_json("code_submissions.json").items():
        for candidate in records:
            if candidate.get("id") == submission_id:
                owner_id, record = student_id, candidate
                break
        if record:
            break
    if (
        record is None
        or owner_id is None
        or record.get("exam_id") != exam_id
        or record.get("release_id") != exam.get("release_id")
    ):
        raise CodeExamError("Submission was not found for this code exam", 404)
    if record.get("status") not in {"graded", "error"}:
        raise CodeExamError("Only completed submissions can be regraded", 409)
    source_code = record.get("source_code")
    if not isinstance(source_code, str):
        raise CodeExamError("Submission source is unavailable for regrading", 409)

    question_id = record.get("question_id")
    question = _question_snapshot(exam, question_id)
    if use_latest_spec:
        latest = get_question(question_id)
        if not latest or latest.get("status") != "published":
            raise CodeExamError("A published question version is required for regrading", 409)
        question = {
            **deepcopy(latest),
            "question_id": question_id,
            "snapshot_version": latest.get("version", 1),
        }

    _validate_source(source_code)
    if not _RUN_SLOTS.acquire(blocking=False):
        raise CodeExamError("Code execution capacity is busy; retry shortly", 429)
    try:
        try:
            execution = execute_question(question, source_code)
        except Exception as exc:
            execution = {
                "verdict": "JUDGE_INFRA_ERROR",
                "score": 0,
                "total_points": question["total_points"],
                "duration_ms": 0,
                "error": f"{type(exc).__name__}: {exc}",
                "error_category": "JUDGE_INFRA_ERROR",
                "checks": [],
                "tests": [],
            }
    finally:
        _RUN_SLOTS.release()
    return _complete_submission(
        owner_id,
        submission_id,
        question,
        execution,
        ip,
        audit_actor=actor,
        audit_event="code.regraded",
        preserve_history=True,
    )


def _sample_passes(question: Mapping, execution: Mapping) -> tuple[bool, str | None]:
    """Whether a sample solution earned every configured point; second item is a reason when it did not."""
    reflection = question["grading_mode"] == "reflection"
    configured = question["checks"] if reflection else question["tests"]
    returned = execution.get("checks" if reflection else "tests", [])
    try:
        if reflection:
            verified = grade_reflection(
                question["checks"],
                {"score": execution.get("score"), "total_points": execution.get("total_points"), "checks": returned},
                question["total_points"],
                verdict=execution.get("verdict"),
            )
        else:
            verified = grade_stdio(question["tests"], returned, question["total_points"], verdict=execution.get("verdict"))
    except GradingError as exc:
        return False, f"Sample solution returned an invalid result: {exc}"
    all_checks_passed = len(returned) == len(configured) and all(item.get("passed") is True for item in returned)
    if (
        execution.get("verdict") != "AC"
        or not all_checks_passed
        or verified.score != _decimal(question["total_points"], "total_points")
    ):
        return False, "Sample solution must pass every configured check/test"
    return True, None


_INFRA_CATEGORIES = {"INVALID_REQUEST", "JDK_NOT_FOUND", "JUDGE_INFRA_ERROR", "PROTOCOL_ERROR"}

# Characters that browsers/editors add when code is pasted and that javac/python reject as "illegal character".
_PASTE_ARTIFACTS = {"\ufeff": "", "\u200b": "", "\u200c": "", "\u200d": "", "\u2060": "", "\u00a0": " ", "\u2007": " ", "\u202f": " "}


def _clean_sample_source(sample_source):
    if not isinstance(sample_source, str):
        return sample_source
    return sample_source.translate({ord(k): v for k, v in _PASTE_ARTIFACTS.items()})


def validate_question_sample(question_id: str, sample_source: str, actor: str, ip: str) -> dict:
    """Run a sample solution against the current draft spec and record the outcome bound to its spec hash.

    Never changes the question status. A record is stored only when the spec is unchanged
    when the run finishes, so a concurrent edit cannot be marked as validated.
    """
    question = get_question(question_id)
    if not question:
        raise QuestionError("question not found", 404)
    if question.get("status") != "draft":
        raise QuestionError("Only draft questions can be validated", 409, "QUESTION_NOT_DRAFT")
    source_hash = _validate_source(sample_source)
    sample_source = _clean_sample_source(sample_source)
    spec_hash = compute_spec_hash(question)
    if not _RUN_SLOTS.acquire(blocking=False):
        raise QuestionError("Code execution capacity is busy; retry shortly", 429)
    try:
        try:
            execution = execute_question(question, sample_source)
        except Exception as exc:
            execution = {
                "verdict": "JUDGE_INFRA_ERROR",
                "score": 0,
                "total_points": question["total_points"],
                "duration_ms": 0,
                "error": f"{type(exc).__name__}: {exc}",
                "error_category": "JUDGE_INFRA_ERROR",
                "checks": [],
                "tests": [],
            }
    finally:
        _RUN_SLOTS.release()

    infra_error = execution.get("error_category") in _INFRA_CATEGORIES
    passed, reason = (False, execution.get("error")) if infra_error else _sample_passes(question, execution)
    record = {
        "spec_hash": spec_hash,
        "passed": passed,
        "validated_at": utc_now(),
        "validated_by": actor,
        "sample_sha256": source_hash,
        "verdict": execution.get("verdict"),
        "score": execution.get("score"),
        "total_points": execution.get("total_points"),
    }
    state = {"stale": False, "kept": None}

    def store(questions):
        current = questions.get(question_id)
        if (
            not current
            or current.get("status") != "draft"
            or compute_spec_hash(current) != spec_hash
        ):
            state["stale"] = True
            return
        if infra_error:
            return
        previous = current.get("validation")
        if (
            not passed
            and isinstance(previous, Mapping)
            and previous.get("passed") is True
            and previous.get("spec_hash") == spec_hash
        ):
            # A failing run of a different sample must not revoke an earlier pass for the very same spec.
            state["kept"] = dict(previous)
            return
        current["validation"] = record

    update_json("questions.json", store)
    audit(
        "code.question_validated",
        actor,
        ip,
        {"question_id": question_id, "spec_hash": spec_hash, "passed": passed, "stale": state["stale"], "sample_sha256": source_hash},
    )
    return {
        "validation": {**record, "current": passed and not state["stale"], "stale": state["stale"], "reason": reason},
        "previous_pass": {**state["kept"], "current": True, "stale": False, "reason": None} if state["kept"] else None,
        "verdict": execution.get("verdict"),
        "score": execution.get("score"),
        "total_points": execution.get("total_points"),
        "duration_ms": execution.get("duration_ms", 0),
        "error": execution.get("error"),
        "error_category": execution.get("error_category"),
        "compile_result": _compiler_summary(execution),
        "results": _normalized_results(question, execution, visible_only=False),
    }


def update_published_question(question_id: str, payload: Mapping, sample_source: str, actor: str, ip: str) -> dict:
    """Commit an edit of a published question only after its sample solution passes the new spec.

    The stored question is untouched unless validation succeeds, so a failed attempt leaves the
    previous published version intact. Code-exam snapshots are separate copies and are never modified.
    """
    current = get_question(question_id)
    if not current:
        raise QuestionError("Không tìm thấy câu hỏi.", 404)
    if current.get("status") != "published":
        raise QuestionError("Chỉ câu hỏi đã xuất bản mới dùng luồng này.", 409, "QUESTION_NOT_PUBLISHED")
    if not isinstance(sample_source, str) or not sample_source.strip():
        raise QuestionError("Cần nhập mã nguồn đáp án mẫu để xác thực trước khi lưu thay đổi.", 400, "SAMPLE_REQUIRED")
    base_version = current.get("version")
    candidate = _validate_question(payload, question_id=question_id, actor=actor)
    source_hash = _validate_source(sample_source)
    sample_source = _clean_sample_source(sample_source)
    spec_hash = compute_spec_hash(candidate)
    if not _RUN_SLOTS.acquire(blocking=False):
        raise QuestionError("Hệ thống chấm đang bận, hãy thử lại sau giây lát.", 429)
    try:
        try:
            execution = execute_question(candidate, sample_source)
        except Exception as exc:
            execution = {
                "verdict": "JUDGE_INFRA_ERROR", "score": 0, "total_points": candidate["total_points"], "duration_ms": 0,
                "error": f"{type(exc).__name__}: {exc}", "error_category": "JUDGE_INFRA_ERROR", "checks": [], "tests": [],
            }
    finally:
        _RUN_SLOTS.release()

    if execution.get("error_category") in _INFRA_CATEGORIES:
        raise QuestionError("Hệ thống chấm gặp lỗi hạ tầng (không phải lỗi câu hỏi); thay đổi chưa được lưu.", 503, "JUDGE_INFRA_ERROR")
    passed, reason = _sample_passes(candidate, execution)
    record = {
        "spec_hash": spec_hash,
        "passed": passed,
        "validated_at": utc_now(),
        "validated_by": actor,
        "sample_sha256": source_hash,
        "verdict": execution.get("verdict"),
        "score": execution.get("score"),
        "total_points": execution.get("total_points"),
    }
    result = {
        "saved": False,
        "validation": {**record, "current": passed, "stale": False, "reason": reason},
        "verdict": execution.get("verdict"),
        "score": execution.get("score"),
        "total_points": execution.get("total_points"),
        "duration_ms": execution.get("duration_ms", 0),
        "error": execution.get("error"),
        "error_category": execution.get("error_category"),
        "compile_result": _compiler_summary(execution),
        "results": _normalized_results(candidate, execution, visible_only=False),
    }
    if not passed:
        audit("code.question_edit_rejected", actor, ip, {"question_id": question_id, "spec_hash": spec_hash, "sample_sha256": source_hash})
        return result

    def commit(questions):
        stored = questions.get(question_id)
        if not stored or stored.get("status") != "published" or stored.get("version") != base_version:
            raise QuestionError("Câu hỏi đã bị thay đổi trong lúc xác thực; hãy tải lại và thử lại.", 409, "QUESTION_CHANGED")
        candidate.update(
            {
                "status": "published",
                "source": {**stored.get("source", {}), "updated_by": actor, "updated_at": utc_now()},
                "usage_count": stored.get("usage_count", 0),
                "version": int(stored.get("version", 1)) + 1,
                "validation": record,
            }
        )
        questions[question_id] = candidate
        return deepcopy(candidate)

    saved = update_json("questions.json", commit)
    audit("code.question_updated", actor, ip, {"question_id": question_id, "version": saved["version"], "spec_hash": spec_hash, "published": True})
    return {**result, "saved": True, "question": saved}


def publish_question(question_id: str, actor: str, ip: str) -> dict:
    """Publish a draft question only if its exact current spec has a successful server-side validation."""

    def publish(questions):
        question = questions.get(question_id)
        if not question:
            raise QuestionError("question not found", 404)
        if question.get("status") == "published":
            raise QuestionError("question is already published", 409, "ALREADY_PUBLISHED")
        if question.get("status") != "draft":
            raise QuestionError("Only draft questions can be published", 409, "QUESTION_NOT_DRAFT")
        record = question.get("validation")
        if not isinstance(record, Mapping):
            raise QuestionError("The question must pass sample validation before publishing", 409, "VALIDATION_REQUIRED")
        if record.get("spec_hash") != compute_spec_hash(question):
            raise QuestionError("The question changed after its last validation; validate it again", 409, "VALIDATION_OUTDATED")
        if record.get("passed") is not True:
            raise QuestionError("The last sample validation failed; fix the question and validate again", 409, "VALIDATION_FAILED")
        question["status"] = "published"
        question.setdefault("source", {}).update({"updated_by": actor, "updated_at": utc_now()})
        question["version"] = int(question.get("version", 1)) + 1
        return deepcopy(question)

    question = update_json("questions.json", publish)
    audit(
        "code.question_published",
        actor,
        ip,
        {"question_id": question_id, "spec_hash": question["validation"]["spec_hash"], "version": question["version"]},
    )
    return question
