# Question Bank, Papers and Exams — Current Behavior

This guide records behavior present in the source tree reviewed on 2026-11-22; branch names and historical commit hashes are intentionally omitted because they are not durable project facts. It is an implementation guide, not a product roadmap. The current API reference is [Code Exam API](CODE_EXAM_API.md).

## Terminology

- **Question**: a versioned source item in the Question Bank (`questions.json`), with lifecycle status and grading metadata.
- **Paper**: an independently identified ordered set of Code Exam questions. New schema-v2 Papers have a stable ID, mutable current record, revision, and status; they do not have nested version history. Legacy schema-v1 Papers retain their old `draft` and `versions` structure and are supported by explicit references.
- **Exam**: an operational exam record with participants, timing, lifecycle and exactly one supported item type: Code or ZIP.
- **Release**: one published/distributed instance of an Exam.
- **Assignment**: a persisted student-to-release mapping. A Code assignment refers to a new Paper ID or an explicit legacy `(paper_id, paper_version_id)` pair; a ZIP assignment refers to an exam file.
- **Snapshot**: release-scoped question/content data used by a student assignment, submission, and regrade. It is distinct from the current editable Paper record.

Do not use “Exam” for a Paper. The Exam's Code/ZIP distribution selects the item delivered to students; Random question selection inside the Paper Builder is a separate action.

## Question eligibility and Paper selection

New Paper selections come from Questions whose status is `published`, whose IDs are unique and valid, and whose language/grading mode is supported: `java/reflection`, `java/stdio`, or `python/stdio`. The Question list API is `GET /api/admin/questions`; the builder loads it once and filters the returned list client-side. The present list is not paginated.

The builder supports these source-backed fields:

| Filter | Source field / matching rule |
|---|---|
| Keyword | Case-insensitive substring in title, Question ID, or tags |
| Category | Exact normalized match on optional `category` |
| Language | `java` or `python` |
| Grading mode | `reflection` or `stdio` |
| Difficulty | Exact normalized match on optional `difficulty` |
| Tags | OR across selected tags; a Question matches if it has any selected tag |

Different filter dimensions combine with AND. Empty filter values impose no condition. Category, difficulty and tags are optional metadata; absent values do not match a non-empty filter. Reset filters clears all dimensions. Changing a filter does not remove selected IDs; selected Questions outside the active pool remain visible and labeled.

`question_limit` is an integer quantity with minimum 1 and maximum equal to the full Question Bank size. Filters control which eligible Questions are visible; they do not constrain the ordered `question_ids` selection. A draft can therefore retain or add Questions across filter changes, even when some selected Questions do not match the last saved filter. The backend validates Question ID uniqueness, eligibility for newly added Questions, filter metadata shape and quantity bounds. A draft may be saved with zero or fewer than the configured number of selected Questions. Publishing requires at least one selected Question and `question_limit == len(question_ids)`.

### Random and Select All

- **Choose Random N** is explicit and samples exactly N unique IDs without replacement from the currently loaded eligible, filtered pool. It is disabled when the pool cannot supply N. It replaces the current list after confirmation.
- **Select all matching Questions** selects the entire current filtered pool from the unpaginated Question response, deduplicates IDs, replaces the current list after confirmation and leaves `question_limit` unchanged.
- The filtered-group checkbox appends matching IDs without reordering existing selections, or removes only matching IDs while retaining IDs outside the filter. Its checked/partial state reflects the matching pool. **Deselect all** clears the full selection after confirmation.
- The selected list stores the explicit ordered Question IDs. Manual reordering changes that order. Save, reload, preview and publish consume these IDs and do not randomize again. Random selection is not a server-side randomization endpoint and has no persisted seed.

## Paper draft, preview and publication

Each new schema-v2 Paper has a stable ID and a current concurrency `revision`. Save/update requests carry `expected_revision`; stale updates are rejected with `409 PAPER_CHANGED`. The Paper is one mutable current record; older draft revisions are not browsable or restorable. Archiving/restoring changes lifecycle status, not content. Legacy schema-v1 Papers continue to use explicit stored version IDs; they are not converted implicitly.

An incomplete Paper draft can be created and saved. The UI shows Saved/Unsaved state, Paper ID/revision and latest published version. A new Paper must be saved to receive a server ID before the UI enables Draft Preview. Preview is read-only and does not publish. The editor uses `?draft=1` to preview the saved current draft even when the Paper has an older published version.

Publishing does not require a prior Preview action. If the editor is dirty, it saves first and publishes only after save succeeds. If publication then fails, the UI reports that the draft was saved and publication failed. Publishing validates and saves the current schema-v2 Paper; it does not append a nested Paper version. Exam release construction snapshots the selected Paper's questions into release-scoped Code Exam records. Later Paper edits do not rewrite those release snapshots. Legacy Paper version records remain unchanged and resolvable by exact reference.

### Verified Paper API examples

Create a draft (the example deliberately shows a partially configured draft):

```http
POST /api/admin/papers/independent
Content-Type: application/json
```

```json
{
  "title": "Example Paper",
  "metadata": {},
  "question_ids": ["question-a"],
  "question_limit": 2,
  "question_filters": {
    "search": "loop",
    "category": "basics",
    "language": "python",
    "grading_mode": "stdio",
    "difficulty": "easy",
    "tags": ["intro", "arrays"]
  }
}
```

Update requires the current revision and uses the same draft fields:

```http
PUT /api/admin/papers/{paper_id}
Content-Type: application/json
```

```json
{
  "expected_revision": 3,
  "title": "Example Paper",
  "metadata": {},
  "question_ids": ["question-a", "question-b"],
  "question_limit": 2,
  "question_filters": {}
}
```

Preview and publish:

```http
GET  /api/admin/papers/{paper_id}/preview?draft=1
POST /api/admin/papers/{paper_id}/publish
Content-Type: application/json
```

```json
{"expected_revision": 4}
```

These routes require an admin session. The examples describe request shapes only; IDs are illustrative and no credentials or real classroom data are included.

## Exam Code/ZIP selection and distribution

The Exam editor presents a persistent Code/ZIP radio selector. Selecting one clears the other configuration. A malformed legacy record with multiple or unsupported items requires an explicit user choice before it can be saved. `app/general_exams.py::_normalize_items()` rejects more than one item; publication requires exactly one supported item.

Code Exam distribution is separate from question selection within a Paper:

- `common` requires exactly one published Paper reference and assigns it to every eligible participant.
- `random` chooses one reference from the configured published-Paper pool per participant while building the release.
- The release persists the mapping; starting the release writes the exact Paper/version/code-exam IDs to `assignments.json`. Student retrieval, submission and default regrade resolve that saved reference. Refresh or repeat retrieval does not choose again.
- Exam releases hold ordered question snapshots. Later Question Bank changes, Paper edits, or Paper archive do not rewrite those snapshots. `use_latest_spec=true` is rejected for Paper releases; only supported non-Paper paths may opt into current Question Bank specifications.

ZIP Exam distribution remains a separate algorithm with `random`, `selected`, `parity`, and `custom` modes. The release and student assignment persist the chosen filename, but student retrieval reads bytes from the current file at that path. Exact historical ZIP byte snapshots are **not implemented**. A replaced or removed file can change or prevent retrieval for an old assignment.

## Compatibility, migration and rollback

- No data migration or bulk rewrite was introduced. Paper IDs, current `draft`, published `versions`, release IDs, assignments and submissions keep their existing storage locations and identifiers.
- The legacy `POST /api/admin/papers` route remains available; the Paper Builder creates new independent records through `POST /api/admin/papers/independent`. Older Paper drafts without `question_limit` or `question_filters` remain readable; no migration occurs merely by reading.
- Existing question-based standalone Code Exams continue through their legacy API/storage path; they are not converted to Paper records.
- The API adds optional draft fields and the `draft=1` preview query. No dependency or database schema change was introduced.
- Downgrade compatibility has not been tested. Before deploying any source rollback, make a normal backup of the JSON data directory and verify it can be restored; do not edit historical release or snapshot records as a rollback mechanism. No live data migration or migration rollback procedure is needed for these changes because no migration runs.

## Evidence and test limits

Relevant checked-in suites include `tests/test_papers.py`, `tests/test_paper_distribution.py`, `tests/test_code_api.py`, and the Paper/Exam JavaScript UI tests. The documentation update did not run tests, browser automation, a LAN workflow, or a restart test; file presence alone is not a pass result.
