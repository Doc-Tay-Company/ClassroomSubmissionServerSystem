from __future__ import annotations
import io
import re
import zipfile
import uuid
import unicodedata
from pathlib import Path
from datetime import datetime, timezone
from .config import UPLOAD_DIR, MAX_REQUEST_SIZE, MAX_ZIP_ENTRIES, MAX_UNCOMPRESSED_SIZE
from .storage import read_json, write_json, utc_now, audit, transaction


def zip_submission_eligibility(student_id: str, assignment: dict | None = None, settings: dict | None = None, all_submissions: dict | None = None, now: datetime | None = None) -> dict:
    """Describe current ZIP upload eligibility using the same contract as acceptance."""
    settings = read_json("settings.json") if settings is None else settings
    if assignment is None:
        assignment = read_json("assignments.json").get(student_id)
    if not isinstance(assignment, dict) or not assignment.get("exam_file"):
        return {"eligible": False, "reason": "not_zip", "count": 0, "limit": 0, "remaining_seconds": 0}
    release_id = assignment.get("release_id")
    submissions = read_json("submissions.json") if all_submissions is None else all_submissions
    records = [record for record in submissions.get(student_id, []) if record.get("release_id") == release_id]
    policy = settings.get("submission_policy", "once")
    try:
        limit = 1 if policy == "once" else max(1, int(settings.get("max_submissions", 1)))
    except (TypeError, ValueError):
        limit = 1
    if policy != "configurable":
        limit = 1
    count = len(records)

    def result(eligible: bool, reason: str | None, remaining: int = 0) -> dict:
        return {"eligible": eligible, "reason": reason, "count": count, "limit": limit, "remaining_seconds": remaining}

    if not release_id or not settings.get("exam_released") or settings.get("exam_state") != "started" or settings.get("exam_release_id") != release_id:
        return result(False, "inactive_release")
    if not assignment.get("started_at"):
        return result(False, "not_started")
    try:
        started = datetime.fromisoformat(assignment["started_at"])
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return result(False, "invalid_start")
    current = now or datetime.now(timezone.utc)
    if started.astimezone(timezone.utc) > current:
        return result(False, "not_started")
    terminal = assignment.get("forced_submit") or assignment.get("finalized_at") or assignment.get("status") in {"expired", "ended"}
    if terminal or assignment.get("status") not in {"in_progress", "submitted"} or not assignment.get("ends_at"):
        return result(False, "terminal")
    try:
        end = datetime.fromisoformat(assignment["ends_at"])
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return result(False, "invalid_deadline")
    remaining = max(0, int((end.astimezone(timezone.utc) - current).total_seconds()))
    if current >= end.astimezone(timezone.utc):
        return result(False, "deadline")
    if assignment.get("status") == "submitted" and policy != "configurable":
        return result(False, "quota_exhausted", remaining)
    if count >= limit:
        return result(False, "quota_exhausted", remaining)
    return result(True, None, remaining)


def validate_zip(data: bytes) -> tuple[bool, str]:
    if not data:
        return False, "File ZIP rỗng."
    if len(data) > MAX_REQUEST_SIZE:
        return False, "File vượt quá giới hạn 50 MiB."
    if not data.startswith(b"PK\x03\x04") and not data.startswith(b"PK\x05\x06") and not data.startswith(b"PK\x07\x08"):
        return False, "Nội dung không có chữ ký ZIP hợp lệ."
    try:
        with zipfile.ZipFile(io.BytesIO(data), "r") as archive:
            infos = archive.infolist()
            if not infos:
                return False, "ZIP không chứa tệp nào."
            if len(infos) > MAX_ZIP_ENTRIES:
                return False, f"ZIP có quá nhiều mục (tối đa {MAX_ZIP_ENTRIES})."
            total = sum(info.file_size for info in infos)
            if total > MAX_UNCOMPRESSED_SIZE:
                return False, "Tổng dung lượng giải nén vượt giới hạn an toàn."
            bad = archive.testzip()
            if bad:
                return False, f"ZIP bị lỗi CRC tại mục {Path(bad).name}."
            for info in infos:
                p = Path(info.filename)
                if p.is_absolute() or ".." in p.parts or "\\" in info.filename:
                    return False, "ZIP chứa đường dẫn không an toàn."
        return True, "ZIP hợp lệ."
    except (zipfile.BadZipFile, OSError, RuntimeError) as exc:
        return False, f"Không thể đọc ZIP: {exc}"

_WINDOWS_RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}

def _safe_filename_part(value: object, fallback: str, limit: int) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^A-Za-z0-9_-]+", "_", text).strip(" _.-")
    text = text[:limit].rstrip(" .")
    if not text or text.upper() in _WINDOWS_RESERVED_NAMES:
        return fallback
    return text

def _exam_title_for_release(release_id: str) -> str:
    for exam in read_json("exams.json").values():
        release = exam.get("release") if isinstance(exam, dict) else None
        if isinstance(release, dict) and release.get("release_id") == release_id:
            return str(exam.get("title") or "Khong_xac_dinh")
    return "Khong_xac_dinh"

def _submission_filename(student_id: str, student_name: str, exam_name: str, attempt: int, extension: str) -> str:
    parts = (
        _safe_filename_part(student_id, "student", 24),
        _safe_filename_part(student_name, "Student", 24),
        _safe_filename_part(exam_name, "Exam", 40),
        f"L{attempt:02d}",
        uuid.uuid4().hex[:6],
    )
    return "_".join(parts)[:176].rstrip(" ._") + extension

def _accept_submission_locked(student_id: str, original_name: str, data: bytes, ip: str) -> dict:
    settings = read_json("settings.json")
    assignments = read_json("assignments.json")
    assignment = assignments.get(student_id)
    if not settings.get("exam_released") or not assignment or assignment.get("release_id") != settings.get("exam_release_id"):
        raise ValueError("Lượt thi đã kết thúc hoặc bạn chưa được giao đề.")
    if not assignment.get("exam_file"):
        raise ValueError("Kỳ thi này không nhận bài nộp file.")
    extension = Path(original_name).suffix.lower()
    accepted = {
        str(item).lower() if str(item).startswith(".") else f".{str(item).lower()}"
        for item in settings.get("accepted_submission_extensions", [".zip"])
    }
    if extension not in accepted:
        raise ValueError(f"Loại file không được chấp nhận. Cho phép: {', '.join(sorted(accepted))}.")
    if extension == ".zip":
        ok, message = validate_zip(data)
        if not ok:
            raise ValueError(message)
    started_at = assignment.get("started_at")
    if not started_at:
        raise ValueError("Student has not started this exam attempt.")
    try:
        started = datetime.fromisoformat(started_at)
    except (TypeError, ValueError) as exc:
        raise ValueError("The exam attempt start time is invalid.") from exc
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    if started.astimezone(timezone.utc) > datetime.now(timezone.utc):
        raise ValueError("The exam attempt has not started yet.")
    # A configurable policy permits repeat uploads only while this release and
    # attempt are still active. It never overrides terminal lifecycle markers.
    terminal = (
        assignment.get("forced_submit")
        or assignment.get("finalized_at")
        or assignment.get("status") in {"expired", "ended"}
        or settings.get("exam_state") != "started"
        or assignment.get("release_id") != settings.get("exam_release_id")
        or not settings.get("exam_released")
    )
    if terminal or assignment.get("status") not in {"in_progress", "submitted"} or not assignment.get("ends_at"):
        raise ValueError("This exam attempt is no longer eligible for file submission.")
    if assignment.get("status") == "submitted" and settings.get("submission_policy") != "configurable":
        raise ValueError("This exam status does not allow another submission.")
    if assignment.get("ends_at"):
        end = datetime.fromisoformat(assignment["ends_at"])
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) >= end.astimezone(timezone.utc):
            assignment["status"] = "expired"
            assignments[student_id] = assignment
            write_json("assignments.json", assignments)
            audit("submission.rejected_expired", student_id, ip, {})
            raise ValueError("The exam deadline has passed; late file submissions are rejected.")
    records = read_json("submissions.json")
    all_records = records.get(student_id, [])
    existing = [item for item in all_records if item.get("release_id") == assignment.get("release_id")]
    eligibility = zip_submission_eligibility(student_id, assignment, settings, records)
    max_submissions = eligibility["limit"]
    if settings.get("submission_policy") == "once" and existing:
        raise ValueError("Bạn đã nộp bài; kỳ thi chỉ cho phép nộp một lần.")
    if settings.get("submission_policy") == "configurable" and eligibility["count"] >= max_submissions:
        raise ValueError("Bạn đã sử dụng hết số lần nộp được phép.")
    attempt_number = len(existing) + 1
    student = read_json("students.json").get(student_id, {})
    exam_name = _exam_title_for_release(assignment.get("release_id"))
    for _ in range(5):
        saved_name = _submission_filename(
            student_id, student.get("full_name", "Student"), exam_name,
            attempt_number, extension,
        )
        destination = UPLOAD_DIR / saved_name
        try:
            with destination.open("xb") as f:
                f.write(data)
            break
        except FileExistsError:
            continue
    else:
        raise ValueError("Could not allocate a unique submission filename.")
    record = {"filename": saved_name, "original_filename": Path(original_name).name[:150], "size_bytes": len(data), "submitted_at": utc_now(), "ip": ip, "sha256": __import__("hashlib").sha256(data).hexdigest(), "status": "received", "release_id": assignment.get("release_id")}
    if settings.get("overwrite_previous") and existing:
        # Replace the previous payload in this release but retain metadata and attempt count.
        old_file = UPLOAD_DIR / existing[-1].get("filename", "")
        try:
            if old_file.is_file() and old_file.parent == UPLOAD_DIR:
                old_file.unlink()
        except OSError:
            pass
        for previous in existing:
            previous["payload_retained"] = False
    record["payload_retained"] = True
    all_records.append(record)
    records[student_id] = all_records
    write_json("submissions.json", records)
    assignment["status"] = "submitted"
    assignments[student_id] = assignment
    write_json("assignments.json", assignments)
    audit("submission.accepted", student_id, ip, {"filename": saved_name, "size_bytes": len(data), "sha256": record["sha256"], "attempt": len(existing) + 1, "release_id": assignment.get("release_id")})
    return record


def accept_submission(student_id: str, original_name: str, data: bytes, ip: str) -> dict:
    # Serialize eligibility validation and persistence with Force Submit, Teacher
    # End, and completion mutations, which use the same process-wide lock.
    with transaction():
        return _accept_submission_locked(student_id, original_name, data, ip)
