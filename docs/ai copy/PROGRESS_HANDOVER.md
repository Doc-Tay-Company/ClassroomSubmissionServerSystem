# Progress Handover — Exam and Paper Improvements

## Repository snapshot

- Repository: `D:\JSD\ClassroomSubmissionServerSystem`
- Branch: `feature/JudgeEngine`
- HEAD: `f00a5835c16518f5c1c1d976a4fad3264619d0ba` (`Đổi cơ chế phát bài`); no commit was created during Prompts 00–11.
- Product and test modifications remain in the working tree. The working tree is not clean; preserve all changes and do not reset, clean, or overwrite them.
- `docs/ai/PROJECT_CONTEXT.md` and `docs/ai/EXAM_PAPER_TASK_SPEC.md` are named by `AGENTS.md` but absent in this checkout. `AGENTS.md`, `docs/ai/IMPLEMENTATION_RULES.md`, `IMPLEMENTATION_CONTEXT.md`, and the active phase prompt were read for this phase.

## Completed prompts and evidence

| Prompt | Result |
|---|---|
| 00 — Recovery | Reconstructed state from current source, Git and docs. This handover replaces the stale multi-stage progress notes. |
| 01 — Re-audit | `RE_AUDIT_REPORT.md` records source-backed findings and runtime-evidence gaps. |
| 02 — Design | `SOLUTION_DESIGN.md` and `IMPLEMENTATION_PLAN.md`; subsequent user approval explicitly selected Model A. |
| 03 — Exam type | `static/js/exams.js` now maintains one selected Code/ZIP type, repairs malformed legacy items only after explicit choice, and emits at most one item. Existing backend `_normalize_items()` rejection remains authoritative. |
| 04 — Quantity and filters | `static/js/code-papers.js` builder and `app/papers.py` validation support quantity and metadata filters. Optional draft fields remain backward-compatible. |
| 05 — Random and Select All | Explicit exact-N Random, full loaded-pool Select All, confirmation, order/ID persistence and manual selection management are implemented. |
| 06 — Draft lifecycle | Save/dirty status, saved Draft Preview, save-before-publish, partial failure feedback, exact-N publish validation and immutable published versions are implemented. |
| 07 — Isolation audit/design | `PAPER_ISOLATION_AUDIT.md` and `DRAFT_REVISION_DESIGN.md` did not confirm backend cross-Paper overwrite. |
| 08 — Approved Model A | Frontend view-generation guards and captured Paper ID/revision isolate delayed card responses. No draft-history schema/API was added. |
| 09 — Distribution | `DISTRIBUTION_SNAPSHOT_VERIFICATION.md`; Common/Random Code Paper assignment passed focused tests. ZIP assignment filename persists, ZIP bytes remain live-path content. |
| 10 — Acceptance | `ACCEPTANCE_REPORT.md` distinguishes PASS/FAIL/NOT TESTED and recommends against claiming full acceptance. ZIP historical-byte snapshot criterion is unmet. |
| 11 — Documentation | This handover and `../EXAM_PAPER_GUIDE.md` now describe actual source behavior; README, SPECIFICATION, Code Exam API, implementation context and historical plan link to current evidence. |

## Current implementation and changed files

### Product code

- `static/js/exams.js` — mutually exclusive item type, selector/legacy repair, payload serialization, and Code preview rendering.
- `static/js/code-papers.js` — filters, quantity, random/select-all, explicit ordered selection, draft lifecycle status, preview/publish flow, stale revision handling and async Paper-card isolation.
- `app/papers.py` — question filter/quantity normalization and validation; incomplete drafts; exact-N publication; saved draft preview routing logic; immutable version append and existing revision checks.
- `app/main.py` — additive `draft=1` Paper preview query dispatch.
- `app/general_exams.py` was not changed; current server-side exactly-one-item invariant predates these phases and remains in place.

### Tests

- Modified: `tests/test_code_api.py`, `tests/test_papers.py`.
- Added: `tests/test_exam_selector.js`, `tests/test_paper_builder_filters.js`.
- No dependency manifest changed.

### Documentation

- Added/current reports: `docs/EXAM_PAPER_GUIDE.md`; `docs/ai/RE_AUDIT_REPORT.md`; `SOLUTION_DESIGN.md`; `IMPLEMENTATION_PLAN.md`; `PAPER_ISOLATION_AUDIT.md`; `DRAFT_REVISION_DESIGN.md`; `DISTRIBUTION_SNAPSHOT_VERIFICATION.md`; `ACCEPTANCE_REPORT.md`; this `PROGRESS_HANDOVER.md`.
- Updated: `README.md`, `SPECIFICATION.md`, `docs/CODE_EXAM_API.md`, `docs/ai/IMPLEMENTATION_CONTEXT.md`, and the historical-status note in `docs/ai/IMPLEMENTATION_PLAN.md`.
- `AGENTS.md` and pre-existing instruction/design documents remain uncommitted workspace files; preserve them.

## Design and storage/API decisions

- **Model A approved:** one current mutable draft per Paper ID; published versions are immutable and append-only. Draft history, old-draft browsing and old-draft restore are not implemented. Paper archive/restore is a status operation.
- Paper draft now optionally stores `question_limit` and normalized `question_filters`; old records without these fields are readable and edit/save derives compatible defaults. No migration or bulk rewrite was run.
- `GET /api/admin/papers/{id}/preview?draft=1` is additive and selects the saved draft. Existing preview route behavior remains available.
- New question IDs are checked server-side for uniqueness, existence, published status, supported grading kind and filter match. Incomplete draft save is permitted; publish requires exact N and at least one ID.
- Exam UI emits at most one Code/ZIP item; server mixed-item validation is unchanged.
- No runtime data migration, new dependency, commit or push occurred.

## Tests actually run

### Prompt 10 runs in the acceptance review

- `node --check static/js/exams.js` — passed.
- `node --check tests/test_exam_selector.js` — passed.
- `node tests/test_exam_selector.js` — PASS.
- `node --check static/js/code-papers.js` — passed.
- `node --check tests/test_paper_builder_filters.js` — passed.
- `node tests/test_paper_builder_filters.js` — PASS, including lifecycle and delayed Paper-card response cases.
- `python -m py_compile app/main.py app/papers.py tests/test_papers.py tests/test_code_api.py` — passed.
- `python -m unittest discover -s tests -p 'test_papers.py'` — 13 tests, OK, run isolated.
- `python -m unittest discover -s tests -p 'test_code_api.py' -k exam_records_reject_mixed_types` — 1 test, OK.
- `git diff --check` — no whitespace errors; Git printed line-ending conversion warnings only.
- PowerShell relative-Markdown-link check over README, SPECIFICATION, the Code Exam API, the new guide and updated AI docs — PASS; all relative targets resolve.
- `data/code_exams.json` and `data/code_submissions.json` SHA-256 hashes were unchanged across Prompt 10 Python test runs.

### Earlier focused phase runs

- Prompt 03: `node --check static/js/exams.js`, selector harness and `python -m unittest discover -s tests -p test_code_api.py -k exam_record` — 3 tests passed.
- Prompts 04–06: JS syntax/harness runs passed; `py_compile` passed; Paper test runs reported 17, 18, then 19 tests OK. Some runs used combined `test_paper*.py` discovery and their module-level fixture interaction changed tracked `data/code_exams.json` and `data/code_submissions.json`; files were restored byte-for-byte to the clean baseline and checked. Do not treat this as evidence that combined suite discovery is safe.
- Prompt 08: UI delayed-response harness passed; isolated/approved Paper test module reported 19 tests OK. The two tracked runtime JSON files were restored after the fixture side effect and verified.
- Prompt 09: isolated `python -m unittest discover -s tests -p 'test_paper_distribution.py'` — 6 passed; isolated `python -m unittest discover -s tests -p 'test_code_api.py' -k zip_only_exam` — 1 passed. Protected JSON hashes remained unchanged.

## Failures, limitations and pending work

- Initial sandboxed Python test attempts could not create temporary fixture directories (`PermissionError`); approved isolated reruns passed. A temporary folder from a failed attempt was removed after path verification.
- Full unittest suite was not run. Earlier combined module fixtures interfered through shared `storage.DATA_DIR` state and touched tracked runtime JSON; a safe all-suite isolation strategy is still needed.
- No real browser/manual UI, application launch, student login, LAN test, or separate-process server restart was performed. Node UI tests use a simulated DOM.
- Judge Engine/runners, hidden tests, pretest, code submission flows, Practice Mode and the complete ZIP mode/student retrieval matrix were not executed as Prompt 10 regression tests.
- ZIP assignment persists a filename, not immutable bytes; replacing/removing the live file can change/break old downloads. This fails a strict exact-historical-ZIP-snapshot requirement.
- `use_latest_spec=true` is an explicit regrade opt-in to latest published Question Bank content; it is not guaranteed to preserve the assigned Paper-version snapshot. The default historical regrade path is covered by Prompt 09 tests.
- Draft revision history/restore is intentionally absent under approved Model A. Cross-Paper overwrite was not confirmed in source; request isolation has simulated-DOM coverage only.
- Downgrade compatibility after deploying the new optional JSON keys was not tested. No migration is involved; back up JSON data before any deployment rollback.

## Exact next action

Documentation and handover phase is complete. Review `../EXAM_PAPER_GUIDE.md` and `ACCEPTANCE_REPORT.md`; do not claim full release acceptance until the ZIP snapshot policy is resolved and the required browser, restart and broader regression checks are run. No further implementation is authorized by this handover alone. Do not commit or push unless requested.
