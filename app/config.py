from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
LOG_DIR = BASE_DIR / "logs"
EXAM_DIR = BASE_DIR / "de-thi"
UPLOAD_DIR = BASE_DIR / "submissions"
STATIC_DIR = BASE_DIR / "static"
TEMPLATE_DIR = BASE_DIR / "templates"
HOST = os.getenv("CSS_HOST", "0.0.0.0")
PORT = int(os.getenv("CSS_PORT", "8080"))
MAX_REQUEST_SIZE = 50 * 1024 * 1024
MAX_ZIP_ENTRIES = 3000
MAX_UNCOMPRESSED_SIZE = 250 * 1024 * 1024
SESSION_COOKIE = "css_session"
SESSION_TTL_SECONDS = 12 * 60 * 60
LOCKOUT_SECONDS = 15 * 60
MAX_FAILED_LOGINS = 3
ALLOWED_EXAM_EXTENSIONS = {".pdf", ".txt", ".png", ".jpg", ".jpeg", ".gif", ".webp"}
for path in (DATA_DIR, LOG_DIR, EXAM_DIR, UPLOAD_DIR, STATIC_DIR, TEMPLATE_DIR):
    path.mkdir(parents=True, exist_ok=True)
