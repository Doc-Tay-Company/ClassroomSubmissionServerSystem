# Code Exam and Exam Paper API

This document describes the routes currently dispatched by `app/main.py` and
the Paper/release behavior implemented by `app/papers.py`,
`app/general_exams.py`, and `app/code_exams.py`. Responses are JSON. Admin
routes require an admin session; student routes require a student session.

## Paper management (admin)

| Method | Route | Result |
|---|---|---|
| `GET` | `/api/admin/papers` | `{"papers":[...]}` summaries, including metadata, status, current version, source status and warnings. |
| `POST` | `/api/admin/papers` | Create draft; request includes `title`, optional `metadata`, and ordered non-empty `question_ids`. Returns `201` and `{"ok":true,"paper":...}`. |
| `GET` | `/api/admin/papers/{paper_id}` | Paper draft, versions and teacher-side source warnings. |
| `PUT` | `/api/admin/papers/{paper_id}` | Update draft fields `title`, `metadata`, `question_ids`, and required `expected_revision`; returns the updated Paper. `/update` POST is also accepted. |
| `GET` | `/api/admin/papers/{paper_id}/preview[?version_id=...]` | `{"preview":...}` for the draft/current version or the requested stored version. |
| `POST` | `/api/admin/papers/{paper_id}/publish` | Capture and append an immutable version; body requires `expected_revision`. |
| `POST` | `/api/admin/papers/{paper_id}/archive` / `restore` | Archive or restore Paper; body requires `expected_revision`. |
| `POST` | `/api/admin/papers/{paper_id}/delete` | Delete only when no exam/release/assignment/code-exam record references the Paper; body requires `expected_revision`. |

New question IDs must exist, be `published`, and be eligible for a supported
Code Exam. Existing snapshot questions can remain in a later version if their
source is inactive or gone; this preserves history and the admin response
includes `source_status` and `warnings`. Paper versions store ordered
question snapshots and `source_ref` metadata. Student payloads do not use the
admin Paper detail/preview serializer.

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
