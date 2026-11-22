"""Persistent, attempt-scoped technical observations for Official Exams."""
from __future__ import annotations

import copy
import re

from .storage import read_json, transaction, utc_now, write_json

EVENT_TYPES = {"window_blur", "document_hidden",
    "multiple_tabs_detected",
    "fullscreen_refused",
    "fullscreen_request_failed",
    "fullscreen_lost",
}
EVENT_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{8,100}$")
DEFAULT_COUNTERS = {event_type: 0 for event_type in sorted(EVENT_TYPES)}


class MonitoringEventError(ValueError):
    pass


def flush_start_precheck(student_id: str) -> None:
    """Replay the server-owned Start outbox; clear only after durable append.

    The marker is committed with Student Start, so replay remains valid even if
    the attempt ends before a failed event write can be retried.
    """
    with transaction():
        assignments = read_json("assignments.json")
        item = assignments.get(student_id, {})
        if not item.get("monitoring_precheck_pending") or not item.get("release_id"):
            return
        if item.get("exam_file"):
            item.pop("monitoring_precheck_pending", None)
            write_json("assignments.json", assignments)
            return
        record_event(student_id, item["release_id"], "start.multiple_tabs", "multiple_tabs_detected")
        item.pop("monitoring_precheck_pending", None)
        write_json("assignments.json", assignments)


def _attempt_record(store: dict, student_id: str, release_id: str, *, create: bool = False):
    attempts = store.setdefault("attempts", {}) if create else store.get("attempts", {})
    if not isinstance(attempts, dict):
        if not create:
            return None
        attempts = store["attempts"] = {}
    student_attempts = attempts.setdefault(student_id, {}) if create else attempts.get(student_id, {})
    if not isinstance(student_attempts, dict):
        if not create:
            return None
        student_attempts = attempts[student_id] = {}
    record = student_attempts.get(release_id)
    if create and not isinstance(record, dict):
        record = {
            "student_id": student_id,
            "release_id": release_id,
            "event_counters": dict(DEFAULT_COUNTERS),
            "latest_event_seq": 0,
            "events": [],
        }
        student_attempts[release_id] = record
    return record if isinstance(record, dict) else None


def record_event(
    student_id: str,
    release_id: str,
    event_id: str,
    event_type: str,
    client_occurred_at: str | None = None,
) -> tuple[dict, bool]:
    """Append once per event_id; caller must establish active-attempt eligibility."""
    if not isinstance(student_id, str) or not student_id or len(student_id) > 120:
        raise MonitoringEventError("Invalid authenticated Student identity.")
    if not isinstance(release_id, str) or not release_id or len(release_id) > 160:
        raise MonitoringEventError("Invalid active Exam release identity.")
    if not isinstance(event_id, str) or not EVENT_ID_RE.fullmatch(event_id):
        raise MonitoringEventError("event_id must contain 8–100 safe characters.")
    if not isinstance(event_type, str) or event_type not in EVENT_TYPES:
        raise MonitoringEventError("event_type is not supported.")
    if client_occurred_at is not None and (
        not isinstance(client_occurred_at, str) or len(client_occurred_at) > 40
    ):
        raise MonitoringEventError("client_occurred_at must be a short timestamp string.")

    # The lock covers deduplication, sequence allocation, append, counters, and write.
    with transaction():
        # read_json returns its configured default object by reference when the
        # file has not been created yet; copy before mutation to avoid leaking
        # this attempt into process-global defaults or another test workspace.
        store = copy.deepcopy(read_json("exam_monitoring.json"))
        if not isinstance(store, dict):
            raise MonitoringEventError("Exam monitoring storage has an invalid shape.")
        record = _attempt_record(store, student_id, release_id, create=True)
        if not isinstance(record.get("events"), list):
            raise MonitoringEventError("Exam monitoring event history has an invalid shape.")
        for existing in record["events"]:
            if not isinstance(existing, dict):
                continue
            if existing.get("event_id") == event_id:
                if existing.get("event_type") != event_type:
                    raise MonitoringEventError("event_id was already used for a different event_type.")
                return existing, False

        try:
            previous_seq = int(record.get("latest_event_seq", 0))
        except (TypeError, ValueError):
            previous_seq = len(record.get("events", []))
        previous_seq = max(previous_seq, max(
            (int(item.get("seq", 0)) for item in record["events"] if isinstance(item, dict)),
            default=0,
        ))
        event = {
            "seq": previous_seq + 1,
            "event_id": event_id,
            "event_type": event_type,
            "student_id": student_id,
            "release_id": release_id,
            "received_at": utc_now(),
            "source": "student_browser",
        }
        if client_occurred_at:
            event["client_occurred_at"] = client_occurred_at
        record["events"].append(event)
        counters = record.get("event_counters")
        if not isinstance(counters, dict):
            counters = record["event_counters"] = dict(DEFAULT_COUNTERS)
        try:
            counters[event_type] = int(counters.get(event_type, 0)) + 1
        except (TypeError, ValueError):
            raise MonitoringEventError("Exam monitoring event counter has an invalid value.")
        record["latest_event_seq"] = event["seq"]
        write_json("exam_monitoring.json", store)
        return event, True


def attempt_summary(student_id: str, release_id: str | None, store: dict | None = None) -> dict:
    if not student_id or not release_id:
        return {"event_counters": dict(DEFAULT_COUNTERS), "latest_event_seq": 0}
    store = read_json("exam_monitoring.json") if store is None else store
    record = _attempt_record(store if isinstance(store, dict) else {}, student_id, release_id)
    if not record:
        return {"event_counters": dict(DEFAULT_COUNTERS), "latest_event_seq": 0}
    counters = dict(DEFAULT_COUNTERS)
    if isinstance(record.get("event_counters"), dict):
        for event_type in EVENT_TYPES:
            try:
                counters[event_type] = max(0, int(record["event_counters"].get(event_type, 0)))
            except (TypeError, ValueError):
                pass
    try:
        latest_seq = max(0, int(record.get("latest_event_seq", 0)))
    except (TypeError, ValueError):
        latest_seq = 0
    return {"event_counters": counters, "latest_event_seq": latest_seq}


def events_after(student_id: str, release_id: str, after_seq: int, limit: int = 100) -> dict:
    store = read_json("exam_monitoring.json")
    record = _attempt_record(store if isinstance(store, dict) else {}, student_id, release_id)
    if not record:
        return {"student_id": student_id, "release_id": release_id, "events": [], "latest_event_seq": 0, "next_after_seq": after_seq, "has_more": False}
    all_events = record.get("events", [])
    try:
        latest_seq = max(0, int(record.get("latest_event_seq", 0)))
    except (TypeError, ValueError):
        latest_seq = 0
    events = []
    for item in (all_events if isinstance(all_events, list) else []):
        if not isinstance(item, dict):
            continue
        try:
            sequence = int(item.get("seq", 0))
        except (TypeError, ValueError):
            continue
        if sequence > after_seq:
            events.append(item)
    page = events[:limit]
    next_after_seq = int(page[-1]["seq"]) if page else after_seq
    return {
        "student_id": student_id,
        "release_id": release_id,
        "events": page,
        "latest_event_seq": latest_seq,
        "next_after_seq": next_after_seq,
        "has_more": len(events) > len(page),
    }
