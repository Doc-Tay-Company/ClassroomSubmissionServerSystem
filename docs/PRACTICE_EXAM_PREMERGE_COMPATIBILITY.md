# Practice Mode and Exam Distribution Pre-Merge Compatibility Audit

**Compared source snapshots**

- Practice Mode: `minghere` at `789d18320d4deadeffa2aca89baf60cc4fe8ffa1`.
- Exam Distribution: committed tree `4c6f5945277d477dd1300b6f286c6b91cda2c68d` (short hash `4c6f594`) in `D:\New_JSD\project_test`.
- Exam workspace status: `feature/JudgeEngine` at this commit, clean working tree; branch reports ahead 1/behind 2 relative to its configured remote. No branch switch or merge was performed.
- Practice workspace has pre-existing documentation deletions/additions; no application source or runtime data was changed for this audit.

## 1. Executive assessment

The exact Owner-designated Exam commit is accessible and verified. The three discrepancies in the earlier audit are resolved in this committed tree: independent Paper references use `{paper_id}` while legacy version pairs remain supported; Paper regrading rejects `use_latest_spec`; and Exam edits require and check `expected_revision`, which the Exam UI sends.

Source contracts are compatible in principle. Practice remains Question Bank based, visible-test only, and separate from official Exam assignments/submissions. Exam Paper releases carry code-exam question snapshots and do not require Practice eligibility. No direct Practice/Exam Student API route collision was found. The main integration work is additive/merge-sensitive in `app/main.py`, `app/general_exams.py`, and `app/code_exams.py`, plus Admin template/UI wiring. This audit did not execute tests or verify the merged application. The commit is suitable for a controlled integration review, not evidence of post-merge acceptance or deployment readiness.

## 2. Practice Mode architecture

### Student access and Question Bank

- `/practice` checks the logged-in Student and account record: `app/main.py:287-292`.
- Practice eligibility requires published status, `practice_enabled is True`, and a valid `practice_revision`: `app/practice.py:40-48`.
- `practice_public_projection()` allowlists Student-safe details and visible tests/checks: `app/practice.py:51-123`.
- The catalog token derives from eligible Question IDs and Practice revisions: `app/practice.py:126-160`.
- Student catalog/detail/progress/run-status handlers enforce Student auth and an active account record: `app/main.py:396-425`.
- Progress is separate in `practice_progress.json`, keyed by Student and Question; unavailable attempted entries are retained: `app/practice.py:380-452`.

### Practice lifecycle and Run

The browser stores per-tab source drafts locally: `static/js/student-practice.js:113-164`. Catalog polling reconciles a changed token: `static/js/student-practice.js:466-540`. Update fetches the authoritative current detail/progress before its CAS request and preserves local source: `static/js/student-practice.js:926-978`.

`run_practice()` validates Student–Question attempt identity, current revision and eligibility, rejects overlapping Student–Question runs, calls the shared runner visible-only, then rechecks revision/attempt before committing the current result: `app/practice.py:509-750`. It writes Practice progress, not official submissions. There is no Practice Submit endpoint; a completed Run is its current result.

### Shared execution versus official submissions

Practice calls `execute_question(question, source_code, visible_only=True, workspace_parent=...)`: `app/practice.py:602-607`. The current function signature supports both options and routes Python/Java STDIO or Java Reflection: `app/code_exams.py:579-623`. Practice and Exam use the same bounded execution slots (`app/code_exams.py:34-38`; Practice admission `app/practice.py:551-552`). Preserve this runner API and capacity behavior.

Official pretest remains tied to a started assignment/release and both Exam/question `allow_pretest` gates: `app/code_exams.py:307-347, 733-760`. Official submission stores source/attempt records and grading in `code_submissions.json`: `app/code_exams.py:776-925, 1060-1089`. Practice progress and source-draft policy remain separate from these records.

## 3. Incoming Exam Distribution contracts

The supplied documents describe the intended Exam-side contracts:

- Technical Handoff, §§ A, C–E: Paper, Exam, Release, Assignment, code-exam snapshot and Submission boundaries; Paper routes; Common/Random; publication/start; snapshots and regrade.
- Merge Contract, §§ A–D: independent Paper identity, legacy references, lifecycle locks, revision checks, frozen release specifications, and runtime-data cautions.
- Code Guide, §§ A–C: Teacher and Student flows, APIs, and navigation. Some Vietnamese prose is encoding-corrupted in the supplied file; identifiers and relevant contracts were cross-checked against commit source.

The previous report compared an older commit. This reassessment inspected the committed tree at the exact Owner-designated hash above. The Exam workspace had no uncommitted modifications at inspection; the branch relation to remote does not change the identity of the inspected commit.

## 4. Shared dependency map

| Component | Practice reference | Exam commit reference | Compatibility | Risk |
|---|---|---|---|---|
| Question eligibility | `app/practice.py:40-48` requires `practice_enabled` | `app/papers.py:65-79, 151-159` validates Published/type/schema without requiring Practice visibility; `app/general_exams.py:766-805` likewise checks publication/type | Compatible | Test a published question with Practice disabled remains Paper-selectable. |
| Student routes/auth | `app/main.py:396-425, 738-758` | Exam code Student routes in `app/main.py` and `app/code_exams.py` | Distinct `/api/student/practice/*` and code Exam routes | Low collision risk; preserve shared auth helpers. |
| Exam record routes | Current `app/main.py` has legacy Exam routes | Commit `app/main.py:374-380, 631-642`; `general_exams` adds Paper distribution to `/api/admin/exam-records` | Same route family, intentionally extended | High merge sensitivity: combine handlers and keep legacy `question_ids` payload support. |
| Paper routes/UI | Current `minghere` has no `/api/admin/papers` backend; its `static/js/code-papers.js` uses old `/api/admin/code-papers*` paths and is not loaded | Commit `app/main.py:350-364, 519-549`; `templates/admin.html:317-322, 377-382`; `static/js/code-papers.js` uses `/api/admin/papers*` | Separate Paper feature absent from Practice baseline | Integrate the committed API, Paper markup, and matching script together; do not retain the stale unmounted client as the active UI. |
| Runner/grader | `app/practice.py:602-607`; `app/code_exams.py:579-623` | Commit `app/code_exams.py:678-722, 843-872, 1072` | Compatible runner call contract; caller policies differ | Keep Practice visible-only; retain full official grading and official submission orchestration. |
| Paper/release snapshots | Practice reads current eligible Question Bank and CAS-checks at Run commit | Commit `app/code_exams.py:182-242, 309-330`; `app/general_exams.py:834-970` | Separate specifications | Do not route Practice through Paper snapshots or official Exam through live Practice projections. |
| JSON persistence | `practice_progress.json`, `questions.json`, `code_exams.json`; `app/storage.py:12-45, 92-117` | Adds `papers.json`, Exam releases/assignments and snapshot references | Helpers are compatible; record schemas differ | Review runtime data separately. `read_json()` returns `{}` for an absent unknown file, and first Paper write creates it; verify initialization and preserve live records. |
| Admin templates/scripts | Current `templates/admin.html` does not load Paper UI script | Commit tree includes Papers tab markup and deferred `code-papers.js` script | Can coexist, but template integration is required | Merge template changes with current Question Bank/Admin work rather than replacing the whole file blindly. |

## 5. Reassessment of previous discrepancies

### C-01 — Independent Paper references: RESOLVED IN COMMIT 4c6f594

- `create_independent_paper()` creates schema version 2 without nested versions or `current_version_id`: `app/papers.py:462-483`.
- `resolve_paper_reference()` accepts `{paper_id}` for schema-v2 Paper snapshots and returns a canonical reference containing only `paper_id`; it requires an explicit `paper_version_id` for schema-v1 legacy records: `app/papers.py:362-384`.
- Exam parsing accepts either the independent form or optional legacy version field: `app/general_exams.py:166-202`. Release selection resolves these refs in `_check_code_papers()`: `app/general_exams.py:812-825`.
- `create_paper_code_exam()` persists the canonical ref and snapshot: `app/code_exams.py:182-224`. The UI selects `{paper_id}` for schema-v2 and a `(paper_id, current_version_id)` pair for legacy Papers: `static/js/exams.js:523-531`.
- The Paper Builder creates independent Papers through `/api/admin/papers/independent`; the older `/api/admin/papers` route still creates the legacy schema-v1 form (`app/main.py:519-526`). This is an intentional compatibility path according to the Code Guide, but external/new clients must use the independent endpoint.
- Commit tests include independent lifecycle and legacy record coverage: `tests/test_papers.py:127-158, 536-552`; release coverage for independent refs and legacy version pairs: `tests/test_paper_distribution.py:164-204`.

### C-02 — Frozen-spec Paper regrading: RESOLVED IN COMMIT 4c6f594

`regrade_submission()` obtains the question from the code-exam snapshot. If `use_latest_spec` is requested and the exam has a Paper reference, it raises 409 before reading the live Question Bank; only the non-Paper path may resolve a current published Question: `app/code_exams.py:1533-1555`.

Committed tests exercise rejection of `use_latest_spec=True`, successful snapshot regrade, and frozen Paper snapshot behavior after source changes: `tests/test_paper_distribution.py:164-204`. These tests were inspected, not executed in this audit.

### C-03 — Exam expected_revision protection: RESOLVED IN COMMIT 4c6f594

- `create_exam()` initializes `revision: 1`: `app/general_exams.py:716-740`.
- `update_exam()` requires an integer token, rejects stale values with 409 before updating, and performs the read/check/write within `transaction()`: `app/general_exams.py:999-1033`. `_touch()` advances the revision after the update (`app/general_exams.py:281-283` and its call at `:1025`). Draft and distributed states are accepted; started/ended are rejected.
- Exam editor `toPayload()` includes `expected_revision: exam.revision || 1` for existing exams, and `persist()` submits that payload to the update route: `static/js/exams.js:264, 320-327`.
- Committed regression coverage references stale Exam revisions and verifies no writes: `tests/test_paper_distribution.py:402-427`; the Merge Contract names `test_invalid_new_paper_selection_and_stale_exam_revision_do_not_write`.

## 6. Remaining conflicts and semantic risks

No direct incompatible Practice contract was confirmed in the inspected committed source. The following are integration risks or limited uncertainties, not demonstrated blockers:

1. **Exam eligibility versus Practice visibility — Compatible in source; retain as a regression check.** Paper selection checks Published status and supported grading kind, not `practice_enabled` (`app/papers.py:65-79, 151-159`; `app/general_exams.py:766-805`). Keep that separation.
2. **Question edits after release — Compatible by snapshot design; verify end-to-end.** Release construction creates Paper-scoped code-exam snapshots (`app/general_exams.py:834-900`; `app/code_exams.py:182-224`). Student access uses embedded `paper_snapshot` when present; legacy records fall back to the exact stored version pair (`app/code_exams.py:309-330`). Regrade uses the same snapshot. Preserve this distinction from Practice's current-Question revision checks.
3. **Common/Random distribution — Source-supported.** `_normalize_code_item()` accepts both modes and optional version IDs; `_build_release()` creates snapshots for the pool and persists the per-Student selection (`app/general_exams.py:166-202, 834-970`). Keep legacy `question_ids` form as well.
4. **Legacy Paper API semantics — Compatibility nuance.** POST `/api/admin/papers` still invokes schema-v1 `create_paper()`, while the new Paper Builder uses `/api/admin/papers/independent` and schema-v2. Do not redirect old clients or reinterpret existing records without an explicit migration decision.
5. **Shared route/file edits — Merge sensitivity, not a source conflict by itself.** Both branches change `app/main.py`, `app/code_exams.py`, and `app/general_exams.py`. Merge by behavior and preserve Practice routes, progress contracts, visible-only runner kwargs, and CAS guards; selecting either entire file can lose the other branch's work.
6. **Runtime JSON — Separate from source merge.** Exam commit includes changes to `data/code_exams.json` and `data/code_submissions.json`, and adds Paper persistence. Never overwrite current runtime JSON wholesale. Compare schemas and IDs and preserve assignments, Practice progress, submissions, scores, and snapshots.
7. **Legacy Paper snapshot fallback — Limited compatibility risk.** `get_code_exam()` uses embedded snapshots for new records and resolves a legacy version pair only when no embedded snapshot exists. Preserve both branches and test a legacy code-exam record with its source Paper still available; behavior after deletion of its legacy Paper record is not established by this audit.

## 7. API and data compatibility

### API overlap and differences

- Practice APIs remain under `/api/student/practice/*`; Paper APIs are `/api/admin/papers*`; Exam records use `/api/admin/exam-records`. No Practice/Exam Student route collision was found.
- `/api/admin/exam-records` is shared by design. The Exam payload supports legacy `question_ids` and new `distribution: {mode, paper_versions}`. The handler and frontend must retain both forms: `app/main.py:631-642`; `app/general_exams.py:166-202`; `static/js/exams.js:236-264`.
- Practice and Exam error/response contracts differ. Preserve `PracticeError` status/code/extra data and Exam-specific response shapes; do not normalize them as part of merge.
- Paper UI requires the matching `templates/admin.html` Paper tab and `static/js/code-papers.js` script from the Exam tree. Current Practice Admin template/script set does not include them.

### Persistence boundaries

Practice uses current Question Bank records and `practice_progress.json`; local source stays in browser storage. Exam adds Paper definitions, releases, assignments, Paper/code-exam snapshots, official submissions and grading data. `app/storage.py` has atomic per-file JSON writes and a process-local reentrant lock; its generic missing-file fallback is `{}` for unknown filenames, while initialization only creates names in `DEFAULTS`.

Source integration does not authorize runtime-data replacement. The incoming commit includes Exam runtime JSON changes; compare them separately and do not copy over current Questions, Students, Practice progress, assignments, official submissions or settings wholesale.

## 8. Merge-critical invariants

| Invariant | Commit evidence | Assessment |
|---|---|---|
| New independent Paper uses stable `paper_id`; legacy pair remains readable | `app/papers.py:362-384, 462-483`; `app/general_exams.py:166-202` | Verified in commit; C-01 resolved. |
| Paper Release regrade uses frozen snapshot | `app/code_exams.py:1533-1555` | Verified in commit; C-02 resolved. |
| Exam edit has required CAS and UI token | `app/general_exams.py:999-1033`; `static/js/exams.js:264, 320-327` | Verified in commit; C-03 resolved. |
| Publishing does not start an Exam | `app/general_exams.py:1036+` publish path; explicit `start_exam()` at `:1160+` | Separate lifecycle actions in source; preserve and regression-test. |
| Students require Teacher Start | release/assignment gates in `app/code_exams.py` and Student access routes in `app/main.py` | Commit code and handoff align; preserve. |
| Draft and Published-not-Started Exams remain editable; started/ended locked | `app/general_exams.py:999-1023` | Verified in update status gate. |
| Common/Random assignments are persisted per release | `app/general_exams.py:834-970` | Verified by source and committed tests (not executed here). |
| Release snapshot survives Paper/Question edits | `app/code_exams.py:182-224, 309-330`; `tests/test_paper_distribution.py:164-204` | Source-supported; end-to-end tests not executed. |
| Practice remains independent and visible-only | `app/practice.py:509-607`; no Paper/Exam assignment lookup in Run path | Verified in current Practice source; regression-test after merge. |
| Exam eligibility does not require Practice flag | `app/papers.py:65-79, 151-159`; `app/general_exams.py:766-805` | Verified in Exam source. |

## 9. Recommended merge handling

1. Use commit `4c6f5945277d477dd1300b6f286c6b91cda2c68d` as the reviewed Exam source; do not fall back to `f00a5835` for these contracts.
2. Combine, rather than wholesale-select, the shared `app/main.py`, `app/general_exams.py`, and `app/code_exams.py` changes. Preserve Practice routing/progress, Question Bank guards, visible-only Run and shared runner arguments.
3. Integrate Paper model/API/UI as a coherent set: `app/papers.py`, Paper routes, the Admin Paper tab markup, `code-papers.js`, and Exam Paper selector code. Preserve the current Question Bank/Admin interface.
4. Keep independent Paper `{paper_id}` semantics and exact legacy pair support. Keep the generic legacy Paper creation route distinct from the independent Paper Builder endpoint.
5. Keep Exam Paper release snapshots and regrade isolated from Practice's live Question Bank contract. Keep `practice_enabled` out of official Exam eligibility.
6. Compare runtime JSON separately; preserve existing IDs, Students, assignments, Practice progress, official submissions and scores. Do not infer that a source commit's JSON is a safe replacement dataset.
7. After integration, run focused Paper/Exam tests plus Practice, Question Bank concurrency and official code API/regression suites. Then verify browser flows for Paper creation/selection, publish versus Start, and Practice Run/Update.

No tests or browser checks were executed for this read-only audit.

## 10. Post-merge regression checklist

- [ ] Practice catalog/detail/progress require active Student auth and expose only eligible questions and visible fields.
- [ ] Practice works without a Paper, Exam release, Student assignment or Exam pretest permission.
- [ ] A published question with practice_enabled=false remains eligible for official Paper selection.
- [ ] Practice Run stays visible-only, uses the current Question revision, preserves prior result on infrastructure failure, and creates no official submission/assignment.
- [ ] Practice local source recovery, independent tab drafts, update and progress polling remain intact.
- [ ] Official pretest still requires a started assignment/release and honors Exam/question allow_pretest gates.
- [ ] Official submissions, hidden-test grading, quotas, Student result ownership and score persistence remain unchanged.
- [ ] New independent Paper refs use `{paper_id}`; legacy `(paper_id, paper_version_id)` references resolve exactly.
- [ ] Common Paper gives all Students the same ordered snapshot; Random selects a pool member once and persists each assignment.
- [ ] Publishing an Exam does not start it; Student content remains unavailable until Teacher Start.
- [ ] Draft and Published-not-Started update accepts the current expected_revision and rejects missing/stale tokens without writes; Started/Ended edits reject.
- [ ] Editing or archiving a source Paper/Question after release does not alter the release snapshot.
- [ ] Paper regrade uses the frozen snapshot; use_latest_spec is rejected for Paper release records and remains available only where supported for non-Paper exams.
- [ ] Runtime JSON integration preserves all existing Practice and Exam data.
- [ ] Python, Java STDIO, Java Reflection, shared capacity/busy behavior, and error classification are regression-tested on the intended Windows host.

## 11. Open questions and verification gaps

1. **No test execution:** The committed test source covers independent and legacy Paper refs, frozen regrade, Common/Random assignment, stale Exam revision, and release snapshots; this audit did not run those tests.
2. **No merged-tree verification:** Compatibility is assessed between the two source snapshots, not a merged checkout. Shared-file conflict resolution and full route/template integration still require post-merge verification.
3. **Legacy Paper deletion:** The current committed `get_code_exam()` fallback requires the legacy Paper/version record if an older code-exam record lacks embedded `paper_snapshot`; survival after deleting that source record is not verified.
4. **Runtime JSON:** The Exam commit contains modified code exam/submission JSON. Their records were not merged or compared field-by-field against current live data; they must be treated as data requiring separate review.
5. **Windows runner and deployment:** This audit does not resolve RUN-01 through RUN-05, validate actual Windows execution, or establish production/deployment readiness.
6. **Tested product behavior:** Tests are source-inspected only; no claim of passing tests, browser verification, or Owner acceptance is made.

### Decision

Commit `4c6f594` resolves C-01, C-02 and C-03 at source level. No direct incompatible Practice contract was confirmed. A controlled merge can proceed for technical integration, but a merge/acceptance decision still requires conflict-aware combination of shared modules, separate runtime-data handling, and post-merge automated and browser verification. This report does not approve the merge or declare deployment readiness.