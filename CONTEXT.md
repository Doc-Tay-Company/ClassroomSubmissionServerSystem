# Project Context

## Paper Management

- Paper Management lives in static/js/code-papers.js; lifecycle, validation, and persistence live in app/papers.py, with routes in app/main.py.
- Schema-v2 Papers use a stable ID and optimistic revision checks (expected_revision). Draft edits are debounced to the server and kept in a local recovery cache after failures. Published schema-v2 Papers require explicit Save Changes; updates retain the ID and published status and validate the complete question selection.
- Revoke applies only to Published schema-v2 Papers and changes published to draft. Legacy versioned Papers keep their existing behavior and cannot use the revoke action.
- Published table rows open Preview; Draft rows open Edit. Archive APIs and historical data remain supported, but Paper Management does not expose Archive buttons.
- General Exam references are retained after revocation. The existing unavailable-Paper warning applies; creating a new Release still requires Published Papers.
- Exam Releases use frozen Code Exam snapshots. Editing or revoking a source Paper does not rewrite existing Release snapshots or student attempts. A distributed, not-yet-started Exam retains its snapshot until the normal supported Exam update/release flow rebuilds it.
- Relevant tests: tests/test_papers.py, tests/test_paper_distribution.py, tests/test_paper_builder_filters.js. See docs/EXAM_PAPER_GUIDE.md for API and lifecycle details.

## Operational constraints

- Runtime JSON files are under data/; do not treat them as source or overwrite them casually.
- Do not stage or commit runtime data as part of source changes.

## Student account creation

- Bulk account import captures the form reference before awaiting /api/admin/accounts/import, so form reset remains valid after the request resolves. A successful import reports created and duplicate counts and refreshes the account list; a refresh failure is reported separately from account creation. Failed create requests retain the form and are not retried automatically. See static/js/admin.js and tests/test_admin_account_import.js.
