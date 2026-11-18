# Exam Distribution Merge Contract

This is the Exam-side contract for integration with Practice Mode. It is not a merge procedure. All Exam statements below are verified against the current `feature/JudgeEngine` working tree. Practice-specific behavior must be rechecked on `minghere`.

## A. Critical invariants

1. **Independent Paper identity:** schema v2 Paper has one stable Paper ID and record revision; Published edits update that record in place. Draft copy creates a separate Paper ID. No new version ID is manufactured.
2. **Legacy references:** retain exact `(paper_id, paper_version_id)` pairs. A pair resolves only to an actual legacy version. A versionless reference resolves only to an independent Paper. Never rewrite historical refs implicitly.
3. **Question Limit:** Publish and Published Save Changes require `len(question_ids) == question_limit` and eligible references. Draft create/update permits empty and incomplete selections while retaining schema checks.
4. **Lifecycle:** Exam `draft` and `distributed` are editable; `distributed` means Published-visible and not yet Teacher-started. Only explicit Teacher Start changes it to `started`. `started` and `ended` are not editable. No automatic scheduling.
5. **Pre-Start Paper Selection:** configuration updates preserve `expected_revision`; published pre-start changes rebuild the pending release and synchronize only preparatory records. Activity markers cause rejection.
6. **Distribution semantics:** Common has exactly one Paper for all Students. Random selects one member of the configured pool per Student at release construction and stores the choice. Neither mode is random question selection inside a Paper.
7. **Release isolation:** each new release stores release-scoped code exam snapshots from Published Paper content and a Paper assignment map. Student paths use the code exam attached to the matching assignment/release.
8. **Student access:** published card visibility alone does not permit work. ZIP and code access require the Teacher-started global release and a started matching Student assignment.
9. **Submission/grading:** submission is tied to exam/release/question. Grading uses the assigned release's question snapshot and server-side grader checks. Paper release regrade cannot opt into latest Question Bank spec.
10. **Revision protection:** Exam updates require current integer `expected_revision`; stale values are rejected before update. Paper writes have a separate Paper revision guard.
11. **Execution-context separation:** current branch has separate Practice routes/progress store, but `app/practice.py` imports the shared `execute_question` helper from `app/code_exams.py`. Verify this API boundary and runner contract against Practice branch before resolving shared code.

## B. Integration-sensitive code

| Area | Exam expectation | Merge hazard | Regression evidence |
|---|---|---|---|
| `app/main.py` routing/auth | Admin Exam routes and Student endpoints must coexist with Practice routes and role guards. | Route collision, wrong auth role, or overwritten handler breaks student access or Practice. | `tests.test_code_api`, `tests.test_paper_distribution`; add/run Practice route suite from `minghere`. |
| `app/code_exams.py` | Paper release loads `paper_snapshot`; Student validation checks assignment/release/ref; exam grading and Paper regrade use that snapshot. | Replacing `get_code_exam()` or execution flow with a Practice projection/current Question loader can change released exam content or grading. | `test_independent_paper_release_freezes_snapshot_and_supports_random_pool`, `test_submission_and_regrade_resolve_the_same_paper_version`, code submission/regrade tests in `tests/test_code_api.py`. |
| `app/practice.py` and `execute_question()` | Current branch Practice uses a distinct progress API but shared question execution helper. | Combining Practice lifecycle/progress with Exam release/deadline/submission checks can leak context or alter runner parameters. Practice branch details unverified here. | Run both branch Practice runner/progress suites and Exam runner tests; include an Exam snapshot regression. |
| Question Bank (`app/questions.py`, `questions.json`) | Paper references validate status, eligibility and filter rules at authoring/release; release snapshot survives later source changes. | Conflict resolution may drop validation fields, Question lifecycle rules, or source identity checks. | `tests.test_papers`; snapshot isolation in `tests.test_paper_distribution`. |
| `app/papers.py` and `papers.json` | Independent Paper IDs coexist with legacy nested version records and pairs. | Flattening JSON or choosing one branch’s data can destroy legacy versions or alter new records. | Legacy resolution tests in `tests.test_papers` and `tests.test_paper_distribution`. |
| `static/js/exams.js` | `distribution.mode` supports `common` and `random`; refs are serialized as `{paper_id}` or legacy pair. | A form merge may hide the select, drop `paper_versions`, or send fake/malformed version IDs. | `tests/test_exam_selector.js` tests Paper editing; add a focused Common↔Random toggle check (current test gap). |
| `static/js/student.js`, `student-code.js` | Student list and access paths are status-aware; code request APIs use authenticated Student context. | A Practice navigation/auth merge could expose official Exam actions before Teacher Start or break polling. | `tests.test_code_api` student route tests and Practice branch browser/API tests. |
| Submission/grading (`code_submissions.json`, `app/code_exams.py`) | `release_id` is part of attempt identity; regrade Paper release uses frozen specification. | Merging current-spec Practice behavior into official regrade could reinterpret historical results. | `test_submission_and_regrade_resolve_the_same_paper_version`, regrade tests in `tests/test_code_api.py`. |
| `app/storage.py` | JSON atomic replacement and an in-process `RLock` protect local read/write sequences. | Replacing helpers with a different lock/write contract may introduce lost updates; lock is not cross-process. | Existing stale revision and invalid update tests; multi-process guarantees are not tested or promised. |

## C. Merge invariant matrix

| Invariant | Code Reference | Failure Mode | Verification |
|---|---|---|---|
| Independent Paper ID/revision, in-place Published edit | `app/papers.py:462-568` | Save creates a fake version/entity or silently overwrites another revision. | `tests.test_papers.ExamPaperApiTests.test_independent_paper_lifecycle_and_draft_copy` plus stale-revision case. |
| Legacy Paper/version pair remains exact | `app/papers.py:329-381`; `app/general_exams.py:166-215` | Old Exam resolves to current Paper or wrong version. | Legacy ref tests in `tests.test_paper_distribution` and `tests.test_papers`. |
| Exact count on Publish / Published edit; empty/incomplete Draft | `app/papers.py:172-202, 508-568, 635-672` | Draft cannot be saved, or invalid Published content is accepted. | `tests.test_papers` exact-count and incomplete/zero Draft tests. |
| Publish is not Start | `app/general_exams.py:1036-1060, 1160-1197` | Student can begin as soon as card is published. | `tests.test_code_api` Student access and lifecycle tests. |
| Edit only before Teacher Start | `app/general_exams.py:999-1034`; `static/js/exams.js:118, 520-544` | Started/ended Exam configuration changes, or pre-start edit is incorrectly blocked. | `tests.test_paper_distribution` pre-start, activity-marker and started-history cases; selector JS test. |
| Common/Random selection persisted per release | `app/general_exams.py:812-970` | Random re-draws on Student reload or Common varies among Students. | `test_common_assigns_one_exact_ordered_snapshot...`; `test_random_selects_only_pool_members...`. |
| Release Paper snapshots are source for Student and grading | `app/code_exams.py:179-240, 309-330, 393-558, 832-1205` | Current Paper/Question edit changes an existing release. | `test_independent_paper_release_freezes_snapshot...`; submission/regrade snapshot test. |
| Student content access requires start | `app/main.py:403-420, 820-846`; `app/code_exams.py:393-558` | Student reads official questions or submits before start/deadline. | Student API access/deadline tests in `tests/test_code_api.py`. |
| Paper regrade stays on release spec | `app/code_exams.py:1503-1587` | Historical score is recalculated with current Question spec. | `test_submission_and_regrade_resolve_the_same_paper_version` and regrade API tests. |
| Stale Exam update rejected | `app/general_exams.py:999-1020` | Concurrent editor silently overwrites newer config. | `test_invalid_new_paper_selection_and_stale_exam_revision_do_not_write`. |
| Practice and Exam execution contexts remain distinct | `app/practice.py:509-607`; `app/code_exams.py:393-558` | Practice progress or unrestricted runs become Exam submissions, or vice versa. | Run Practice branch tests plus Exam access/submission tests; not verified for `minghere` in this task. |

## D. Data safety

Merging code and merging runtime JSON are separate operations. Runtime files include:

- `papers.json`: independent and legacy Paper records; legacy version IDs may be referenced by saved Exams/history.
- `exams.json`: Exam configuration, lifecycle and release plans.
- `code_exams.json`: release-scoped question snapshots and legacy code exam records.
- `assignments.json`, `settings.json`: current release assignment/state pointers.
- `code_submissions.json`, `submissions.json`: attempts, source and historical grading/submission records.
- `questions.json`, `practice_progress.json`: shared Question Bank and Practice progress.

Do not blindly select either branch's runtime JSON version. Compare schema and record-level differences, preserve IDs and snapshots, and do not apply a source-code merge as a data migration. This task does not authorize data-file conflict resolution.

## E. Confirmed unresolved issues / investigation result

**Reported Common/Random mode-switch limitation is not confirmed by current source.** `static/js/exams.js:542-544` renders a `select` with both modes and enables it when `canEdit` is true; `canEdit` includes Draft and `distributed` (Published-not-started) exams (`:523`). The change handler updates `code.mode`; when selecting Common it keeps at most the first Paper. `tests/test_exam_selector.js` does not currently exercise switching an existing Exam between modes, so browser behavior is not fully covered. No fix was made.

Other documented constraints, not newly introduced merge defects: storage locking is process-local; individual JSON writes use temp-file replacement but a sequence of writes across JSON files is not a crash-atomic transaction. Historical legacy Paper fallback requires retained version data. Current merge branch's Practice behavior must be audited on `minghere`; this branch alone cannot certify it.

## F. Post-merge acceptance checklist

- [ ] Create, edit, publish and archive an independent Paper; keep its ID/revision semantics.
- [ ] Save Draft with zero/incomplete questions; reject Publish and Published edit unless exact limit and eligibility pass.
- [ ] Read a legacy Paper using its exact `(paper_id, paper_version_id)`; verify no reference was rewritten.
- [ ] Create Exam with Common Paper; verify one identical ordered snapshot for all assigned Students.
- [ ] Create Exam with Random pool; verify only pool members are selected and each persisted assignment remains stable.
- [ ] Toggle Common↔Random in Edit Mode, save, reload and verify mode/pool; verify Common trims to one selection and Random accepts multiple.
- [ ] Publish Exam and verify Student can see permitted card data but cannot start before Teacher Start.
- [ ] Edit Paper Selection while Draft and while Published-not-started; verify new selection is used at explicit Start.
- [ ] Verify Started and Ended Exam edits are rejected; existing assignments/submissions/results stay intact.
- [ ] Edit source Paper/Question after release; verify Student access, submit, grade, historical view and regrade use the intended release snapshot.
- [ ] Verify stale revision, invalid Paper ref and activity-marker failure leave persistent Exam/assignment/snapshot data unchanged.
- [ ] **Practice branch required:** run Practice route/auth/progress tests, verify shared runner API and Question shape, and ensure Practice records never appear as Exam assignments/submissions.
- [ ] **Practice branch required:** verify merged Student navigation, polling and authenticated views in the actual `minghere` implementation.
