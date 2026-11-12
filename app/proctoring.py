"""Strict exam proctoring: warnings, return grace period, and zero-score termination.

The browser reports when the student leaves the exam screen.  The server keeps the
authoritative counter in ``assignments.json`` so a page reload, a closed tab, or a
modified client cannot reset it.  A small watchdog also terminates students whose
heartbeat has been silent for the grace period (closed browser / network loss).
"""
from __future__ import annotations

from datetime import datetime, timezone
import time
import traceback

from .storage import audit, read_json, transaction, write_json

MAX_WARNINGS = 3
RETURN_GRACE_SECONDS = 120
ACTIVE_STATUS = "in_progress"

# Give students a short reconnect window after a server restart instead of
# immediately terminating every in-progress assignment whose session is stale.
_SWEEP_STARTED_AT = time.monotonic()


def _parse_time(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _elapsed_seconds(value, now: datetime) -> float | None:
    parsed = _parse_time(value)
    if parsed is None:
        return None
    return max(0.0, (now - parsed).total_seconds())


def is_terminated(assignment: dict | None) -> bool:
    return bool(assignment and assignment.get("terminated_by_proctoring"))


def _is_active(settings: dict, assignment: dict | None) -> bool:
    return bool(
        assignment
        and assignment.get("started_at")
        and assignment.get("status") == ACTIVE_STATUS
        and not assignment.get("forced_submit")
        and not is_terminated(assignment)
        and settings.get("exam_state") == "started"
        and settings.get("exam_released")
        and assignment.get("release_id") == settings.get("exam_release_id")
    )


def _state(assignment: dict | None, active: bool, now: datetime) -> dict:
    assignment = assignment or {}
    count = int(assignment.get("proctoring_violation_count", 0) or 0)
    pending_since = assignment.get("proctoring_pending_since")
    grace_remaining = None
    if active and pending_since:
        elapsed = _elapsed_seconds(pending_since, now) or 0.0
        grace_remaining = max(0, int(RETURN_GRACE_SECONDS - elapsed))
    return {
        "active": bool(active),
        "terminated": is_terminated(assignment),
        "violation_count": count,
        "max_warnings": MAX_WARNINGS,
        "warning_pending": bool(active and pending_since),
        "grace_seconds": RETURN_GRACE_SECONDS,
        "grace_remaining": grace_remaining,
        "termination_reason": assignment.get("proctoring_termination_reason"),
        "terminated_at": assignment.get("proctoring_terminated_at"),
        "final_score": 0 if is_terminated(assignment) else None,
    }


def _terminate_locked(
    assignments: dict,
    student_id: str,
    reason: str,
    ip: str | None,
    now: datetime,
) -> dict:
    assignment = assignments.get(student_id) or {}
    if not is_terminated(assignment):
        timestamp = now.isoformat(timespec="seconds")
        assignment.update(
            {
                "status": "submitted",
                "submitted_at": timestamp,
                "ends_at": timestamp,
                "forced_submit": True,
                "terminated_by_proctoring": True,
                "proctoring_termination_reason": reason,
                "proctoring_terminated_at": timestamp,
                "proctoring_final_score": 0,
                "final_score": 0,
            }
        )
        assignment.pop("proctoring_pending_since", None)
        assignments[student_id] = assignment
        write_json("assignments.json", assignments)
        audit(
            "proctoring.terminated",
            student_id,
            ip,
            {
                "reason": reason,
                "violation_count": int(assignment.get("proctoring_violation_count", 0) or 0),
            },
        )
    return assignment


def state_for(student_id: str, *, ip: str | None = None, enforce_timeout: bool = True) -> dict:
    """Return the current proctoring state, terminating an expired warning first."""
    now = datetime.now(timezone.utc)
    with transaction():
        settings = read_json("settings.json")
        assignments = read_json("assignments.json")
        assignment = assignments.get(student_id)
        active = _is_active(settings, assignment)
        if active and enforce_timeout and assignment.get("proctoring_pending_since"):
            elapsed = _elapsed_seconds(assignment.get("proctoring_pending_since"), now)
            if elapsed is not None and elapsed >= RETURN_GRACE_SECONDS:
                assignment = _terminate_locked(assignments, student_id, "return_timeout", ip, now)
                active = False
        return _state(assignment, active, now)


def register_violation(student_id: str, event: str = "leave", ip: str | None = None) -> dict:
    """Record one warning.  The warning after the configured maximum terminates the exam."""
    now = datetime.now(timezone.utc)
    with transaction():
        settings = read_json("settings.json")
        assignments = read_json("assignments.json")
        assignment = assignments.get(student_id)
        if not _is_active(settings, assignment):
            return _state(assignment, False, now)

        count = int(assignment.get("proctoring_violation_count", 0) or 0) + 1
        timestamp = now.isoformat(timespec="seconds")
        assignment["proctoring_violation_count"] = count
        assignment["proctoring_last_violation_at"] = timestamp
        if not assignment.get("proctoring_pending_since"):
            assignment["proctoring_pending_since"] = timestamp
        assignments[student_id] = assignment
        write_json("assignments.json", assignments)
        audit(
            "proctoring.violation",
            student_id,
            ip,
            {"event": str(event)[:40], "violation_count": count, "max_warnings": MAX_WARNINGS},
        )

        if count > MAX_WARNINGS:
            assignment = _terminate_locked(assignments, student_id, "violation_limit", ip, now)
            return _state(assignment, False, now)
        return _state(assignment, True, now)


def acknowledge_warning(student_id: str, ip: str | None = None) -> dict:
    """Student accepted the warning and is back in the exam screen."""
    now = datetime.now(timezone.utc)
    with transaction():
        settings = read_json("settings.json")
        assignments = read_json("assignments.json")
        assignment = assignments.get(student_id)
        if not _is_active(settings, assignment):
            return _state(assignment, False, now)

        pending_since = assignment.get("proctoring_pending_since")
        if pending_since:
            elapsed = _elapsed_seconds(pending_since, now)
            if elapsed is not None and elapsed >= RETURN_GRACE_SECONDS:
                assignment = _terminate_locked(assignments, student_id, "return_timeout", ip, now)
                return _state(assignment, False, now)
            assignment.pop("proctoring_pending_since", None)
            assignment["proctoring_last_ack_at"] = now.isoformat(timespec="seconds")
            assignments[student_id] = assignment
            write_json("assignments.json", assignments)
            audit(
                "proctoring.warning_acknowledged",
                student_id,
                ip,
                {"violation_count": int(assignment.get("proctoring_violation_count", 0) or 0)},
            )
        return _state(assignment, True, now)


def sweep_abandoned(*, now: datetime | None = None, ignore_startup_grace: bool = False) -> int:
    """Terminate active exams with an expired warning or a silent heartbeat.

    Returns the number of students terminated.  ``ignore_startup_grace`` is used
    by tests; production calls let the watchdog give a reconnect window after a
    server restart.
    """
    now = now or datetime.now(timezone.utc)
    terminated = 0
    with transaction():
        settings = read_json("settings.json")
        assignments = read_json("assignments.json")
        sessions = read_json("sessions.json")
        latest = {}
        for session in sessions.values():
            if session.get("role") != "student":
                continue
            student_id = session.get("user_id")
            seen = session.get("last_seen", "")
            if student_id and seen >= latest.get(student_id, ""):
                latest[student_id] = seen

        startup_ready = ignore_startup_grace or (time.monotonic() - _SWEEP_STARTED_AT) >= RETURN_GRACE_SECONDS
        changed = False
        for student_id, assignment in list(assignments.items()):
            if not _is_active(settings, assignment):
                continue
            pending_elapsed = _elapsed_seconds(assignment.get("proctoring_pending_since"), now)
            if pending_elapsed is not None and pending_elapsed >= RETURN_GRACE_SECONDS:
                _terminate_locked(assignments, student_id, "return_timeout", None, now)
                terminated += 1
                changed = True
                continue
            if not startup_ready:
                continue
            last_seen = _elapsed_seconds(latest.get(student_id), now)
            if last_seen is None:
                started = _elapsed_seconds(assignment.get("started_at"), now)
                if started is not None and started >= RETURN_GRACE_SECONDS:
                    _terminate_locked(assignments, student_id, "disconnect_timeout", None, now)
                    terminated += 1
                    changed = True
            elif last_seen >= RETURN_GRACE_SECONDS:
                _terminate_locked(assignments, student_id, "disconnect_timeout", None, now)
                terminated += 1
                changed = True
        if changed:
            # _terminate_locked already writes after each change; this keeps the
            # final state explicit if a future edit changes that behaviour.
            write_json("assignments.json", assignments)
    return terminated


def watchdog_loop() -> None:
    """Daemon loop started by the HTTP server."""
    while True:
        try:
            sweep_abandoned()
        except Exception:  # pragma: no cover - defensive background task
            traceback.print_exc()
        time.sleep(10)
