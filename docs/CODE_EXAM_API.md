# Code Exam and Exam Paper API

This document describes the routes currently dispatched by `app/main.py` and
the Paper/release behavior implemented by `app/papers.py`,
`app/general_exams.py`, and `app/code_exams.py`. Responses are JSON. Admin
routes require an admin session; student routes require a student session.

## Paper management (admin)

| Method | Route | Result |
|---|---|---|
| `GET` | `/api/admin/papers` | `{"papers":[...]}` summaries, including metadata, status, current version, source status and warnings. |
| `POST` | `/api/admin/papers` | Create a draft; accepts `title`, optional `metadata`, ordered `question_ids` (including an empty list for an incomplete draft), and optional `question_limit` / `question_filters`. Returns `201` and `{"ok":true,"paper":...}`. |
| `GET` | `/api/admin/papers/{paper_id}` | Paper draft, versions and teacher-side source warnings. |
| `PUT` | `/api/admin/papers/{paper_id}` | Update draft fields `title`, `metadata`, ordered `question_ids`, optional `question_limit` / `question_filters`, and required `expected_revision`; returns the updated Paper. `/update` POST is also accepted. |
| `GET` | `/api/admin/papers/{paper_id}/preview[?version_id=...][&draft=1]` | `{"preview":...}` for the saved draft (`draft=1`), the default current/published target, or the requested stored version. |
| `POST` | `/api/admin/papers/{paper_id}/publish` | Capture and append an immutable version; body requires `expected_revision`. |
| `POST` | `/api/admin/papers/{paper_id}/archive` / `restore` | Archive or restore Paper; body requires `expected_revision`. |
| `POST` | `/api/admin/papers/{paper_id}/delete` | Delete only when no exam/release/assignment/code-exam record references the Paper; body requires `expected_revision`. |

New question IDs must exist, be `published`, and be eligible for a supported
Code Exam. Existing snapshot questions can remain in a later version if their
source is inactive or gone; this preserves history and the admin response
includes `source_status` and `warnings`. Paper versions store ordered
question snapshots and `source_ref` metadata. Student payloads do not use the
admin Paper detail/preview serializer.

The eligible new-question pool is based on published Questions with supported
language/grading pairs: `java/reflection`, `java/stdio`, and `python/stdio`.
The Question list is currently unpaginated and the builder filters its single
loaded result by keyword (title, ID, tags), category, language, grading mode,
difficulty and tags. Dimensions combine with AND; selected tags combine with
OR. Optional category/difficulty/tags are matched only when present in the
Question record. Filter changes retain selected IDs, including selections
outside the active filter.

`question_limit`, when set, is an integer >= 1. It may exceed the selected
count while the draft is incomplete, but publication requires a nonempty
selection whose count exactly equals the limit. The server validates unique
IDs, new-question eligibility, filter membership and quantity; it does not
trust the client maximum. Existing unchanged IDs are compatible with source
status/filter changes and are not silently removed.

Random and Select All are client actions over the full loaded eligible pool.
Random explicitly samples exactly N without replacement and Select All means
all current filtered results. Both replace the selected list after
confirmation. The group checkbox adds/removes matching IDs while retaining
nonmatching selections. The ordered explicit IDs are saved in the draft, so
reload, preview and publish do not randomize again.

Each Paper has one current mutable draft and a revision precondition; Model A
does not provide prior-draft history or draft restore. Save may persist an
incomplete draft. Preview is read-only; `?draft=1` explicitly selects the
saved draft, and Preview is not required before Publish. The UI saves dirty
content before publishing. Publish appends an immutable Paper version; a
later edit changes the current draft only. Existing records without
`question_limit` / `question_filters` remain readable and require no migration.

## Exam configuration and release (admin)

Exam sessions use `/api/admin/exam-records`, not the legacy standalone
question-based Code Exam endpoint:

- `GET /api/admin/exam-records` lists exams; `GET /api/admin/exam-records/{id}`
  retrieves one.
- `POST /api/admin/exam-records` creates a draft. A Code item selects Paper
  versions with this relevant shape (the surrounding exam `title`, `config`,
  and `items` are also validated by the server):

```json
{
  "items": [{
    "item_id": "code-item-id",
    "type": "code",
    "distribution": {
      "mode": "random",
      "paper_versions": [
        {"paper_id": "paper-a", "paper_version_id": "paper-a:v1"},
        {"paper_id": "paper-b", "paper_version_id": "paper-b:v2"}
      ]
    },
    "show_final_score_immediately": false,
    "allow_pretest": true,
    "max_pretest_runs": 20,
    "pretest_cooldown_seconds": 2
  }]
}
```

`mode` is `common` or `random`. COMMON requires exactly one version. RANDOM
requires a non-empty pool; duplicate references are rejected. The backend
checks each Paper/version and its published lifecycle. There is no minimum
pool size of two in the current validator.

- `POST /api/admin/exam-records/{id}/update` updates an editable exam.
- `GET /api/admin/exam-records/{id}/preview` returns a student-safe preview.
  Paper mode returns `distribution_mode` and `paper_versions`, with public
  question content and no hidden checks.
- `POST /api/admin/exam-records/{id}/publish` creates the release;
  `/start`, `/end`, `/revoke`, `/copy`, and `/delete` use the existing lifecycle
  actions.

At publish, the backend creates release-scoped Code Exam records referencing
`paper_ref`, selects a Paper once for each eligible student in RANDOM mode,
and persists the mapping. COMMON maps all students to the same reference.
The release summary may contain `distribution_mode`, `paper_pool`, and
`paper_distribution_summary`; detailed `paper_assignments` remain server-side.
Starting the release writes each student's `paper_id`, `paper_version_id`, and
`code_exam_id` into `assignments.json`. Retrieval and retries use that stored
choice; refresh/relogin do not rerandomize it. Question order inside a Paper
is unchanged.

## Legacy standalone Code Exam APIs

`GET /api/admin/code-exams` and `GET /api/admin/code-exams/{id}` remain
available. `POST /api/admin/code-exams` and `PUT
/api/admin/code-exams/{id}` retain the legacy `question_ids` contract and
snapshot currently published questions directly. Historical question-based
records and assignments are not converted into Paper records.

## Student APIs

- `GET /api/student/code-exam` resolves the authenticated student's started
  assignment and exact Code Exam/Paper reference. It returns questions in
  stable order, progress, deadline/read-only state and public test/check data;
  it does not return the alternative RANDOM pool or hidden tests/expected
  values.
- `POST /api/student/code/run` accepts `question_id` and `source_code` for a
  visible-only pretest.
- `POST /api/student/code/submit` accepts `question_id` and `source_code` for
  one question; `POST /api/student/code/submit-exam` accepts an `answers` map
  for whole-exam submission.
- `GET /api/student/code/submission?question_id={id}` returns the latest
  submission subject to score-visibility rules.

The existing student UI draft key remains question/exam/student scoped as
`css-code-draft-v1:<student>:<exam>:<question>`.

Paper submissions persist `paper_id`, `paper_version_id`, `question_id`, and
`snapshot_version` alongside the submission. Default regrading resolves the
Code Exam's stored question snapshot. **Current behavior caveat:** the shared
`use_latest_spec=true` regrade option replaces that question snapshot with the
latest published Question Bank record even for a Paper Code Exam. This does
not meet a strict “always regrade the assigned Paper version” policy and
requires a code-phase correction or an explicit product decision; this page
documents the current source behavior.

## ZIP boundary and storage notes

ZIP release distribution remains the separate `distribution_mode` /
`distribution_config` workflow. Its random mode chooses exam files, not Paper
versions. Existing `/api/student/submit` and ZIP validation are unchanged.

Paper versions, exam releases, assignments and submissions are stored in
separate JSON files. Storage uses process-local locking and per-file atomic
replacement; there is no transaction spanning all files or multi-process
coordination. Run a single server process against a data directory.
