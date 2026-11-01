"""Create the first administrator interactively. Run: python -m app.setup_admin"""
from getpass import getpass
from .storage import initialize, read_json, write_json, utc_now, audit
from .security import hash_password


def main():
    initialize()
    admins = read_json("admins.json")
    username = input("Tên tài khoản Admin đầu tiên: ").strip()
    if not username or len(username) > 80 or not all(c.isalnum() or c in "._-@" for c in username):
        raise SystemExit("Tên tài khoản không hợp lệ.")
    if username in admins or username in read_json("students.json"):
        raise SystemExit("Tài khoản đã tồn tại.")
    password = getpass("Mật khẩu Admin (tối thiểu 10 ký tự): ")
    confirm = getpass("Nhập lại mật khẩu: ")
    if len(password) < 10 or password != confirm:
        raise SystemExit("Mật khẩu không khớp hoặc ngắn hơn 10 ký tự.")
    admins[username] = {"username": username, "password_hash": hash_password(password), "active": True, "created_at": utc_now(), "created_by": "bootstrap"}
    write_json("admins.json", admins)
    audit("setup.first_admin_created", username, "127.0.0.1", {})
    print(f"Đã tạo Admin {username}. Mật khẩu không được lưu dạng văn bản thuần.")

if __name__ == "__main__":
    main()
