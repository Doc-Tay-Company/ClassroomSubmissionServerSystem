from __future__ import annotations
import ipaddress
import random
import uuid
from pathlib import Path
from datetime import datetime, timezone, timedelta
from .config import EXAM_DIR, ALLOWED_EXAM_EXTENSIONS
from .storage import read_json, write_json, utc_now, audit
from .security import hash_password, verify_password
from .code_exams import attach_code_exam_to_release, prepare_code_exam_distribution, transition_code_exam


def list_exam_files() -> list[dict]:
    result = []
    for path in sorted(EXAM_DIR.iterdir(), key=lambda p: p.name.casefold()):
        if path.is_file() and not path.is_symlink() and path.suffix.lower() in ALLOWED_EXAM_EXTENSIONS:
            result.append({"name": path.name, "size": path.stat().st_size, "extension": path.suffix.lower()})
    return result

def _ip_sort(ip: str):
    if not ip or ip == "unknown":
        return (2, 0)
    try:
        return (0, int(ipaddress.ip_address(ip)))
    except ValueError:
        return (1, ip)

def _subnet_key(ip: str) -> str:
    if not ip or ip == "unknown":
        return "unknown"
    try:
        return str(ipaddress.ip_network(f"{ip}/24", strict=False)) if ":" not in ip else str(ipaddress.ip_network(f"{ip}/64", strict=False))
    except ValueError:
        return "unknown"

def distribute_exams(mode: str, config: dict | None = None) -> dict:
    students = read_json("students.json")
    files = [x["name"] for x in list_exam_files()]
    if not students:
        raise ValueError("Chưa có tài khoản sinh viên.")
    config = config or {}
    code_exam_id = config.get("code_exam_id")
    if not files and not code_exam_id:
        raise ValueError("Thư mục de-thi chưa có file đề hợp lệ.")
    if code_exam_id:
        prepare_code_exam_distribution(code_exam_id)
    if mode not in {"random", "selected", "parity", "custom"}:
        raise ValueError("Chế độ phân phối không hợp lệ.")
    assignments = {}
    settings = read_json("settings.json")
    participant_ids = settings.get("exam_participants") or []
    eligible = [(sid, students[sid]) for sid in participant_ids if sid in students and students[sid].get("active", True)] if participant_ids else [(sid, data) for sid, data in students.items() if data.get("active", True)]
    if not eligible:
        raise ValueError("Không có tài khoản sinh viên đang hoạt động để phát đề.")
    if code_exam_id and (config.get("code_only") is True or not files):
        assignments = {sid: None for sid, _ in eligible}
    elif mode == "selected":
        selected_files = config.get("exam_files") or []
        if isinstance(selected_files, str):
            selected_files = [selected_files]
        selected_files = list(dict.fromkeys(selected_files))
        if not selected_files or any(exam not in files for exam in selected_files):
            raise ValueError("Hãy chọn ít nhất một file đề hợp lệ.")
        order = selected_files[:]
        random.SystemRandom().shuffle(order)
        assignments = {sid: order[index % len(order)] for index, (sid, _) in enumerate(eligible)}
    elif mode == "parity":
        even_exam, odd_exam = config.get("even_exam"), config.get("odd_exam")
        if even_exam not in files or odd_exam not in files:
            raise ValueError("Hãy chọn file đề hợp lệ cho cả nhóm chẵn và lẻ.")
        for sid, _ in eligible:
            digit = next((c for c in reversed(sid) if c.isdigit()), None)
            if digit is None:
                raise ValueError(f"MSSV {sid} không có chữ số để xác định chẵn/lẻ.")
            assignments[sid] = even_exam if int(digit) % 2 == 0 else odd_exam
    elif mode == "custom":
        rules = {str(key).strip(): str(value).strip() for key, value in (config.get("last_digit_map", {}) or {}).items()}
        if not rules:
            raise ValueError("Chế độ tùy chỉnh cần ánh xạ chữ số cuối MSSV tới tên file đề.")
        try:
            modulus = int(config.get("custom_modulus", 10))
        except (TypeError, ValueError):
            raise ValueError("Số chia trong quy tắc tùy chỉnh không hợp lệ.")
        if not 2 <= modulus <= 10:
            raise ValueError("Số chia phải nằm trong khoảng từ 2 đến 10.")
        selected_files = list(dict.fromkeys(config.get("exam_files") or []))
        if len(selected_files) != modulus:
            raise ValueError(f"Với phép chia {modulus}, cần chọn đúng {modulus} đề.")
        if any(exam not in files for exam in selected_files):
            raise ValueError("Danh sách đề trong quy tắc tùy chỉnh không hợp lệ.")
        for digit, exam in rules.items():
            if str(digit) not in {str(i) for i in range(10)} or exam not in files:
                raise ValueError("Quy tắc tùy chỉnh chứa chữ số hoặc file đề không hợp lệ.")
        if any(str(remainder) not in {str(int(digit) % modulus) for digit in rules} for remainder in range(modulus)):
            raise ValueError("Cần cấu hình đủ tất cả các số dư.")
        for sid, _ in eligible:
            digit = next((c for c in reversed(sid) if c.isdigit()), None)
            if digit is None or str(digit) not in rules:
                raise ValueError(f"Chưa có quy tắc cho MSSV {sid}.")
            assignments[sid] = rules[str(digit)]
    else:
        # Allocate in ascending IP order within each /24; shuffle exam order and rotate
        # so adjacent addresses receive different exams whenever at least two exams exist.
        active_sessions = read_json("sessions.json")
        pool = config.get("exam_files") or files
        if isinstance(pool, str):
            pool = [pool]
        pool = list(dict.fromkeys(pool))
        if not pool or any(exam not in files for exam in pool):
            raise ValueError("Danh sách đề được chọn không hợp lệ.")
        ip_by_sid = {sid: (student.get("last_ip") or "unknown") for sid, student in students.items()}
        for token, session in active_sessions.items():
            if session.get("role") == "student":
                ip_by_sid[session.get("user_id")] = session.get("ip", "unknown")
        buckets = {}
        for sid, _ in eligible:
            ip = ip_by_sid.get(sid, "unknown")
            buckets.setdefault(_subnet_key(ip), []).append((sid, ip))
        for _, group in buckets.items():
            group.sort(key=lambda pair: (_ip_sort(pair[1]), pair[0]))
            order = pool[:]
            random.SystemRandom().shuffle(order)
            offset = random.SystemRandom().randrange(len(order)) if len(order) > 1 else 0
            order = order[offset:] + order[:offset]
            for index, (sid, _) in enumerate(group):
                assignments[sid] = order[index % len(order)]
    release_id = uuid.uuid4().hex
    created_at = utc_now()
    persisted = {sid: {"exam_file": filename, "release_id": release_id, "assigned_at": created_at, "started_at": None, "ends_at": None, "status": "assigned", "ip_at_assignment": None, **({"code_exam_id": code_exam_id} if code_exam_id else {})} for sid, filename in assignments.items()}
    # A release can be replaced while waiting to start. Once started, assignments
    # and the active release must remain immutable.
    old_settings = read_json("settings.json")
    if old_settings.get("exam_state") == "started" or old_settings.get("exam_released"):
        raise ValueError("Kỳ thi đã bắt đầu. Không thể phát hoặc đổi đề trong lúc sinh viên đang thi.")
    sessions = read_json("sessions.json")
    for sid, item in persisted.items():
        for session in sessions.values():
            if session.get("user_id") == sid and session.get("role") == "student":
                item["ip_at_assignment"] = session.get("ip")
                break
    write_json("assignments.json", persisted)
    old_settings.update({"distribution_mode": mode, "distribution_config": config, "exam_state": "distributed", "exam_released": False, "exam_release_id": release_id, "exam_release_at": created_at})
    write_json("settings.json", old_settings)
    if code_exam_id:
        attach_code_exam_to_release(code_exam_id, release_id)
    audit("exam.distributed", "admin", None, {"release_id": release_id, "mode": mode, "student_count": len(persisted), "exam_count": len(set(assignments.values()))})
    return {"release_id": release_id, "assigned_count": len(assignments), "distribution": assignments}

def start_exam(student_id: str, supplied_password: str | None = None, ip: str | None = None) -> dict:
    settings = read_json("settings.json")
    if settings.get("exam_state") != "started":
        raise ValueError("Giảng viên chưa bắt đầu kỳ thi.")
    if settings.get("exam_password_enabled"):
        if not verify_password(supplied_password or "", settings.get("exam_password_hash")):
            raise PermissionError("Mật khẩu đề thi không đúng.")
    assignments = read_json("assignments.json")
    item = assignments.get(student_id)
    if not item or item.get("release_id") != settings.get("exam_release_id"):
        raise ValueError("Bạn chưa được giao đề trong kỳ thi này.")
    if item.get("started_at"):
        return item


    now = datetime.now(timezone.utc)
    duration = max(1, min(int(settings.get("exam_duration_minutes", 90)), 24 * 60))
    item["started_at"] = now.isoformat(timespec="seconds")
    item["ends_at"] = (now + timedelta(minutes=duration)).isoformat(timespec="seconds")
    item["status"] = "in_progress"
    item["ip_at_start"] = ip or item.get("ip_at_assignment")
    assignments[student_id] = item
    write_json("assignments.json", assignments)
    audit("exam.started", student_id, ip or item.get("ip_at_assignment"), {"exam_file": item["exam_file"], "started_at": item["started_at"], "ends_at": item["ends_at"]})
    return item


def start_exam_session() -> dict:
    settings = read_json("settings.json")
    if settings.get("exam_state") != "distributed":
        raise ValueError("Cần phân phối đề trước khi bắt đầu kỳ thi.")
    release_id = settings.get("exam_release_id")
    settings.update({"exam_state": "started", "exam_released": True, "exam_started_at": utc_now()})
    write_json("settings.json", settings)
    transition_code_exam(release_id, "started")
    audit("exam.started_by_admin", "admin", None, {"release_id": settings.get("exam_release_id")})
    return settings

def remaining_seconds(item: dict) -> int:
    if not item.get("ends_at"):
        return 0
    end = datetime.fromisoformat(item["ends_at"])
    return max(0, int((end - datetime.now(timezone.utc)).total_seconds()))
