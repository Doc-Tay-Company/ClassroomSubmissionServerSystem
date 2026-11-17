# Exam Distribution and Snapshot Verification

**Phase:** Prompt 09, source audit with isolated relevant tests. No product-code or runtime-data change was made in this phase.

## Baseline and execution safety

- Repository: `ClassroomSubmissionServerSystem`; branch `feature/JudgeEngine`; HEAD `f00a5835c16518f5c1c1d976a4fad3264619d0ba`.
- The checkout already contained modifications from earlier phases in `app/main.py`, `app/papers.py`, `static/js/code-papers.js`, `static/js/exams.js`, `tests/test_code_api.py`, `tests/test_papers.py`, plus untracked user/project files. Those changes were preserved. This phase adds this report and a handover entry only.
- `AGENTS.md`, `IMPLEMENTATION_RULES.md`, `IMPLEMENTATION_CONTEXT.md`, `SOLUTION_DESIGN.md`, `IMPLEMENTATION_PLAN.md`, `PROGRESS_HANDOVER.md`, and Prompt 09 were read. The instruction-referenced `docs/ai/PROJECT_CONTEXT.md` and `docs/ai/EXAM_PAPER_TASK_SPEC.md` are absent.
- Before and after isolated test runs, SHA-256 hashes of `data/code_exams.json` and `data/code_submissions.json` matched; neither file became modified. The two test commands used isolated test modules with temporary fixtures.
- No application process, browser, student login, real server restart, or LAN session was exercised.

## Findings

| Area | Status | Finding |
|---|---|---|
| Common Paper distribution | **Confirmed in source and tests** | Release validation requires exactly one published Paper version. `_build_release()` assigns that same `(paper_id, paper_version_id)` to every eligible participant and persists it in `release.paper_assignments`. |
| Random Paper distribution | **Confirmed in source and tests** | `_build_release()` chooses one version from the validated pool per eligible participant, once while constructing the release. It stores the result and corresponding `code_exam_id`; later student retrieval does not call the random chooser. |
| Persisted assignment and repeat retrieval | **Confirmed in source and tests** | The release's choice map is written with the Exam record; `_apply_release()` copies the chosen Paper/version/code-exam IDs into `assignments.json`. Student retrieval reads the assignment and checks that its release/version matches the code exam. |
| Refresh/relogin stability | **Confirmed by storage path; partly covered by tests** | Authenticated requests resolve by stable student ID and read persisted assignment records. Tests retrieve assigned snapshots and compare assignments after reinitialization, but do not exercise browser refresh or an actual logout/login sequence. |
| Process restart persistence | **Expected from persistent JSON storage; not runtime-verified** | Release and assignment state are stored in JSON files. The test calls `main.initialize()` in the same process; this invokes storage initialization, not a new process. It is not proof of a real server restart. |
| Paper version immutability / post-release edit | **Confirmed in source and tests** | Release stores exact Paper/version IDs; published Paper versions are append-only. The Common test edits and archives the source Paper after release and still retrieves the original ordered questions. |
| Question unpublish/deletion after release | **Confirmed for the saved Paper version path** | Published Paper versions contain saved question snapshots. Retrieval resolves the version snapshot rather than current Question Bank state. The Common test removes one source question and changes another to draft, then still retrieves the released questions. |
| Submission and default regrade | **Confirmed in source and tests** | Submission records persist Paper ID/version ID. Regrade verifies these match the code exam and gets question data through that code exam's Paper-version reference. Default regrade uses the historical snapshot; `use_latest_spec=True` is an explicit opt-in to current Question Bank content. |
| Duplicate Paper question snapshots per student | **Not found** | A Paper code-exam record stores `paper_ref`; `get_code_exam()` resolves its immutable Paper version. Release and per-student assignment records store IDs/references, not repeated question bodies. Paper question content remains in the published Paper version. |
| ZIP distribution mode persistence | **Confirmed in source; partial test coverage** | The source supports `random`, `selected`, `parity`, and `custom`; assignment results are stored in the release and then in `assignments.json`. Only ZIP-only release publication has a focused test in the inspected suite; no direct mode-by-mode persistence/restart test was found. |
| ZIP content snapshot | **Not implemented; source-backed limitation** | ZIP assignments persist a filename. `_apply_release()` checks that the filename still exists, and `/api/student/exam` later reads the file currently at that path. Replacing bytes under the same name can change what a student downloads; removing/renaming it prevents retrieval. This is distinct from Code Paper version snapshots and no ZIP snapshot redesign is made in this phase. |

## Code Paper trace: configuration to regrade

### 1. Configure and validate

- General Exam item normalization in `app/general_exams.py::_normalize_items()` and code distribution normalization validates a `common` or `random` mode and a nonempty list of `{paper_id, paper_version_id}` references (`:180-198`). It rejects duplicate references. `_check_code_papers()` (`:706-728`) resolves each reference with `get_paper_version_snapshot(..., require_published=True)`; Common requires exactly one version.
- The immutable version is created by Paper publishing in `app/papers.py`; release creation uses the explicit version ID rather than the current mutable draft. `get_paper_version_snapshot()` returns the stored version content from that Paper's `versions` map.

### 2. Create the release and choose assignments once

- `app/general_exams.py::_build_release()` (`:730-865`) first validates the complete exam and builds eligible participant IDs. For each validated Paper version it creates a release-scoped code-exam record containing `paper_ref`, then attaches that record to the release.
- For `common`, `selected = refs[0]` for every eligible participant. For `random`, `_choose_random_paper(refs)` is called once for each eligible participant during release creation. The result is saved in `release.paper_assignments[student_id]` with Paper ID, Paper version ID and the matching code-exam ID. The release also retains the Paper pool and distribution summary.
- `publish_exam()` (`:921-945`) returns an existing distributed release unchanged on retry, so a publish retry does not re-sample. `exams.json` stores the release map before the exam begins.

### 3. Apply and persist student assignment

- `start_exam()` (`:1045-1070`) applies the saved release. `_apply_release()` (`:966-1043`) rebuilds each persisted assignment from `release.assignments` and `release.paper_assignments`, checks that the referenced code exam has the same release ID and exact Paper/version reference, then writes `assignments.json` and `settings.json`.
- Each started assignment records `release_id`, `paper_id`, `paper_version_id`, and `code_exam_id`. No random selection runs on a student request. Reapplying a release preserves existing `started_at`, `ends_at`, status and IP fields for the same release.
- `general_exams.reconcile()` (`:361-...`) is idempotent and repairs legacy/uncommitted release records. `app/main.py::main()` calls storage `initialize()`; it does not itself invoke `general_exams.reconcile()` on process boot. Exam lifecycle endpoints call `reconcile()` before relevant mutations. Normal committed release assignments remain available from JSON after process restart, but no actual restart was performed.

### 4. Student retrieval and submission

- `GET /api/student/code-exam` in `app/main.py` (`:417-418`) calls `get_student_code_exam(student_id)`. That function (`app/code_exams.py:477-565`) reads the persisted assignment, verifies release and Paper/version consistency, loads its code-exam record, and returns the exact referenced Paper version's questions. It returns the Paper and version IDs to the client.
- `GET /api/student/code/submission?question_id=...` (`app/main.py:419-422`) reads a submission for that assigned release. `POST /api/student/code/submit` and `/api/student/code/submit-exam` (`app/main.py:825-835`) call `submit_code`/`submit_code_exam`; `_active_context()` verifies the active assignment and code exam match. `_reserve_submission()` (`app/code_exams.py:883-905`) persists `release_id`, question snapshot version, Paper ID and Paper version ID on each submission.

### 5. Regrade and historical content protection

- Admin regrade routes are `POST /api/admin/code-results/{exam_id}/regrade` and `/regrade-student` (`app/main.py:600-621`). `regrade_submission()` (`app/code_exams.py:1510-1589`) verifies the submission belongs to the exam/release and that its Paper ID/version matches the code exam. It then resolves the historical question snapshot by default. Only an explicit `use_latest_spec=True` switches to current Question Bank data.
- `get_code_exam()` (`app/code_exams.py:319-334`) resolves `paper_ref` through `get_paper_version_snapshot()` and attaches the stored version's question snapshots. It does not rebuild from current Question Bank content.
- `delete_paper()` (`app/papers.py:589-604`) checks exams, assignments and code exams for references and refuses deletion while referenced. Archiving a Paper or deleting/unpublishing a source Question does not mutate the published version.

## ZIP distribution trace

- New Exam ZIP configuration is normalized by `app/general_exams.py::_normalize_zip_item()` (`:142-163`) and limited to `DISTRIBUTION_MODES = ("random", "selected", "parity", "custom")` (`:43`).
- `app/general_exams.py::_build_release()` (`:730-755`) delegates ZIP file assignment to `app/exams.py::compute_assignments()` (`:71-147`). Selected mode shuffles the selected file order and assigns cyclically; random mode uses the configured pool/all available files with IP-subnet grouping and a randomized rotation; parity maps the last numeric student-ID digit to even/odd files; custom validates a modulus and complete remainder map.
- The assignment map is kept in the Exam release. `_apply_release()` verifies every assigned filename still exists, then writes the same filename/release ID to `assignments.json`. Student ZIP retrieval is `GET /api/student/exam` (`app/main.py:401-411`): it resolves the current student's saved assignment, checks active release/deadline, then reads the current path in `EXAM_DIR`.
- The legacy `/api/admin/distribute` route (`app/main.py:735-754`) uses `app/exams.py::distribute_exams()`, `compute_assignments()`, and `persist_distribution()` (`:41-69`, `:71-170`). This path persists the assigned filename and release ID directly in `assignments.json`; `start_exam()` (`:172-196`) marks the same record started and is idempotent once `started_at` exists.

The persisted ZIP assignment is stable by student and release. The bytes are not content-addressed or copied into a release snapshot. If exact ZIP historical bytes are a future requirement, it needs a separate product decision and acceptance test; this phase does not alter the ZIP algorithm.

## Existing tests inspected and executed

### Executed

- `python -m unittest discover -s tests -p 'test_paper_distribution.py'` — **6 tests passed**. This covers Common exact ordered Paper version for all participants, Random pool membership and persisted selection, reinitialization/retrieval stability, invalid Paper references/Common cardinality, orphan reconciliation, legacy reconciliation, Paper edit/archive/source-question deletion after release, and submission/default regrade against the same Paper version.
- `python -m unittest discover -s tests -p 'test_code_api.py' -k zip_only_exam` — **1 test passed**. This verifies a ZIP-only Exam publishes without creating a Code snapshot.

### Inspected, not executed

- `tests/test_code_api.py` distribution-related tests include legacy mixed Code/file rejection, ZIP-only publish, and code-only assignment lifecycle. They do not test all four ZIP distribution algorithms through release, student retrieval and restart.
- `tests/test_papers.py` includes published-version immutability and deletion/reference checks; it was not run in this phase.
- No separate ZIP mode/restart test module or true process-restart test was found.

Both executed test commands were run as isolated modules after prior experience showed that importing multiple test modules together can cause their module-level storage fixture overrides to interfere. Runtime JSON SHA-256 values matched before and after these isolated runs.

## Conclusion and minimal follow-up

No confirmed Code Paper Common/Random assignment or historical Paper-version defect was found, so no distribution code was changed. ZIP's assignment mapping is persisted, but content bytes are resolved from the live filename; retain this as a documented limitation unless ZIP content snapshots become an explicit requirement.

Minimal future verification additions, without redesigning distribution:

1. Add a release-level ZIP test for each `random`, `selected`, `parity`, and `custom` mode, then assert student refresh/relogin reads the same `exam_file`.
2. Add an isolated process-restart test that starts a second process against the same temporary `DATA_DIR`; current Common/Random tests call storage initialization in-process and should not be described as a real restart.
3. If ZIP byte immutability is required, decide and test a content snapshot/checksum policy separately before changing file storage.

**Stop point:** distribution behavior is verified as above; no product changes are proposed in this phase.
