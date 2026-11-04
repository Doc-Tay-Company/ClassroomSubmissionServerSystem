# Changes Added by `add-backend`

This document summarizes the changes brought from `add-backend` into `test` by merge commit `d2c6f29` (`Merge branch 'add-backend' into test`).

## Code-grading backend

- Added question-bank support for Java Reflection, Java STDIO, and Python STDIO questions, including validation, draft/publish lifecycle, versioning, archive/delete safeguards, and exam snapshots.
- Added code-exam lifecycle and shared student APIs for fetching an exam, pretesting visible tests/checks, and submitting final solutions.
- Reused the same execution and submission flow for the supported languages and grading modes rather than introducing a separate STDIO submission system.
- Added result retrieval for students and administrators, hidden-test protection in student responses, audit metadata, and regrading with retained grading history.
- Integrated code-only exam completion and force-submit behavior with the existing assignment lifecycle.
- Added admin monitoring summaries for code submissions without exposing student source code.

## Java and Python execution

- Added a shared STDIO runner for Java and Python. Java sources are compiled once per run and executed separately for each test; Python sources are syntax-checked and each test runs in a separate process.
- Added output comparison modes (`exact`, `normalized`, `tokens`, and `float_tolerance`) and per-test verdicts and scoring.
- Added Windows Job Object process-tree limits, memory limits, output bounds, timeouts, and kill-on-close cleanup for code execution.
- Added startup checks for a usable JDK 17 or newer. `JAVA_HOME` selects the toolchain when set, and `java` and `javac` must resolve to matching versions.
- For Java STDIO questions, the configured exercise total is split evenly across its test cases. Any representational remainder is assigned to the final test so the configured points still sum to the exercise total. Python STDIO and Reflection retain explicitly configured per-test/check points.

## Local runtime data

- Added initialization for the code-grading JSON stores and tests that verify default files are created without overwriting existing local data.
- Changed Git tracking so runtime JSON under `data/` is ignored, while `data/.gitkeep` keeps the directory in the repository. Existing tracked runtime JSON files were removed from the merge result; local copies remain on the working machine and are not shared through Git.
- Updated the README and specification with the local-data and backup implications.

## API surface

The backend adds or extends endpoints for:

- Admin question list/detail/create/update/duplicate/archive/delete/publish.
- Admin code-exam list/create and exam state transitions.
- Student code-exam retrieval, pretest, submission, and result retrieval.
- Admin code-result retrieval and regrade.
- Admin monitoring summaries for code submissions.

These are backend APIs; this merge does not add a complete teacher/student code-grading interface.

## Tests and verification

The merge includes API, runner, Java toolchain, storage-initialization, and Windows Job Object tests. The merged suite was run on the Windows environment with the installed JDK 21.0.8:

- `python -m unittest discover -s tests`
- Result: **250 tests passed, 1 skipped**.

The skip is platform/environment-specific. Java execution requires Windows Job Objects and a supported JDK.

## Source areas

- `app/questions.py` — question validation and lifecycle.
- `app/code_exams.py` — code exam, pretest, submission, result, and regrade logic.
- `app/code_runner.py` and `app/java_runner.py` — STDIO and Java execution.
- `app/main.py` — HTTP API routes and monitoring.
- `app/storage.py` — runtime JSON initialization.
- `tests/` — API, runner, JDK, storage, and Job Object coverage.
