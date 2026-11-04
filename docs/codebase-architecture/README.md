# Codebase architecture guide

## Project overview

Classroom Submission Server is a Python application for administering classroom exams, distributing exam files, collecting ZIP submissions, and running code-exam grading. The implementation is a single-process standard-library HTTP server, with Jinja2 for HTML templates and JSON/JSONL files plus directories for persistence. The repository also contains a Java reflection judge and Java/Python STDIO runners.

This guide is reconstructed from the checked-out source and configuration, not from claims in the root README. Detailed module paths and diagrams are indexed below. Claims are labeled **Verified**, **Inferred**, or **Unknown** where that distinction matters.

## Technology and architecture summary

- **Backend:** Python 3 source; standard-library `http.server.ThreadingHTTPServer`, `urllib`, `email`, `ssl`, `subprocess`, and `threading`.
- **Runtime dependency:** `Jinja2>=3.1,<4` (`requirements.txt`); no Python web framework.
- **Frontend:** HTML templates, local JavaScript/CSS, and locally vendored Font Awesome. `package.json` declares Tailwind CSS 3.4.17 as a build-only dependency.
- **Persistence:** JSON files under `data/`, uploads under `submissions/`, exam assets under `de-thi/`, and JSONL audit log under `logs/`. There is no relational database.
- **Network:** One HTTP(S) listener, default `0.0.0.0:8080`; browser requests and API calls use HTTP/1.1. The admin/student pages use HTTP polling, not WebSockets.
- **Execution:** Code-exam requests invoke process runners. Windows Job Objects are used for process resource limits; current documentation and startup checks identify code grading as Windows/JDK-specific.

## Main components and entry points

| Component | Responsibility |
|---|---|
| [`app/main.py`](../../app/main.py) | Import-time storage initialization, `Handler`, request parsing/authentication, page/API routing, response generation, optional TLS wrapping, server startup. |
| [`app/security.py`](../../app/security.py) | Password hashing, session token persistence/verification, login lockout, role checks and client-IP handling. |
| [`app/storage.py`](../../app/storage.py) | JSON/JSONL persistence, atomic file replacement, one-process `RLock`, audit records. |
| [`app/exams.py`](../../app/exams.py) | Exam distribution and student start/deadline state. |
| [`app/submissions.py`](../../app/submissions.py) | ZIP validation, upload storage, attempt metadata and audit. |
| [`app/questions.py`](../../app/questions.py), [`app/code_exams.py`](../../app/code_exams.py) | Question bank, immutable exam question snapshots, code-exam lifecycle, execution orchestration and result persistence. |
| [`app/code_runner.py`](../../app/code_runner.py), [`app/java_runner.py`](../../app/java_runner.py), [`app/windows_job.py`](../../app/windows_job.py) | STDIO and reflection evaluation, process management, and Windows process limits. |
| [`app/grading.py`](../../app/grading.py) | Result validation and point aggregation; does not execute programs. |

`run_server.py` imports `app.main.main`; `submission_server.py` is a compatibility entry point that delegates to `run_server.py`. On Windows, `start_windows.bat` invokes `app.configure_admin` before starting `run_server.py`; `start_unix.sh` invokes the project virtualenv directly. See [runtime details](07-runtime-and-resource-management.md).

## Network architecture (verified)

The browser is the client and the Python process is the server. `Handler` subclasses `BaseHTTPRequestHandler`; `do_GET`/`do_POST` perform in-function path matching and call domain modules directly. Request bodies accepted by the parser are URL-encoded forms, multipart forms, or JSON objects, subject to the 50 MiB request cap. Responses are HTML, JSON, files, or redirects. Optional TLS is enabled only when both `CSS_TLS_CERT` and `CSS_TLS_KEY` are provided.

There is no custom TCP protocol, separate client/server application, WebSocket endpoint, connection pool, heartbeat protocol, or reconnect logic. Browser status and dashboard updates are HTTP polling. The listener creates a thread per request; the code-runner subsystem separately limits concurrent code executions.

## Important state and data structures

- `students.json`, `admins.json`, `sessions.json`, `login_attempts.json`: accounts, hashed session tokens and login throttling.
- `settings.json`, `assignments.json`, `notifications.json`: exam settings/lifecycle, student assignments and notifications.
- `submissions.json` plus files in `submissions/`: ZIP attempt metadata and retained payloads.
- `questions.json`, `code_exams.json`, `code_submissions.json`, `code_runs.json`: coding question definitions/snapshots, exam data, final submissions and pretest history.
- `audit.jsonl`: append-only event records.

These are application-managed JSON structures, not database tables or cross-process transactions. See [data architecture](06-data-architecture.md).

## Documentation map

- [Project structure and stack](01-project-structure-and-tech-stack.md)
- [System architecture](02-system-architecture.md)
- [Module and dependency analysis](03-module-and-dependency-analysis.md)
- [Execution paths](04-code-logic-and-execution-paths.md)
- [Network architecture](05-network-architecture.md)
- [Data architecture](06-data-architecture.md)
- [Runtime and resources](07-runtime-and-resource-management.md)
- [Technical observations and unknowns](08-code-quality-and-technical-observations.md)
- [Source-code index](09-source-code-index.md)
- [Mermaid diagrams](diagrams/)

## Caveats for future code analysis

1. The root README and specification are supplementary; verify current route and feature behavior against `app/main.py` and the domain modules. The code-grading backend is present even though older documents describe it as not yet integrated into the UI.
2. HTTP handlers and business/domain operations are concentrated in `app/main.py`; routes are not registered through a separate router abstraction.
3. JSON locking is process-local. Do not assume safe multi-process or multi-instance concurrent writes.
4. `ThreadingHTTPServer` allows concurrent HTTP requests, but its threads are daemon threads. Code-run concurrency is separately limited by `CSS_MAX_CONCURRENT_CODE_RUNS` (default 2, bounded 1..16).
5. In this checkout, `data/admins.json` and `data/sessions.json` are modified and `investigation task.md` is untracked. This investigation did not read or edit those data files.

## Unknowns / questions for a runtime owner

- The supported Python version is not declared in a `pyproject.toml` or equivalent manifest.
- TLS termination, trusted proxy behavior, firewall exposure, and deployment topology are environment-specific and not established by source.
- Linux/macOS code-execution behavior is explicitly unavailable/not verified in the project docs; the Windows Job Object code is platform-specific.
- The runtime persistence/backup/recovery behavior under abrupt power loss or simultaneous server processes has not been exercised here.
- Whether every UI control described in root-level documents remains reachable should be confirmed against live browser behavior; this document only establishes the route/backend and checked-in frontend code.
