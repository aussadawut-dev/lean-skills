---
name: lean-run
description: Own an end-to-end implementation request from initial decisions to verified delivery, coordinating available Lean skills without repeated planning or manual handoffs.
license: MIT
---

# lean-run

Carry the user's request through its authorized endpoint, including scoped proposal/diagnosis deliverables. Follow project instructions and preserve unrelated work. This skill works alone: companions are optional and no Lean runtime or workflow directory is required.

For **assessment-only** work, use a focused review: map acceptance to the current source, diff and tests; run required checks once; then independently challenge remaining boundary/failure risks through the public interface. Do not recreate a second comprehensive test suite or alternative implementation when inspected source and verified tests already establish that behavior. Expand probes for a concrete gap or contradictory evidence, and finish when coverage and findings are resolved. Reproduce old failures only when needed to establish a finding or explicitly requested. Keep the risk/quality review requirements below; an assessment is not an implementation or delivery request.

## Establish scope once

Read applicable instructions, existing decisions and the closest relevant source. Reuse verified context and commands while their inputs remain unchanged. For broad goals or material ambiguity, read [exploration](references/exploration.md). Skip that loop for clear requests or an instruction to proceed; ask only indispensable missing decisions and continue independent work. An unanswered question or elapsed time is not consent.

Record outcome, behavior, observable acceptance, constraints, verification and destination; one sentence suffices for a mechanical change. Default to standard procedure depth and verified workspace changes. Depth changes investigation detail, not acceptance or model settings. For substantial work, track decisions, remaining work, evidence and next action in conversation; create workflow files only when requested.

Resolve consequential business rules, permissions, data lifecycle and external contracts early. Decide reversible implementation details using project conventions. A clear implementation request authorizes matching work without another plan approval. Requested PRs or deployments remain part of acceptance and require matching authority/tools; finish authorized preparation before any necessary final approval. “End-to-end” grants no extra publishing, spending or provider permissions.

For user-facing work, include affected usability/accessibility, keyboard/focus, screen sizes, feedback and loading/empty/error/recovery behavior in acceptance. For performance work, establish a representative workload and measured baseline before optimization; a research/proposal request alone does not authorize benchmarking. On explicit pause, handoff or cross-session resume, read [continuation and handoff](references/handoff.md).

## Load only relevant procedures

Read an available companion only when its procedure helps the current task. Pass settled scope, relevant artifacts/evidence and the remaining question; continue the original request without asking the user to invoke the next stage. If absent, perform the core procedure here. Missing a skill is not a blocker; a required capability can be.

| Need | Optional companion |
| --- | --- |
| Requested repository, unknown conventions, requested agent instructions | `lean-target`, `lean-init`, `lean-instructions` |
| Scope, decisions, implementation research | `lean-scope`, `lean-grill`, `lean-research` |
| Implementation, useful delegation | `lean-task`, `lean-agents` |
| Change review, completion evidence | `lean-review`, `lean-gate` |
| Requested security concern/changed trust boundary, authorized release/recovery | `lean-security`, `lean-release` |
| Requested procedure depth, skill/model updates | `lean-effort`, `lean-update`, `lean-model-update` |

This workflow requests selective delegation when useful or needed for independent review, subject to user/host restrictions. Keep small work inline; default to one active worker, with more only for explicit parallel work. Before dispatch, read [provider-aware delegation](references/delegation.md) for model/effort selection, naming, isolation and escalation. One controller retains scope, integration, repair counts and delivery.

## Implement and verify efficiently

1. Reuse or classify risk as LOW/MEDIUM/HIGH and quality as STANDARD/HIGH/VERY_HIGH. Consequential security, destructive data and breaking external-contract changes are HIGH risk. Limit implementation to acceptance. Prefer existing project or standard-library primitives with verified semantics over custom replacement logic. For unclear faults, preserve expected/actual behavior and environment, minimize the reproducer, trace the failing boundary and distinguish causes with targeted probes; label hypotheses and workarounds honestly.
2. Map each requirement to evidence; reuse existing coverage and add compact table-driven checks for gaps. Reproduce bugs before repair and verify afterward, disclosing unavailable reproduction. For consequential writes, assert all required effects and failure atomicity, including partial/no-effect outcomes when the storage API can silently skip a write. Run affected checks during iteration and required project checks on final content; inspect unfamiliar project commands first.
3. Exercise the relevant journey through integrated components via its real UI, API, CLI or artifact consumer, including important failures. Record environment, actions, expected/observed results and simulated boundaries. Unit tests, builds and mocks do not prove an untested live integration. Finish useful work when live access is missing, then report unmet acceptance rather than substituting simulation.
4. Review the final diff, including new files, after deterministic validation. LOW permits an acceptance self-check; MEDIUM needs focused correctness/regression review; HIGH needs a fresh independent reviewer. Quality HIGH requires at least MEDIUM review; VERY_HIGH requires HIGH. Unavailable required independence is BLOCKED, never a self-issued independent PASS. For bounded changes, derive equivalence classes and boundary/failure cases from the contract, inspect the implementation and batch independent probes. Extend to exhaustive/random sweeps only for an identified coverage gap or unresolved hypothesis; case count alone is not evidence. Stop once mandatory coverage and findings are resolved, without skipping independent checks.
5. Repair in-scope failures, rerun affected checks and renew review of changed content. Reuse evidence only if its inputs, relevant environment and acceptance are unchanged and project rules allow. Integrated worker results need verification. Complete the requested destination; local success alone does not satisfy an authorized PR/deployment.

Batch independent reads/checks; serialize dependencies and mutations. Read each relevant source once, then changed sections. Inspect new files too, but avoid repeatedly printing full files/diffs. A fresh reviewer inspects current source and runs independent checks; do not substitute author conclusions.

For potentially noisy suites or expected failures, use the bundled [check runner](scripts/check.py): `python3 /resolved/skill/path/scripts/check.py -- COMMAND ARG...`. It retains full stdout/stderr, returns the command's exit status and emits a bounded excerpt. There is no default timeout; `--timeout SECONDS` is optional, and `--log NEW_PATH` refuses overwrite. Execute this documented helper without reading its source unless debugging/changing it. If Python is unavailable, use equivalent host log capture without installing a runtime. Small checks with bounded output can run directly. For a successful check with its expected completion summary, record that evidence and move on; do not reread or rerun its full passing log merely because earlier progress lines were omitted. For failures or missing/ambiguous completion evidence, inspect the saved log until distinct causes are understood. Passing a check is only evidence for its mapped acceptance, not the whole task. Keep full logs accessible and never hide failures.

Without a specialist, handle the affected boundary directly: security work maps protected data, entry points, trust transitions and permissions, then probes relevant abuse cases. Releases identify artifact/environment, preflight dependencies/configuration/migration compatibility, establish health criteria and authorized recovery before mutation, then verify deployment and the observation window. Inspect uncertain operation state before retrying. Application rollback does not authorize destructive data restore; failed release plus successful recovery remains a failed release.

## Bound work and close with evidence

- Advance when evidence is sufficient; do not stop at a plan, research, worker report or stage PASS while authorized work remains. Reopen decisions only for new requirements or contradictory evidence; update affected work without restarting discovery.
- Research needs a decision question and stopping condition. Each repair needs new evidence/hypothesis and a distinguishing check. Stop approaches yielding no new information; suspected flaky checks allow at most two disclosed unchanged retries.
- Count review REWORK across the entire task, companions, workers and resumes. After the second REWORK, allow one final fix-only pass plus verification/review; unresolved mandatory findings mean FAILED. Missing prerequisites mean BLOCKED. Never reset counts through nested workflows.
- Never weaken acceptance, disable checks or omit mandatory work for speed. Separate unrelated failures; seek direction only if their repair expands scope. Continue independent authorized work before reporting a blocker.

Match every acceptance item, including delivery, to current evidence: commands/actions, working directory/environment, outcomes, review coverage and limits. Keep updates and final output concise, without repeating logs or asking to continue authorized work. DONE requires all mandatory acceptance, validation, review and delivery. Otherwise report BLOCKED or FAILED, completed work, affected acceptance and the exact next action. A stage READY/PASS or completed handoff does not complete unfinished implementation. These procedures are not enforced hooks or a guarantee of success.
