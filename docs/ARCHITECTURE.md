# Kiến trúc hiện tại

> Tài liệu được viết lại từ working tree hiện tại. References giúp điều hướng; kiểm tra source trước mọi thay đổi. Không phải chứng nhận chạy test/deployment.

## 1. Thành phần

| Lớp | Trách nhiệm |
|---|---|
| `run_server.py` → `app.main.main()` | Entry point; `Handler` dispatch HTTP routes, auth, templates và responses. |
| `app/config.py`, `app/storage.py` | Paths/host/port; JSON/JSONL, atomic file replacement, process-local lock. |
| `app/security.py` | Session cookie, token hashing, role checks, last_seen, logout. |
| `app/questions.py`, `static/js/questions.js` | Question schema/lifecycle/revisions; Teacher editor/import/export/validation. |
| `app/practice.py`, `static/js/student-practice.js` | Eligibility, safe Student projection, catalog/progress, visible-only Practice Run. |
| `app/papers.py`, `static/js/code-papers.js` | Independent Paper schema v2, legacy reference resolution, Paper CRUD/preview. |
| `app/general_exams.py`, `static/js/exams.js` | Exam configuration, Common/Random paper selection, release, assignment, lifecycle. |
| `app/exams.py` | File Exam distribution/assignment and legacy/global exam session behavior. |
| `app/code_exams.py` | Release-scoped Code Exam snapshots, Student access, Pretest, Submit, grading/regrade. |
| `app/code_runner.py`, `app/java_runner.py`, `app/grading.py`, `app/windows_job.py` | STDIO/Reflection execution, result validation/aggregation and Windows process controls. |
| Templates/static JS | Jinja-rendered pages and browser requests/polling/editor state. |

## 2. Persistence boundaries

| File/group | Nội dung |
|---|---|
| `questions.json` | Question Bank content, lifecycle, server-managed validation/revision data. |
| `practice_progress.json` | Student-keyed Practice progress/result/current attempt; editor source drafts live in browser storage. |
| `papers.json` | Independent schema v2 Papers plus retained legacy versioned records. |
| `exams.json` | Exam configuration and release data, including persisted selection/assignment information. |
| `code_exams.json` | Code Exam records and release-scoped question snapshots. |
| `assignments.json` | Student release/Paper assignment, start/deadline/status. |
| `code_submissions.json`, `submissions.json` | Code result/submission records and uploaded file metadata/payload relationship. |
| `sessions.json` | Session entries keyed by token hash, presence fields and current telemetry snapshot. |

Optional fields differ across legacy and current shapes. Never reinterpret historical content from current Question/Paper state or flatten legacy records.

## 3. Data flows

### Question → Practice

```mermaid
flowchart LR
  TE[Teacher Question Editor] -->|JSON / form| API[Question API]
  API --> QV[questions._validate_question]
  QV --> Q[(questions.json)]
  Q --> EL[Practice eligibility + safe projection]
  EL --> ST[Student Library]
  ST -->|revision, attempt, source| PR[practice.run_practice]
  PR -->|visible_only| RUN[shared Runner]
  RUN --> RES[normalized visible result]
  RES --> PP[(practice_progress.json)]
```

### Paper → Exam Release → Student

```mermaid
flowchart LR
  QB[(Question Bank)] --> P[Independent Paper]
  P --> EC[Exam config]
  EC -->|Publish / build release| R[Release snapshots + Student choices]
  R --> A[(assignments.json)]
  R --> C[(code_exams.json snapshots)]
  T[Teacher Start] --> R
  S[Student Start] --> A
  A --> W[Student Exam access]
  W --> PRE[Pretest]
  W --> SUB[Official Submit]
  SUB --> G[full grading]
  G --> RG[regrade using intended release spec]
```

## 4. Detailed execution paths

### 4.1 Question create/import/validate/persist
1. `static/js/questions.js::importSpec()` parses JSON client-side, removes fields in `SERVER_OWNED`, then loads editable draft state. `exportSpec()` exports editor payload; this does not mean every server field is import-owned.
2. `POST /api/admin/questions` and update routes in `app/main.py` call `app/questions.py::_validate_question()`. Backend validates allowed language/grading modes, types, execution config, nested checks/tests and sizes.
3. `create_question()` initializes server-owned lifecycle/revision metadata and writes to `questions.json`; update/publish paths enforce current state/revision. Candidate validation/publish uses code-exam sample validation routes.

### 4.2 Practice Question → Run → progress
- Student routes: GET `/api/student/practice/questions`, question detail, progress and run-status; POST `/api/student/practice/run`; update/delete progress routes in `app/main.py`.
- `is_practice_eligible()` requires published, enabled and valid `practice_revision`; `practice_public_projection()` allowlists Student-visible fields.
- `run_practice()` validates current revision/attempt, protects mutation under storage transaction, guards duplicate active Run, calls `execute_question(..., visible_only=True, workspace_parent=...)` and persists progress/result.
- `student-practice.js` stores source drafts locally; server progress and result are separate from source autosave.

### 4.3 Paper → Release snapshot
- Paper APIs are under `/api/admin/papers`; service in `app/papers.py`. Schema v2 uses independent Paper ID/revision/status. Legacy `paper_id` + explicit `paper_version_id` remain supported.
- `resolve_paper_reference()` resolves new `{paper_id}` vs explicit legacy pair; it never guesses a version ID.
- `static/js/exams.js` sends Code distribution mode and Paper refs. Draft/distributed-before-activity editor supports Common/Random selection; Common requires one Paper, Random selects from an eligible pool.
- `general_exams._build_release()` creates persisted release selection/snapshot data; `_apply_release()` applies pre-start assignment map at Teacher Start. Pre-start updates synchronize relevant assignment state. `expected_revision` protects stale writes; Student activity blocks edits that could rewrite history.
- Release-scoped code exams retain question snapshots. Paper changes affect later release only; Paper-release regrade rejects `use_latest_spec`.

### 4.4 Student Start → Pretest → Submit → Grading
1. Publish creates visibility/release; Teacher Start is a separate action.
2. Student shell `student.js` POSTs `/api/student/start`; backend `exams.start_exam()` checks Teacher state, assignment/release and password, then writes Student `started_at`, deadline, status and audit.
3. `student-code.js` loads `GET /api/student/code-exam`; `_active_context()` rechecks release, assignment, deadline and state.
4. Pretest follows `allow_pretest` settings. Official per-question/exam submit uses release snapshot, full configured checks and persisted `code_submissions.json`.
5. Regrade verifies ended/completed state and uses Paper release snapshot; ZIP/file Exam has separate `/api/student/exam` and `/api/student/submit` routes.

### 4.5 Student heartbeat → telemetry → Teacher Monitoring
- `student.js::heartbeat()` runs immediately and every 15s, calls telemetry then `GET /api/student/status`; focus/blur/visibility/storage events also send telemetry.
- `updateTabs()` tracks recent page IDs in origin-scoped `localStorage["css-exam-tabs"]`; it cannot inventory every browser tab.
- `POST /api/student/telemetry` replaces a session-level snapshot in `sessions.json`. `security.get_session()` updates `last_seen` on authenticated requests independently.
- `monitoring_snapshot()` combines latest session, assignment and submission data; alerts are derived from current visibility/focus/tab_count. `admin.js::loadMonitor()` polls `GET /api/admin/monitor` every 5s.
- No Exam/Release/Assignment association or persistent telemetry event history exists in current snapshot contract. Practice page loads `student-practice.js`, not main `student.js`.

Chi tiết telemetry fields, stale snapshot và tab-count limitations: [Telemetry Audit](TELEMETRY_ARCHITECTURE_AUDIT.md).

## 5. Authentication and persistence

`security.get_session()` validates cookie by hashing token to lookup key in `sessions.json`, enforces expiration and updates `last_seen`. Login revokes prior Student session for same ID; logout removes current session.

`storage.py` offers atomic replacement per file and a process-local reentrant lock; `transaction()` only protects call sequences that participate. It is not a multi-process lock or multi-file atomic commit. Inspect each workflow's lock boundary before making concurrency claims. Runtime JSON is operational data, not disposable fixtures.

## 6. Shared Runner / Grader

- `code_runner.run_stdio()`: Java/Python STDIO, separate tests, supports `visible_only` and `workspace_parent`.
- `java_runner.run_reflection_judge()`: Reflection request/spec validation, compile and judge protocol.
- `code_exams.execute_question()` chooses execution mode. Practice invokes it visible-only; Official grading uses full configured checks.
- `grading.py` validates and aggregates results, rather than running student processes.
- Windows Job Objects provide process/resource lifecycle controls; do not treat them alone as proof of filesystem/network sandbox isolation.

## 7. Navigation and verification

Key tests: `test_practice.py`, `test_practice_workspace.js`, `test_question_concurrency.py`, `test_papers.py`, `test_paper_distribution.py`, `test_exam_selector.js`, `test_code_api.py`, `test_grading.py`, `test_java_runner.py`, `test_reflection_judge.py`, `test_core.py`. Check `rg --files tests` for current inventory. This documentation task did not run tests.

## 8. Proposed / under discussion

Exam-only behavioral telemetry, tab precheck/dialog, fullscreen entry and persistent monitoring events are proposals, not current implementation. Student Start handler has no Fullscreen API call. No proposal here changes lifecycle or API.
