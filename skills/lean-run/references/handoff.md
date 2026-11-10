# Continuation and handoff

Use when the user asks to pause, hand off or resume work across sessions, or a context boundary would otherwise lose material state. Prefer a concise conversation record; write a durable checkpoint only when requested or required by an existing project record. Never include credentials or sensitive log payloads.

## What to capture

Capture enough for another authorized agent to continue without recreating the whole investigation:

- **Goal and contract.** Goal, current merged contract and delivery destination. Include accepted decisions, reversible assumptions, unresolved material choices and any paused work the user intends to resume. Distinguish granted authority from pending approval.
- **Workspace state.** Exact repository/worktree path, branch and revision or unborn state; relevant uncommitted/new files and unrelated user work to preserve. Do not claim a commit contains pending changes.
- **Acceptance status.** Completed and remaining acceptance items, affected artifacts and dependencies. Link the source of decisions and evidence rather than copying large transcripts.
- **Evidence.** Commands/actions, environment, observed outcomes and the content/revision they validate. Include review coverage, simulated boundaries and task-wide repair/REWORK counts.
- **Operations.** Running or externally mutating operations, known identifiers and whether each completed, failed, was denied, is pending or has an uncertain outcome. An uncertain operation must be inspected before retrying.
- **Next action.** Blockers, next safe action and the owner or missing answer needed to continue. State whether only the handoff is complete or the original task is also complete.

## Resume

On resume, read applicable instructions and compare the record with the actual checkout, pending changes, operation state and relevant environment. Reuse decisions and evidence whose inputs remain unchanged; revalidate only affected evidence after changes. Resolve material discrepancies without resetting, discarding work or silently switching repositories. Carry repair counts and explicit authorization limits forward. Ask only for missing consequential facts and continue independent authorized work.

## Result

A handoff-only request concludes DONE when the usable record is delivered, with the underlying task's state explicitly stated. Resumed implementation follows its original acceptance and delivery conditions; a missing required record/access/decision is BLOCKED and an unresolved demonstrated failure is FAILED. A checkpoint or summary alone does not prove implementation or deployment success.
