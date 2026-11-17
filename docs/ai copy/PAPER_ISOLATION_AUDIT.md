# Paper Card Isolation and Draft History Audit

**Scope:** Prompt 07, source investigation only. No application or tests were run. No product code or runtime data was changed.

## Repository baseline

- Repository: `ClassroomSubmissionServerSystem`
- Branch: `feature/JudgeEngine`
- HEAD: `f00a5835c16518f5c1c1d976a4fad3264619d0ba` (`f00a583`), matching the checkout named in the project context.
- Working tree was already changed before this audit: modified `app/main.py`, `app/papers.py`, `static/js/code-papers.js`, `static/js/exams.js`, `tests/test_code_api.py`, `tests/test_papers.py`; untracked `AGENTS.md`, `docs/ai/`, `tests/test_exam_selector.js`, `tests/test_paper_builder_filters.js`. These changes were preserved. This document is added under the pre-existing untracked `docs/ai/` directory.
- `AGENTS.md` requires `docs/ai/PROJECT_CONTEXT.md` and `docs/ai/EXAM_PAPER_TASK_SPEC.md`; neither exists. `IMPLEMENTATION_CONTEXT.md`, `IMPLEMENTATION_RULES.md`, `SOLUTION_DESIGN.md`, `IMPLEMENTATION_PLAN.md`, `PROGRESS_HANDOVER.md`, and the Prompt 07 file were inspected. The context and solution design agree that cross-Paper storage overwrite has not been established and the current model intentionally has one mutable draft per Paper.
- Runtime-data spot check was read-only and aggregate-only: `data/papers.json` contained one schema-v1 Paper with one current `draft`, revision 1, no published versions, and no draft-history field. This single record cannot establish or disprove the reported incident. No record ID or contents are reproduced here.

## Finding summary

| Finding | Classification | Evidence-based conclusion |
|---|---|---|
| A save can address another Paper through the service/storage key | **Not confirmed** | Save URL uses `current.id`; service loads and writes `papers.json[paper_id]`. No shared title-based key or cross-record write path was found. |
| The editor has shared state across Paper cards | **Confirmed** | `code-papers.js` holds one module-level `current`, `selected`, `questions`, `isNew`, and operation state for the whole view. |
| A late response can repaint or contaminate the currently selected card | **Confirmed as a source-level race risk; runtime occurrence requires reproduction** | `openPaper`, `openEditor`, `preview`, save, publish and preview-draft completions assign shared state without a request-generation/current-card guard. A delayed earlier response can overwrite the displayed state after a later card was selected. |
| A stale revision can silently overwrite a newer saved draft | **Not confirmed; backend guard contradicts this path** | Mutating routes require `expected_revision`; mismatch returns `409 PAPER_CHANGED`. The UI preserves local edits on this error. |
| JSON storage key collision or title collision caused the symptom | **Not confirmed** | Keys are UUID Paper IDs, not titles. No UUID collision check exists before insertion, but no collision is evidenced and random UUID collision is an unlikely explanation. |
| Earlier saves of the same Paper are retained as draft history | **Not found in source** | Each save replaces the single `draft` object. Only published `versions` are accumulated. |
| “Restore” recovers a prior draft revision | **Not found in source** | Restore only changes an archived Paper's status back to `draft` and increments the Paper revision. It does not select historical content. |
| Cross-Paper persistent overwrite reported by the user | **Requires runtime reproduction** | Source shows a plausible wrong-card UI race, but the storage path itself is keyed by explicit Paper ID. No test or inspected runtime record demonstrates Paper A content persisted under Paper B. |

## Identity and revision trace

The canonical server identity is `paper.id`. `papers.json` is a map keyed by that ID. `paper.revision` is a mutable optimistic-concurrency counter; it is not a content-history ID. Published versions use separate immutable IDs such as `<paper-id>:vN` and are referenced by `current_version_id`.

| Operation | Frontend state and request | Route/service/storage behavior | Response and isolation note |
|---|---|---|---|
| Create / create card | `createNew()` clears global `current`/`selected`, sets `isNew`, then `openEditor(null)` loads the Question Bank. First dirty save POSTs `/api/admin/papers` with title, metadata, ordered `question_ids`, limit and filters. No ID exists in the initial editor. | `POST /api/admin/papers` in `app/main.py` calls `create_paper`. `app/papers.py` creates UUID4 hex ID, revision 1, `status=draft`, a singleton `draft`, empty `versions`, then inserts at `papers[paper_id]` in `papers.json`. | Returns `{ok, paper}` with generated ID and revision. `create_paper` does not check whether the generated UUID key already exists before assignment; collision is theoretically possible but not evidenced. |
| List | `loadList()` GETs `/api/admin/papers`; response replaces global `papers`. Each card closure passes its own `paper.id` into actions. | GET route calls `list_papers()`, iterates values from `papers.json`, and returns ID/status/revision/current version/count metadata. | List contains revision used by card-level archive/restore/delete. No content key is derived from title. |
| Open detail | `openPaper(paperId)` GETs `/api/admin/papers/{encoded ID}` through `loadPaper`; assigns response into global `current`, sets `isNew=false`, then renders. | GET detail route decodes the path ID and calls `get_paper(id)` → `_get_paper(id)` → `read_json("papers.json").get(id)`. | Response includes serialized same Paper ID, revision, draft and versions. There is no request token to reject a response after another card is opened. |
| Open/edit / switch | `openEditor(paperId)` concurrently loads detail (unless new) and `/api/admin/questions`; after both resolve it assigns global `current`, `questions`, `isNew`, and `selected` from the response. The selected IDs retain array order. | Detail leg uses GET above; questions leg is independent. No Paper-specific browser storage key was found; editor state is in module globals and DOM closures. | Both results apply after `Promise.all` regardless of whether the user has switched cards or gone back to the list. This is the clearest unguarded late-load path. |
| Save existing draft | Editor closure builds payload from title/metadata/selected IDs/quantity/filters. URL is formed from global `current.id`; body adds `expected_revision: current.revision`. New cards POST; existing cards PUT `/api/admin/papers/{id}`. | Route calls `update_paper(id, payload, ...)`; under `transaction()` it loads that exact key, checks expected revision, replaces `draft`, increments `revision`, writes the same map key. | Response paper is assigned to global `current` and selection, then list reloads and editor rerenders. Completion has no check that the visible editor still belongs to the request's Paper. Backend target ID is explicit, so the identified client race is not itself proof of a wrong storage key. |
| Preview a published version | `preview(paperId, versionId)` embeds both IDs in GET `/api/admin/papers/{id}/preview?version_id=...`; on return it assigns `current.preview`. | GET preview route calls `preview_paper(id, version_id)`, which reads that Paper and version without writing. | Request target is explicit; response is nevertheless applied to whichever global `current` exists when it resolves. The render reads the global `current`, so this can mix card state. |
| Draft preview | `previewSavedDraft()` captures `paperId=current.id`, saves first if editor is dirty, checks current ID after save, reloads detail and compares its revision, then GETs `/api/admin/papers/{id}/preview?draft=1`. On completion it assigns `current.preview`. | GET route passes `draft_only=true`; service reads the current `draft` and current Question snapshots. No server mutation occurs in the preview route. | It protects against an ID change immediately after save and detects stale revision before requesting preview. It lacks a selection-generation check after the later awaits, so a switch during detail/preview can still race. |
| Publish | UI optionally saves dirty content first, captures `paperId=current.id`, POSTs `/api/admin/papers/{id}/publish` with `expected_revision: current.revision`. | `publish_paper(id, payload, ...)` checks revision, snapshots the draft into a new version, appends that version under the same Paper, updates pointer/status, increments revision. | Returns that Paper with version ID/number. Existing published snapshots are copied forward unchanged. Frontend unconditionally assigns the response to global `current`, so a late publish response can repaint a different currently opened card; the request itself remains bound to captured URL ID. |
| Reload / conflict recovery | Open/reload uses the list's ID, or the stale-revision action calls `openEditor(stalePaperId)`. `backToList()` clears the editor DOM and triggers `loadList()`. | GET detail uses explicit ID; no storage mutation. Mutations use expected revision. | `backToList()` does not invalidate pending operations. A pending open/save/preview may still update module globals or render after navigation. Stale conflict is rejected by service, not silently merged. |
| Archive / restore | List action closes over a `paper` record and POSTs `/api/admin/papers/{paper.id}/archive|restore` with that list record's `expected_revision`. | `archive_paper`/`restore_paper` update that ID's key and increment revision. Restore is allowed only for archived records; it sets status to `draft`, retaining existing `draft` and versions. | Success reloads list. A stale list revision gets `PAPER_CHANGED`. Restore is not draft-history restoration. |
| Delete | Card action posts `/api/admin/papers/{paper.id}/delete` with list revision. | `delete_paper` verifies revision and refuses if exam/assignment/code-exam data references the Paper ID, then deletes that map entry. | Explicit ID prevents title-based selection; behavior is guarded against known references. |

### State and storage details

- Frontend module globals are declared at `static/js/code-papers.js:16-24`; no per-card editor store, local/session storage key, `AbortController`, or request-generation token was found.
- `renderList()` binds action callbacks to each record's ID (`:37-60`). This is positive evidence that list actions initially target the intended Paper.
- `openPaper()` (`:75-90`) and `openEditor()` (`:145-167`) have no response identity guard. `backToList()` (`:672-678`) clears the DOM but does not cancel or invalidate requests.
- Save (`:494-557`) resolves target URL/body before its request, but response assignment (`current=data.paper`) is unconditional. Publish (`:559-598`) and previews (`:119-128`, `:600-640`) also update shared state after awaits.
- Server persistence lives in `app/storage.py`: `_path()` maps `papers.json` into `DATA_DIR` (`:51-54`); `read_json`, `write_json`, `transaction`, and `update_json` use a process-local reentrant lock (`:93-119`); writes use temporary-file replacement (`:83-91`). The record map is keyed by Paper ID in `app/papers.py` (`:250-252`, `:350-356`, `:413-415`, `:484-506`).
- `revision` increments on draft update, publish, archive, and restore. `_require_revision()` (`app/papers.py:361-367`) rejects missing, noninteger, boolean, or stale values. It prevents stale writes against a selected ID but cannot identify a UI response that belongs to a card no longer selected.
- No independent draft-revision ID exists. A current draft is overwritten on each successful update. `versions` is a separate append-only collection of published snapshots.

## Cross-Paper overwrite: evidence and reproduction

### What source establishes

The server mutations use an explicit path ID and exact map key. No source path was found that selects a Paper by title, reuses a shared storage key across IDs, or moves one Paper's draft into another record. Published version IDs also include the Paper ID. Therefore, persistent cross-Paper overwrite is **not confirmed from source**.

The frontend race is confirmed as a code property. Example sequence: start opening Paper A; before A's detail request resolves, open Paper B; B resolves and becomes `current`; A resolves later and unconditionally replaces `current`, even though B is the visible intent. Equivalent late-response windows exist for edit hydration, preview and save/publish completion. If the UI then displays A as selected, a subsequent user save can legitimately PUT A's ID, which may be misperceived as editing B. This is a plausible UI-level path, not proof that a specific incident happened or that the server wrote to B incorrectly.

### Runtime reproduction plan (not performed)

1. Use two existing Papers A and B with distinct titles and distinct ordered question IDs; record each ID, revision, and a read-only backup/hash of the relevant `papers.json` records.
2. In browser developer tools, delay the detail response for A. Click Open/Edit A, then Open/Edit B before A returns; release B first and A second. Observe the selected card/editor title and IDs after each response.
3. Repeat with a delayed preview for A while B is opened, and with save/publish response delay. Capture request method, URL, body, response ID/revision and the Paper ID shown in the DOM.
4. If a write anomaly is suspected, compare the before/after JSON records by ID and correlate the exact PUT/POST path and response. A UI showing A while the user believes B is selected is not itself a cross-record persistence proof.
5. Repeat with two independent browser tabs and concurrent edits to one Paper to confirm stale revision receives `409 PAPER_CHANGED` and does not overwrite the first saved update.

Do not execute the plan against production or irreplaceable data without a disposable copy. No such runtime reproduction was performed for this report.

## Existing tests inspected (not run)

- `tests/test_papers.py:148-190`: create/list/detail/preview/update, stale revision rejection, archive.
- `tests/test_papers.py:208-265`: incomplete drafts, draft preview, publish and immutable republish.
- `tests/test_papers.py:373-394`: legacy draft without quantity/filter metadata remains readable and editable.
- `tests/test_papers.py:539-555`: archive/restore/delete lifecycle.
- `tests/test_paper_builder_filters.js`: simulated DOM/API tests for builder operations; this harness does not model delayed out-of-order card requests in the inspected coverage.
- `tests/test_paper_distribution.py`: existing assignment/version snapshot tests were identified in repository context and inspected by name; no test was run. This audit does not re-audit distribution behavior.

The current API test suite verifies stale revisions and immutable published snapshots, but no inspected test exercises two-card delayed-response ordering or asserts that a response is ignored after selection changes.

## Minimal fixes and risks

1. Preserve the current per-Paper server identity and revision contract; add a frontend selection/request generation counter. Increment it on every open, create, back-to-list, and card switch. Each async load/preview/save/publish captures `(generation, paper_id)` and may update/render shared state only if both still match. This prevents stale UI responses from repainting another card.
2. Keep each mutation URL and expected revision captured from the editor session before awaiting. For a response to an old card, do not rebind the active editor. If product policy allows background completion, update only that Paper's list row after refetch; otherwise tell the user it completed on the prior Paper and require reopening it.
3. Add delayed-response tests for open A/open B, edit hydration, preview, save, publish, and back-to-list. Assert response identity and DOM/current selection remain B (or list) after late A resolves. Keep separate server tests proving ID A mutations affect only map key A.
4. No draft-history schema migration is required to address the demonstrated client race. Adding history would increase persistence and UI complexity without proving it addresses cross-Paper overwrite.

Risks: generation guards must not suppress a successful server write; they should guard only which UI selection consumes its response. Reloading the list after a background completion may still be useful. Revision conflicts remain server-authoritative. Process-level JSON locking does not coordinate separate application processes; current architecture is a single-process server and this audit found no multi-process deployment evidence.
