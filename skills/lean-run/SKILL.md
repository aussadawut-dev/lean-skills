---
name: lean-run
description: Own an end-to-end implementation request from initial decisions to verified delivery, coordinating available Lean skills without repeated planning or manual handoffs.
license: MIT
---

# lean-run

Carry the request to its authorized destination. Preserve unrelated work and reuse verified context. This skill works alone; companions are optional and no workflow directory is required.

## Settle scope, then act

Batch applicable instructions, contract and relevant source/tests. Record outcome, acceptance, constraints, verification and destination briefly. Use standard procedure depth unless requested; depth does not select model settings. Resolve consequential business rules, permissions, data lifecycle and external contracts; decide reversible details from conventions. Ask only indispensable decisions and continue independent work. Silence is not consent. For broad ambiguity read [exploration](references/exploration.md); skip discovery loops for clear requests.

Implementation authority includes matching preparation and verification. Requested PRs/deployments remain acceptance and need matching authority/tools; finish preparation before necessary final approval. Work grants no extra publishing, spending or provider permissions. Create workflow files only when requested. For an actual pause, handoff or resume of interrupted work read [continuation](references/handoff.md); a fresh reviewer or fully briefed repair alone does not require it.

## Use the smallest complete procedure

Reuse or classify risk LOW/MEDIUM/HIGH and quality STANDARD/HIGH/VERY_HIGH. Security, destructive data and breaking external contracts are HIGH risk. For persistent, concurrent or access-scoped application writes, read [write integrity](references/write-integrity.md) and prove the mechanism before expanding implementation. For single-owner in-memory state, use local staging/rollback and skip storage guidance.

Map public signatures to evidence, including element/key types, copy ownership, failure atomicity and replay where specified. Convert every caller-supplied value, scalars, keys and field names as well as containers, into an owned value of the plain built-in type before validating, comparing, computing with, storing or merging it: a subclass or proxy can override arithmetic, comparison, equality, hashing, string, copying, merging or missing-key behavior. Where a signature accepts such values, include subclasses in the boundary cases. Reproduce representative root causes in one small batch, implement, then cover remaining acceptance. Use shared setup, a reusable state assertion and parameterized boundary cases instead of repeated fixture boilerplate. A full new suite need not run against the broken baseline; use test-first development when requested.

Read each relevant source region once. Use one complete diff plus new-file inspection; do not print full unchanged source and the same diff. Check for a local VCS root once; standalone fixtures need one temporary comparison copy. Keep large source/logs on disk. Expand only for an uncovered requirement, demonstrated failure or concrete hypothesis.

Run affected and required checks on final content and exercise the public journey with important failures. Reuse unchanged passing evidence; inspection, cleanup of comparison copies or writing a completion summary alone does not justify another suite. A check proves only its mapped acceptance; mocks/builds do not prove untested live integration. Record actions, environment, expected/observed results and simulated boundaries. Disclose unavailable access and remaining acceptance.

For assessment-only work, inspect the contract, complete source delta and added tests, then run required checks once and independently probe uncovered risks. For a small source shown fully in a diff, that diff supplies the source read. Inspect test helpers and case tables together; avoid reproducing their complete data matrices in another suite. Do not implement or repair during assessment. Reproduce old failures only to establish a finding or when requested.

## Budget bounded work

In the first working batch execute `python3 /resolved/skill/path/scripts/budget.py`. It reads optional caller-supplied `LEAN_RUN_DEADLINE_UNIX`; UNBOUNDED needs no repeat. When bounded, recheck after the first runnable edit/check and before another investigation. VERIFY means use reserved time for outstanding mandatory checks, focused necessary corrections and a concise result, without speculative work. DEADLINE means report incomplete acceptance immediately. Never convert unfinished checks/findings into PASS to meet a clock. The helper reports time; it neither extends a cap nor terminates work. `LEAN_RUN_PHASE_SECONDS` sets a proportional reserve; explicit `--reserve` overrides it.

## Review and repair

LOW permits acceptance self-check; MEDIUM needs focused correctness/regression review; HIGH needs a fresh independent reviewer. Quality HIGH requires at least MEDIUM review; VERY_HIGH requires HIGH. A reviewer inspects current source and runs independent checks; author conclusions cannot supply independence. Unavailable required independence is BLOCKED.

Start repair from the finding, relevant source and distinguishing reproducer; reuse unchanged contract/runtime evidence. Prove the smallest changed mechanism before expanding tests or replacing a subsystem. Derive boundary/failure classes from acceptance; exhaustive/random sweeps need a concrete gap. Rerun affected/required checks and renew review of changed content; verify integrated worker results. Stop when mandatory coverage and findings are resolved. A finding that is a new equivalent form of an already-repaired boundary shows the mechanism failed: replace the mechanism rather than adding the case. Findings that demand mutually exclusive outcomes need a paired reproducer and a user decision, not a patch toward both.

Count REWORK across the whole task, companions, workers and resumes. After the second REWORK, allow one final fix-only pass plus verification/review; unresolved mandatory findings mean FAILED. Never reset counts in nested workflows. Each repair needs new evidence/hypothesis; abandon approaches yielding none. Suspected flakiness permits at most two disclosed unchanged retries. Never weaken acceptance, disable checks or omit mandatory work for speed. Separate unrelated failures; seek direction only for expanded scope.

## Load procedures when relevant

Load optional companions only for remaining work, passing settled scope and raw evidence. Repository/conventions: `lean-target`, `lean-init`, `lean-instructions`; decisions/research: `lean-scope`, `lean-grill`, `lean-research`; implementation/delegation: `lean-task`, `lean-agents`; review/evidence: `lean-review`, `lean-gate`; security/release: `lean-security`, `lean-release`; requested depth/updates: `lean-effort`, `lean-update`, `lean-model-update`. Missing companions are not blockers; required capabilities can be.

This workflow requests selective delegation when useful or required for independence, subject to host/user restrictions. Keep small work inline; default to one active worker, more only for explicit parallel work. Before dispatch read [delegation](references/delegation.md). One controller owns scope, integration, repair counts and delivery. Relay a known phase deadline to the worker rather than leaving it implicit.

For noisy checks run `python3 /resolved/skill/path/scripts/check.py -- COMMAND ARG...` without reading its implementation. It preserves full logs, returns command status and emits a bounded excerpt. No default timeout; optional `--timeout SECONDS`; `--log NEW_PATH` refuses overwrite. Inspect failures/ambiguous completion until distinct causes are understood. Small bounded checks may run directly; without Python use equivalent capture, without installing a runtime.

## Deliver with evidence

For UI, security or releases read [delivery checks](references/delivery.md). Performance work requires representative measured baseline and optimization authorization; a proposal alone does not authorize benchmarking. Match every acceptance, including delivery, to current evidence and review coverage. DONE requires all mandatory acceptance, verification, review and the authorized destination. Otherwise report BLOCKED/FAILED, completed work, remaining acceptance and the exact next action. A plan, worker report, checkpoint or stage PASS does not finish the task. Keep updates/final concise and continue authorized work without asking to continue. These procedures are not enforced hooks or a guarantee of success.
