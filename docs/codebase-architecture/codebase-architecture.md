# 1. Project structure and technology stack

## Repository map

```text
app/                 Python server, routes, domain modules, storage, runners
assets/              Tailwind input stylesheet
data/                Runtime JSON application state (do not treat records as source schema)
de-thi/              Exam files served from the application
docs/                Existing technical notes and this architecture package
judge/               Java ReflectionJudge command-line helper
logs/                Runtime JSONL audit log
static/              Browser JavaScript, CSS, local icon CSS/fonts
submissions/         Uploaded student files
templates/           Jinja2 login, student, admin, and base HTML templates
tests/               unittest API, business, runner, grading and Windows-job tests
```

The repository root also contains startup scripts, `run_server.py`, the compatibility `submission_server.py`, `requirements.txt`, `package.json`, `tailwind.config.js`, `SPECIFICATION.md`, and README documents.

## Entry points and setup

| Path | Role |
|---|---|
| [`run_server.py`](../../run_server.py) | Canonical Python script entry point: imports and calls `app.main.main()`. |
| [`submission_server.py`](../../submission_server.py) | Legacy-named compatibility entry point delegating to `run_server.main`. |
| [`start_windows.bat`](../../start_windows.bat) | Requires `.venv`, runs `python -m app.configure_admin`, starts the server and polls `/health`. |
| [`start_unix.sh`](../../start_unix.sh) | Requires `.venv/bin/python`, then executes `run_server.py`. |
| [`setup_windows.bat`](../../setup_windows.bat) | Creates `.venv` if absent and installs `requirements.txt`. |
| [`app/setup_admin.py`](../../app/setup_admin.py) | Interactive first-admin bootstrap (`python -m app.setup_admin`). |
| [`app/configure_admin.py`](../../app/configure_admin.py) | Interactive Windows-start admin configuration. |

`app.main` calls `storage.initialize()` during module import, before `main()` creates the listening server. `app.config` resolves paths relative to the repository and creates runtime directories as it is imported.

## Technologies and dependencies

| Area | Evidence-based implementation |
|---|---|
| Python backend | Standard library HTTP server, sockets for local-address discovery, `ssl`, standard `email` multipart parser, JSON, files, threads, and subprocess APIs. No framework is declared. |
| Python runtime package | `requirements.txt` declares only `Jinja2>=3.1,<4`; templates use it for server-side HTML rendering. |
| Browser frontend | Jinja2 templates plus `static/js/*.js` and `static/css/app.css`. The code paths inspected do not identify a frontend framework or package manager build for JS. |
| CSS build | `package.json` pins Tailwind CSS 3.4.17 as a dev dependency and defines `build:css`/`build`; this is not an application runtime dependency. |
| Code execution | Java compiler/runtime plus a Java helper source in `judge/`; Python STDIO mode uses a Python executable. Windows process restrictions are implemented with `ctypes`/Job Objects in `app/windows_job.py`. |
| Data persistence | Python `json` files and append-only JSONL, not SQL/ORM. Uploaded payloads are normal files. |

The repo has no Python dependency lockfile or declared `requires-python` floor/ceiling. JDK version details are validated by the runner/startup path and should be checked in [`app/java_runner.py`](../../app/java_runner.py), not inferred from a README statement.

## Assets and test scope

- Templates: `base.html`, `login.html`, `student.html`, `admin.html`.
- Frontend scripts: `app.js`, `admin.js`, `student.js`.
- Tests: `test_core.py`, `test_code_api.py`, `test_code_runner.py`, `test_java_runner.py`, `test_reflection_judge.py`, `test_grading.py`, and `test_windows_job.py`.
- Existing handover and planning docs under `docs/` provide background, but source code is the authority for current behavior.

## Source anchors

- Paths and limits: [`app/config.py`](../../app/config.py#L4)
- Python package list: [`requirements.txt`](../../requirements.txt)
- CSS commands/dependency: [`package.json`](../../package.json)
- Startup wiring: [`run_server.py`](../../run_server.py), [`app/main.py`](../../app/main.py#L631)

---

# 2. System architecture

## Architectural shape

**Verified:** The application is a single Python process with a standard-library threaded HTTP listener. `app/main.py` owns HTTP input/output, route dispatch, and authentication gates; imported domain modules implement account security, exam lifecycle, submissions, question management, code-exam orchestration, scoring and process execution. Persistence is shared JSON/JSONL/filesystem state.

**Not asserted:** The source does not establish a formal MVC/clean/hexagonal architecture. There are recognizable UI/template, HTTP handler, domain helper, and persistence responsibilities, but boundaries are pragmatic rather than enforced by an application framework or interfaces.

## Component responsibilities

| Component | Responsibility / I/O | State and dependencies |
|---|---|---|
| HTTP adapter (`app/main.py`) | Parses request bytes and form/JSON/multipart bodies; resolves paths; authenticates; returns HTTP responses. Input: browser/API requests. Output: HTML, JSON, downloads, redirects. | Reads/writes through domain functions and storage helpers; owns Jinja environment and server lifecycle. |
| Security (`app/security.py`) | Password hash verification, session issuance/lookups, role checks, login attempt lockout, IP extraction. | `sessions.json`, `login_attempts.json`, user/admin JSON. |
| Exam domain (`app/exams.py`) | Exam-file listing/distribution and student start/deadline handling. | `settings.json`, `assignments.json`, users and exam files; calls security/storage. |
| ZIP submissions (`app/submissions.py`) | Validates ZIP boundaries/CRC/paths and stores upload bytes and metadata. | `submissions/`, `submissions.json`, `assignments.json`, `settings.json`, audit log. |
| Question and code-exam domain (`questions.py`, `code_exams.py`) | Validates question schemas, snapshots published questions, manages code exams and pretest/final grading flows. | Question/exam/submission/run JSON; runners, grading, storage, Job limits. |
| Execution (`code_runner.py`, `java_runner.py`, `windows_job.py`, `judge/ReflectionJudge.java`) | Compiles/runs student code, captures bounded output, classifies execution results. | Temporary workspaces, child processes, Java/Python toolchains; Windows Job Object APIs. |
| Scoring (`app/grading.py`) | Validates judge results and calculates question/exam points. | Pure transformations over configured cases/checks and execution results. |
| Persistence (`app/storage.py`) | JSON read/write/update, atomic replacement, JSONL audit. | Files under `data/` and `logs/`; process-global `threading.RLock`. |
| Presentation (`templates/`, `static/`) | Login/student/admin markup and polling/forms. | Requests endpoints served by `Handler`. |

## Communication boundaries

1. **Browser to server:** HTTP/1.1 to a single configured host/port; HTTPS optionally wraps the listener socket.
2. **Handler to domain:** direct in-process Python calls; no internal RPC or message bus.
3. **Domain to persistence:** direct function calls to JSON/JSONL storage and filesystem.
4. **Code grading to child processes:** subprocess execution, pipes/captured streams, and a bounded judge protocol; process restrictions are provided by Windows Job Objects on supported Windows runs.
5. **Application to external services:** No remote service dependency is declared for normal runtime; local Java/Python toolchains are required for grading.

## Main dependency direction

`browser → Handler → domain modules → storage/filesystem`

For code grading: `Handler → code_exams → questions/grading/runners → java_runner/windows_job → javac/java/python child process`. `code_exams` also persists results and audit entries. The direction is direct imports, not a dependency-injection container.

See [module analysis](03-module-and-dependency-analysis.md) and [system diagram](diagrams/system-architecture.mmd).

## Shared state

- Process-local storage lock in `app/storage.py`.
- Process-local semaphore for code execution in `app/code_exams.py`.
- Filesystem records that survive process restart (subject to persistence correctness).
- Each request-handler thread may access this shared state concurrently.

No separate database, cache, distributed lock, queue, or multi-instance coordination mechanism was found.

---

# 3. Module and dependency analysis

## Direct dependency map

The diagram captures important runtime imports/interactions rather than every standard-library import. See [`diagrams/module-dependencies.mmd`](diagrams/module-dependencies.mmd).

| Caller | Direct dependency | Why / functionality |
|---|---|---|
| `app.main` | `config`, `storage` | Paths/limits, initialization, persistence and audit. |
| `app.main` | `security` | Session extraction, role authorization, password verification, login lockout. |
| `app.main` | `exams`, `submissions`, `accounts` | Exam lifecycle, upload, account import parsing. |
| `app.main` | `questions`, `code_exams` | Admin question/code-exam and student code-run APIs. |
| `app.main` | `java_runner` | Startup JDK readiness check on Windows. |
| `questions` | `grading`, `storage`, `windows_job` | Validate configured score totals, persist question bank, validate Java memory minimum. |
| `code_exams` | `questions`, `grading`, `code_runner`, `java_runner`, `windows_job`, `storage` | Snapshot validation, dispatch runner, result normalization/scoring, persistence and bounded execution. |
| `code_runner` | `java_runner`, `grading`, `windows_job` | Shared workspace/process helpers for Java/Python STDIO and verdict/scoring behavior. |
| `java_runner` | `windows_job`, `grading` | Spawn bounded child processes; process and validate reflection judge results. |
| `exams`, `submissions`, `security`, `questions` | `storage` | JSON state and audit. |
| `templates` / `static` | HTTP endpoints | Browser requests rendered/served by `app.main`; JS polling goes back to same origin. |

## Static dependencies vs runtime interactions

- **Static/import dependencies:** the direct Python imports above. Importing `app.main` also imports `code_exams` and `java_runner` and calls storage initialization.
- **Runtime interactions:** a matching HTTP route invokes a specific domain function; code-exam execution can start `javac`, `java`, and/or Python subprocesses; requests share the same in-process storage lock and runner semaphore.
- **Filesystem interaction:** templates/static files and exam assets are read by HTTP routes; uploads and data/audit are written directly.

## Coupling and boundaries

- **Verified coupling:** HTTP route definitions and route-level validation are colocated in `Handler`; changes to API behavior therefore commonly involve `app/main.py` and one or more domain modules.
- **Verified coupling:** `code_exams` coordinates storage and execution runners, while `grading` is separately reusable and does not launch processes.
- **Potential limitation:** storage state is file-oriented and its lock is module-process-local. Multiple server processes would not coordinate their read-modify-write cycles.
- **Circular imports:** no circular import was observed in the primary module import graph. This is an inspection result, not a static import-graph proof over every optional execution branch.
- **Unused/isolation:** no module was conclusively identified as unused. `submission_server.py` is a compatibility entry point; execution/legacy files are referenced by active imports and tests.

## Diagram

The diagram uses `Handler` as the composition point and shows the code-grading runtime branch as distinct from the ordinary exam/ZIP flow. It intentionally omits standard-library dependencies and individual API routes.

---

# 4. Code logic and execution paths

## Request path

`run_server.py → app.main.main() → ThreadingHTTPServer((HOST, PORT), Handler) → Handler.do_GET/do_POST → domain function(s) → storage/filesystem → HTTP response`

`app.main` initializes storage on import. `Handler._parse_body()` applies the request-size limit and decodes URL-encoded, multipart, or JSON-object bodies. `do_GET` and `do_POST` contain path conditionals; there is no separate router registry. `_auth()` translates `SecurityError` into an HTTP-facing error.

## Important flows

### Sign-in and session

1. `POST /login` reads username/password form fields and asks `security.login_allowed`.
2. It loads admin/student JSON, checks active state and password hash, records lockout failures or clears failures.
3. Successful login creates a random token with `security.new_session`; only token hash is the session key in JSON state. Student login revokes earlier student sessions.
4. Handler sets the cookie (`HttpOnly`, `SameSite=Strict`, 12-hour max age; `Secure` only when TLS env vars are present).
5. Authenticated requests call `_auth()` → `require_user()` → `get_session()`.

### Exam distribution and submission

1. Admin form/API route calls `exams.distribute_exams(mode, config)` and writes release/assignment state.
2. Student calls `POST /api/student/start`; handler delegates to `exams.start_exam`.
3. Student may fetch `/api/student/exam` only while the current assignment/release is active, started, and not expired.
4. `POST /api/student/submit` parses multipart upload, then calls `submissions.accept_submission`.
5. `validate_zip()` checks archive signature, entry count, total uncompressed bytes, CRC, and path safety. Accepted bytes are written to `submissions/`; metadata, assignment status, and audit are updated.

### Code question and grading

1. Admin routes create/publish questions and code exams. `code_exams.create_code_exam` snapshots published questions so later edits do not silently mutate an already-created exam.
2. Distribution associates the code exam with a release; student code endpoints are protected by role and active-exam context checks.
3. `/api/student/code/run` invokes `run_pretest`: source size/hash, run budget/cooldown and semaphore are checked; visible tests/checks are executed; pretest history and audit are updated. It does not create a final scored submission.
4. `/api/student/code/submit` invokes `submit_code`: reserves submission state, executes question mode, validates/grades results, then persists final submission and exam score.
5. `execute_question()` dispatches Java reflection to `run_reflection_judge`, otherwise STDIO to `run_stdio`. The runners start bounded child processes. `grading.py` validates result shapes/verdicts and aggregates points.
6. Admin code-results and regrade routes read saved results or explicitly re-run grading.

See [execution-path diagram](diagrams/execution-paths.mmd) and existing [`docs/JUDGE_EXECUTION_TECHNICAL_HANDOVER.md`](../JUDGE_EXECUTION_TECHNICAL_HANDOVER.md) for additional runner protocol and platform notes.

## Important side effects and errors

- Routes can persist several separate JSON files for a single logical operation; JSON writes are atomic per file, not transactional across files.
- ZIP submission writes a file before updating metadata and assignment status.
- Code execution reserves run/submission records and can spawn compiler/interpreter/JVM processes.
- Handler maps expected `ClientError`, `SecurityError`, `CodeExamError`, and `QuestionError` to response status. An unhandled exception is printed with traceback and returned as generic 500.
- Process outcomes distinguish compile/infra errors and student outcomes (e.g. AC/WA/CE/TLE/MLE/RE/OLE); details are in `app/java_runner.py`, `app/code_runner.py`, and `app/grading.py`.

## Source anchors

- Request adapter/routing: [`Handler`](../../app/main.py#L137), `do_GET`, `do_POST`
- Session primitives: [`app/security.py`](../../app/security.py#L19)
- Exam state: [`app/exams.py`](../../app/exams.py#L36)
- ZIP flow: [`app/submissions.py`](../../app/submissions.py#L11)
- Code-exam orchestration: [`app/code_exams.py`](../../app/code_exams.py#L325), `run_pretest`, `submit_code`
- Scoring: [`app/grading.py`](../../app/grading.py#L399)

---

# 5. Network architecture

## Topology and endpoints

**Verified topology:** one server process listens on `(CSS_HOST, CSS_PORT)`; defaults are `0.0.0.0:8080`. Browser clients use the same origin for rendered pages, static assets, form submissions, and JSON API. `Handler` subclasses Python's `BaseHTTPRequestHandler`; the server is `ThreadingHTTPServer` with daemon request threads.

No independent client executable, peer-to-peer link, separate grading listener, or custom raw TCP protocol was found. Java/Python child-process pipes are local process communication, not network connections.

## HTTP protocol and message parsing

- HTTP/1.1 is selected by `Handler.protocol_version`.
- Methods handled explicitly: `GET`, `HEAD` (delegates to GET), and `POST`; other methods use base-class behavior.
- `Content-Length` is read before body processing. Requests above 50 MiB are rejected. No chunked-request parser is implemented in the visible handler.
- Body encodings: `application/x-www-form-urlencoded`, `multipart/form-data` parsed with `email.parser`, and `application/json` parsed as an object.
- Responses set `Content-Length`, content type, security-related headers, and `Cache-Control: no-store`; payloads are HTML, JSON, files, or redirects.
- API errors use JSON `{"detail": ...}`; unexpected handler exceptions become generic 500 responses after traceback output.

## Request lifecycle and authentication

The browser opens a normal TCP connection, sends an HTTP request with cookie/body, and receives one response. Session state is represented by a random cookie token; server-side JSON is keyed by a SHA-256 digest. The code sets HttpOnly and SameSite=Strict, Max-Age 43200, and adds Secure only if TLS certificate and key env vars are configured. TLS wraps the listener socket when both `CSS_TLS_CERT` and `CSS_TLS_KEY` are present.

There is no app-level connection registry or reconnect/heartbeat protocol. The student frontend sends telemetry/updates over ordinary HTTP; monitoring and notification refresh use polling. There is no WebSocket or server-push transport.

## Concurrency and resource lifecycle

- The HTTP server creates request-handler threads; `server.daemon_threads = True`.
- JSON read-modify-write locking is via a process-global `threading.RLock`; this does not coordinate across processes.
- Code execution has a distinct `threading.BoundedSemaphore`; `CSS_MAX_CONCURRENT_CODE_RUNS` defaults to 2 and is clamped to 1..16.
- Runner processes are launched from request-handling work and have time/output/memory bounds depending on runner and platform. Windows Job Object assignment is part of the Windows process path.
- No HTTP client heartbeat, server-side idle timeout policy, or reconnect mechanism was found. Socket/server shutdown is handled in `main()`'s `finally` by `server.server_close()` after `serve_forever` ends.
- There is no distributed synchronization or queue when work exceeds the code-run semaphore; pretest path returns a busy response.

## Diagrams

- [Topology](diagrams/network-topology.mmd)
- [Connection/request lifecycle](diagrams/connection-lifecycle.mmd)
- [Message transmission](diagrams/message-transmission.mmd)

## Unknown / environment-dependent

- Whether an external reverse proxy is deployed, its forwarded-header policy, and TLS termination point are not discoverable from repository source.
- Bind address is configurable but there is no in-app network allowlist. Actual exposure depends on host firewall/network policy.
- Socket options/default timeouts beyond standard-library server defaults were not found in application configuration.

## Source anchors

- Host/port/body limit: [`app/config.py`](../../app/config.py#L4)
- Handler methods: [`app/main.py`](../../app/main.py#L137)
- Listener/TLS/shutdown: [`app/main.py`](../../app/main.py#L631)
- Code-run semaphore: [`app/code_exams.py`](../../app/code_exams.py#L30)
- Browser telemetry: [`static/js/student.js`](../../static/js/student.js)

---

# 6. Data architecture

## Persistence model

**Verified:** There is no relational database or ORM. `app/storage.py` maps JSON names to `data/`, `.jsonl` names to `logs/`, serializes UTF-8 JSON, writes a temporary sibling file, flushes/fsyncs, and atomically replaces the target. `update_json()` serializes a mutator under a process-global `RLock`. Audit appends one compact JSON object per line and flushes/fsyncs.

The lock is local to one Python process. Atomic replacement protects an individual file from partial writes; it does not provide multi-file transactions or inter-process locking.

## Stored collections and relationships

| File(s) | Key/shape (high-level) | Relationships |
|---|---|---|
| `students.json`, `admins.json` | Mapping from student ID/admin username to account record and password hash. | Account identity referenced by sessions, assignments, submissions, audit. |
| `sessions.json` | Mapping from hashed session token to role/user, expiration and request metadata. | References one account; student login revokes previous student sessions. |
| `login_attempts.json` | Login throttling state by normalized account key. | Authentication subsystem only. |
| `settings.json` | Singleton exam configuration/release state, participant list, distribution settings. | Current release ID matches assignments and code-exam release. |
| `assignments.json` | Mapping from student ID to exam file, release, state and timestamps. | Student account; ties submission and release. |
| `submissions.json` | Mapping from student ID to array of submission metadata. | Metadata points to a file in `submissions/`; each attempt associates to release ID. |
| `questions.json` | Question bank mapping; question schema is validated in `questions.py`. | Published question IDs referenced by code exams. |
| `code_exams.json` | Code-exam records and question snapshots. | Question snapshots, release ID, student results. |
| `code_submissions.json` | Per-student final code submissions and grade/result details. | Code exam, release, question, student identity. |
| `code_runs.json` | Bounded pretest run records and outcomes. | Student, exam/release/question identifiers. |
| `notifications.json` | Notification records with optional student target. | Admin author and optionally student recipient. |
| `audit.jsonl` | Append-only events with timestamp/event/actor/IP/details. | Cross-cutting event trail; not a relational foreign-key system. |
| `machines.json` | Defaulted JSON mapping; its current active use was not established in this investigation. | Unknown. |

This describes code-level keys and relationships. Runtime data files may be user-specific and were not read for this documentation.

## File and request data paths

### ZIP submission

`multipart upload bytes → handler parser → extension and active assignment checks → ZIP structural/CRC/path checks → `submissions/<safe-id>_<timestamp>.<ext>` → metadata in `submissions.json` → assignment state in `assignments.json` → audit JSONL`

### Code question execution

`JSON request {question_id, source_code} → code-exam active-context/snapshot → runner input → compiler/interpreter or Java judge process → protocol/stdout result → result normalization and scoring → `code_runs.json` (pretest) or `code_submissions.json` (final) → audit JSONL`

### Browser monitoring

`student JS telemetry form → `/api/student/telemetry` → session record telemetry + last_seen → `monitoring_snapshot()` joins students/sessions/assignments/submissions → admin HTML/API JSON`

## Network vs internal representation

- Network request bodies are parsed into form dictionaries, multipart file dictionaries (`filename`, bytes, content type), or JSON dictionaries.
- Domain functions operate on Python dictionaries/lists and dataclass/result objects.
- Storage serializes these structures as JSON; no explicit ORM/domain entity layer exists.
- Uploaded file bytes are stored as files; only metadata is kept in JSON.
- Child-process result channels are not the HTTP schema. Runner details are normalized before API output; `ProcessResult.to_dict()` deliberately excludes internal protocol pipe data.

No SQL ERD applies. See the [JSON relationship diagram](diagrams/data-model.mmd).

## Source anchors

- Defaults, locking and JSON persistence: [`app/storage.py`](../../app/storage.py#L13), `initialize()`, `atomic_write()`, `update_json()`
- Paths and limits: [`app/config.py`](../../app/config.py#L4)
- ZIP path: [`app/submissions.py`](../../app/submissions.py#L11)
- Code question schema: [`app/questions.py`](../../app/questions.py#L39)
- Code exam lifecycle and results: [`app/code_exams.py`](../../app/code_exams.py#L65)

---

# 7. Runtime and resource management

## Startup order

1. A launcher invokes `run_server.py` or compatibility `submission_server.py`.
2. Importing `app.main` imports config/domain modules, runs `storage.initialize()`, and creates the Jinja2 template environment.
3. `main()` checks JDK configuration on Windows before opening the listener. Non-Windows startup prints a warning that code grading is unavailable while ZIP submission remains enabled.
4. It reads `CSS_TLS_CERT` and `CSS_TLS_KEY`, prints local/LAN URLs, constructs `ThreadingHTTPServer((HOST, PORT), Handler)`, and sets `daemon_threads=True`.
5. If both TLS values are set, it loads the certificate chain and wraps the server socket with `ssl.SSLContext`.
6. `serve_forever(poll_interval=0.5)` runs until interrupted; `server_close()` runs in `finally`.

`app.config` resolves repository-relative storage directories and creates them on import. The default listener is `0.0.0.0:8080`; environment variables can override host and port.

## Runtime resources

| Resource | Owner / lifecycle |
|---|---|
| HTTP listen socket | `main()`, optionally wrapped by TLS; `server_close()` in `finally`. |
| Request threads | Standard `ThreadingHTTPServer`, daemon threads; one handler per request. |
| JSON files and audit stream | `storage.py`; opens/closes per operation; uses in-process reentrant lock and atomic replacement for JSON. |
| Uploaded ZIP payloads | `submissions.accept_submission`; writes under `submissions/`; overwrite policy may unlink prior payload. |
| Temporary execution workspace/processes | `java_runner.py` and `code_runner.py`; subprocess time/output handling and workspace cleanup are encapsulated in runner paths. |
| Windows Job handles/process assignment | `windows_job.py`; native handles/Job Object API, process is assigned before resume; close/cleanup behavior belongs to that module. |
| Code-run admission slots | `code_exams.py`; bounded semaphore limits simultaneous code runs within one process. |
| TLS certificate/key | Environment-specified files loaded at startup; actual certificate provisioning is external. |

## Background work and concurrency

No standalone scheduler, worker process, durable queue, async event loop, or daemon maintenance service was found. HTTP routes perform domain work synchronously in their request thread. A code-grading route therefore waits for compilation/execution and response construction. Background execution exists only within runner internals (for example output-capture threads) and is per invocation.

Multiple requests can race over shared files. The storage lock prevents simultaneous operations that use the same in-process storage API lock, but multi-file workflows and other filesystem actions are not transactional. A second server process would have a different lock.

## Platform constraints

- Windows start script configures admin credentials before starting.
- On Windows, startup verifies the JDK configuration before serving.
- `windows_job.py` uses Windows APIs; project technical docs characterize current code grading as Windows-specific. Python and Java code-execution availability on Linux/macOS is not certified here.
- Runtime Python version support is not declared in package metadata.

## Source anchors

- Launcher: [`run_server.py`](../../run_server.py)
- Import-time initialization and server lifecycle: [`app/main.py`](../../app/main.py#L52), [`main()`](../../app/main.py#L631)
- Environment/path defaults: [`app/config.py`](../../app/config.py#L4)
- Windows setup and launch: [`setup_windows.bat`](../../setup_windows.bat), [`start_windows.bat`](../../start_windows.bat)
- Unix-like launch: [`start_unix.sh`](../../start_unix.sh)

---

# 8. Code quality and technical observations

These are architecture-level observations, not a security audit. They do not imply that a conventional pattern is required. Confidence indicates confidence in the evidence/observation, not proof of an incident.

| Observation | Evidence and affected components | Potential impact | Suggested follow-up | Confidence |
|---|---|---|---|---|
| HTTP routing and presentation orchestration are centralized in one handler module. | `app/main.py` contains body parsing, route matching, authentication, template context construction, response helpers, startup and server lifecycle. | Route growth can make behavior difficult to locate and test independently; route changes often couple to domain modules. | Keep route-level behavior explicit and add focused API tests; if refactoring is later chosen, preserve HTTP contract and move cohesive route groups without changing semantics. | High |
| JSON persistence is single-process and not a transaction boundary. | `storage.py` uses one process-local `RLock` and atomic replacement per JSON file; business operations can write separate files sequentially. | Multiple processes may lose updates; a crash between writes may leave related records inconsistent. | Avoid multiple server instances against one data directory; consider a transactional backend only if deployment/concurrency requirements change. | High |
| Request workers perform grading synchronously. | Student code endpoints call `run_pretest`/`submit_code` within `do_POST`; code-exam code acquires bounded run slots and waits on runner results. | Slow compilation or execution occupies an HTTP worker; when the run limit is reached, new code runs are rejected as busy rather than queued. | Load-test expected concurrency and align HTTP capacity, execution slots and user-visible retry behavior. | High |
| Server request thread shutdown is not graceful for active requests. | `server.daemon_threads=True`; shutdown path closes listener in `finally`. | In-flight work may not be joined on process exit; active child-process cleanup depends on the runner/process/Job Object paths. | Verify shutdown during long-running grading and define operational stop procedure. | Medium |
| There are two submission domains with different schemas/lifecycles. | ZIP flow in `submissions.py` and coding flow in `code_exams.py` persist to different JSON files and run via different endpoints. | Shared reporting/admin tools must deliberately aggregate both; assumptions that all submissions are ZIPs are stale. | Keep API/data documentation explicit and test both workflows when changing common exam release state. | High |
| The public technical docs have drifted from active implementation. | `SPECIFICATION.md` describes code-grading UI as not integrated, while the repository has question/exam/code-result routes and frontend files; route existence is verified, full UI parity is not. | A developer using docs as authority may miss active backend capabilities or overstate UI availability. | Treat root docs as supplementary and update them only after checking source and live UI behavior. | High |

## Unknowns requiring further verification

- Whether the current frontend exposes all backend code-exam operations (notably code exam authoring and student run/submit flows) in the intended environment.
- Whether deployment uses TLS directly in this server or a reverse proxy; no proxy-trust configuration was established.
- Actual operational scale, concurrent class size, storage growth, and restart/recovery procedures.
- The practical test coverage/runtime status on a clean environment, especially Windows-only job controls and installed JDK behavior.
- The active use, if any, of `machines.json` and legacy project assets.

No source changes were made to address these observations.

---

# 9. Source-code index

Paths are relative to the repository root. Line references point to current checked-out source locations; recheck after edits.

| Symbol | Type | File | Responsibility | Important relationships |
|---|---|---|---|---|
| `run_server.main` | Entry point | `run_server.py:2` | Import and invoke application entry. | Calls `app.main.main`. |
| `Handler` | HTTP handler class | `app/main.py:137` | HTTP/1.1 response, body parsing, auth, GET/POST routing. | Calls security, exam, submission, question and code-exam modules. |
| `Handler._parse_body` | Method | `app/main.py` | Enforces body limit and parses URL-encoded, multipart and JSON. | Produces request form/files/JSON for route handlers. |
| `Handler.do_GET` | Method | `app/main.py` | Static/page/admin/student GET and API routes. | Reads domain state and renders templates. |
| `Handler.do_POST` | Method | `app/main.py` | Login, mutation, upload, telemetry, run/submit APIs. | Dispatches to domain modules. |
| `monitoring_snapshot` | Function | `app/main.py:85` | Joins account/session/assignment/submission state for admin monitoring. | Called by admin page and monitor API. |
| `main` | Function | `app/main.py:631` | JDK check, optional TLS, listener lifecycle. | Entrypoint calls; constructs `ThreadingHTTPServer`. |
| `hash_password`, `verify_password` | Functions | `app/security.py:19`, `:24` | Password hash and verification. | Login/setup/admin operations. |
| `new_session`, `get_session`, `require_user` | Functions | `app/security.py:36`, `:44`, `:62` | Issue and authenticate token sessions. | Used by `Handler._auth` and page routing. |
| `login_allowed`, `record_login_failure` | Functions | `app/security.py:73`, `:79` | Account-key login lockout state. | `POST /login`, admin unlock operation. |
| `initialize`, `read_json`, `write_json`, `update_json`, `audit` | Persistence API | `app/storage.py:53`, `:81`, `:94`, `:98`, `:105` | JSON/JSONL state and event logging. | Most domain modules. |
| `distribute_exams`, `start_exam`, `remaining_seconds` | Functions | `app/exams.py:36`, `:149`, `:187` | Allocate exam files, begin student exam and calculate remaining time. | Handler routes, `assignments.json`, settings. |
| `validate_zip`, `accept_submission` | Functions | `app/submissions.py:11`, `:39` | Validate and persist ZIP submission. | Handler upload route and JSON assignment state. |
| `_validate_question`, `create_question`, `update_question` | Functions | `app/questions.py` | Validate/code-question schema and mutate bank. | `storage`, grading limits, code exams. |
| `create_code_exam` | Function | `app/code_exams.py:65` | Validate exam request and snapshot published questions. | Question bank, code exam persistence. |
| `prepare_code_exam_distribution`, `transition_code_exam` | Functions | `app/code_exams.py:165`, `:184` | Attach code exam to release and transition lifecycle. | Admin distribution/end-exam routes. |
| `execute_question` | Function | `app/code_exams.py:325` | Dispatch reflection versus STDIO execution. | `java_runner`, `code_runner`, scoring. |
| `run_pretest` | Function | `app/code_exams.py:473` | Enforce pretest rules/capacity, run visible checks, store run history. | `code_runs.json`, runner, semaphore. |
| `submit_code` | Function | `app/code_exams.py:800` | Reserve, execute, grade and persist final coding submission. | `code_submissions.json`, runners and grading. |
| `get_admin_code_results`, `regrade_submission` | Functions | `app/code_exams.py:854`, `:881` | Admin result query and explicit regrading. | Code-exam snapshots/submission records. |
| `QuestionScore`, `ExamScore`, `grade_reflection`, `grade_stdio`, `grade_exam` | Types/functions | `app/grading.py` | Validate outcomes and aggregate score. | Called from code-exam orchestration/runners. |
| `run_stdio` | Function | `app/code_runner.py:598` | Compile/run Java or Python STDIO test cases and compare outputs. | Uses workspace/process helpers from `java_runner`. |
| `run_process`, `compile_java_in_workspace`, `run_reflection_judge` | Functions | `app/java_runner.py:800`, `:1240`, `:1581` | Bounded process capture, Java compilation, reflection judge execution. | Windows Job Object process helper; `ReflectionJudge.java`. |
| `ProcessResult`, `ProcessStatus` | Types | `app/java_runner.py` | Normalized child-process outcome. | Consumed by runners and result classification. |
| `JobLimits`, `create_job_process` | Types/functions | `app/windows_job.py:27`, `:724` | Windows Job Object limits and suspended-child assignment/resume. | `java_runner`, `code_runner`, question validation. |
| `ReflectionJudge.main` | Java entry point | `judge/ReflectionJudge.java` | Reads protocol request, loads student class and emits bounded judge response. | Launched by `java_runner.run_reflection_judge`. |
| `TEMPLATES` | Module state | `app/main.py` | Jinja `Environment` rooted at `templates/`. | `Handler._render`. |
| `_RUN_SLOTS` | Module state | `app/code_exams.py` | Process-local bounded code-run semaphore. | Pretest/submission execution. |
| `BASE_DIR`, `HOST`, `PORT` | Configuration | `app/config.py:4` | Repository paths and listener defaults. | Imported throughout runtime. |

## Tests and source map

| Test file | Main target |
|---|---|
| `tests/test_core.py` | Core account/exam/submission behavior. |
| `tests/test_code_api.py` | HTTP routes, authorization, exam lifecycle and code API persistence. |
| `tests/test_code_runner.py` | STDIO execution and output comparison. |
| `tests/test_java_runner.py` | Java compile/process/reflection runner behavior. |
| `tests/test_reflection_judge.py` | Java judge protocol and reflection checks. |
| `tests/test_grading.py` | Result validation and point aggregation. |
| `tests/test_windows_job.py` | Windows Job Object/process lifecycle. |

Current declared test style is Python `unittest`; no test runner dependency is listed in `requirements.txt`.