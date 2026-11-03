"""Score validation and aggregation for code question and exam results."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, localcontext
import math
from typing import Mapping, Sequence


class GradingError(ValueError):
    """A grading input failed validation and carries its execution category."""

    def __init__(self, message: str, category: str = "JUDGE_INFRA_ERROR") -> None:
        super().__init__(message)
        self.category = category


@dataclass(frozen=True)
class QuestionScore:
    score: int | float
    total_points: int | float
    results: list[dict]


@dataclass(frozen=True)
class ExamScore:
    score: int | float
    total_points: int | float
    questions: list[dict]


_STUDENT_VERDICTS = frozenset({"AC", "WA", "CE", "TLE", "MLE", "RE", "OLE"})
_INFRASTRUCTURE_VERDICTS = frozenset(
    {"INVALID_REQUEST", "JDK_NOT_FOUND", "JUDGE_INFRA_ERROR", "PROTOCOL_ERROR"}
)
_VALID_VERDICTS = _STUDENT_VERDICTS | _INFRASTRUCTURE_VERDICTS


def _validate_verdict(verdict: str | None) -> None:
    if verdict is None:
        return
    if not isinstance(verdict, str) or verdict not in _VALID_VERDICTS:
        raise GradingError("Judge result has an invalid verdict", "PROTOCOL_ERROR")
    if verdict in _INFRASTRUCTURE_VERDICTS:
        raise GradingError(
            f"Cannot calculate a score for infrastructure verdict {verdict}", verdict
        )


def _validate_verdict_matches_results(verdict: str | None, results: list[dict]) -> None:
    if verdict == "AC" and not all(result["passed"] for result in results):
        raise GradingError("AC verdict conflicts with failed checks/tests", "PROTOCOL_ERROR")
    if verdict == "WA" and all(result["passed"] for result in results):
        raise GradingError("WA verdict conflicts with passing checks/tests", "PROTOCOL_ERROR")


def _is_json_value(value, seen: set[int] | None = None, depth: int = 0) -> bool:
    if value is None or isinstance(value, (str, bool, int)):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    if depth >= 100:
        return False
    if not isinstance(value, (list, dict)):
        return False
    if seen is None:
        seen = set()
    identity = id(value)
    if identity in seen:
        return False
    seen.add(identity)
    try:
        if isinstance(value, list):
            return all(_is_json_value(item, seen, depth + 1) for item in value)
        return all(
            isinstance(key, str) and _is_json_value(item, seen, depth + 1)
            for key, item in value.items()
        )
    finally:
        seen.remove(identity)


def parse_nonnegative_decimal(
    value, field: str, *, allow_decimal: bool = True
) -> Decimal:
    """Parse bounded finite non-negative numeric input without losing precision."""
    accepted_types = (int, float, Decimal) if allow_decimal else (int, float)
    if isinstance(value, bool) or not isinstance(value, accepted_types):
        raise ValueError(f"{field} must be a finite non-negative number")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field} must be a finite non-negative number") from exc
    if not number.is_finite() or number < 0:
        raise ValueError(f"{field} must be a finite non-negative number")
    if len(number.as_tuple().digits) > 1000 or abs(number.as_tuple().exponent) > 1000:
        raise ValueError(f"{field} exceeds the supported numeric range")
    try:
        if not math.isfinite(float(number)):
            raise ValueError(f"{field} exceeds the supported numeric range")
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"{field} exceeds the supported numeric range") from exc
    return number


def plain_number(value: Decimal) -> int | float:
    if value == value.to_integral_value():
        return int(value)
    return float(value)


def _number(value, field: str, category: str) -> Decimal:
    try:
        return parse_nonnegative_decimal(value, field)
    except ValueError as exc:
        raise GradingError(str(exc), category) from exc


def _decimal_sum(values) -> Decimal:
    numbers = list(values)
    with localcontext() as context:
        context.prec = 4000 + len(str(len(numbers)))
        return sum(numbers, Decimal(0))


def _sequence(value, field: str, category: str) -> Sequence:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise GradingError(f"{field} must be an array", category)
    return value


def _configured_points(
    specifications: Sequence[Mapping], total_points, *, item_name: str
) -> tuple[list[dict], dict[str, Decimal], Decimal]:
    specs = _sequence(specifications, f"{item_name} specifications", "INVALID_REQUEST")
    total = (
        None
        if total_points is None
        else _number(total_points, "total_points", "INVALID_REQUEST")
    )
    normalized: list[dict] = []
    points_by_id: dict[str, Decimal] = {}
    point_values: list[Decimal] = []
    for index, raw in enumerate(specs):
        if not isinstance(raw, Mapping):
            raise GradingError(
                f"{item_name} specification at index {index} must be an object",
                "INVALID_REQUEST",
            )
        item_id = raw.get("id")
        if not isinstance(item_id, str) or not item_id.strip():
            raise GradingError(
                f"{item_name} specification at index {index} needs a non-empty id",
                "INVALID_REQUEST",
            )
        if item_id in points_by_id:
            raise GradingError(f"duplicate {item_name} id: {item_id}", "INVALID_REQUEST")
        points = _number(raw.get("points"), f"{item_name} '{item_id}' points", "INVALID_REQUEST")
        points_by_id[item_id] = points
        point_values.append(points)
        normalized.append({"id": item_id, "points": points})
    points_sum = _decimal_sum(point_values)
    if total is not None and points_sum != total:
        raise GradingError(
            f"total_points ({total}) must equal configured {item_name} points ({points_sum})",
            "INVALID_REQUEST",
        )
    return normalized, points_by_id, points_sum if total is None else total


def sum_configured_points(specifications, *, item_name: str) -> Decimal:
    """Validate configured check/test points and return their exact sum."""
    _, _, total = _configured_points(specifications, None, item_name=item_name)
    return total


def _normalize_question_results(
    specifications: Sequence[Mapping],
    results,
    total_points,
    *,
    item_name: str,
    reported_score=None,
    reported_total_points=None,
    verdict: str | None = None,
) -> QuestionScore:
    specs, configured_points, total = _configured_points(
        specifications, total_points, item_name=item_name
    )
    protocol_category = "PROTOCOL_ERROR" if item_name == "check" else "JUDGE_INFRA_ERROR"
    _validate_verdict(verdict)
    result_list = _sequence(results, f"{item_name} results", protocol_category)
    if len(result_list) != len(specs):
        raise GradingError(
            f"{item_name} results do not match the configured {item_name} set",
            protocol_category,
        )

    results_by_id: dict[str, Mapping] = {}
    for index, raw in enumerate(result_list):
        if not isinstance(raw, Mapping):
            raise GradingError(
                f"{item_name} result at index {index} must be an object", protocol_category
            )
        item_id = raw.get("id")
        if not isinstance(item_id, str) or item_id not in configured_points:
            raise GradingError(f"unknown {item_name} result id", protocol_category)
        if item_id in results_by_id:
            raise GradingError(f"duplicate {item_name} result id: {item_id}", protocol_category)
        if item_name == "test":
            if raw.get("verdict") is not None:
                _validate_verdict(raw["verdict"])
            error_category = raw.get("error_category")
            if error_category is not None:
                if (
                    not isinstance(error_category, str)
                    or error_category not in _INFRASTRUCTURE_VERDICTS
                ):
                    raise GradingError("STDIO result has an invalid error_category", protocol_category)
                _validate_verdict(error_category)
        results_by_id[item_id] = raw

    normalized_results: list[dict] = []
    earned_values: list[Decimal] = []
    for spec in specs:
        item_id = spec["id"]
        result = results_by_id.get(item_id)
        if result is None:
            raise GradingError(f"missing {item_name} result id: {item_id}", protocol_category)
        points_earned = _number(
            result.get("points_earned"),
            f"{item_name} '{item_id}' points_earned",
            protocol_category,
        )
        if points_earned > configured_points[item_id]:
            raise GradingError(
                f"{item_name} '{item_id}' earned more than its configured points",
                protocol_category,
            )
        if item_name == "check":
            required = {"passed", "expected", "actual", "error"}
            if not required.issubset(result):
                raise GradingError(f"{item_name} '{item_id}' is missing result fields", protocol_category)
            if not isinstance(result["passed"], bool):
                raise GradingError(f"{item_name} '{item_id}' passed must be a boolean", protocol_category)
            if result["error"] is not None and not isinstance(result["error"], str):
                raise GradingError(f"{item_name} '{item_id}' error must be a string or null", protocol_category)
            if not _is_json_value(result["expected"]):
                raise GradingError(f"{item_name} '{item_id}' expected must be a JSON value", protocol_category)
            if not _is_json_value(result["actual"]):
                raise GradingError(f"{item_name} '{item_id}' actual must be a JSON value", protocol_category)
            if "points" in result:
                reported_points = _number(
                    result["points"], f"{item_name} '{item_id}' points", protocol_category
                )
                if reported_points != configured_points[item_id]:
                    raise GradingError(
                        f"{item_name} '{item_id}' points do not match configuration",
                        protocol_category,
                    )
            normalized = {
                "id": item_id,
                "passed": result["passed"],
                "points_earned": plain_number(points_earned),
                "expected": result["expected"],
                "actual": result["actual"],
                "error": result["error"],
            }
        else:
            reported_points = _number(
                result.get("points"), f"{item_name} '{item_id}' points", protocol_category
            )
            if reported_points != configured_points[item_id]:
                raise GradingError(
                    f"{item_name} '{item_id}' points do not match configuration",
                    protocol_category,
                )
            if not isinstance(result.get("passed"), bool):
                raise GradingError(f"{item_name} '{item_id}' passed must be a boolean", protocol_category)
            reported_earned = _number(
                result.get("points_earned"),
                f"{item_name} '{item_id}' points_earned",
                protocol_category,
            )
            if reported_earned > configured_points[item_id]:
                raise GradingError(
                    f"{item_name} '{item_id}' earned more than its configured points",
                    protocol_category,
                )
            expected_earned = configured_points[item_id] if result["passed"] else Decimal(0)
            if reported_earned != expected_earned:
                raise GradingError(
                    f"{item_name} '{item_id}' points_earned conflicts with passed",
                    protocol_category,
                )
            points_earned = reported_earned
            normalized = dict(result)
            normalized["id"] = item_id
            normalized["points"] = plain_number(reported_points)
            normalized["points_earned"] = plain_number(points_earned)
        earned_values.append(points_earned)
        normalized_results.append(normalized)
    earned_sum = _decimal_sum(earned_values)

    if reported_total_points is not None:
        reported_total = _number(reported_total_points, "reported total_points", protocol_category)
        if reported_total != total:
            raise GradingError("reported total_points do not match configuration", protocol_category)
    if reported_score is not None:
        score_from_result = _number(reported_score, "reported score", protocol_category)
        if score_from_result > total:
            raise GradingError("reported score exceeds total_points", protocol_category)
        if score_from_result != earned_sum:
            raise GradingError("reported score does not equal the sum of points_earned", protocol_category)
    if earned_sum > total:
        raise GradingError("score exceeds total_points", protocol_category)

    return QuestionScore(
        score=plain_number(earned_sum),
        total_points=plain_number(total),
        results=normalized_results,
    )


def grade_reflection(
    check_specifications,
    judge_payload: Mapping,
    total_points,
    *,
    verdict: str | None = None,
) -> QuestionScore:
    """Validate an untrusted judge payload and calculate its score.

    ``verdict`` is optional because the frozen child JSON schema omits it; Python
    runner callers pass the surrounding JudgeResult verdict when they have it.
    """
    _validate_verdict(verdict)
    if not isinstance(judge_payload, Mapping):
        raise GradingError("ReflectionJudge result must be an object", "PROTOCOL_ERROR")
    error_category = judge_payload.get("error_category")
    if error_category is not None:
        if not isinstance(error_category, str) or error_category not in _INFRASTRUCTURE_VERDICTS:
            raise GradingError("ReflectionJudge returned an invalid error_category", "PROTOCOL_ERROR")
        _validate_verdict(error_category)
    if not {"score", "total_points", "checks"}.issubset(judge_payload):
        raise GradingError("ReflectionJudge result is missing score fields", "PROTOCOL_ERROR")
    checks = judge_payload["checks"]
    if not isinstance(checks, list):
        raise GradingError("ReflectionJudge checks must be a list", "PROTOCOL_ERROR")
    payload_verdict = judge_payload.get("verdict")
    if payload_verdict is not None:
        _validate_verdict(payload_verdict)
        if verdict is not None and payload_verdict != verdict:
            raise GradingError("Judge verdict fields do not match", "PROTOCOL_ERROR")
        verdict = payload_verdict
    _validate_verdict(verdict)
    graded = _normalize_question_results(
        check_specifications,
        checks,
        total_points,
        item_name="check",
        reported_score=judge_payload["score"],
        reported_total_points=judge_payload["total_points"],
        verdict=verdict,
    )
    _validate_verdict_matches_results(verdict, graded.results)
    return graded


def grade_stdio(
    test_specifications,
    test_results,
    total_points,
    *,
    force_zero: bool = False,
    verdict: str | None = None,
) -> QuestionScore:
    """Validate generated STDIO test results and calculate one question score."""
    _validate_verdict(verdict)
    if not isinstance(force_zero, bool):
        raise GradingError("force_zero must be a boolean", "JUDGE_INFRA_ERROR")
    if force_zero:
        # Retain this legacy keyword but refuse to hide an infrastructure failure as zero.
        raise GradingError(
            "Cannot calculate a score for infrastructure failure",
            verdict if verdict in _INFRASTRUCTURE_VERDICTS else "JUDGE_INFRA_ERROR",
        )
    graded = _normalize_question_results(
        test_specifications,
        test_results,
        total_points,
        item_name="test",
        verdict=verdict,
    )
    _validate_verdict_matches_results(verdict, graded.results)
    return graded


def grade_exam(question_scores) -> ExamScore:
    """Validate question score records and return the aggregate exam score."""
    questions = _sequence(question_scores, "question_scores", "JUDGE_INFRA_ERROR")
    normalized: list[dict] = []
    seen_ids: set[str] = set()
    score_values: list[Decimal] = []
    points_values: list[Decimal] = []
    for index, raw in enumerate(questions):
        if not isinstance(raw, Mapping):
            raise GradingError(
                f"question score at index {index} must be an object", "JUDGE_INFRA_ERROR"
            )
        # Legacy exam score records use `id`; retain this fallback for stored results.
        question_id = raw.get("question_id", raw.get("id"))
        if not isinstance(question_id, str) or not question_id.strip():
            raise GradingError(
                f"question score at index {index} needs a non-empty question_id",
                "JUDGE_INFRA_ERROR",
            )
        if question_id in seen_ids:
            raise GradingError(f"duplicate question id: {question_id}", "JUDGE_INFRA_ERROR")
        seen_ids.add(question_id)
        total = _number(raw.get("total_points"), f"question '{question_id}' total_points", "JUDGE_INFRA_ERROR")
        score = _number(raw.get("score"), f"question '{question_id}' score", "JUDGE_INFRA_ERROR")
        if score > total:
            raise GradingError(f"question '{question_id}' score exceeds total_points", "JUDGE_INFRA_ERROR")
        normalized_question = dict(raw)
        normalized_question["question_id"] = question_id
        normalized_question["score"] = plain_number(score)
        normalized_question["total_points"] = plain_number(total)
        normalized.append(normalized_question)
        score_values.append(score)
        points_values.append(total)
    score_sum = _decimal_sum(score_values)
    points_sum = _decimal_sum(points_values)
    return ExamScore(
        score=plain_number(score_sum),
        total_points=plain_number(points_sum),
        questions=normalized,
    )
