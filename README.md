# Classroom Submission Server

> **A lightweight, self-hosted Learning Management System (LMS) for exams — designed for classroom LAN use today, with a roadmap toward public web-server hosting.**

Classroom Submission Server (CSS) works like a stripped-down LMS (think Google Classroom or Moodle) focused entirely on **exam delivery and submission collection**. What sets it apart is that **the Admin sees and controls everything in real time**: live student status, time-on-task, tab-switching alerts, per-student time adjustments, forced submissions, and instant broadcast notifications — all from a single dashboard that refreshes automatically.

Currently runs on a local area network (LAN) from the instructor's machine. The next milestone is a production-ready public web-server deployment.

---

## Table of Contents

1. [Overview](#1-overview)
2. [Roadmap](#2-roadmap)
3. [Architecture](#3-architecture)
4. [Features](#4-features)
5. [Directory Structure](#5-directory-structure)
6. [Requirements](#6-requirements)
7. [Setup on Windows](#7-setup-on-windows)
8. [Setup on macOS / Linux](#8-setup-on-macos--linux)
9. [Running the Server](#9-running-the-server)
10. [First-Time Configuration](#10-first-time-configuration)
11. [Exam Workflow](#11-exam-workflow)
12. [Network & TLS](#12-network--tls)
13. [Offline Operation](#13-offline-operation)
14. [Backup & Recovery](#14-backup--recovery)
15. [Running Tests](#15-running-tests)
16. [Troubleshooting](#16-troubleshooting)
17. [Security Notes](#17-security-notes)

---

## 1. Overview

CSS is a **focused exam-delivery LMS** built for instructors who need tight control over a live exam session. Unlike general LMS platforms, it is purpose-built around the exam lifecycle:

| What a typical LMS does | What CSS adds on top |
|---|---|
| Distribute course materials | Distribute unique exam files per student (random / parity / custom rules) |
| Accept assignment uploads | Validate ZIP archives (signature, CRC, path traversal) before saving |
| Show student progress | **Live dashboard**: online status, time remaining, submission count — refreshed automatically |
| Basic role separation | **Admin real-time controls**: adjust per-student time, force-submit, broadcast notifications, lock accounts |
| Passive audit trail | **Active telemetry**: detects tab-switching, unfocused windows, and multiple open tabs |

Everything runs as a **single Python process** using only the standard library plus [Jinja2](https://jinja.palletsprojects.com/) for HTML templating. No FastAPI, Pydantic, Uvicorn, Starlette, WebSockets, MySQL, or PostgreSQL required.

> **Why no FastAPI / Pydantic?**
> Some institutional Windows environments enforce Device Guard / Application Control policies that block native extension DLLs such as `_pydantic_core`. This server was rewritten to avoid those dependencies entirely.

---

## 2. Roadmap

The project currently targets **LAN / classroom deployment**. The next milestone is a **production-ready public web server** so any student with an internet connection can participate without needing to be on the same network.

### ✅ Current (v0.x — LAN)
- Full exam workflow on a local network
- Admin dashboard with real-time monitoring and controls
- TLS support via environment variables
- Offline-capable (no CDN, no internet required at runtime)

### 🚧 In Progress / Planned (v1.x — Public Web Server)

| Feature | Status | Notes |
|---|---|---|
| Deploy behind Nginx + HTTPS (Let's Encrypt) | Planned | Nginx as reverse proxy; Certbot for TLS |
| Run as a systemd service on Linux VPS | Planned | Auto-restart, logging via journald |
| CSRF protection on all POST endpoints | Planned | Required for public internet exposure |
| Per-IP rate limiting on upload endpoints | Planned | Prevent abuse of the 50 MiB upload endpoint |
| SQLite storage backend | Planned | Replace JSON files for safe concurrent access |
| Persistent volume for `data/`, `submissions/`, `de-thi/` | Planned | Required for cloud / containerised deployments |
| Docker / container image | Planned | One-command deployment |
| Multi-session / multi-course support | Planned | Run several exam sessions in parallel |

> Contributions toward any roadmap item are welcome. See [Security Notes](#17-security-notes) for the current limitations that must be addressed before exposing the server to the public internet.

---

## 3. Architecture

| Component | Choice | Rationale |
|---|---|---|
| HTTP server | `http.server.ThreadingHTTPServer` (stdlib) | No third-party runtime dependency for the server itself |
| Form / multipart parsing | `urllib` + `email` (stdlib) | Eliminates `python-multipart` |
| HTML rendering | Jinja2 (only external runtime dep.) | Reuses existing templates; MarkupSafe ships a pure-Python fallback |
| CSS | Tailwind CSS pre-built → local `app.css` | No CDN calls at runtime |
| Icons | Font Awesome 4.7.0 (local files) | No external font loading at runtime |
| Dashboard refresh | HTTP polling every 5 seconds | No WebSocket library needed |
| Data storage | JSON / JSONL files | Simple, human-readable, easy to back up *(SQLite planned — see Roadmap)* |
| Passwords | `hashlib.scrypt` + per-user salt | Passwords are never stored in plain text |
| Sessions | Random token in `HttpOnly` cookie; only SHA-256 hash stored server-side | Leaking the session file does not expose a usable bearer token |
| Submissions | ZIP files saved to `submissions/` | Compatible with existing submission workflows |

---

## 4. Features

### Student experience
- Login with student ID; date of birth is the initial password (not stored after creation).
- Cannot see the exam file or its name before clicking **Start**.
- Optionally enter an exam password before starting (if configured by admin).
- Countdown timer displayed; `started_at` and `ends_at` are set by the **server clock** — changing the local machine clock has no effect.
- Submit a `.zip` file; the server validates the archive before saving.
- Receives broadcast notifications from the admin in real time (polled every 5 s).

### Admin real-time monitoring & control

This is where CSS goes beyond a typical LMS. The admin dashboard gives live visibility and direct control over every student during an active exam:

| Control | Description |
|---|---|
| **Live student list** | Online/offline status, last-seen timestamp, current IP, User-Agent |
| **Exam progress** | Assigned exam file, start time, time remaining (per student) |
| **Submission status** | Number of attempts, latest submission time and file hash |
| **Tab / focus telemetry** | Flags when a student switches tabs, loses window focus, or opens multiple tabs |
| **Per-student time adjustment** | Add or subtract minutes from an individual student's deadline without affecting others |
| **Force-submit** | Mark a student's exam as submitted when they cannot submit themselves |
| **Broadcast notifications** | Send a message to all students or specific students; appears on their screen within the next polling cycle |
| **Account lock / unlock** | Lock a student account mid-exam if needed |
| **Password reset** | Reset any student's password instantly |
| **End exam** | Close the current session; students can no longer start or submit |

### Account management
- Bulk import from `.txt` file or pasted text (`StudentID | DateOfBirth | FullName`).
- Duplicate detection and per-line error reporting during import.
- Create additional admin accounts.
- Full audit log: every action is recorded in `logs/audit.jsonl`.

### Exam distribution modes
- **`random`** — shuffles the exam pool; tries to give adjacent IP addresses different exams.
- **`parity`** — assigns exam A or B based on whether the last digit of the student ID is odd or even.
- **`custom`** — maps each last digit (0–9) to a specific exam file.
- Distribution is a **locked, one-way action** per session — prevents re-distribution mid-exam.

### Automatic code grading (backend API)
- Admin APIs manage question drafts, publishing, versioned updates, duplication, archiving, and safe deletion; code exams snapshot published questions.
- Student APIs support visible-only pretests, final submissions, and score visibility governed by exam state.
- Admin APIs expose full results and regrade completed submissions after an exam ends. Regrading can use the original exam snapshot or an explicitly selected latest published question version; prior grades are retained.
- Code grading runs only on Windows under Job Objects. It is currently an API/backend feature; the teacher and student web interfaces are not yet integrated.

### Submission validation
- Only `.zip` files accepted; magic bytes verified.
- Max upload: **50 MiB**. Max ZIP entries: **3,000**. Max uncompressed size: **250 MiB**.
- Path traversal and unsafe archive entries are rejected. Archive is **never extracted to disk**.

---

## 5. Directory Structure

```text
ClassroomSubmissionServer/
├── app/
│   ├── config.py            # Directories, limits, and policy constants
│   ├── accounts.py          # Account list parsing and validation
│   ├── storage.py           # Atomic JSON writes and JSONL audit log
│   ├── security.py          # Password hashing, sessions, lockout, origin check
│   ├── exams.py             # Exam scanning, distribution logic, server clock
│   ├── submissions.py       # ZIP validation and file saving
│   ├── main.py              # ThreadingHTTPServer, routing, and HTML rendering
│   ├── configure_admin.py   # Interactive admin setup helper
│   └── setup_admin.py       # First-run admin bootstrap CLI
├── templates/               # Jinja2 HTML templates (login, admin dashboard, student)
├── static/
│   ├── css/                 # Pre-built CSS (Tailwind output)
│   ├── js/                  # Client-side JavaScript
│   └── vendor/fontawesome/  # Font Awesome 4.7.0 (local copy + license)
├── data/                    # Runtime JSON data (auto-created)
├── logs/                    # audit.jsonl (auto-created)
├── de-thi/                  # Place exam files here (PDF, TXT, PNG, JPG, JPEG, GIF, WEBP)
├── submissions/             # Student ZIP submissions (auto-created)
├── tests/
│   └── test_core.py         # Unit tests
├── requirements.txt         # Jinja2 only
├── setup_windows.bat        # One-click Windows setup
├── start_windows.bat        # One-click Windows start
├── start_unix.sh            # macOS/Linux start script
├── run_server.py            # Server entry point
└── submission_server.py     # Legacy launcher alias
```

---

## 6. Requirements

- **Python 3.10 or later** (3.12 / 3.13 recommended).
- **Jinja2 ≥ 3.1, < 4** — the only runtime dependency outside the standard library.
- No database server, Node.js, or internet connection is needed once Jinja2 is installed.
- Place the project folder in a location where the running user has **write access** (e.g. `C:\ClassroomSubmissionServer\` on Windows). Avoid `Program Files` or cloud-synced folders during exams.
- **Automatic code grading (backend API, not yet integrated into the web UI): Windows with Windows Job Objects and JDK 17+ (`java` and `javac` from the same JDK).** On Windows, startup validates the JDK and stops with a clear error if it is missing or unusable. The existing ZIP submission workflow remains separate and can still run on macOS/Linux; code grading is unavailable there.

---

## 7. Setup on Windows

### Option A — Automated (recommended)

1. Extract `ClassroomServer.zip` or clone the repository.
2. Open the `ClassroomSubmissionServer` folder.
3. Double-click **`setup_windows.bat`**.
   - Creates a `.venv` virtual environment inside the project.
   - Installs Jinja2 into the venv (not the system Python).
4. When setup completes, double-click **`start_windows.bat`** to launch (see §9).

### Option B — Manual

Open **Command Prompt** in the project folder:

```bat
py -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

If `py` is not available, try `python -m venv .venv` on the first line. Always use `.venv\Scripts\python.exe -m pip`, not `pip.exe` directly.

### Offline install

If the machine has no internet access, obtain `Jinja2` and `MarkupSafe` wheels from IT and install with:

```bat
.venv\Scripts\python.exe -m pip install --no-index --find-links <wheel_folder> -r requirements.txt
```

---

## 8. Setup on macOS / Linux

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install -r requirements.txt
```

Do **not** use `sudo pip install`. Keep dependencies inside the `.venv`.

---

## 9. Running the Server

### Windows

Double-click **`start_windows.bat`**. The script will:
1. Prompt for admin credentials (or skip if already configured).
2. Start the server.
3. Wait for the health endpoint to respond.
4. Open the browser at `http://127.0.0.1:8080/login`.

Manual start:
```bat
.venv\Scripts\python.exe run_server.py
```

### macOS / Linux

```bash
chmod +x start_unix.sh
./start_unix.sh
```

Or manually:
```bash
./.venv/bin/python run_server.py
```

The terminal prints both the **local URL** (`http://127.0.0.1:8080`) and one or more **LAN URLs** (e.g. `http://192.168.1.10:8080`). Share the LAN URL with students.

### Changing the port

If port `8080` is already in use:

**Windows (PowerShell):**
```powershell
$env:CSS_PORT = "8081"
.\.venv\Scripts\python.exe run_server.py
```

**macOS / Linux:**
```bash
export CSS_PORT=8081
./.venv/bin/python run_server.py
```

To find the process using port 8080 on Windows (see §9 for the port option):
```bat
netstat -ano | findstr :8080
```
Identify the PID in the last column using Task Manager before killing it.

---

## 10. First-Time Configuration

### Create the first admin account

**Windows:**
```bat
.venv\Scripts\python.exe -m app.setup_admin
```

**macOS / Linux:**
```bash
./.venv/bin/python -m app.setup_admin
```

Enter a username and a password of at least 10 characters. Passwords are stored as a `scrypt` hash — they cannot be recovered, only reset.

### Student account template

Download the import template from the admin dashboard or find the sample at `student_accounts_template.txt`.

Each line follows the format:
```
StudentID | DateOfBirth | FullName
```

Lines starting with `#` and blank lines are ignored. Leading/trailing whitespace is trimmed automatically. The date of birth is used as the student's initial password and is **not stored** after account creation.

---

## 11. Exam Workflow

```
Admin sets up exam
       ↓
Place exam files in de-thi/
       ↓
Admin configures settings (duration, submission policy, distribution mode)
       ↓
Admin clicks "Distribute" → server assigns an exam file to each student
       ↓
Students log in → click "Start" → server records started_at and ends_at
       ↓
Students view their assigned exam and work on their submission
       ↓
Students upload a .zip file before the deadline
       ↓
Admin downloads submissions from the dashboard
       ↓
Admin clicks "End Exam" to close the session before starting a new one
```

**Key rules:**
- Exam distribution is a **one-way, locked action** — once distributed, the configuration cannot be changed and cannot be re-distributed without ending the current session.
- The server clock governs all deadlines. Client-side countdowns are display only.
- Students cannot open their exam file until they click **Start**.
- Late submissions (after `ends_at`) are rejected by the server.

### Supported exam file types
`.pdf`, `.txt`, `.png`, `.jpg`, `.jpeg`, `.gif`, `.webp`

### Submission validation
- File must be a valid `.zip` (magic bytes verified).
- Maximum upload size: **50 MiB**.
- Maximum number of ZIP entries: **3,000**.
- Maximum total uncompressed size: **250 MiB**.
- Path traversal and unsafe archive entries are rejected.
- The archive is **never extracted to disk**.

---

## 12. Network & TLS

- Allow **TCP port 8080** (or your chosen port) through the firewall on the instructor's machine — only on the Private/trusted LAN, not on the internet.
- By default the server uses **HTTP** (unencrypted). Suitable for a closed, trusted classroom LAN.

### Enabling HTTPS (optional)

Obtain a certificate and private key trusted by student machines.

**Windows (PowerShell):**
```powershell
$env:CSS_TLS_CERT = "C:\certs\server.crt"
$env:CSS_TLS_KEY  = "C:\certs\server.key"
.\.venv\Scripts\python.exe run_server.py
```

**macOS / Linux:**
```bash
export CSS_TLS_CERT="$HOME/certs/server.crt"
export CSS_TLS_KEY="$HOME/certs/server.key"
./.venv/bin/python run_server.py
```

When TLS is active, session cookies gain the `Secure` flag. Self-signed certificates will trigger browser warnings unless installed as trusted on each student machine.

---

## 13. Offline Operation

The server is **fully offline after the one-time Jinja2 installation**:

- CSS and Font Awesome are bundled locally — no CDN calls.
- The dashboard polls a local API endpoint.
- No Node.js or npm is needed to run the server. `package.json` and `tailwind.config.js` are only present for rebuilding CSS assets from source (development use only).

---

## 14. Backup & Recovery

| Path | Contents |
|---|---|
| `data/*.json` | Accounts, sessions, settings, assignments, submission metadata, lockout state |
| `logs/audit.jsonl` | Append-only event log |
| `de-thi/` | Exam source files |
| `submissions/` | Student ZIP payloads |

**Always stop the server before backing up.** Copy all four directories above to a safe location.

- Do **not** edit JSON files manually while the server is running.
- Run only **one** server instance against the same data directory. The JSON-file locking model is single-process only *(SQLite migration planned — see [Roadmap](#2-roadmap))*.

---

## 15. Running Tests

From the project root:

**Windows:**
```bat
.venv\Scripts\python.exe -m compileall app run_server.py tests
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

**macOS / Linux:**
```bash
./.venv/bin/python -m compileall app run_server.py tests
./.venv/bin/python -m unittest discover -s tests -v
```

After starting the server, visit `/health`. A healthy server responds with:
```json
{"status": "ok"}
```

**Recommended pre-exam checklist:**
1. Compile and run the unit tests (above).
2. Start the server and verify `/health`.
3. Log in as admin, import a test student account, place a sample exam file in `de-thi/`.
4. Configure the exam and distribute.
5. Log in as the test student, start the exam, and submit a sample ZIP.
6. Verify the submission appears in the admin dashboard and can be downloaded.

---

## 16. Troubleshooting

### Windows: `Application Control policy has blocked this file`

This server no longer depends on FastAPI, Pydantic, or `_pydantic_core`. If the error still appears:

1. Stop the server and delete the old `.venv`:
   ```bat
   rmdir /s /q .venv
   ```
2. Re-run `setup_windows.bat` to create a fresh environment.
3. If Device Guard / App Control still blocks Python itself or Jinja2, do **not** disable the policy, rename DLLs, or run as Administrator to bypass it. Contact IT and request that your Python environment and required packages be approved.
4. If the package index is also blocked, ask IT to provide approved wheels.

### Port already in use

Find the conflicting process (see §9), stop it, or change the port via `CSS_PORT`.

### Server started but students cannot connect

- Make sure the firewall on the instructor's machine allows inbound TCP on port 8080 for the Private network.
- Share the correct **LAN IP** printed in the terminal — not `127.0.0.1`.
- If the machine has multiple network interfaces (Wi-Fi, VPN, Docker bridge), pick the IP on the same subnet as the student machines.

### Browser shows stale content after a code update

Stop all running server instances, then restart with the correct start script. Clearing the browser cache is a secondary step; the priority is ensuring the new server process is actually running.

### `file://` URLs do not work

Always access the server via its `http://` URL. Do not open template files directly in the browser.

---

## 17. Security Notes

- **Passwords**: Stored as `scrypt` hashes with per-user salts. Admins cannot read passwords — only reset them.
- **Sessions**: A random token is placed in an `HttpOnly`, `SameSite=Strict` cookie. Only the SHA-256 hash is stored on disk, so leaking the session file does not directly yield a usable token. Sessions expire after **12 hours**.
- **Login lockout**: Three consecutive failed attempts for the same account triggers a **15-minute lockout**.
- **Single active student session**: A student logging in from a second device revokes the previous session.
- **Origin header**: Not checked on POST endpoints (for Windows/WebView compatibility). Session validation and role checks are still enforced.
- **HTTP vs. HTTPS**: HTTP is unencrypted. Use TLS if you need to protect credentials and submissions on an untrusted LAN segment.
- **Monitoring scope**: The server records IP addresses, User-Agents, login events, exam start times, and submission metadata. It does **not** monitor the student's desktop, other applications, keystrokes, or screen.
- **Upload limit**: 50 MiB per request; ZIP archives are inspected but never extracted to disk.
- **Data files**: `data/` contains hashed passwords and personal data (names, IPs). Restrict OS-level file system permissions accordingly.
- **Single process**: Do not run multiple server instances against the same data directory. JSON atomic replacement avoids partial writes within one process but does not protect against concurrent processes.
- **Public internet (current limitation)**: The server is currently hardened for a trusted LAN. Before deploying to the public internet, CSRF protection must be added to all POST endpoints and per-IP rate limiting must be applied to upload endpoints. See the [Roadmap](#2-roadmap) for the planned work items.
