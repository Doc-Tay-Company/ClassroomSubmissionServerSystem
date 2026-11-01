"""Configure an administrator from the Windows start console."""
from __future__ import annotations

from getpass import getpass

from .security import hash_password
from .storage import audit, initialize, read_json, utc_now, write_json


def main() -> None:
    initialize()
    admins = read_json("admins.json")
    students = read_json("students.json")
    current = next(iter(admins), None)

    print()
    print("=== Cau hinh tai khoan Admin ===")
    if current:
        print(f"Admin hien tai: {current}")
        username = input("Ten dang nhap (Enter de giu nguyen): ").strip() or current
    else:
        username = input("Ten dang nhap Admin: ").strip()

    if not username or len(username) > 80 or not all(c.isalnum() or c in "._-@" for c in username):
        raise SystemExit("Ten tai khoan Admin khong hop le.")
    if username in students:
        raise SystemExit("Ten tai khoan da duoc su dung cho sinh vien.")

    password = getpass("Mat khau moi (Enter de giu nguyen): ")
    if not password and username in admins:
        print("Giu nguyen cau hinh Admin.")
        return
    if len(password) < 10 or len(password) > 200:
        raise SystemExit("Mat khau Admin phai dai tu 10 den 200 ky tu.")
    confirm = getpass("Nhap lai mat khau: ")
    if password != confirm:
        raise SystemExit("Mat khau khong khop.")

    created = username not in admins
    record = admins.get(username, {})
    record.update({
        "username": username,
        "password_hash": hash_password(password),
        "active": True,
        "created_at": record.get("created_at", utc_now()),
        "created_by": record.get("created_by", "windows-start"),
    })
    admins[username] = record
    write_json("admins.json", admins)
    audit("setup.admin_configured", username, "127.0.0.1", {"created": created})
    print(f"Da luu cau hinh Admin: {username}")


if __name__ == "__main__":
    main()
