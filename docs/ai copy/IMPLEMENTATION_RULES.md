# Implementation Rules

## Before every phase
1. Read `AGENTS.md`, this file, `docs/ai/IMPLEMENTATION_CONTEXT.md` and the current prompt.
2. Inspect branch, commit, working tree and repository instructions.
3. Compare actual source with any previous audit/handover.

## Plan before code
Trace UI state → API route → service → storage → tests. State confirmed problem, reproduction, exact files/functions, minimal fix, compatibility risks and tests. Respect approval gates.

## Implementation discipline
- Minimal, requirement-driven changes; follow existing conventions.
- Preserve API compatibility unless explicitly required otherwise.
- Server validation is authoritative.
- Reuse existing helpers, snapshots and revision controls.
- No speculative abstractions, dependencies or duplicate distribution engines.
- Filter changes must not silently drop selected questions.
- Never mutate published versions or historical releases.

## Data safety
No destructive migration. Preserve IDs and legacy records. If schema change is necessary, provide backward-compatible reads, backup/rollback and migration plan. Do not manually edit runtime data without approval. Historical snapshots must not be rewritten from current Question Bank data.

## Testing and Git
Add focused tests. Clearly distinguish inspected tests from executed tests. Never claim pass unless actually run. Do not reset/clean/discard user changes. Do not commit/push unless asked. Review full diff.

## Phase boundary
At each phase end, stop and report findings, files changed, behavior, data/API impact, tests and actual results, known issues and next prompt. Do not continue automatically.
