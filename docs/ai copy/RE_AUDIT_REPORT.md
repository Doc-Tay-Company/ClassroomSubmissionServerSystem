# Repository Re-audit — Exam & Paper Management

- **Repository:** `ClassroomSubmissionServerSystem`
- **Checkout:** branch `feature/JudgeEngine`, commit `f00a583` (`Đổi cơ chế phát bài`), HEAD matches `origin/feature/JudgeEngine` and the audit baseline supplied in the project context.
- **Working tree at audit start:** no tracked staged or unstaged changes. Existing user-provided untracked files were `AGENTS.md`, `docs/ai/IMPLEMENTATION_CONTEXT.md`, `docs/ai/IMPLEMENTATION_RULES.md`, and the recovery handover under `docs/ai/`. They were read and preserved. This report is newly created.
- **Method:** source/API/storage/test inspection only. No app launch and no tests executed. Findings about runtime interactions are labeled separately from source-derived facts.

## Findings at a glance

| Topic | Status | Conclusion |
|---|---|---|
| Baseline and file responsibilities | **Confirmed** | Checkout is exactly `feature/JudgeEngine` / `f00a583`. Existing paper, exam, release, ZIP, and code assignment code is present. |
| Code/ZIP behavior in the reported normal click path | **Not found in source** | On a new or valid single-item Exam, selecting one type hides the other type's selector. A second checkbox cannot be clicked in that state. The reported normal sequence does not match this checkout's current source. |
| Both-type state and disappearing sections | **Partially confirmed** | `fromExam()` can hydrate both values from an invalid/legacy record; render conditions then hide both sections. Backend rejects a payload with more than one item. A runtime report from the deployed browser/build is needed to reconcile the user's exact observation. |
| Paper quantity/filter/random/select-all controls | **Confirmed** | Paper editor supports text search, add/remove and ordering only. There is no question count limit, metadata filter UI, random pick, or select-all. |
| Paper storage isolation | **Confirmed** | Paper records are keyed by independently generated Paper IDs; service mutations take the URL Paper ID and preserve revision checks. No service-level cross-Paper write path was found. |
| Paper editor async state race | **Partially confirmed** | Editor state is shared globally and async handlers do not verify that the selected Paper is still the one whose request began. A late response can replace the currently rendered editor. Actual occurrence and any mistaken subsequent save need runtime evidence. |
| One draft vs draft history | **Confirmed** | Each Paper has one current `draft` object plus immutable published `versions`; each draft update replaces that one draft. Historical draft revisions are not retained. |
| ZIP and Code Paper distribution | **Confirmed** | ZIP supports random/selected/parity/custom; Paper code supports Common/Random. Release assignments and Paper version IDs are persisted and used for retrieval/submission/regrade. |

## A. Baseline and file responsibilities

### Repository instructions

- Read `AGENTS.md`, `docs/ai/IMPLEMENTATION_CONTEXT.md`, `docs/ai/IMPLEMENTATION_RULES.md`, `docs/ai/PROGRESS_HANDOVER.md`, and the requested Prompt 01.
- `AGENTS.md` refers to `docs/ai/PROJECT_CONTEXT.md` and `docs/ai/EXAM_PAPER_TASK_SPEC.md`; those files are absent from this checkout. The project context/rules files named in the session-recovery prompt are present.
- The recovery handover says the earlier report was absent. That remains consistent with the checkout at audit start; no earlier `docs/ai/RE_AUDIT_REPORT.md` existed.

### Relevant modules

| File | Responsibility confirmed in source |
|---|---|
| `static/js/exams.js` | Admin Exam cards/detail editor; state hydration, Code/ZIP selection, Paper version pool selection, Exam draft save/autosave, preview and publish actions. |
| `app/general_exams.py` | Exam record normalization and lifecycle; one-item validation; release construction; Paper validation and per-student Code Paper assignments; release application/start/end; legacy Exam reconciliation. |
| `app/exams.py` | ZIP file inventory, legacy/global distribution algorithms, assignment persistence, student start/end helpers. `general_exams` reuses `compute_assignments()` when building a release. |
| `static/js/code-papers.js` | Paper list/detail/editor and question selection UI, save, draft preview, publish, archive/restore/delete. |
| `app/papers.py` | Paper validation, persistence, revision checks, draft preview, immutable published version snapshots, archive/restore/delete and reference checks. |
| `app/questions.py` | Question validation, lifecycle and Question Bank storage/listing. `/api/admin/questions` returns `list_questions()` records. |
| `app/code_exams.py` | Code Exam snapshot creation, student-facing retrieval, pretest/submission, score release and regrade. Paper-backed snapshots retain `paper_ref`. |
| `app/submissions.py` | ZIP upload validation and persistence against the student's active `release_id`/ZIP assignment. |
| `app/main.py` | HTTP routes for admin Question/Paper/Exam operations and student exam, code and ZIP submission operations. |
| `app/storage.py`, `app/config.py` | JSON defaults, locking/atomic single-file writes and repository-root `data/` paths. Paper data is stored in `data/papers.json`; related records live in `data/exams.json`, `data/assignments.json`, `data/code_exams.json`, and `data/code_submissions.json`. |
| `tests/test_papers.py` | Paper UI route/API CRUD, selection validation, preview, revision conflict, publication snapshots, source changes, archive/restore/delete. |
| `tests/test_paper_distribution.py` | Common/Random assignment, Paper version stability, student retrieval, release persistence, submission/regrade references and invalid release inputs. |

## B. Code / ZIP selector

### State initialization and hydration

- `static/js/exams.js::blank()` (around lines 180–184) initializes `code: null` and `zip: null`.
- `fromExam()` (around lines 186–215) loops over every stored item and sets `f.code` for `type === "code"`; every other item is hydrated as ZIP. It does not explicitly clear the opposite property or reject a record containing both item types.
- In a normal new form, state starts mutually empty. With a valid stored Exam, backend normalization permits at most one item. A legacy/corrupt record containing both types can nevertheless hydrate both state properties.

### Checkbox handlers and render conditions

- `codeSection()` (around lines 458–465) updates only `form.code`; its render returns `null` whenever `form.zip` exists.
- `zipSection()` (around lines 547–555) updates only `form.zip`; its render returns `null` whenever `form.code` exists.
- `render()` (around lines 680–692) invokes both functions, so a state with both values set makes both sections return `null`.
- For a new/valid Exam, selecting Code causes the ZIP section—including its checkbox—to disappear. Selecting ZIP causes the Code section—including its checkbox—to disappear. Therefore a user cannot perform “check Code, then check ZIP” via the ordinary visible controls in this checkout. This contradicts the earlier audit's assertion that the visible normal interaction directly leaves both values selected.

### Serialization, save and backend validation

- `toPayload()` (around lines 223–251) emits one item for each non-null state property. It would emit both if passed a both-true state.
- `persist()` (around lines 307–324) POSTs a new Exam or POSTs `/{examId}/update`; existing draft autosave calls it through `scheduleAutosave()` (around lines 328–337).
- `publish` handler (around lines 599–619) validates client fields, saves, then POSTs `/{examId}/publish`.
- `app/main.py` routes create/update/publish at `/api/admin/exam-records` and `/api/admin/exam-records/{exam_id}/{update|publish}` (around lines 619–630).
- `app/general_exams.py::_normalize_items()` (around lines 217–245) rejects more than one item. `_validate_publishable()` (around lines 637–654) independently requires exactly one supported item before release.

### Status and reproduction

**Status: partially confirmed overall; the reported normal click sequence is not found in current source.**

Source-derived failure path for an invalid stored record:

1. Load an Exam record whose `items` contains one Code item and one ZIP item.
2. `fromExam()` sets both `form.code` and `form.zip`.
3. `render()` calls `codeSection()` and `zipSection()`; each returns `null` because the opposite value is truthy.
4. Neither type checkbox remains visible to clear the bad state. If a save/publish handler can be reached, `toPayload()` emits two items and server validation rejects it.

This path requires pre-existing invalid/legacy data or state injection; it is not reachable by ordinary clicks from the blank form as currently rendered. Confirm the user's exact scenario against the deployed JavaScript/build, browser cache, and the loaded Exam record before calling the normal click bug confirmed.

### Minimal direction and risk

- If the intended experience is an explicit mutually exclusive choice, use a persistent radio/toggle control and normalize legacy dual-type data so the user can recover it. Keep `_normalize_items()` and publish validation as server safeguards.
- Add a focused UI regression for both directions and hydration of an invalid two-item record. Existing source tests do not provide browser coverage for these conditions.
- Do not change server distribution semantics based on the reported click sequence alone; current backend rejection is appropriate for the stated one-type rule.

## C. Paper question selection

### Question fields and list API

- `app/questions.py::_validate_question()` (around lines 107–145, 201–214) requires title, statement, supported `(language, grading_mode)`, grading limits and point totals; it stores new questions with `status: "draft"`. Optional metadata fields such as `category`, `tags`, and `difficulty` are accepted from the question editor payload, but are not given explicit type/normalization checks in this validator.
- `static/js/questions.js::newDraft()` (around lines 620–627) models `category`, `tags`, and `difficulty`; `buildPayload()` (around lines 1021–1041) preserves them (except blank difficulty). The Question Bank UI filters by language, grading mode, status, category, usage count and text over title/tags/ID (around lines 167–190).
- `app/questions.py::list_questions()` (around lines 258–260) returns stored question objects. `GET /api/admin/questions` in `app/main.py` (around lines 346–347) returns that list without server-side filtering or a Paper-specific projection.
- Paper editor's `openEditor()` filters the returned records to `status === "published"` and supported kinds: Java reflection, Java stdio, Python stdio (`static/js/code-papers.js`, around lines 133–147; supported predicate at lines 11–13).

### Metadata-backed filter dimensions

For a Paper picker, dimensions supported by current question fields are:

- `language` and `grading_mode`: required and enumerated by the server validator; also displayed by the picker.
- `category`, `tags`, and `difficulty`: modeled by the Question editor and preserved in stored/API records, but optional and not strongly type-validated in `app/questions.py`; normalize/validate before relying on them as structured filters.
- `title` and `id`: available text fields and already used by the picker search.
- `total_points`: computed/validated numeric question metadata and displayed in the picker. It could support a points filter if desired.
- `status`: stored lifecycle field; Paper picker currently prefilters to Published, so a status filter would have no useful variation unless the picker scope is deliberately expanded.

Do not infer other filter dimensions from UI wording or project plans; the list above is limited to fields evidenced in Question creation/list/editor code.

### Paper picker behavior and missing capabilities

- `static/js/code-papers.js::renderEditor()` builds one search input, available/selected panes and a question count (around lines 153–205).
- `renderQuestions()` searches title, category and ID, excludes already selected IDs, and adds one question per click (around lines 166–188). Selected questions can be reordered and removed; `selected` order is serialized to `question_ids` (around lines 174–185, 223).
- No Paper-builder control accepts a quantity limit. No structured category/language/mode/difficulty/tag filter controls, random selection, or select-all control exists in this component.
- `app/papers.py::_validate_ids()` requires a nonempty array of valid unique IDs (around lines 35–42); `_validate_new_questions()` confirms existence, Published status, supported kind and valid question data (around lines 62–82). There is no limit or filter/random-selection contract in the API.

**Status: confirmed missing in the Paper builder.**

### Paper CRUD/preview/publish validation

- Create: `POST /api/admin/papers` in `app/main.py` (around lines 513–516) calls `create_paper()`. Service validates title/metadata/IDs, assigns a UUID Paper ID, creates status `draft`, revision 1, one `draft` object and empty `versions`, then stores under `papers[paper_id]` (around lines 204–234).
- Update: `PUT /api/admin/papers/{paper_id}` or `POST .../{paper_id}/update` routes to `update_paper()` (`app/main.py` lines 517–538). `_require_revision()` requires the current integer revision (lines 237–244); update re-reads only the requested ID, validates newly added questions, increments revision and replaces that record's draft (lines 246–283).
- Preview: `GET /api/admin/papers/{paper_id}/preview[?version_id=...]` routes to `preview_paper()` (`app/main.py` lines 350–358). Without version ID, an unpublished/current draft is rendered from current question records; missing source questions are skipped and warnings returned (service lines 372–401). For a published Paper without explicit version ID, preview defaults to current published version.
- Publish: `POST /api/admin/papers/{paper_id}/publish` routes to `publish_paper()` (`app/main.py` lines 517–538). The service checks revision and archive state, builds snapshots in draft order, increments revision, appends a version and changes status to published (`app/papers.py` lines 286–369).

### Minimal direction and compatibility risks

- Add quantity/filter/random/select-all behavior first in `static/js/code-papers.js`; enforce a clear server-side maximum in `app/papers.py` if the business rule requires one. Keep submitted ordered question IDs as the durable selection so preview/publish do not rerandomize.
- Do not silently remove already-selected questions when filters change. Make the selection pool and selected list visibly distinct.
- If category/tags/difficulty become structured filters, define and validate their types in `app/questions.py`, while retaining backward reads for existing optional/missing fields. Risks include legacy inconsistent metadata and selected IDs that are no longer Published.

## D. Paper lifecycle, isolation and draft history

### Record identity and storage keys

- `app/config.py` resolves `DATA_DIR` from the project root; `app/storage.py::_path()` maps JSON data to that directory and defaults `papers.json` to `{}`. Writes use a temporary file plus atomic replacement; `transaction()` is a process-local reentrant lock.
- `create_paper()` uses `uuid.uuid4().hex` and inserts the Paper into the top-level `papers.json` map at that exact ID (`app/papers.py` lines 204–234).
- `_get_paper(paper_id)` reads `read_json("papers.json").get(paper_id)` (lines 137–139). Update/publish/archive/restore/delete each look up and mutate the explicit `paper_id`; delete additionally refuses records referenced by `exams.json`, `assignments.json` or `code_exams.json` (lines 438–463).
- No shared global counter, title-based key, or Paper-ID derivation from question IDs was found. The key collision path is not found in the normal create/service code. No Paper schema migration is visible in `app/papers.py`; `general_exams.reconcile()` handles legacy Exam/Code Exam records, not Paper record conversion.

### List/detail/editor selection

- `renderList()` creates one row per object returned from `/api/admin/papers`, with actions bound to that row's `paper.id` (`static/js/code-papers.js` lines 22–64).
- `openPaper(id)` loads `/api/admin/papers/{id}` into module-level `current`; `openEditor(id)` independently loads that same Paper plus the Question Bank, then sets module-level `current`, `selected`, and `isNew` (`lines 66–82, 133–151`).
- `createNew()` clears `current` and `selected`, marks `isNew`, then calls `openEditor(null)` (`lines 292–297`). The API does not accept a Paper ID in create payload; the server creates it.
- There is one shared set of module variables (`papers`, `questions`, `current`, `selected`, `isNew`, `busy`) and no editor request-generation/token check. `openEditor`, `openPaper`, `preview`, `previewDraft`, and `save` apply async results without checking that the user is still viewing the same Paper. The Back button is not disabled while save is pending (editor code around lines 190–205), and Back/list navigation can occur independently of the outstanding request.

**Status: partially confirmed UI race risk; runtime evidence required for an observed wrong-card interaction.**

A late response can set global `current`/`selected` after the user has navigated, then call `renderEditor()` against the new UI. This can show the wrong Paper editor or stale preview. Service writes themselves use the ID embedded in the API URL at request creation and mutate that keyed record, so direct cross-Paper storage overwrite is **not found in service source**. The asynchronous UI interleaving and what a user subsequently saves must be reproduced before labeling an actual cross-Paper overwrite.

### Revision and draft lifecycle

- `_require_revision()` rejects stale/missing revisions with HTTP conflict semantics (PaperError 409). Existing test source covers stale revision rejection (`tests/test_papers.py`, around lines 158–168); tests were not run.
- There is a single `paper["draft"]` object. `update_paper()` replaces it at the same Paper ID, so prior draft saves are not retained as addressable historical revisions.
- Publishing appends immutable records into `paper["versions"]`; editing a published Paper makes it draft again while retaining existing published versions. Version IDs are `{paper_id}:v{n}`. Each draft is therefore independent across Paper cards, but draft revisions within one Paper are not independently editable/restorable.
- `renderDetail()` lists published versions and a current draft; it offers “Chỉnh sửa bản mới”/continue draft. `renderEditor()` only shows “Xem trước bản nháp” for an existing Paper. That action saves first then previews. `publishButton` is not gated on preview and `publish()` calls `save()` before publish (`static/js/code-papers.js` lines 190–197, 207–255, 259–268).

**Status: single-draft limitation confirmed; publish-preview dependency described in the supplied audit is not found in source.**

### Existing test evidence (inspected, not run)

- `tests/test_papers.py::test_admin_authorization_and_create_list_get_preview_update_archive` covers create/list/detail/preview/update and stale revision (lines 134–176).
- `test_selection_rejects_missing_duplicate_unpublished_and_invalid_payload` covers the server selection constraints (178–194).
- `test_publish_captures_complete_ordered_snapshot_and_never_mutates_it` checks ordered immutable published snapshots and delete protection when referenced (196–234).
- Other tests cover source lifecycle warnings, reuse of prior snapshots, and archive/restore/delete (236–327).
- These tests do not exercise browser card switching, delayed API responses, selector interactions, or multiple historical draft revisions.

### Minimal direction and risk

- Keep Paper ID-keyed records and immutable published versions. Do not redesign storage based on the current evidence.
- Add a per-editor request generation/current-ID guard and capture the target Paper ID/revision in each operation; ignore stale responses. Consider disabling navigation during save or warning on pending changes. Test delayed responses and rapid card switching in a browser test when implementation is authorized.
- If the product needs historical draft revisions, add that as a distinct data-model feature with migration/compatibility design. The current schema intentionally stores one current draft; silently adding draft history risks confusing Paper versions, Exam releases and assignments.
- To diagnose a claimed cross-Paper write, capture the request URL/body and response Paper ID/revision for each save, and compare them with top-level keys in `data/papers.json`; redact question contents if sharing logs.

## E. Distribution and snapshot chain

### ZIP/file assignment

- `app/exams.py::compute_assignments()` implements:
  - `selected`: validates selected files, shuffles the selected order and cycles assignments;
  - `parity`: maps the last numeric student-ID digit to even/odd file;
  - `custom`: validates modulus 2–10 and digit mapping;
  - default/random: groups students by subnet, sorts within subnet by IP, shuffles/rotates the exam pool and cycles it.
- `persist_distribution()` stores per-student `exam_file` and `release_id` in `assignments.json`, sets distribution/release state in `settings.json`, and links Code Exam release when applicable (`app/exams.py` lines 149–170).
- General Exam release construction calls this assignment function for ZIP at `app/general_exams.py::_build_release()` (around lines 730–755). `_apply_release()` validates the file still exists and writes the assignments/settings under the release ID (around lines 966–1043).
- Student ZIP routes are `/api/student/start`, `/api/student/exam`, and `/api/student/submit` (`app/main.py` around lines 397–407, 808–813, 832–839). `app/submissions.py::accept_submission()` verifies active release, that the assignment contains an exam file, start/deadline/submission limits and accepted extension before saving metadata keyed by `release_id`.

**Status: ZIP distribution is confirmed present; the claim that no distribution mechanism exists is not true for this checkout.**

### Code Paper Common/Random assignment

- `static/js/exams.js::codeSection()` selects a Common single Paper version or a Random pool (`around lines 484–508`).
- `app/general_exams.py::_check_code_papers()` requires published Paper versions and exactly one version for Common (around lines 706–722). `_build_release()` creates release-scoped Code Exam snapshots for pool entries, then chooses the single Common ref or one random ref per eligible student and persists `paper_assignments` plus `paper_pool` and summary (around lines 730–865).
- `publish_exam()` persists the release in `exams.json`; `start_exam()`/`_apply_release()` copies per-student selection into `assignments.json` and verifies the matching snapshot (`app/general_exams.py` around lines 921–945, 966–1043).
- Student gets `/api/student/code-exam`; `get_student_code_exam()` checks the assignment/release/code-exam and Paper-ref identities before returning the assigned snapshot (`app/main.py` lines 413–414; `app/code_exams.py` around lines 477–565).
- Code submission reservation records `exam_id`, `release_id`, question snapshot version, Paper ID and Paper version (`app/code_exams.py` around lines 883–929). Default regrade resolves the question from the ended Code Exam snapshot and verifies Paper references (around lines 1510–1563). An explicit `use_latest_spec` option can regrade using the latest currently Published Question; that is a deliberate override and must not be confused with default historical-snapshot regrade.

**Status: Common/Random assignment and snapshot linkage are confirmed in source.**

### Existing distribution tests (inspected, not run)

- `tests/test_paper_distribution.py::test_common_assigns_one_exact_ordered_snapshot_and_survives_archive_restart` checks ordered Paper snapshot, persisted Common assignments, source edits/archive and restart stability (lines 93–132).
- `test_random_selects_only_pool_members_and_persists_server_choice` checks one persisted random choice per student and stability through startup reconciliation (134–158).
- `test_submission_and_regrade_resolve_the_same_paper_version` checks Paper/version metadata on submission and default regrade snapshot use (160–193).
- `test_release_rejects_invalid_paper_references_and_common_multiple_versions` checks invalid version references and Common cardinality (195–210).
- The tests provide source-level coverage evidence only; none were executed for this audit.

### Gaps / risks found

- No evidence of a missing ZIP or Paper assignment algorithm in the source reviewed. The reported “no distribution” may refer to selecting a limited/random subset of Question Bank questions to construct each Paper; that feature is absent from Paper builder (section C), which is a separate operation from assigning completed Papers to students.
- Release creation spans JSON files and Code Exam snapshots. The code includes cleanup on caught failures and `reconcile()` handling for uncommitted paper-backed snapshots, but no runtime/crash-injection verification was performed here.
- Latest-spec regrade is opt-in. If strict historical immutability is required for all admin actions, review that explicit override separately; do not change existing regrade behavior without a requirement.

## Suggested minimal follow-up, if separately approved

1. Reproduce the Code/ZIP report on the deployed checkout and inspect loaded item data. If legacy both-item Exams exist, provide a recovery UI while preserving backend rejection.
2. Implement Paper quantity/filter/random/select-all only after agreeing the maximum count, metadata normalization, whether “select all” means all filtered or all eligible questions, and how selection is frozen for preview/publish.
3. Add stale-response guards to Paper editor requests if delayed switching is reproduced or accepted as a risk.
4. Decide explicitly whether the product requires only one editable current draft per Paper or persistent historical draft revisions. Preserve current published version and release snapshot semantics either way.
5. Keep existing ZIP/Common/Random distribution logic and add regression coverage only for a demonstrated gap.

## Audit limits

This is a source and test inspection at `f00a583`; no app, browser, test suite, LAN path, or crash recovery was run. The normal Code/ZIP click path described by the user and the Paper editor race require runtime reproduction. The earlier supplied analysis report was not present in this checkout, so its claims were checked against the current code and project context rather than against a report file.
