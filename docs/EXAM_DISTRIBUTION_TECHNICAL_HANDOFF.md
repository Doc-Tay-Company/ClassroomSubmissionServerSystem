# Exam Distribution Technical Handoff

> **Historical handoff:** this document records a point-in-time integration state. It contains old branch/worktree observations, source line numbers, and test reports; do not use these as current instructions. For current state, use [Architecture](ARCHITECTURE.md), [Code Exam API](CODE_EXAM_API.md), [Exam Monitoring plan](EXAM_MONITORING_IMPLEMENTATION_PLAN.md), and [Known Issues](KNOWN_ISSUES.md).

This handoff was written for an Agent starting without the prior conversation. Its original working-tree and branch claims are intentionally preserved as historical provenance. Recheck the actual working tree before any future integration work.

## A. Current architecture

`app/papers.py` owns Paper validation, independent Paper CRUD/publication, legacy Paper/version resolution and previews. `app/general_exams.py` owns the newer Exam record workflow, configuration validation, release construction, Paper assignment map, lifecycle and lifecycle guards. `app/code_exams.py` owns code-question snapshots, student code access, pretests, submissions, grading, results and regrading. `app/exams.py` retains the original single-running-exam ZIP/code distribution machinery and per-Student assignment start behavior. `app/main.py` routes both API families and applies role authentication. `app/storage.py` stores JSON atomically per file and uses an `RLock` for in-process transactions.

Important entity distinction:

- Paper is a reusable content entity. New Papers (`schema_version: 2`) have one `id`, `revision`, `status`, `question_ids`, `question_limit`, `question_filters`, and current `questions` snapshots. Legacy Paper records (`schema_version` absent/1) retain `draft`, `versions`, and `current_version_id`.
- Exam is a configuration/lifecycle record with `id`, `revision`, `title`, `config`, `items`, and optional `release`.
- Release captures assignments and Paper-choice map. For Paper mode, the code creates a release-scoped code exam snapshot per Paper ref, then records the exact per-Student selected ref and code exam ID.
- Assignment links a Student to `release_id` and, for code Paper exams, `paper_id`, optional legacy `paper_version_id`, and `code_exam_id`.
- Submission carries Exam/release/question identifiers and source/attempt/grading information. It is separate from the Paper and Exam configuration.

## B. Implementation changes and provenance

History contains exam/distribution-related commits (`f00a583` “Đổi cơ chế phát bài”, `af2903b` “Fix phần đề thi”) and a merge commit (`736818a`). The current worktree also contains substantial uncommitted changes in Paper, Exam and code-exam files. Therefore a line-by-line introduction attribution cannot safely be inferred from branch history alone. In particular, do not treat every current function as newly introduced by the independent Paper refactor.

Current source responsibilities that are verified:

| Existing or current area | Current behavior |
|---|---|
| `app/exams.py` | Original file distribution algorithms (`compute_assignments`, `persist_distribution`), per-Student start (`start_exam`), and global session lifecycle. This is still reachable from older API routes. |
| `app/questions.py` | Question Bank validation, lifecycle and persistence. Paper selection checks Question eligibility through this module. Practice and Exam share Question Bank data, but Practice has separate progress records. |
| `app/general_exams.py` | Current Exam record workflow, Paper pool normalization, release snapshots, Common/Random Paper allocation, expected revision guard, edit-before-Start behavior and assignment synchronization. |
| `app/papers.py` | Independent Paper schema and CRUD/publication coexist with legacy versioned Paper schema. Explicit version pairs remain resolvable. |
| `app/code_exams.py` | Release-scoped Paper snapshots, existing standalone code snapshots, execution, submission, grading and Paper-safe regrading. |
| `static/js/exams.js`, `static/js/code-papers.js` | Exam configuration/editor and Paper Manager frontend. Current mode selector includes Common and Random for editable Draft/distributed Exam. |

Git history and working-tree diff do not prove authorship of each helper. No generic changelog claim should be made from filenames or commit titles alone.

## C. API and execution contracts

### Paper Manager

All routes require admin authentication (see `app/main.py:515-549`). Main independent Paper APIs:

| Method / path | Purpose |
|---|---|
| `GET /api/admin/questions` | Question Bank for editor. |
| `GET /api/admin/papers` | Paper cards including status, revision and unavailable-source warnings. |
| `GET /api/admin/papers/{paper_id}` | Paper detail. |
| `GET /api/admin/papers/{paper_id}/preview` | Saved preview; `?draft=1` selects current Draft for eligible legacy shape. `version_id` is for legacy Paper versions. |
| `POST /api/admin/papers/independent` | Create independent Draft Paper. |
| `PUT /api/admin/papers/{paper_id}` or legacy `POST .../{id}/update` | Update Paper; requires `expected_revision`. Draft can be incomplete/empty; published save requires exact question count and valid content. |
| `POST /api/admin/papers/{paper_id}/publish` | Publish; exact `len(question_ids) == question_limit`, eligible references and snapshots required. |
| `POST /api/admin/papers/{paper_id}/draft-copy` | Create a new independent Draft from Published Paper. |

`resolve_paper_reference()` is the boundary: `{paper_id}` resolves only `schema_version >= 2`; `{paper_id, paper_version_id}` is an explicit legacy reference. An independent Paper does not have an inferred/fabricated version ID. Draft Paper references fail `require_published=True`.

### Exam record API

Routes require admin authentication (`app/main.py:631-642`):

| Method / path | Purpose |
|---|---|
| `GET /api/admin/exam-records` | List Exams. |
| `POST /api/admin/exam-records` | Create Draft Exam. |
| `GET /api/admin/exam-records/{id}` | Read Exam. |
| `GET /api/admin/exam-records/{id}/preview` | Read-only code-question preview. Before release, preview resolves current Paper; after release it uses release code snapshots where present. |
| `POST /api/admin/exam-records/{id}/update` | Edit Draft or Published-not-started Exam. Payload must contain integer `expected_revision`. |
| `POST /api/admin/exam-records/{id}/publish` | Validate and publish Draft; creates release, does not Start. |
| `POST /api/admin/exam-records/{id}/revoke` | Revoke distributed-not-started Exam. |
| `POST /api/admin/exam-records/{id}/start` | Teacher-initiated Start; applies release. |
| `POST /api/admin/exam-records/{id}/end` | End running Exam and close code snapshots. |
| `POST /api/admin/exam-records/{id}/copy`, `/delete` | Copy or delete/archive per lifecycle. |

The code item accepts either legacy `question_ids` or `distribution: {mode: "common"|"random", paper_versions: [...]}`. API key `paper_versions` is retained even for independent Paper refs; each new ref is `{paper_id}`. Common requires exactly one ref. Random requires a nonempty unique pool. References resolve and Published status is checked before release creation.

`update_exam()` only allows statuses `draft` and `distributed`. It compares `expected_revision` to current `revision`. For a distributed Exam, it builds a new pre-start release and synchronizes preparatory assignments. Existing activity markers cause rejection. `started` and `ended` records are not editable.

### Student and code APIs

`GET /api/student/status` provides assigned state and `published_exams` (only IDs, titles, tags) for active visibility. `GET /api/student/exam` provides ZIP content only after a matching assignment has `started_at`; `POST /api/student/start` starts the Student's assignment only after Teacher has started the global release. Code path:

- `GET /api/student/code-exam`: code exam projection after matching assignment has started.
- `POST /api/student/code/run`: pretest; returns 503 for runner infrastructure failures.
- `POST /api/student/code/submit`: per-question submit.
- `POST /api/student/code/submit-exam`: bulk submit.
- `GET /api/student/code/submission?question_id=...`: own submission state.
- Admin: `GET /api/admin/code-results?exam_id=...`; `POST /api/admin/code-results/{exam_id}/regrade`; `POST .../regrade-student`.

Legacy routes `/api/admin/distribute`, `/api/admin/start-exam`, `/api/admin/end-exam` still call `app.exams` machinery and must remain compatible. They are not the same API workflow as Exam record publish/start.

Errors are converted by `Handler._handle_error()` to JSON with `detail`, and optional `code`, `fields`, or extra metadata. Exam errors use 409 for stale revisions; Paper errors use 409 with `PAPER_CHANGED` for stale Paper writes.

## D. Data models and references

Representative shapes below are structural descriptions, not promises that all optional fields exist on every legacy record.

```json
{
  "id": "paper-id",
  "schema_version": 2,
  "status": "draft or published",
  "revision": 1,
  "question_ids": ["question-id"],
  "question_limit": 1,
  "question_filters": {},
  "questions": []
}
```

Published independent Papers persist `questions` snapshot entries with `question_id`, order and grading/content fields. Drafts may have empty `question_ids`; publication and Published edits still enforce exact count. Published Paper edit is in-place and increments record revision.

Legacy Paper shape includes parent `id`, `draft`, `current_version_id`, and `versions` keyed by actual version ID. A legacy Exam reference must preserve both IDs. Do not convert a legacy pair to `{paper_id}` or infer a version from a new Paper ID.

An Exam has `status` in `draft`, `distributed`, `started`, `ended`, `title`, `config`, `items`, `revision`, timestamps and optional `release`. A code `items[]` entry contains either legacy question IDs or Paper distribution. Release includes `release_id`, `released_at`, `applied`, file `assignments`, optional `distribution_mode`, `paper_pool`, `paper_assignments`, and summaries. `paper_assignments[student_id]` preserves selected Paper ref and `code_exam_id`.

`code_exams.json` entries created for Paper distribution include `schema_version: 2`, `release_id`, `general_exam_id`, `paper_ref`, `paper_snapshot`, lifecycle status, Paper snapshot questions and grading/execution policy. Legacy snapshots may instead have `paper_ref` with `paper_version_id` but no embedded `paper_snapshot`.

`assignments.json` is keyed by Student ID. For code Paper release it carries `release_id`, optional `paper_id` plus optional legacy `paper_version_id`, `code_exam_id`, `started_at`, `ends_at`, and status. `code_submissions.json` is keyed by Student and stores records identified by `exam_id`, `release_id`, `question_id`, snapshot version, submission attempt/source and grade. ZIP/file submissions use a separate structure in `submissions.json`.

## E. Snapshot and grading integrity

At `_build_release()`, each validated Paper ref is passed to `create_paper_code_exam()`. That function calls `resolve_paper_reference(require_published=True)` and stores a deep copy as `paper_snapshot`. The release plan stores the eligible pool and deterministic per-Student selection. `get_code_exam()` returns embedded snapshot questions when `paper_snapshot` exists. Paper edits after release therefore do not change that code exam's questions.

Historical legacy path: if a code exam has `paper_ref` but no `paper_snapshot`, `get_code_exam()` requires an explicit legacy `paper_version_id` and reads that persisted version from the legacy parent Paper. It rejects a missing/invalid pair; it does not infer a version for an independent Paper. The safety of that legacy path depends on the referenced version record remaining intact.

At Teacher Start, `_apply_release()` validates each stored Paper assignment against its release-scoped code exam (`release_id` and `paper_ref`) before it writes assignment records. Student retrieval validates assignment, code exam, Paper ref and release. `_active_context()` enforces the live exam state, deadline, status, forced-submit condition and assignment linkage. `run_pretest()`, submission and grading resolve question content through that code exam snapshot. `regrade_submission()` obtains the same snapshot question; for Paper release it explicitly rejects `use_latest_spec`.

Current caveats: snapshots are persisted JSON records and are protected by application behavior, not immutable storage permissions. The legacy fallback depends on preserved legacy Paper versions. JSON writes are atomic per file, but multi-file release changes are not a crash-atomic transaction. The storage lock is process-local; multiple server processes do not share it.

## F. Compatibility, known constraints and open checks

- Common Paper means exactly one Paper ref for every Student. Random means each Student receives one Paper selected from the configured pool at release build time. It does not randomize questions inside a Paper.
- Editing a Draft or `distributed` Exam before Teacher Start is supported. Editing Started/Ended is rejected; actual activity markers also reject a superficially editable release.
- Published Paper updates are in place. Existing release snapshots use embedded Paper snapshot and remain isolated from current Paper contents.
- Question Bank and Practice share `questions.json` and current branch `app/practice.py` imports `execute_question` from `app.code_exams`, but Practice has separate API/progress storage (`practice_progress.json`). The `minghere` branch still requires its own pre-merge audit; this document does not claim its current behavior.
- At handoff time, `docs/EXAM_PAPER_GUIDE.md` still described nested Paper versions. That guide has since been reconciled; for present behavior use the current [Paper guide](EXAM_PAPER_GUIDE.md) and [Code Exam API](CODE_EXAM_API.md), not this historical handoff.
- Current source has Common/Random select UI in `static/js/exams.js:542-544`; the source does not confirm the reported inability to switch. The existing selector test covers Paper selection editing but not a focused Common↔Random toggle. Treat behavior as source-confirmed, browser-test coverage incomplete.
- One running exam is modeled in global `settings.json` (`exam_state`, `exam_release_id`, `exam_released`). No automatic schedule is present.

## G. Tests and verification

No tests were executed during this documentation-only task.

Previously reported in the conversation (not rerun for this report):

| Suite | Previously reported result | Coverage / caveat |
|---|---|---|
| `tests.test_papers` | PASS, 20 tests | Independent/legacy Paper, exact count, incomplete Draft, revision, unavailable reference. |
| `tests.test_paper_distribution` | PASS, 15 tests | Common/random release, snapshot isolation, legacy refs, selection updates before Start, activity guard, stale/invalid refs. |
| `tests.test_code_api` | 34 tests, 1 failure | Runner test received HTTP 503 due Windows `CreateProcessW(suspended)` error 87; reported as environment failure, not a Paper assertion. |
| `node tests/test_exam_selector.js` | PASS, previously reported | Exam selector UI and Paper editing lifecycle; does not verify Common↔Random switching. |
| `node tests/test_paper_builder_filters.js` | PASS, previously reported | Paper builder lifecycle and card request isolation. |

Relevant test locations: `tests/test_papers.py`, `tests/test_paper_distribution.py`, `tests/test_code_api.py`, `tests/test_exam_selector.js`, `tests/test_paper_builder_filters.js`. Validate these results again in the actual merge environment.

## H. Agent onboarding index

1. Read `app/general_exams.py:166-264` for payload normalization and lifecycle fields.
2. Read `app/papers.py:329-381` for legacy/new Paper resolution and `app/papers.py:462-672` for independent CRUD/publish semantics.
3. Read `app/general_exams.py:812-970` for validation, release snapshots, and Common/Random assignment.
4. Read `app/general_exams.py:999-1197` for editing, publish, Start and End.
5. Read `app/code_exams.py:179-350, 393-558, 832-1205, 1443-1587` for Paper snapshot resolution, Student execution, grading and regrading.
6. Read API routing in `app/main.py:348-420, 515-549, 608-654, 763-846` and persistence in `app/storage.py:56-121`.
7. Read `static/js/exams.js`, `static/js/student.js`, `static/js/student-code.js`, `static/js/code-results.js`; then run the relevant tests only with isolated storage.
