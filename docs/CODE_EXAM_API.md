# Code Exam API

This document covers the backend contract for assembling, distributing, and
grading multi-question code exams.

All responses use JSON. Errors use `{"detail":"..."}`. Admin routes require an
admin session; student routes require a student session.

## Admin exam APIs

### List exams

`GET /api/admin/code-exams`

Returns `{"code_exams":[...]}`. Each exam includes its ID, title, lifecycle
status, settings, and ordered question snapshots.

### Get one exam

`GET /api/admin/code-exams/{exam_id}`

Returns `{"code_exam":...}`.

### Create an exam

`POST /api/admin/code-exams`

Creates a `draft` and snapshots each selected published question in the exact
order of `question_ids`.

Request:

```json
{
  "title": "Programming Exam",
  "question_ids": ["question-a", "question-b"],
  "submission_policy": "configurable",
  "max_submissions": 2,
  "show_final_score_immediately": false,
  "allow_pretest": true,
  "max_pretest_runs": 20,
  "pretest_cooldown_seconds": 2
}
```

Response: `201 Created`, `{"ok":true,"code_exam":...}`.

Every question snapshot contains the question-bank fields plus
`question_id`, `snapshot_version`, `snapshot_at`, and `order`. Later changes to
the question bank do not change this snapshot.

### Update a draft / explicitly refresh snapshots

`PUT /api/admin/code-exams/{exam_id}`

The request supplies the complete ordered question list and exam settings. A
successful draft update refreshes the snapshots of the supplied questions
using their current published bank versions. Reordering does not change
question usage counts; removing or adding a question adjusts the count for the
exam's current references.

Request shape is the same as create. Response: `200 OK`,
`{"ok":true,"code_exam":...}`.

Only exams with `status == "draft"` can be updated. Once distributed, content
is immutable. To correct a distributed exam, create a replacement exam.

### Results

`GET /api/admin/code-results?exam_id={exam_id}[&student_id={id}][&question_id={id}]`

Uses the existing results endpoint. It returns submissions for the exam's
release, with admin-only source and full grading details. Regrade is available
at `POST /api/admin/code-results/{exam_id}/regrade`.

## Student APIs

- `GET /api/student/code-exam` returns the ordered snapshot with only public
  question data and visible tests/checks.
- `POST /api/student/code/run` runs a pretest against visible tests/checks.
- `POST /api/student/code/submit` submits one question.
- `GET /api/student/code/submission?question_id={question_id}` returns the
  student's latest submission for that question.

The exam's `show_final_score_immediately` flag controls whether a question
score is returned after that question's submission. If false, score details
remain hidden until the exam is ended. At exam end, final per-question and
exam-level score data is available. Hidden tests/checks are never returned to
students.

Completing all code questions marks a code-only assignment submitted. For a
combined code+ZIP assignment, the ZIP submission remains available after code
completion and the existing ZIP submission policy remains in effect.

## Status codes

| Condition | Status |
|---|---:|
| Exam created | 201 |
| Draft updated | 200 |
| Missing exam or question | 404 |
| Invalid lifecycle transition or update after distribution | 409 |
| Duplicate question IDs | 422 |
| Invalid request fields or malformed JSON on exam create/update | 422 |
| Student submits after the server deadline | 409 |
| Unauthenticated | 401 |
| Authenticated with wrong role | 403 |

Malformed JSON on other existing routes retains the shared parser's existing
status behavior.

## ZIP compatibility

The existing ZIP endpoint remains `POST /api/student/submit`. Its validation,
file limits, submission policy, and stored submission format are unchanged by
code-exam creation/update APIs.
