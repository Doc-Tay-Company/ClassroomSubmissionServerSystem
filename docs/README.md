# Documentation index

This folder contains current operating guides, implementation references, and retained historical reports. For current behavior, use the source-backed documents below and verify the relevant implementation before changing it. Historical merge/audit reports describe the exact snapshots named in those reports; they are not current branch instructions.

## Project footprint at this documentation pass

Counts are a checkout snapshot, not product limits. Runtime JSON contents, logs, uploaded submissions, and exam PDFs are deliberately excluded because they are operational or user data.

| Area | Current footprint |
|---|---:|
| Python files under `app/` | 22 (including `__init__.py`) |
| Frontend JavaScript files under `static/js/` | 14 |
| HTML templates | 6 |
| Test files under `tests/` | 27 (16 Python, 11 JavaScript) |
| Markdown documents in `docs/` before this index | 17 |

The application covers accounts and roles, question authoring, Practice, Papers, ZIP/file exams and code exams, distribution/releases/assignments, grading and regrading, results, exam monitoring, and server-side exam completion. The implementation is a threaded Python HTTP server with local browser assets and JSON/JSONL persistence; these counts do not establish supported classroom capacity, deployment readiness, or test status.

## Current reference documents

| Document | Use it for |
|---|---|
| [Project context](PROJECT_CONTEXT.md) | Product areas, roles, current workflows, and Practice/Official Exam boundary. |
| [Architecture](ARCHITECTURE.md) | Runtime components, persistence, data flows, and implementation constraints. |
| [Codebase architecture](codebase-architecture/README.md) | Repository map, technology, and detailed source navigation. |
| [Code Exam API](CODE_EXAM_API.md) | Paper, Exam, results, student code API and compatibility behavior. |
| [Question Bank, Papers and Exams guide](EXAM_PAPER_GUIDE.md) | Authoring and Paper/Exam behavior, including new and legacy Paper records. |
| [Exam Distribution code guide](EXAM_DISTRIBUTION_CODE_GUIDE.md) | Distribution implementation flow and code navigation. |
| [Exam Monitoring implementation plan](EXAM_MONITORING_IMPLEMENTATION_PLAN.md) | Approved monitoring scope, source implementation status, and acceptance requirements. |
| [Known issues](KNOWN_ISSUES.md) | Current implementation limits and verification gaps. |
| [Decisions](DECISIONS.md) | Owner-approved requirements separated from source observations. |
| [Engineering lessons](ENGINEERING_LESSONS.md) | Reusable implementation and review practices. |

## Historical reports

These reports are retained for provenance and may contain stale branch names, routes, line numbers, or pre-implementation findings. Use the current references above for present behavior.

| Document | Historical purpose |
|---|---|
| [Telemetry architecture audit](TELEMETRY_ARCHITECTURE_AUDIT.md) | Pre-implementation analysis; monitoring features described as proposals have since been implemented in source. |
| [Practice/Exam pre-merge audit](PRACTICE_EXAM_PREMERGE_COMPATIBILITY.md) | Comparison of two specified source snapshots before integration. |
| [Exam Distribution merge contract](EXAM_DISTRIBUTION_MERGE_CONTRACT.md) | Integration safeguards for the earlier Exam/Practice merge. |
| [Exam Distribution technical handoff](EXAM_DISTRIBUTION_TECHNICAL_HANDOFF.md) | Point-in-time implementation handoff and verification record. |
| [Archived decisions](archieve/DECISIONS_legacy.md) | Previous decision log; superseded by current [Decisions](DECISIONS.md). |
| [Archived known issues](archieve/KNOWN_ISSUES_legacy.md) | Previous issue baseline; superseded by current [Known issues](KNOWN_ISSUES.md). |

## Maintenance rules

- Keep this index and the footprint figures current when the project structure materially changes.
- Treat code as the authority for implementation; keep Owner decisions and source observations distinct.
- State whether tests/browser checks were run. A test file in the repository is not evidence that it passed in a given checkout.
- Preserve historical reports as historical records; do not silently rewrite their snapshot conclusions as current facts.
- Do not include live classroom records, credentials, logs, or uploaded student work in documentation.
