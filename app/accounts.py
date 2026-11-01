"""Validation and parsing helpers for student account imports."""
from __future__ import annotations


def parse_accounts(text: str) -> tuple[list[dict[str, str]], list[dict[str, object]]]:
    parsed: list[dict[str, str]] = []
    errors: list[dict[str, object]] = []
    seen: set[str] = set()

    for line_no, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [part.strip() for part in line.split("|")]
        if len(parts) != 3:
            errors.append({"line": line_no, "message": "Cần đúng 3 trường: MSSV|Ngày sinh|Họ tên."})
            continue
        sid, dob, name = parts
        if not sid or len(sid) > 30 or not all(c.isalnum() or c in "_-" for c in sid):
            errors.append({"line": line_no, "message": "MSSV rỗng hoặc chứa ký tự không hợp lệ."})
            continue
        if not dob or not name:
            errors.append({"line": line_no, "message": "Ngày sinh và họ tên không được để trống."})
            continue
        if sid in seen:
            errors.append({"line": line_no, "message": f"MSSV {sid} bị lặp trong nội dung nhập."})
            continue
        seen.add(sid)
        parsed.append({"student_id": sid, "dob": dob, "full_name": name})

    return parsed, errors
