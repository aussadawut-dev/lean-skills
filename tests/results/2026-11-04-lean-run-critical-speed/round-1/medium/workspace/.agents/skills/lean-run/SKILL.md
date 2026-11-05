---
name: lean-run
description: Own an end-to-end implementation request from initial decisions to verified delivery, coordinating available Lean skills without repeated planning or manual handoffs.
license: MIT
---

# lean-run

Carry the request through its authorized endpoint. Follow project instructions, preserve unrelated work and reuse verified context. This skill works alone; companions are optional and no Lean runtime or workflow directory is required.

## Settle scope, then act

Read applicable instructions and the nearest relevant source/tests in one focused pass. Record outcome, observable acceptance, constraints, verification and destination; a sentence suffices for a bounded change. Use standard procedure depth unless requested otherwise; depth does not select model settings. For broad ambiguity read [exploration](references/exploration.md); skip discovery loops for clear requests or an instruction to proceed. Ask only indispensable missing decisions and continue independent work. Silence is not consent.

Resolve consequential business rules, permissions, data lifecycle and external contracts before implementation. Decide reversible details from project conventions. Implementation authorization includes matching preparation and verification without another plan approval. Requested PRs/deployments remain acceptance and require matching authority/tools; finish preparation before any necessary final approval. End-to-end work grants no extra publishing, spending or provider permissions. Create workflow files only when requested. On pause, handoff or cross-session resume read [continuation](references/handoff.md).

## Use the smallest complete procedure

Reuse or classify risk as LOW/MEDIUM/HIGH and quality as STANDARD/HIGH/VERY_HIGH. Consequential security, destructive data and breaking external contracts are HIGH risk. For persistent, concurrent or access-scoped **application data** writes, use [write integrity](references/write-integrity.md) to select and verify one mechanism before expanding implementation or review.

For a bounded implementation, settle a short requirement-to-evidence map and make the smallest complete edit. Prefer verified project/library primitives. Reproduce a fault with one targeted batch before repair; a full baseline suite is useful only when required or needed to locate it. Write compact checks for actual gaps. Use test-first development when requested; ordinary work does not require building a comprehensive new suite before the edit. Expand investigation for a demonstrated failure or unresolved requirement.

After the edit, run affected and required checks on final content, exercise the relevant public journey with important failures, and review the complete diff including new files. Reuse passing evidence whose inputs and relevant environment remain unchanged. Do not repeat whole suites to confirm a clear completion summary. A check proves only its mapped acceptance; unit tests, builds and mocks do not establish an untested live integration. Record actions, environment, expected/observed results and simulated boundaries. Disclose unavailable reproduction or live access and report remaining acceptance.

Use existing VCS diffs when available. Otherwise save one temporary copy of files before editing and compare with it; inspect added files separately. Keep source on disk: do not print base64/serialized copies merely to reconstruct a later diff. Read a source once, then changed sections. Batch independent reads/checks and serialize dependent work.

For **assessment-only** work, inspect contract, current source/diff and tests; run required checks once, then independently probe remaining boundary/failure risks through the public interface. Do not recreate a comprehensive suite or alternative implementation when inspected source and verified tests establish the behavior. Expand for a concrete gap or contradiction. Reproduce old failures only to establish a finding or when requested. Assessment does not authorize implementation or delivery.

## Review and repair

LOW permits an acceptance self-check; MEDIUM needs focused correctness/regression review; HIGH needs a fresh independent reviewer. Quality HIGH requires at least MEDIUM review; VERY_HIGH requires HIGH. A reviewer inspects current source and runs independent checks; author conclusions cannot supply independence. Unavailable required independence is BLOCKED.

Derive equivalence classes and boundary/failure cases from acceptance. Extend to exhaustive/random sweeps only for an identified gap or hypothesis; case count alone is not evidence. Repair demonstrated in-scope failures, rerun affected checks and renew review of changed content. Verify integrated worker results. Stop once mandatory coverage and findings are resolved.

Count review REWORK across the entire task, companions, workers and resumes. After the second REWORK, allow one final fix-only pass plus verification/review; unresolved mandatory findings mean FAILED. Never reset counts through nested workflows. Each repair needs new evidence/hypothesis and a distinguishing check; abandon approaches yielding no new information. Suspected flaky checks permit at most two disclosed unchanged retries. Never weaken acceptance, disable checks or omit mandatory work for speed. Separate unrelated failures and seek direction only if repairing them expands scope.

## Load procedures only when useful

Read an available companion only when its procedure helps the remaining work; pass settled scope and relevant raw evidence. If absent, perform the core procedure here. Missing a skill is not a blocker; a required capability can be.

| Need | Optional companion |
| --- | --- |
| Repository, conventions, agent instructions | `lean-target`, `lean-init`, `lean-instructions` |
| Scope, decisions, research | `lean-scope`, `lean-grill`, `lean-research` |
| Implementation, useful delegation | `lean-task`, `lean-agents` |
| Review, completion evidence | `lean-review`, `lean-gate` |
| Security, authorized release/recovery | `lean-security`, `lean-release` |
| Requested depth or skill/model update | `lean-effort`, `lean-update`, `lean-model-update` |

This workflow requests selective delegation when useful or required for independence, subject to host/user restrictions. Keep small work inline; default to one active worker, with more only for explicit parallel work. Before dispatch read [delegation](references/delegation.md). One controller owns scope, integration, repair counts and delivery.

For noisy suites or expected failures, execute the bundled [check runner](scripts/check.py): `python3 /resolved/skill/path/scripts/check.py -- COMMAND ARG...`. It retains full stdout/stderr, returns the command exit status and emits a bounded excerpt. No default timeout; optional `--timeout SECONDS`; `--log NEW_PATH` refuses overwrite. Execute it without reading its implementation unless debugging/changing it. Small bounded checks can run directly. If Python is unavailable, use equivalent host capture without installing a runtime. Inspect saved logs for failures or ambiguous completion until distinct causes are understood; keep full logs accessible and never hide failures.

## Deliver with evidence

For user-facing work include affected accessibility, keyboard/focus, screen sizes and loading/empty/error/recovery states. Performance work needs a representative workload and measured baseline before optimization; a proposal alone does not authorize benchmarking. Security work maps protected data, entry points, trust transitions and permissions, then probes relevant abuse cases. Releases check artifact/environment, dependencies/configuration/migration compatibility, health criteria and authorized recovery before mutation; verify deployment and observation. Inspect uncertain state before retrying. Application rollback grants no destructive data-restore authority; a failed release followed by recovery remains a failed release.

Advance when evidence is sufficient and reopen decisions only for new requirements or contradictions. Match every acceptance item, including delivery, to current commands/actions and outcomes, review coverage and limits. DONE requires all mandatory acceptance, verification, review and the authorized destination. Otherwise report BLOCKED or FAILED, completed work, affected acceptance and the exact next action. A plan, worker report or stage PASS does not complete unfinished work. Keep updates/final concise; do not ask to continue authorized work. These procedures are not enforced hooks or a guarantee of success.
