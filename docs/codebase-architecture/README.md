# Codebase architecture guide

> Reconciled against the source tree on 2026-11-22. The repository currently has 22 Python files under `app/` (including `__init__.py`), 14 frontend JavaScript files, 6 templates, and 27 checked-in test files. These are checkout counts, not capacity or coverage guarantees. See the [documentation index](../README.md).

## Project overview

Classroom Submission Server is a Python application for managing accounts, questions, Practice, Papers, ZIP/file exams, code exams, releases/assignments, grading and regrading, results, exam monitoring, and code-exam completion. The implementation is a threaded standard-library HTTP server, with Jinja2 templates, local browser assets, and JSON/JSONL/file persistence. The repository also contains a Java reflection judge and Java/Python STDIO runners.

This guide is reconstructed from the checked-out source and configuration, not from claims in the root README. Detailed module paths and runtime maps are indexed below; separate diagram files referenced by older drafts are not present in this checkout. Claims are labeled **Verified**, **Inferred**, or **Unknown** where that distinction matters.

## Technology and architecture summary

- **Backend:** Python 3 source; standard-library `http.server.ThreadingHTTPServer`, `urllib`, `email`, `ssl`, `subprocess`, and `threading`.
- **Runtime dependency:** `Jinja2>=3.1,<4` (`requirements.txt`); no Python web framework.
- **Frontend:** HTML templates, local JavaScript/CSS, and locally vendored Font Awesome. `package.json` declares Tailwind CSS 3.4.17 as a build-only dependency.
- **Persistence:** JSON files under `data/`, uploads under `submissions/`, exam assets under `de-thi/`, and JSONL audit log under `logs/`. There is no relational database.
- **Network:** One HTTP(S) listener, default `0.0.0.0:8080`; browser requests and API calls use HTTP/1.1. The admin/student pages use HTTP polling, not WebSockets.
- **Execution:** Code-exam requests invoke process runners. Windows Job Objects are used for process resource limits; current documentation and startup checks identify code grading as Windows/JDK-specific.
- **Monitoring/completion:** Active-attempt telemetry snapshots and per-Student/release monitoring events are persisted separately from session presence; code-exam draft checkpoints and finalization are also server-side.

## Main components and entry points

| Component | Responsibility |
|---|---|
| [`app/main.py`](../../app/main.py) | Import-time storage initialization, `Handler`, request parsing/authentication, page/API routing, response generation, optional TLS wrapping, server startup. |
| [`app/security.py`](../../app/security.py) | Password hashing, session token persistence/verification, login lockout, role checks and client-IP handling. |
| [`app/storage.py`](../../app/storage.py) | JSON/JSONL persistence, atomic file replacement, one-process `RLock`, audit records. |
| [`app/exams.py`](../../app/exams.py) | Exam distribution and student start/deadline state. |
| [`app/submissions.py`](../../app/submissions.py) | ZIP validation, upload storage, attempt metadata and audit. |
| [`app/questions.py`](../../app/questions.py), [`app/papers.py`](../../app/papers.py), [`app/general_exams.py`](../../app/general_exams.py), [`app/code_exams.py`](../../app/code_exams.py) | Question bank, independent and legacy Paper records, releases, assignments, code-exam snapshots, execution orchestration and result persistence. |
| [`app/practice.py`](../../app/practice.py), [`app/exam_completion.py`](../../app/exam_completion.py), [`app/exam_monitoring.py`](../../app/exam_monitoring.py) | Practice access/run, server-side code-exam completion, and attempt-scoped monitoring events. |
| [`app/code_runner.py`](../../app/code_runner.py), [`app/java_runner.py`](../../app/java_runner.py), [`app/windows_job.py`](../../app/windows_job.py) | STDIO and reflection evaluation, process management, and Windows process limits. |
| [`app/grading.py`](../../app/grading.py) | Result validation and point aggregation; does not execute programs. |

`run_server.py` imports `app.main.main`; `submission_server.py` is a compatibility entry point that delegates to `run_server.py`. On Windows, `start_windows.bat` invokes `app.configure_admin` before starting `run_server.py`; `start_unix.sh` invokes the project virtualenv directly. See section 7 in [the consolidated architecture guide](codebase-architecture.md#7-runtime-and-resource-management).

## Network architecture (verified)

The browser is the client and the Python process is the server. `Handler` subclasses `BaseHTTPRequestHandler`; `do_GET`/`do_POST` perform in-function path matching and call domain modules directly. Request bodies accepted by the parser are URL-encoded forms, multipart forms, or JSON objects, subject to the 50 MiB request cap. Responses are HTML, JSON, files, or redirects. Optional TLS is enabled only when both `CSS_TLS_CERT` and `CSS_TLS_KEY` are provided.

There is no custom TCP protocol, separate client/server application, WebSocket endpoint, or connection pool. The Student client polls status over HTTP and sends telemetry snapshots/events over ordinary HTTP while an attempt is active; admin dashboards poll for updates. The listener creates a thread per request; the code-runner subsystem separately limits concurrent code executions.

## Important state and data structures

- `students.json`, `admins.json`, `sessions.json`, `login_attempts.json`: accounts, hashed session tokens and login throttling.
- `settings.json`, `assignments.json`, `notifications.json`: exam settings/lifecycle, student assignments and notifications.
- `submissions.json` plus files in `submissions/`: ZIP attempt metadata and retained payloads.
- `questions.json`, `code_exams.json`, `code_submissions.json`, `code_runs.json`: coding question definitions/snapshots, exam data, final submissions and pretest history.
- `papers.json`, `exams.json`, `practice_progress.json`, `code_attempts.json`, `exam_monitoring.json`: Paper/Exam state, Practice progress, server-side code drafts/finalization, and per-attempt monitoring event history.
- `audit.jsonl`: append-only event records.

These are application-managed JSON structures, not database tables or cross-process transactions. See section 6 in [the consolidated architecture guide](codebase-architecture.md#6-data-architecture).

## Documentation map

- [Detailed codebase architecture](codebase-architecture.md) — consolidated sections 1–9; separate chapter and diagram files linked by older drafts are not present in this checkout.
- [Project context](../PROJECT_CONTEXT.md), [current architecture](../ARCHITECTURE.md), and [Code Exam API](../CODE_EXAM_API.md) — current product and API references.
- [Known Issues](../KNOWN_ISSUES.md) — implementation limits and verification gaps.
- [Documentation index](../README.md) — all documents and historical-report status.

## Caveats for future code analysis

1. The root README and specification are supplementary; verify current route and feature behavior against `app/main.py` and the domain modules. Code grading, Practice, Paper distribution, monitoring, and server-side completion are present in this checkout.
2. HTTP handlers and business/domain operations are concentrated in `app/main.py`; routes are not registered through a separate router abstraction.
3. JSON locking is process-local. Do not assume safe multi-process or multi-instance concurrent writes.
4. `ThreadingHTTPServer` allows concurrent HTTP requests, but its threads are daemon threads. Code-run concurrency is separately limited by `CSS_MAX_CONCURRENT_CODE_RUNS` (default 2, bounded 1..16).
5. Runtime JSON files may contain live classroom state; document data shapes and behavior without copying records or credentials.

## Unknowns / questions for a runtime owner

- The supported Python version is not declared in a `pyproject.toml` or equivalent manifest.
- TLS termination, trusted proxy behavior, firewall exposure, and deployment topology are environment-specific and not established by source.
- Linux/macOS code-execution behavior is explicitly unavailable/not verified in the project docs; the Windows Job Object code is platform-specific.
- The runtime persistence/backup/recovery behavior under abrupt power loss or simultaneous server processes has not been exercised here.
- Whether every UI control described in root-level documents remains reachable should be confirmed against live browser behavior; this document only establishes the route/backend and checked-in frontend code.
