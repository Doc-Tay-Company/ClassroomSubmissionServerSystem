# Current Implementation Context — Exam and Paper Management

This file describes the current checked-out source and working tree. Verify Git state, source and tests before relying on repository-specific claims. Audit snapshot: branch `feature/JudgeEngine`, HEAD `f00a5835c16518f5c1c1d976a4fad3264619d0ba`.

See [`../EXAM_PAPER_GUIDE.md`](../EXAM_PAPER_GUIDE.md) for current behavior, terminology, payload examples and compatibility. Acceptance evidence and limits are in [`ACCEPTANCE_REPORT.md`](ACCEPTANCE_REPORT.md); distribution trace is in [`DISTRIBUTION_SNAPSHOT_VERIFICATION.md`](DISTRIBUTION_SNAPSHOT_VERIFICATION.md).

## Terminology

- **Question**: a versioned Question Bank source record persisted in `questions.json`.
- **Paper**: an independently identified ordered code-question set, with one current mutable draft and immutable published versions.
- **Exam**: an operational exam with participants and exactly one Code or ZIP item.
- **Release**: a published/distributed instance of an Exam.
- **Assignment**: persisted student-to-release mapping; Code references a Paper version, ZIP references an exam filename.
- **Snapshot**: immutable question/content data or a reference to a published Paper version used by release/submission/regrade.

## Implemented behavior

### Exam item type

`static/js/exams.js` stores a single `itemType`, renders a persistent radio selector, clears the inactive Code/ZIP configuration on switch, requires explicit repair of malformed multi-item legacy state, and emits at most one item from `toPayload()`. The existing `app/general_exams.py::_normalize_items()` enforces the server invariant and is unchanged by these phases.

### Paper Builder

`static/js/code-papers.js` loads the Question list once and applies client filters for keyword, category, language, grading mode, difficulty and tags. Dimensions combine with AND; selected tags combine with OR. The API currently returns the full unpaginated list.

The UI quantity has minimum 1 and a maximum based on the filtered pool. Random selection is an explicit exact-N sample without replacement and replaces the current ordered selection after confirmation. Select All spans all currently loaded filtered questions and adjusts the limit. The filtered-group checkbox preserves selected questions outside the active filter. Explicit ordered Question IDs are persisted; save/reload/preview/publish does not rerandomize.

`app/papers.py` validates IDs, supported/published eligibility for newly selected Questions, quantity and filters. Drafts may be incomplete; publish requires at least one Question and exact N. Previously selected IDs can remain when source state or current filters change, through a compatibility path. Optional `question_limit`/`question_filters` are backward-compatible fields; no migration runs.

### Save, preview, publish and isolation

The editor tracks dirty/saved state, Paper ID and revision; stale updates are rejected, and view generations stop late responses from being applied after card switching. Preview reads the saved draft and does not publish. Publish saves dirty edits first and is not gated on Preview. Successful publication appends an immutable version; edits affect the one current draft. `?draft=1` explicitly selects draft preview.

The user approved **Model A**: one current mutable draft per Paper plus immutable published versions. Draft revision history and old-draft restore are not implemented. Paper archive/restore changes card status; it does not restore an earlier draft. Persistent cross-Paper overwrite was not confirmed in the source audit; UI isolation is simulated-DOM tested, not browser or multi-process tested.

### Distribution

Common/Random Code Paper selections are persisted in the Exam release and student assignments by exact Paper/version/code-exam references. Student retrieval, submission and default regrade follow those references. ZIP assignments persist a filename, but retrieval reads the current bytes at that path; immutable ZIP byte snapshots are not implemented.

## Source and test map

| File | Responsibility |
|---|---|
| `static/js/exams.js` | Exam editor state, Code/ZIP selector, hydration and payload |
| `app/general_exams.py` | Exam validation, release build/apply and assignment persistence |
| `static/js/code-papers.js` | Paper list/editor, filters, selection, lifecycle and async card isolation |
| `app/papers.py` | Paper CRUD, concurrency, validation, preview and immutable publish snapshots |
| `app/main.py` | HTTP routes and authentication boundary |
| `app/questions.py` | Question validation, lifecycle and list data |
| `app/exams.py` | ZIP distribution and filename assignments |
| `app/code_exams.py` | Paper-version retrieval, submission references and regrade resolution |
| `tests/test_exam_selector.js` | Simulated-DOM selector regression |
| `tests/test_paper_builder_filters.js` | Simulated-DOM builder/lifecycle/isolation regression |
| `tests/test_papers.py` | Paper API, validation, lifecycle and snapshot tests |
| `tests/test_paper_distribution.py` | Common/Random assignment and historical Paper version tests |

## Compatibility and limits

- No storage migration, dependency addition or live runtime-data rewrite was part of these phases.
- Old Paper drafts without quantity/filter fields remain readable; edit/save derives defaults. Legacy question-based Code Exams remain on their existing API/storage path.
- The full test suite is not established safe to run in a single process because module-scoped fixture overrides previously interfered and altered tracked JSON. Run focused Python modules in isolation and check runtime-data hashes.
- Browser/LAN/full-suite and separate-process restart verification remain pending. Judge Engine/runners, hidden tests, pretest, Practice Mode and full ZIP retrieval modes were not exercised by the final acceptance review.
- Draft history/restore is outside approved Model A. ZIP historical bytes are not snapshot-safe.

`AGENTS.md` refers to `docs/ai/PROJECT_CONTEXT.md` and `docs/ai/EXAM_PAPER_TASK_SPEC.md`; both are absent from this checkout. Do not infer their contents. Use current source, implementation rules and the source-backed guide.
