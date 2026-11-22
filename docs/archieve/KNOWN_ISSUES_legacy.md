# Known issues, risks and limitations — archived baseline

> Historical snapshot. The findings below are not the current issue tracker and include status/links that may be stale. Use [current Known Issues](../KNOWN_ISSUES.md) and [documentation index](../README.md).

Initial evidence baseline: 2026-11-10. These risks came from the Phase 1 documentation audit; the Runner/Judge findings below were added from a later targeted audit. Not every item has been re-verified after subsequent changes. Check `ai-workflow/CURRENT.md` for active phase status. Source-supported risks are not claims of reproduced exploits, data loss, or operational incidents unless an entry explicitly says otherwise.

Priority indicates investigation urgency: **High** for plausible host/data-integrity or exposure impact; **Medium** for capacity, portability, recovery or documentation uncertainty. It is not a measured exploit severity. Every entry starts unresolved and creates no implementation authorization.

## KI-001 — Student execution lacks filesystem/network isolation

- **Description:** Job Objects enforce resource/process limits but do not restrict the student's filesystem/network access under the server identity.
- **Sources:** [windows_job.py](../../app/windows_job.py), `create_job_process`; historical judge handover (not retained in this checkout); [java_runner.py](../../app/java_runner.py).
- **Potential impact:** Submitted programs may access host resources available to the execution identity. Actual exposure depends on host privileges and policy.
- **Evidence status:** Verified implementation limitation, corroborated by technical handover; no exploit reproduced.
- **Priority:** High, because execution involves student-controlled programs and host data.
- **Current status:** Documented limitation; deployment protections unverified.
- **Future investigation:** Establish execution identity, ACLs, network access and threat model; verify permitted access in an isolated environment before choosing controls.
- **Resolution status:** Unresolved.

## KI-002 — Potential lost updates across concurrent read/modify/write operations

- **Description:** Individual storage calls lock, but session updates and file-submission workflows separately read and write whole JSON collections. An intervening request may be overwritten. `transaction()` protects only participating sequences.
- **Sources:** [storage.py](../../app/storage.py), `read_json`, `write_json`, `update_json`, `transaction`; [security.py](../../app/security.py), `new_session`/`get_session`; [submissions.py](../../app/submissions.py), `accept_submission`.
- **Potential impact:** Missing session changes, submission metadata, or assignment updates under concurrent requests.
- **Evidence status:** Source-supported race possibility; no lost-update reproduction performed.
- **Priority:** High, because the server uses concurrent request threads and affected state includes submissions.
- **Current status:** Requires targeted concurrency verification.
- **Future investigation:** Trace lock coverage for affected operations and exercise controlled overlapping requests against temporary data; identify the exact interleaving before proposing a change.
- **Resolution status:** Unresolved.

## KI-003 — Related files lack crash atomicity

- **Description:** Atomic replacement protects individual JSON files. Payload, metadata, assignments, settings and audit can be persisted separately. The process lock has no rollback or inter-process coordination.
- **Sources:** storage.py `atomic_write`/`transaction`; submissions.py `accept_submission`; [general_exams.py](../../app/general_exams.py), release/start operations; supplied Architecture §6.
- **Potential impact:** Abrupt interruption may leave orphan payloads or inconsistent linked state; simultaneous server instances may overwrite changes.
- **Evidence status:** Verified persistence boundary; crash/power-loss/multi-instance outcomes untested.
- **Priority:** High, because exam/submission integrity and recovery depend on related records.
- **Current status:** Single-process operational constraint; recovery guarantees unspecified.
- **Future investigation:** Define invariants, inspect restart reconciliation and backup restoration, and verify interrupted writes using disposable state. Do not infer a storage migration decision.
- **Resolution status:** Unresolved.

## KI-004 — Synchronous bounded grading and shutdown behavior

- **Description:** Grading occupies request work; the run semaphore defaults to two slots and can reject busy requests with 429. HTTP threads are daemon threads; shutdown does not establish completion of in-flight work.
- **Sources:** [code_exams.py](../../app/code_exams.py), `_RUN_SLOTS`, `run_pretest`, `submit_code`; [main.py](../../app/main.py), `main` and grading routes; supplied Architecture §§7–8.
- **Potential impact:** Contention and retries during synchronized submission; interrupted work during shutdown. Supported class size is unknown.
- **Evidence status:** Verified mechanism; capacity and shutdown failures not reproduced.
- **Priority:** Medium; operational impact depends on workload and stop procedure.
- **Current status:** Capacity/shutdown behavior requires measurement.
- **Future investigation:** Measure expected concurrent workloads, busy responses, execution duration and shutdown cleanup on supported hardware.
- **Resolution status:** Unresolved.

## KI-005 — Platform/toolchain constraints and uncertain Python support

- **Description:** Windows startup requires working JDK 17+ even for file-only use. Non-Windows startup reports grading unavailable. Python 3.10+ is claimed by the secondary README but lacks established compatibility results/package metadata.
- **Sources:** main.py `main`; java_runner.py `verify_jdk_configuration`; windows_job.py `create_job_process`; [root README §6](../../README.md#6-requirements); supplied Overall “Unknowns.”
- **Potential impact:** Missing/mismatched tools block startup; unsupported environments cannot provide grading; deployment compatibility may be overstated.
- **Evidence status:** Verified platform/startup checks; installed toolchains and Python compatibility uncertain.
- **Priority:** Medium; directly affects deployability and pre-exam readiness.
- **Current status:** Constraints documented; environment support matrix unverified.
- **Future investigation:** Verify clean startup and applicable tests on intended Python/Windows/JDK combinations and file-only Unix deployments.
- **Resolution status:** Unresolved.

## KI-006 — Public deployment security/readiness unverified

- **Description:** HTTP/all-interface binding is the default. `check_origin` exists but main.py does not call it; helper tests do not establish endpoint protection. No upload-specific rate limiter was identified. TLS/proxy trust and firewall configuration are unknown.
- **Sources:** [config.py](../../app/config.py); main.py request handling/TLS; security.py `check_origin`; [test_core.py](../../tests/test_core.py); root README §§2/12/17.
- **Potential impact:** Credentials/submissions may be exposed on untrusted networks; request abuse or cross-origin behavior requires assessment. No exploit is asserted.
- **Evidence status:** Verified inspected defaults/helper wiring; deployment protection and exploitability uncertain.
- **Priority:** High before any exposure beyond the trusted deployment baseline; public hosting itself remains unapproved.
- **Current status:** Readiness not established.
- **Future investigation:** Establish actual topology, TLS and proxy behavior; assess endpoint CSRF/Origin and abuse controls with deployment-specific evidence if public exposure is proposed.
- **Resolution status:** Unresolved.

## KI-007 — Historical documentation drift and navigation inconsistencies

- **Description/evidence:** The following discrepancies remain in documents outside the five approved Phase 2 targets. Owner decisions settle the baseline policies, but do not repair those documents.

| Source/section | Classification | Current evidence / remaining discrepancy |
|---|---|---|
| Root README §§4/6, backend-only grading UI | Outdated | admin.html/student.html and loaded scripts wire code UI to APIs; complete live UI behavior still unverified |
| Root README §11, immediately irreversible distribution | Outdated | general_exams.py permits revoke and qualifying distributed updates before admin start; legacy-applied releases require special handling |
| Root README §4, ZIP-only uploads and three distribution modes | Outdated | Configurable extensions in submissions.py; `selected` also exists in exams.py. DEC-002 confirms extension policy |
| Root README §4, five-second notification delivery | Outdated | student.js heartbeat retrieves notifications every 15 seconds plus events; admin polling is five seconds |
| Supplied Architecture §1 and §§2–3 component inventories | Outdated | Missing current coding frontend modules and general_exams.py/exams.json orchestration |
| Supplied Overall “Network architecture”; Architecture §5, no heartbeat | Conflict | student.js has an HTTP heartbeat function; no custom socket heartbeat protocol was established. Terminology needs qualification |
| Supplied Architecture §5, explicit methods | Outdated | main.py includes delegated PUT handling |
| Supplied Overall “Caveats” item 5 | Uncertain | Old checkout-specific dirty-file claims are not reusable project facts |
| Supplied Overall documentation map / Architecture diagrams | Uncertain | Links assume split chapter/diagram paths; supplied detailed document combines chapters. Complete link reconciliation remains pending |

- **Potential impact:** Agents may omit active workflows, mistake historical claims for requirements, or navigate to stale references.
- **Priority:** Medium; incorrect context can misdirect future changes.
- **Current status:** Shared baseline records corrections; historical sources remain unchanged.
- **Future investigation:** If separately authorized, check referenced targets and revise historical docs against current source and owner decisions. Preserve provenance.
- **Resolution status:** Unresolved.

## KI-008 — Runtime verification and operational requirements incomplete

- **Description:** Automated test evidence has been recorded for selected phases, but full browser acceptance, representative capacity results, backup/restore exercise and deployment inspection remain incomplete. Supported class size, latency/recovery targets, retention policy and active purpose of machines.json are unspecified/unverified.
- **Sources:** [PROJECT_CONTEXT](../PROJECT_CONTEXT.md); [tests](../../tests/) (mocked API execution and platform guards); storage.py defaults; supplied Architecture §8 unknowns.
- **Potential impact:** Source-level feature presence may be mistaken for operational readiness or guaranteed behavior.
- **Evidence status:** Automated test runs and a Checkpoint 2 Node harness were recorded in historical `ai-workflow/IMPLEMENTATION.md` (not retained here); real-browser behavior, representative capacity, backup/restore, and deployment remained unverified at that time.
- **Priority:** Medium; verification should be selected for the next approved task or intended deployment.
- **Current status:** Phase 2 Checkpoint 2 Owner browser acceptance remains pending. Operational targets and deployment evidence remain pending.
- **Future investigation:** Obtain owner targets, execute relevant existing tests in a suitable environment, trace complete browser workflows, and record environment/results without overstating coverage.
- **Resolution status:** Unresolved.

## KI-009 — CSP warning for Base64-embedded WOFF2 font

- **Description:** The project owner reports a browser Content Security Policy warning blocking a Base64-embedded WOFF2 font. The warning has not been independently reproduced in this review. Practice and base stylesheets load as same-origin files; the server CSP is defined in `app/main.py` and may block inline/data-backed font sources depending on its `font-src` policy and browser enforcement.
- **Sources:** Owner report in the Phase 2 planning request; `app/main.py` CSP response header; `templates/base.html` stylesheet links; `static/css/app.css` font fallback stack; `static/vendor/fontawesome/css/all.min.css` icon font declarations.
- **Potential impact:** Font Awesome glyphs or the intended typeface may fall back, affecting visual appearance. No workspace, API, or execution behavior impact is established from current source inspection.
- **Evidence status:** Warning is owner-reported; exact violating URL/directive and visible impact are unverified. Treat as potentially non-blocking pending browser inspection.
- **Priority:** Low, unless manual browser verification shows material text legibility or controls are obscured.
- **Current status:** Deferred for Phase 2; CSP must not be weakened as a workaround without a separately approved security review.
- **Future investigation:** Capture the browser console/network request and CSP directive. If only a decorative font/icon falls back, retain current policy and defer; otherwise serve an approved font asset from same origin or use an existing system-font fallback.
- **Resolution status:** Unresolved.

## Execution and Judge audit — RUN-01 through RUN-05

The findings below are summarized from a historical source-based and targeted test investigation in `ai-workflow/REVIEW.md` (not retained in this checkout), “Comprehensive Code Runner and Judge Architecture & Reliability Audit.” The audit is historical evidence; verify current source and intended-host behavior before relying on a status. No finding here authorizes a fix by itself.

| ID | Current finding | Evidence status and impact | Closure / next verification |
|---|---|---|---|
| RUN-01 | Java Reflection using the default Windows system-temp workspace can fail with `INVALID_REQUEST: invalid output directory`. | **Unresolved; High impact for official Java Reflection grading.** The recent combined run of `tests.test_java_runner` and `tests.test_reflection_judge` reported 118 tests, 60 failures, and 1 skipped. Representative failures returned the invalid-output-directory result and are consistent with RUN-01, but the 60 failures have not all been individually classified. The underlying filesystem exception was not conclusively re-verified in that latest run. By contrast, Practice's repository-volume workspace passed its real Java Reflection integration test. This does not verify the official default workspace or intended Teacher-host reliability. | Reproduce and capture the first filesystem/path failure on the intended Windows account, then run the official Java Reflection execution path with its production-equivalent workspace parent. Verify unique workspace isolation, permissions, and cleanup. Close only after repeatable official-path tests and intended-host validation pass; Practice-specific success alone is insufficient. |
| RUN-02 | An official infrastructure execution error can consume a reserved submission attempt before the error is returned. | Confirmed in submission reservation/completion path; may prevent a Student retry after infrastructure failure. | Verify an Owner-approved retry policy and test that infrastructure failure does not become a student grading verdict; preserve official score integrity. |
| RUN-03 | Student code execution has resource/process limits but no demonstrated filesystem/network isolation from resources available to the server identity. | Confirmed implementation limitation; exploitability depends on host identity and configuration. Affects official execution and future Practice execution. | Define deployment threat boundary and verify least privilege/access restrictions in an isolated intended-host environment before untrusted classroom execution sign-off. |
| RUN-04 | Historical workspace-cleanup failure during full discovery remains unexplained. | Not reproduced in representative isolated runs; treat as an unresolved test/cleanup observation, not a confirmed production defect. | Re-investigate only if reproducible; capture first failing cleanup, workspace path, and process state. |
| RUN-05 | Synchronous grading uses a shared process-local capacity semaphore that defaults to two runs and rejects excess work rather than queueing. | Mechanism verified; contention and classroom impact not measured. | Measure representative simultaneous runs and document expected busy/retry behavior on intended hardware. |

Detailed trace, test results, severity, and phase/deployment recommendations remain in the linked audit. RUN-03 is a deployment blocker for untrusted classroom execution; RUN-01 remains unresolved for official Java Reflection and intended-host validation, while the Practice-specific workspace override has passing real-runner evidence. The latest combined Java suites are not fully diagnosed: their 60 failures must not be treated as 60 independently confirmed RUN-01 defects. RUN-02 is an official reliability issue. RUN-04 remains unconfirmed; RUN-05 is a capacity risk. These findings remain separate from Practice bug-fix manual acceptance and do not establish deployment readiness.
