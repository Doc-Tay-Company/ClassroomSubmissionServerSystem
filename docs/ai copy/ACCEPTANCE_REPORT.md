# Prompt 10 — Regression, Acceptance and Safety Review

**Review snapshot:** branch `feature/JudgeEngine`, HEAD `f00a5835c16518f5c1c1d976a4fad3264619d0ba`.
**Scope:** review the approved Prompt 03–09 work against current source, tests, design and distribution verification. No product code was changed for this review. The report itself is new.

## Executive result

**Recommendation: do not claim full acceptance or release readiness yet.** The focused exam selector and Paper Builder UI harnesses pass; the Paper API module passes all 13 tests; the server rejects mixed Code/ZIP items in its focused API test. Common/Random Code Paper assignment and historical Paper-version paths were also covered by the isolated Prompt 09 tests. There is no real-browser or full-suite run, no true separate-process restart test, and the ZIP workflow does not preserve historical file bytes. Judge Engine, runners and broader student workflows were not exercised in this review.

Model A was approved: one mutable current draft per Paper, with immutable published versions. Historical *draft* revision browse/preview/restore is therefore outside the approved model and is not represented as an implemented feature.

## Acceptance checklist

Status meanings: **PASS** means the stated behavior is supported by current source and the listed focused tests; **FAIL** means source contradicts the stated acceptance requirement; **NOT TESTED** means evidence is insufficient. A PASS based on a simulated DOM is not a browser acceptance result.

### Exam type

| Requirement | Status | Evidence and limitation |
|---|---|---|
| Exactly one Code or ZIP item is emitted | **PASS** | `static/js/exams.js` form state uses `itemType`; `toPayload()` appends only the selected item. `tests/test_exam_selector.js` passed. `app/general_exams.py::_normalize_items()` rejects payloads with more than one item. |
| Both Code → ZIP and ZIP → Code transitions work | **PASS** | `selectItemType()` clears the inactive config and initializes/restores the selected config; simulated-DOM selector regression passed both directions. |
| Type selector remains visible, including malformed dual-type legacy state | **PASS** | `itemTypeSelector()` is rendered independently of `codeSection()` and `zipSection()`; malformed legacy state has an explicit repair notice and requires a user selection. Simulated-DOM test passed; no browser run. |
| Backend rejects a dual-item payload | **PASS** | `_normalize_items()` rejects `len(raw) > 1`. `python -m unittest discover -s tests -p 'test_code_api.py' -k exam_records_reject_mixed_types` ran **1 test, OK**, including mixed-item rejection and incomplete publish rejection. |
| Editing/reloading retains the chosen type and unrelated exam settings | **PASS** | `fromExam()` hydrates one supported item; `toPayload()` preserves the rest of the form config. API test `test_exam_record_edit_and_reload_preserve_selected_item_type` is present; in this review the UI harness passed. It was not separately selected in the Python run. |

### Question builder

| Requirement | Status | Evidence and limitation |
|---|---|---|
| Quantity is integer, minimum 1, bounded by eligible filtered pool, and checked server-side | **PASS** | UI `renderEditor()` sets `min`, `step`, `max` and validates before save/publish. `app/papers.py::_validate_question_selection()` rejects booleans, non-integers, values below 1, quantity below selected count, and limits above the pool plus explicitly grandfathered old selections. `test_question_limit_rejects_invalid_bounds_and_nonmatching_new_questions` and lifecycle tests passed in the 13-test Paper module. |
| Filters use fields present in the Question records/list API | **PASS** | UI/API filters use title, ID, category, language, `grading_mode`, difficulty and tags. `GET /api/admin/questions` retains category/difficulty/tags metadata; test `test_question_filter_metadata_and_combination_semantics` passed. The list is fetched once; filtering is client-side over the returned full list. |
| Filter combination semantics are predictable | **PASS** | `app/papers.py::_question_matches_filters()` and UI `filteredQuestions()` combine dimensions with AND and selected tags with OR. The API combination/normalization cases passed. |
| Filter changes retain selected questions and expose nonmatching selections | **PASS** | Filter refresh does not remove IDs; selected rows label outside-filter and inactive questions. UI simulated-DOM tests passed retention behavior. |
| Random chooses exactly N unique IDs from the current eligible filtered pool | **PASS** | `randomizeSelection()` samples without replacement and replaces only after confirmation; backend validates explicit IDs. `tests/test_paper_builder_filters.js` passed exact-N, unique, pool-too-small and replacement-confirmation cases. |
| Select All covers the entire filtered result set and updates quantity | **PASS** | The current `GET /api/admin/questions` response is unpaginated; Select All consumes the entire loaded list, deduplicates IDs and sets quantity. Simulated-DOM test passed. No multi-page API/browser behavior exists to verify independently. |
| Selected order remains stable through save, reload, preview and publish | **PASS** | Explicit `question_ids` order is stored and consumed by draft preview and `_make_version()`. `test_explicit_selection_order_is_stable_through_save_reload_preview_and_publish` passed. Random selection is not invoked during these paths. |

### Paper lifecycle

| Requirement | Status | Evidence and limitation |
|---|---|---|
| Save Draft persists and reports saved/unsaved state | **PASS** | UI fingerprint and response revision handling are in `static/js/code-papers.js::renderEditor()`; create/update API paths persist the draft. Paper API tests passed save/reload cases; the simulated-DOM lifecycle harness passed dirty/saved and duplicate-request checks. |
| Preview reads a draft without publishing | **PASS** | `app/main.py` routes `?draft=1` to `preview_paper(..., draft_only=True)`; this rejects a simultaneous version target and reads the saved draft. API lifecycle test confirms empty draft preview creates no published version; UI harness passed preview-without-publish. |
| Publish works without preview and saves dirty changes first | **PASS** | UI `publish()` saves dirty content first and then calls the publish route; backend `_make_version()` enforces nonempty exact quantity. API lifecycle test directly published without preview; UI harness passed save-then-publish without a preview call. |
| Save-success/publish-failure is reported clearly | **PASS** | UI reports `Draft saved …; publishing failed` on the publish error path. Simulated-DOM failure-path test passed; not verified in a browser/networked deployment. |
| Published versions are immutable; edits affect draft and republish appends | **PASS** | `publish_paper()` appends to `versions`; update changes `draft` and does not rewrite prior version entries. The lifecycle and snapshot tests passed, including v1 immutability after v2. |

### Paper independence and history

| Requirement | Status | Evidence and limitation |
|---|---|---|
| Separate Paper IDs/data remain independent; card switching ignores stale responses | **PASS** | Save/publish requests capture Paper ID and revision; `viewGeneration` guards late open/detail/preview/save/publish responses. `tests/test_paper_builder_filters.js` passed delayed-response and independent A/B save scenarios. This is a simulated-DOM test, not a browser or concurrent multi-user test. |
| Backend rejects stale Paper revision rather than silently overwriting | **PASS** | `update_paper()` and `publish_paper()` use `_require_revision()` and return `PAPER_CHANGED`; Paper API module passed stale revision coverage. UI preserves edits and offers explicit reload in the simulated harness. |
| Browse/preview/restore old *draft* revisions | **NOT TESTED — outside approved Model A** | Model A retains only the current draft and immutable published versions. No draft-history list/read/restore API or storage is included. Published Paper versions have their own preview path. Do not interpret archive/restore of a Paper card as restoring an earlier draft revision. |
| Legacy Papers remain readable/editable | **PASS** | Missing quantity/filter fields are read without migration; update derives compatible values. `test_legacy_paper_without_quantity_metadata_remains_readable_and_editable` passed. Existing snapshots are reused for unchanged legacy selections. |

### Distribution and snapshots

| Requirement | Status | Evidence and limitation |
|---|---|---|
| Common assigns the same exact published Paper version to eligible students | **PASS** | Prompt 09 source trace and `test_common_assigns_one_exact_ordered_snapshot_and_survives_archive_restart`; isolated distribution module passed **6 tests**. |
| Random assigns one version from the configured pool and persists the choice | **PASS** | `app/general_exams.py::_build_release()` chooses once per participant and stores `paper_assignments`; Prompt 09 `test_random_selects_only_pool_members_and_persists_server_choice` passed. Repeated retrieval reads persisted assignment. |
| Exact historical Paper version remains bound through retrieval, submission and default regrade | **PASS** | Prompt 09 source trace follows release, `assignments.json`, `app/code_exams.py` submission records and default regrade. `test_submission_and_regrade_resolve_the_same_paper_version` passed. Explicit `use_latest_spec=True` remains an intentional opt-in. |
| Source question unpublish/delete or later Paper edit corrupts a released Paper snapshot | **PASS — no corruption found** | Version snapshot path and Prompt 09 tests confirm old released content remains available after source change/delete and Paper edit/archive. |
| Assignment survives a true server restart | **NOT TESTED** | JSON persistence supports it by source inspection; current test reinitializes in-process. No separate-process restart was run. |
| ZIP assignment mode persistence | **PARTIAL** | Source supports `random`, `selected`, `parity`, `custom` and persists assignments. Prompt 09 ran the ZIP-only publish test (1 pass), but did not exercise every algorithm through student retrieval/restart. |
| ZIP release preserves exact historical file bytes | **FAIL against this acceptance criterion** | `app/exams.py`/student ZIP route persist and resolve a filename under the live exam directory. Replacing bytes at that path changes the delivered content; removing/renaming it can break retrieval. This limitation is documented in `DISTRIBUTION_SNAPSHOT_VERIFICATION.md`; no ZIP snapshot fix was approved or made. |

### Non-regression

| Requirement | Status | Evidence and limitation |
|---|---|---|
| Changes remain scoped; no new dependencies or unrelated refactor | **PASS by diff inspection** | Product/test diff is limited to `app/main.py`, `app/papers.py`, `static/js/code-papers.js`, `static/js/exams.js`, `tests/test_code_api.py`, and `tests/test_papers.py`; no dependency manifest or Judge Engine/runner implementation file changed. `app/general_exams.py` server validation was pre-existing and unchanged. |
| Judge Engine, Java/Python runners and hidden tests remain functional | **NOT TESTED** | These areas were not modified in the reviewed diff, but no runner/hidden-test suite was executed. |
| Pretest, code submission, Practice Mode and student flows remain functional | **NOT TESTED** | No relevant end-to-end or regression suite was run in Prompt 10. Prompt 09 traced only the released Code Paper submission/regrade path. |
| ZIP Exam and authentication remain functional | **PARTIAL** | ZIP-only publish and admin-auth checks are present in the Paper/API suites; the mixed-item backend test passed. No complete ZIP student flow or auth regression suite was executed. |

## Engineering and safety review

- Reviewed the complete tracked product diff. No dependency changes, unrelated files, or edits to Judge Engine/runner modules were found. `app/general_exams.py` remains unchanged; the server's existing one-item validation is exercised by a focused API test.
- Server-side validation remains authoritative for supported Question kind/status, unique IDs, quantity and filter constraints, expected Paper revision, and exact-N publish. Paper routes remain behind existing admin authentication; API tests include unauthorized/forbidden responses.
- Published Paper versions and release/assignment references are not rewritten by the reviewed changes. The new `draft=1` preview parameter is additive; default published-version preview behavior remains.
- UI isolation is generation-based. It prevents stale responses from being applied to a different active card, while the backend still addresses the captured Paper ID and expected revision. No multi-process race or browser-level request cancellation test was run.
- A combined Python test discovery is intentionally not used: prior combined fixture execution caused module-level shared `storage.DATA_DIR` overrides to interfere and temporarily changed tracked `data/code_exams.json` and `data/code_submissions.json`. Those files were restored and verified clean in the earlier phase. Prompt 10 used isolated modules and verified both SHA-256 hashes unchanged after its Python runs.
- Python test fixture creation under the sandbox was denied on the first attempts. The isolated tests were subsequently run with approved access; this did not modify source/runtime JSON. A temporary folder from the failed attempt was removed after verifying its exact repository-local path.

## Commands and actual results

### Run during Prompt 10

- `node --check static/js/exams.js` — passed.
- `node --check tests/test_exam_selector.js` — passed.
- `node tests/test_exam_selector.js` — **PASS**, “Exam Code/ZIP selector UI state regressions”.
- `node --check static/js/code-papers.js` — passed.
- `node --check tests/test_paper_builder_filters.js` — passed.
- `node tests/test_paper_builder_filters.js` — **PASS**, filter/selection/lifecycle/stale-conflict cases and Paper card delayed-response isolation cases.
- `git diff --check` — passed; no whitespace errors (Git reported line-ending conversion warnings only).
- `python -m py_compile app/main.py app/papers.py tests/test_papers.py tests/test_code_api.py` — passed.
- `python -m unittest discover -s tests -p 'test_papers.py'` — **13 tests, OK**. Run as an isolated module with approved filesystem access for temporary fixtures.
- `python -m unittest discover -s tests -p 'test_code_api.py' -k exam_records_reject_mixed_types` — **1 test, OK**.
- Before/after SHA-256 checks of `data/code_exams.json` and `data/code_submissions.json` — both unchanged for each Python run.

### Previously run in Prompt 09 (recorded in `DISTRIBUTION_SNAPSHOT_VERIFICATION.md`)

- `python -m unittest discover -s tests -p 'test_paper_distribution.py'` — **6 tests passed**.
- `python -m unittest discover -s tests -p 'test_code_api.py' -k zip_only_exam` — **1 test passed**.
- Protected runtime JSON hashes matched before/after.

### Not run

- Full unittest discovery/full suite: not run because of the known shared-storage fixture interference and observed tracked JSON side effect when modules execute together. An isolated full-suite strategy is not currently established.
- Real browser/manual UI test, app launch, student login, LAN test and true separate-process restart: not run.
- Runner/Judge Engine, hidden tests, Practice Mode and complete ZIP assignment/retrieval matrix: not run.

## Remaining risks and release recommendation

1. **Release gate:** do not mark the whole acceptance checklist complete while ZIP byte snapshot integrity is a hard requirement; the current implementation uses the live ZIP path.
2. Run a browser-level smoke test for both Exam type switches and the full Paper save/preview/publish flow, including a real failed publish response.
3. Establish a safe isolated full-suite fixture strategy before broad CI acceptance; do not run modules together against shared runtime JSON.
4. Add or run separate-process restart coverage for assignment persistence, plus ZIP mode-by-mode student retrieval coverage.
5. Keep draft-revision restore explicitly out of scope under approved Model A. If product needs historical draft restore, approve a separate design/model before implementation.
6. Run existing runner, hidden-test, pretest, submission, Practice Mode and authentication regression suites before a broad production release.

**Final assessment:** focused acceptance for the approved Exam selector and Paper builder/lifecycle changes is supported by source and targeted tests. Full project acceptance is **NOT ESTABLISHED**. The ZIP historical-byte requirement is **not met**, and the listed end-to-end/non-regression areas remain untested.
