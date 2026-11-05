from __future__ import annotations
import io
import re
import zipfile
from pathlib import Path
from datetime import datetime, timezone
from .config import UPLOAD_DIR, MAX_REQUEST_SIZE, MAX_ZIP_ENTRIES, MAX_UNCOMPRESSED_SIZE
from .storage import read_json, write_json, utc_now, audit


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

def accept_submission(student_id: str, original_name: str, data: bytes, ip: str) -> dict:
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
    if not assignment.get("started_at"):
        raise ValueError("Bạn chưa bắt đầu làm bài.")
    if assignment.get("status") in {"submitted", "expired"} and settings.get("submission_policy") != "configurable":
        raise ValueError("Trạng thái bài thi không cho phép nộp bài.")
    if assignment.get("ends_at"):
        end = datetime.fromisoformat(assignment["ends_at"])
        if datetime.now(timezone.utc) > end:
            assignment["status"] = "expired"
            assignments[student_id] = assignment
            write_json("assignments.json", assignments)
            audit("submission.rejected_expired", student_id, ip, {})
            raise ValueError("Đã hết giờ. Server từ chối bài nộp muộn.")
    records = read_json("submissions.json")
    all_records = records.get(student_id, [])
    existing = [item for item in all_records if item.get("release_id") == assignment.get("release_id")]
    max_submissions = max(1, int(settings.get("max_submissions", 1)))
    if settings.get("submission_policy") == "once" and existing:
        raise ValueError("Bạn đã nộp bài; kỳ thi chỉ cho phép nộp một lần.")
    if settings.get("submission_policy") == "configurable" and len(existing) >= max_submissions:
        raise ValueError("Bạn đã sử dụng hết số lần nộp được phép.")
    safe_id = re.sub(r"[^A-Za-z0-9_-]", "_", student_id)[:30]
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    saved_name = f"{safe_id}_{timestamp}{extension}"
    destination = UPLOAD_DIR / saved_name
    with destination.open("xb") as f:
        f.write(data)
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
