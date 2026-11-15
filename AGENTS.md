# Codex Instructions — ClassroomSubmissionServerSystem

This file is the entry point for AI coding agents working in this repository.

## Mandatory reading before every task

Before planning, editing, or answering a project implementation request, read these files in order:

1. `docs/ai/PROJECT_CONTEXT.md`
2. `docs/ai/IMPLEMENTATION_RULES.md`
3. `docs/ai/EXAM_PAPER_TASK_SPEC.md` when the task concerns Exam Paper / Exam Distribution
4. The specific phase prompt under `prompts/` that the user has asked you to execute
5. The relevant current source files and tests

Do not rely on a previous chat, a previous model response, or remembered file contents as a substitute for rereading these files and inspecting the current workspace.

If the repository contains another `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, or project-specific instruction file, inspect it and reconcile instructions. If instructions conflict, do not silently choose: explain the conflict and follow the repository owner's latest explicit instruction.

## Required response before implementation

For each phase, first provide a short plan containing:
- What you inspected.
- Current behavior found in source.
- Files/functions expected to change.
- Data/API compatibility risks.
- Tests to run.

Do not start a later phase automatically. Execute only the phase explicitly requested by the user.

## Completion gate

At the end of each phase, stop and report:
- Implemented behavior.
- Files created/modified.
- Important decisions.
- Tests actually run and their actual results.
- Tests not run and why.
- Known limitations and next phase.

Never claim successful runtime, browser, LAN, or end-to-end verification based only on source inspection.
