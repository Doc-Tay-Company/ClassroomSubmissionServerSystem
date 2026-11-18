# Decisions and provenance

Baseline: 2026-11-10. Approval source below means the project owner's explicit “Phase 2 — Project Context Initialization & Technical Risk Documentation” request in the project conversation on that date. These directions establish a revisable baseline. Source observations alone are not approvals or evidence of historical rationale.

## Approved working decisions

| ID | Decision | Evidence / approval | Known rationale | Consequences | Status |
|---|---|---|---|---|---|
| DEC-001 | Preserve publication, admin start, student start and currently permitted pre-start changes | Owner Phase 2 §1; general_exams.py/exams.py as described in [architecture](ARCHITECTURE.md#exam-lifecycle-and-state) | Owner selected current behavior as the documentation baseline; historical rationale unknown | Describe legacy exceptions and separate start transitions accurately | Approved baseline |
| DEC-002 | Preserve configurable submission extensions | Owner Phase 2 §1; submissions.py/general_exams.py | Explicit owner direction; historical rationale unknown | ZIP inspection applies to ZIP; do not describe all uploads as ZIP-only | Approved baseline |
| DEC-003 | Maintain the current architecture until a future authorized task changes it | Owner Phase 2 §1 | Current priority is reliable shared context and incremental investigation | No refactoring or migration follows from documenting a risk | Approved baseline |
| DEC-004 | Keep public hosting, simultaneous running exams, Docker, SQLite and other roadmap ideas outside approved scope | Owner Phase 2 §1 | Explicit scope control; no separate architectural rationale asserted | Root README roadmap entries remain proposals, not commitments | Approved baseline |
| DEC-005 | Keep shared project context, workflow status, implementation history, review history, and reusable lessons in documents with distinct responsibilities | Owner documentation-workflow authorization; [AGENTS.md](../AGENTS.md) and [documentation index](README.md) | Maintainable handoffs with low duplication and explicit evidence; historical rationale not asserted | Use the document ownership table in README; links replace copied histories | Approved documentation approach |

## Approved Practice contract

These are Owner-approved product and phase-boundary decisions, not claims that every feature is implemented. Current implementation status is in [PROJECT_CONTEXT](PROJECT_CONTEXT.md#current-practice-feature-status) and [CURRENT](../ai-workflow/CURRENT.md).

| ID | Decision | Evidence / approval | Consequences | Status |
|---|---|---|---|---|
| DEC-006 | Keep the Question Bank as the single source; Practice listing requires `published && practice_enabled`; preserve the safe Student projection and hidden-test/reference confidentiality | Owner-approved Phase 2 plan and subsequent Phase 2 instructions; [PLAN](../ai-workflow/PLAN.md) | Practice visibility is independent of official exam selection; public projection remains allowlisted | Approved requirement |
| DEC-007 | Keep one authoritative current progress/attempt per Student-Question. Students continue the current attempt; Update preserves attempt and local source, adopts current revision, and invalidates the old result. There is no Redo operation. | Owner-approved Phase 2 decisions, superseded by the Owner authorization to permanently remove Practice Redo | No historical attempts, best score, Saved Work, or server source persistence; Reset Code only replaces editor text with starter code within the current attempt | Approved requirement |
| DEC-008 | Keep source and `needs_retest` in local browser storage, with independent tab-local drafts and shared server attempt/progress authority; first actual edit creates the attempt ID; no server-side source autosave during Phases 1-3 | Owner-approved Phase 2 persistence, attempt lifecycle, and multi-tab decisions | Same-profile browser recovery only; deleting browser storage or switching devices can lose source; deferred autosave needs separate later approval | Approved requirement |
| DEC-009 | Keep Practice Run disabled in Checkpoint 2; real Practice execution evaluates visible tests only and belongs to Checkpoint 3; Phase 3 owns catalog/revision polling and reconnect synchronization | Owner-approved C2-F01 correction and three-phase/checkpoint scope | No fabricated result in CP2; official exam hidden-test grading, snapshots, submissions, quotas, and telemetry remain unchanged | Approved phase boundary |
| DEC-010 | Practice result is a weighted visible-test percentage; a valid compile failure may be 0%, but absent/invalid denominator is unscored; infrastructure/rejected failures preserve the previous valid result | Owner-approved Phase 2 scoring decisions | `100%` describes visible tests only; exact 50% uses light orange; official grading is unchanged | Approved requirement; Run implementation pending |
| DEC-011 | A question with current progress that becomes unavailable remains visible to that Student; its modal offers only Delete/Cancel. Delete removes only that Student's current progress and local Practice data; if later restored, it is unattempted for that Student | Owner-approved Phase 2 unavailable-question decision | No attempt history is retained; deletion cannot affect Question Bank, exams, or another Student | Approved requirement |

### Resolved Checkpoint 3 lifecycle decision

The Owner clarified that a Student must make an actual source edit before the first Practice Run. The frontend keeps Run disabled until an edit creates the `attempt_id`; an unchanged starter-code submission does not establish an attempt. This resolves the earlier planning ambiguity and does not change the server attempt contract.

## Existing implementation choices

These are observations, not newly approved architectural mandates. Detailed evidence and consequences are linked to avoid duplicating architecture and issue records.

| ID | Observed choice | Evidence | Historical rationale | Consequences | Status |
|---|---|---|---|---|---|
| OBS-001 | Standard-library threaded HTTP server, Jinja2, direct module calls | main.py; requirements.txt; supplied Architecture §§1–3 | Root README attributes framework removal to institutional native-extension restrictions; not independently confirmed by the authoritative sources | Local threaded request handling; [components](ARCHITECTURE.md#components-and-communication) | Implemented observation |
| OBS-002 | JSON/JSONL persistence with atomic replacement and process lock | storage.py; supplied Architecture §6 | Unknown | One-process coordination and no crash rollback; KI-002/KI-003 | Implemented observation |
| OBS-003 | One running exam, one file/code type per exam | general_exams.py `_normalize_items`, `start_exam`; tests/test_code_api.py | Unknown | Saved records can coexist; mixed/running parallel exams are unsupported | Implemented observation |
| OBS-004 | Windows Job Objects and Windows JDK startup preflight | windows_job.py; main.py `main`; java_runner.py `verify_jdk_configuration` | Resource containment is evidenced; reason for mandatory JDK on file-only startup is unknown | Platform and isolation limits; KI-001/KI-005 | Implemented observation |
| OBS-005 | Question snapshots and public field filtering | code_exams.py `_snapshot_question`, `public_question`; supplied Guide §§E/G | Guide explicitly identifies stable exams and protection of private grading data | Bank edits must not silently change active exam content or expose private fields | Implemented observation with documented rationale |

## Future proposals

The root README §2 lists public hosting/proxy deployment, rate limiting, CSRF work, SQLite, Docker and multi-session ideas. They have no approved schedule or selected design under this baseline (DEC-004). Entries in [KNOWN_ISSUES](KNOWN_ISSUES.md) request investigation only; they are not implementation tasks or architectural selections.
