```

"""
Classroom Submission Server
===========================
LAN-based exam viewer and assignment submission server.

Requirements:
    Python 3.9+
    No third-party packages required.

Run:
    python submission_server.py

Default address:
    http://127.0.0.1:8000

Folders:
    de-thi/       Exam files
    submissions/  Uploaded student assignments
"""

import html
import re
import uuid
import mimetypes

from datetime import datetime
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlparse


# ============================================================
# 1. CONFIGURATION
# ============================================================

HOST = "0.0.0.0"
PORT = 8000

BASE_DIR = Path(__file__).resolve().parent
EXAM_DIR = BASE_DIR / "de-thi"
UPLOAD_DIR = BASE_DIR / "submissions"

# Maximum size of the entire HTTP request, including form overhead.
MAX_REQUEST_SIZE = 50 * 1024 * 1024

# Maximum size of an original filename.
MAX_FILENAME_LENGTH = 150

# Supported exam formats.
ALLOWED_EXAM_EXTENSIONS = {
    ".pdf",
    ".txt",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
}

# Student IDs may contain letters, numbers, underscores and hyphens.
STUDENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,30}$")

EXAM_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# 2. HTML PAGE
# ============================================================

HTML_PAGE = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Classroom Submission Server</title>

<style>
* {
    box-sizing: border-box;
}

body {
    margin: 0;
    padding: 24px 14px;
    background: #f1f5f9;
    color: #1e293b;
    font-family: Arial, Helvetica, sans-serif;
}

.container {
    max-width: 850px;
    margin: 20px auto;
}

.header {
    padding: 28px;
    background: #1e3a8a;
    color: white;
    border-radius: 12px 12px 0 0;
}

.header h1 {
    margin: 0 0 10px;
}

.header p {
    margin-bottom: 0;
    line-height: 1.6;
}

.card {
    margin-bottom: 20px;
    padding: 25px;
    background: white;
    border-radius: 0 0 12px 12px;
    box-shadow: 0 4px 18px rgba(15, 23, 42, 0.06);
}

.card + .card {
    border-radius: 12px;
}

h2 {
    margin-top: 0;
    color: #1d4ed8;
}

label {
    display: block;
    margin: 18px 0 8px;
    font-weight: bold;
}

input[type="text"],
input[type="file"] {
    width: 100%;
    padding: 12px;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    background: white;
}

button {
    width: 100%;
    margin-top: 22px;
    padding: 14px;
    border: 0;
    border-radius: 6px;
    background: #2563eb;
    color: white;
    font-size: 16px;
    font-weight: bold;
    cursor: pointer;
}

button:hover {
    background: #1d4ed8;
}

.exam-list {
    padding-left: 0;
    list-style: none;
}

.exam-list li {
    margin: 10px 0;
    padding: 14px;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    overflow-wrap: anywhere;
}

.exam-list a {
    color: #1d4ed8;
    text-decoration: none;
    font-weight: bold;
}

.exam-list a:hover {
    text-decoration: underline;
}

.exam-type {
    display: block;
    margin-top: 5px;
    color: #64748b;
    font-size: 12px;
    font-weight: normal;
}

.notice {
    margin-top: 18px;
    padding: 13px;
    background: #eff6ff;
    color: #1e40af;
    border-radius: 6px;
    line-height: 1.6;
}

.footer {
    padding: 15px;
    color: #64748b;
    font-size: 12px;
    text-align: center;
}

@media (max-width: 600px) {
    .header, .card {
        padding: 20px;
    }

    .header h1 {
        font-size: 24px;
    }
}
</style>
</head>

<body>
<div class="container">

    <header class="header">
        <h1>Classroom Submission Server</h1>
        <p>
            View examination materials and submit your assignment
            through the classroom local network.
        </p>
    </header>

    <section class="card">
        <h2>Available Exams</h2>
        <p>Select an exam file below to open it in your browser.</p>

        {{EXAM_LIST}}
    </section>

    <section class="card">
        <h2>Submit Assignment</h2>

        <form action="/submit" method="post"
              enctype="multipart/form-data">

            <label for="student_id">Student ID</label>

            <input
                type="text"
                id="student_id"
                name="student_id"
                maxlength="30"
                pattern="[A-Za-z0-9_-]{1,30}"
                title="Use 1-30 letters, numbers, underscores or hyphens."
                autocomplete="off"
                required
            >

            <label for="assignment">Assignment File</label>

            <input
                type="file"
                id="assignment"
                name="assignment"
                required
            >

            <button type="submit">Submit Assignment</button>
        </form>

        <div class="notice">
            Check your student ID and selected file before submitting.
            Wait for the confirmation page after uploading.
        </div>
    </section>

    <footer class="footer">
        Classroom LAN Submission Service
    </footer>

</div>
</body>
</html>
"""


# ============================================================
# 3. EXAM FILE FUNCTIONS
# ============================================================

def get_exam_files():
    """Return supported exam files in the exam directory."""

    files = []

    try:
        for path in EXAM_DIR.iterdir():
            if not path.is_file():
                continue

            if path.suffix.lower() not in ALLOWED_EXAM_EXTENSIONS:
                continue

            # Do not expose symbolic links.
            if path.is_symlink():
                continue

            files.append(path)

    except OSError as exc:
        print(f"[ERROR] Cannot list exam files: {exc}")

    return sorted(files, key=lambda item: item.name.lower())


def make_exam_list():
    """Generate a safe HTML list of available exam files."""

    files = get_exam_files()

    if not files:
        return (
            '<p>No exam files are available.</p>'
            '<p>Please contact the lecturer.</p>'
        )

    items = []

    for path in files:
        filename = html.escape(path.name)
        extension = path.suffix.upper().lstrip(".")

        # URL-encode the filename so spaces and special characters work.
        file_url = "/exams/" + quote(path.name, safe="")

        items.append(
            '<li>'
            f'<a href="{file_url}" target="_blank" '
            'rel="noopener noreferrer">'
            f'{filename}'
            '</a>'
            f'<span class="exam-type">{extension} document</span>'
            '</li>'
        )

    return '<ul class="exam-list">' + "".join(items) + "</ul>"


# ============================================================
# 4. UPLOAD FUNCTIONS
# ============================================================

def sanitize_filename(filename):
    """Remove path components and unsafe filename characters."""

    filename = filename.replace("\\", "/").split("/")[-1]

    filename = re.sub(
        r'[\x00-\x1f<>:"|?*]',
        "_",
        filename
    )

    filename = filename.strip().strip(".")

    if not filename:
        filename = "uploaded_file"

    return filename[:MAX_FILENAME_LENGTH]


def make_result_page(title, message, success=False):
    """Generate a result page with escaped content."""

    color = "#15803d" if success else "#b91c1c"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>
body {{
    margin: 0;
    padding: 24px 14px;
    background: #f1f5f9;
    font-family: Arial, Helvetica, sans-serif;
}}
.box {{
    max-width: 650px;
    margin: 30px auto;
    padding: 28px;
    background: white;
    border-radius: 12px;
}}
h1 {{ color: {color}; }}
p {{ line-height: 1.7; overflow-wrap: anywhere; }}
a {{ color: #2563eb; }}
</style>
</head>
<body>
<main class="box">
<h1>{html.escape(title)}</h1>
<p>{html.escape(message)}</p>
<p><a href="/">Return to the main page</a></p>
</main>
</body>
</html>"""


# ============================================================
# 5. HTTP REQUEST HANDLER
# ============================================================

class SubmissionHandler(BaseHTTPRequestHandler):
    """Handle exam viewing and assignment submissions."""

    server_version = "ClassroomSubmissionServer"
    sys_version = ""

    def log_message(self, format_string, *args):
        message = format_string % args

        print(
            f"[{self.log_date_time_string()}] "
            f"{self.client_address[0]} - {message}"
        )

    def send_html(self, status_code, content):
        body = content.encode("utf-8")

        self.send_response(status_code)
        self.send_header(
            "Content-Type",
            "text/html; charset=utf-8"
        )
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

        self.wfile.write(body)

    def do_GET(self):
        """Serve the home page or an exam file."""

        path = urlparse(self.path).path

        if path == "/":
            page = HTML_PAGE.replace(
                "{{EXAM_LIST}}",
                make_exam_list()
            )

            self.send_html(200, page)
            return

        if path.startswith("/exams/"):
            self.serve_exam(path)
            return

        self.send_html(
            404,
            make_result_page(
                "Page Not Found",
                "The requested page does not exist."
            )
        )

    def serve_exam(self, request_path):
        """Serve only supported files directly inside EXAM_DIR."""

        encoded_name = request_path[len("/exams/"):]
        filename = unquote(encoded_name)

        # Reject empty names and directory traversal.
        if (
            not filename
            or filename in {".", ".."}
            or "/" in filename
            or "\\" in filename
        ):
            self.send_html(
                403,
                make_result_page(
                    "Forbidden",
                    "Invalid exam file path."
                )
            )
            return

        exam_path = EXAM_DIR / filename

        try:
            # Do not follow symbolic links.
            if exam_path.is_symlink():
                raise PermissionError("Symbolic links are not allowed.")

            resolved_path = exam_path.resolve(strict=True)

            if resolved_path.parent != EXAM_DIR.resolve():
                raise PermissionError("Invalid exam directory.")

            if not resolved_path.is_file():
                raise FileNotFoundError("Exam file not found.")

            if resolved_path.suffix.lower() not in ALLOWED_EXAM_EXTENSIONS:
                raise PermissionError("File type not allowed.")

            data = resolved_path.read_bytes()

        except FileNotFoundError:
            self.send_html(
                404,
                make_result_page(
                    "Exam Not Found",
                    "The requested exam file does not exist."
                )
            )
            return

        except (OSError, PermissionError):
            self.send_html(
                403,
                make_result_page(
                    "Access Denied",
                    "The requested exam file cannot be accessed."
                )
            )
            return

        content_type = mimetypes.guess_type(resolved_path.name)[0]

        if not content_type:
            content_type = "application/octet-stream"

        # Treat text files as UTF-8.
        if resolved_path.suffix.lower() == ".txt":
            content_type = "text/plain; charset=utf-8"

        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Disposition", "inline")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

        self.wfile.write(data)

        print(f"[EXAM] Viewed: {resolved_path.name}")

    def do_POST(self):
        """Receive and save a student assignment."""

        path = urlparse(self.path).path

        if path != "/submit":
            self.send_html(
                404,
                make_result_page(
                    "Page Not Found",
                    "The requested endpoint does not exist."
                )
            )
            return

        content_length = self.headers.get("Content-Length")

        if content_length is None:
            self.send_html(
                411,
                make_result_page(
                    "Invalid Request",
                    "Content-Length is required."
                )
            )
            return

        try:
            request_size = int(content_length)
        except ValueError:
            self.send_html(
                400,
                make_result_page(
                    "Invalid Request",
                    "Invalid Content-Length."
                )
            )
            return

        if request_size <= 0:
            self.send_html(
                400,
                make_result_page(
                    "Invalid Request",
                    "The request body is empty."
                )
            )
            return

        if request_size > MAX_REQUEST_SIZE:
            self.send_html(
                413,
                make_result_page(
                    "File Too Large",
                    "The request exceeds the 50 MiB limit."
                )
            )
            return

        content_type = self.headers.get("Content-Type", "")

        if not content_type.lower().startswith("multipart/form-data"):
            self.send_html(
                415,
                make_result_page(
                    "Unsupported Request",
                    "Please use the assignment submission form."
                )
            )
            return

        try:
            body = self.rfile.read(request_size)

            if len(body) != request_size:
                self.send_html(
                    400,
                    make_result_page(
                        "Incomplete Upload",
                        "The upload was incomplete. Please try again."
                    )
                )
                return

            # Parse multipart form data using Python's standard library.
            message_bytes = (
                b"Content-Type: "
                + content_type.encode("latin-1")
                + b"\r\nMIME-Version: 1.0\r\n\r\n"
                + body
            )

            message = BytesParser(
                policy=policy.default
            ).parsebytes(message_bytes)

            if not message.is_multipart():
                raise ValueError("Invalid multipart form data.")

            student_id = None
            uploaded_filename = None
            uploaded_data = None

            for part in message.iter_parts():
                if part.get_content_disposition() != "form-data":
                    continue

                field_name = part.get_param(
                    "name",
                    header="content-disposition"
                )

                filename = part.get_filename()

                if field_name == "student_id" and filename is None:
                    raw_value = part.get_payload(decode=True) or b""

                    charset = part.get_content_charset() or "utf-8"

                    student_id = raw_value.decode(
                        charset,
                        errors="replace"
                    ).strip()

                elif field_name == "assignment" and filename is not None:
                    uploaded_filename = sanitize_filename(filename)
                    uploaded_data = part.get_payload(decode=True)

            if (
                not student_id
                or not STUDENT_ID_PATTERN.fullmatch(student_id)
            ):
                self.send_html(
                    400,
                    make_result_page(
                        "Invalid Student ID",
                        "Use 1-30 letters, numbers, underscores or hyphens."
                    )
                )
                return

            if uploaded_data is None or not uploaded_filename:
                self.send_html(
                    400,
                    make_result_page(
                        "Missing File",
                        "Please select an assignment file."
                    )
                )
                return

            if len(uploaded_data) == 0:
                self.send_html(
                    400,
                    make_result_page(
                        "Empty File",
                        "The selected file is empty."
                    )
                )
                return

            timestamp = datetime.now().strftime(
                "%Y%m%d-%H%M%S-%f"
            )

            unique_suffix = uuid.uuid4().hex[:8]

            saved_filename = (
                f"{student_id}_{timestamp}_"
                f"{unique_suffix}_{uploaded_filename}"
            )

            saved_path = UPLOAD_DIR / saved_filename

            # Exclusive creation prevents overwriting existing files.
            with saved_path.open("xb") as output_file:
                output_file.write(uploaded_data)

            print(
                f"[UPLOAD] Student ID: {student_id} | "
                f"File: {saved_filename} | "
                f"Size: {len(uploaded_data)} bytes"
            )

            self.send_html(
                200,
                make_result_page(
                    "Submission Successful",
                    f"Your file has been received. "
                    f"Student ID: {student_id}. "
                    f"Saved filename: {saved_filename}. "
                    f"Please keep this page as confirmation.",
                    success=True
                )
            )

        except (BrokenPipeError, ConnectionResetError):
            print("[WARNING] Client disconnected during upload.")

        except Exception as exc:
            print(f"[ERROR] Upload failed: {exc}")

            try:
                self.send_html(
                    500,
                    make_result_page(
                        "Submission Failed",
                        "The server could not save your file. "
                        "Please contact the lecturer."
                    )
                )
            except (BrokenPipeError, ConnectionResetError):
                pass


# ============================================================
# 6. SERVER STARTUP
# ============================================================

def main():
    """Start the classroom submission server."""

    print("=" * 60)
    print("CLASSROOM SUBMISSION SERVER")
    print("=" * 60)
    print(f"Server port : {PORT}")
    print(f"Exam folder : {EXAM_DIR}")
    print(f"Upload folder: {UPLOAD_DIR}")
    print(f"Request limit: {MAX_REQUEST_SIZE // (1024 * 1024)} MiB")
    print()
    print(f"Local URL: http://127.0.0.1:{PORT}")
    print("LAN URL  : http://<LECTURER_IP>:8000")
    print()
    print("Press Ctrl+C to stop the server.")
    print("=" * 60)

    try:
        server = ThreadingHTTPServer(
            (HOST, PORT),
            SubmissionHandler
        )
    except OSError as exc:
        print(f"[ERROR] Could not start server: {exc}")
        print("Check whether port 8000 is already in use.")
        return

    server.daemon_threads = True

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server...")
    finally:
        server.server_close()
        print("Server stopped.")


if __name__ == "__main__":
    main()
```