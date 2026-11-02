---
name: lean-run
description: Own an end-to-end implementation request from initial decisions to verified delivery, coordinating available Lean skills without repeated planning or manual handoffs.
license: MIT
---

# lean-run

Use this as the controller for a request to carry work through completion. Input is the user's goal, relevant repository/context, existing decisions and requested endpoint. A proposal-only or diagnosis-only request ends with that scoped deliverable. Follow project instructions and the user's authorized scope. This skill works alone: companion skills are optional, and no Lean runtime, workflow directory or installation step is required.

## Establish the delivery agreement

Read the relevant project instructions, existing decisions and closest source before asking questions. Reuse verified repository context and commands while their inputs remain unchanged. Discover only what this task needs.

For a broad or unclear request or materially different directions, explore before settling scope: reflect the goal, draft a few unconfirmed use cases or before/after scenarios and ask whether they match. Offer useful work sizes and trade-offs, then ask small related batches adapted to replies. Number questions or use-case confirmations and label choices a, b, c, etc.; recommend only supported choices with brief reasons and show a copyable suggested reply such as `1a 2b`. Accept codes, natural language and mixed answers. Unanswered choices are not consent; follow up on material omissions. Prefer the host's structured question dialog whenever a suitable tool is available in the current mode; follow its schema and limits, splitting batches when needed. Keep use-case context in chat and make each dialog question self-contained, retaining numbered questions and lettered choices where supported. Include brief recommendation reasons and allow free-text corrections. A preselected recommendation is not a submitted answer. Fall back to numbered, lettered chat questions and copyable replies when no suitable dialog is available; do not claim unsupported input prefilling. Keep agreed items, open decisions and proposals distinct. Recap and ask what is missing before converting exploratory discussion to scope; if something is added, explore its goal and relevant use case, update the recap and ask again until the user says it is complete. Research current external facts with sources when needed for the decision. Skip unnecessary discovery and this confirmation loop for small or clear requests or when the user says to proceed; still ask indispensable material decisions and continue independent work.

State the outcome, included behavior, observable acceptance, constraints, verification method and delivery destination. Keep this to a sentence for a mechanical change. For substantial work, keep a compact record of decisions, remaining work, evidence, blockers and next action in the conversation or an existing project record. Create persistent workflow files only when requested. Use the requested procedure depth; otherwise use standard. Depth changes investigation detail, not acceptance or model settings.

For user-facing work, connect acceptance to the user's goal and relevant usability/accessibility needs, not just successful API calls. Agree meaningful keyboard/focus, feedback, screen-size and loading/empty/error/recovery behavior where affected. For performance work, define a representative workload and measured baseline before choosing an optimization; research/proposal-only requests do not authorize a benchmark.

For an explicit pause/handoff or work resumed across sessions, use [continuation and handoff](references/handoff.md). A requested handoff can be complete while the underlying implementation remains open; report both scopes separately. Do not impose a checkpoint file or restart settled discovery on ordinary short work.

Resolve consequential business rules, permissions, data lifecycle and external-contract choices near the beginning. Batch the necessary questions, explain consequences and recommend an option when evidence supports it. Decide reversible implementation details yourself using project conventions. A clear implementation request already authorizes matching work: do not add an approval round for the plan. Wait for missing material answers before dependent work; elapsed time is not an answer. Continue independent work.

Default to verified changes in the current workspace when no delivery destination is specified. A requested PR, deployment or other destination is part of acceptance and needs matching authorization and tools. Do all authorized preparatory work before any required final approval. Do not infer permission to publish, spend money or change provider settings from the word "end-to-end".

## Route only when useful

Discover which companion skills are actually available and read a selected skill before applying it. Do not load or invoke every skill as a checklist. Pass the settled agreement, relevant decisions, current content, evidence and remaining question; use the result to continue the original request. A stage result is not a reason to ask the user to invoke the next skill.

| Need | Optional companion |
| --- | --- |
| Select a different requested repository | `lean-target` |
| Discover unknown project commands and conventions | `lean-init` |
| Create or update repository-root agent instructions when requested | `lean-instructions` |
| Bound acceptance or resolve material ambiguity | `lean-scope`, `lean-grill` |
| Answer a technical question that affects implementation | `lean-research` |
| Implement and verify the agreed behavior | `lean-task` |
| Delegate useful independent work when authorized and supported | `lean-agents` |
| Review current changes and assess completion evidence | `lean-review`, `lean-gate` |
| Assess or repair a requested security concern or changed trust boundary | `lean-security` |
| Plan or execute an authorized release, recovery or rollback | `lean-release` |
| Apply a requested procedure depth | `lean-effort` |
| Update skills or evaluate model configuration when explicitly requested | `lean-update`, `lean-model-update` |

If a companion is absent, perform the corresponding core procedure below directly. Missing a skill is not a blocker; missing a required capability can be. Keep one owner of scope, integration, repair counts and final delivery, even when workers are used.

## Match delegation to the provider

This workflow requests selective delegation when it materially helps completion or supplies required independent review, subject to user and host restrictions. Finish small work directly when briefing a cold worker and integrating its result would cost more. Default to at most one active worker; an explicit parallel-work request may use more within user, project and runtime limits. Use exclusive file ownership and serialize dependencies.

Classify each delegated task by the work it needs: mechanical lookup/edit, bounded implementation, ordinary implementation/review, or difficult reasoning across security, data or component boundaries. Use the provider's own supported models, effort controls and project conventions; no universal size ladder or cross-provider equivalence is required. Start with the lightest setting supported by evidence for this work. Complex reasoning may justify stronger settings; file count, task length and procedure depth alone do not. Required independent review means a fresh reviewer, not automatically the largest model.

Honor explicit user model/effort first, then an existing project mapping. Otherwise choose a task-local model/effort from verified runtime capabilities and descriptions, using the smallest capable option; do not invent a model catalog, benchmark ranking or persistent configuration. Record task, work classification, selection reason, requested model/effort and context mode before dispatch. Pass model and effort explicitly when supported; use fresh context plus a self-contained brief when overrides require it (Codex spawn_agent uses fork_turns="none"). Report backend settings only when runtime metadata actually exposes them. If selection controls are absent, disclose the known default or unknown setting; do not pretend inheritance is verified workload-based routing. An unavailable explicit or mapped setting must not be silently replaced. If delegation is optional, finish directly when permitted; if a requested setting or independent execution is required, report the unmet requirement.

Name each worker for the user as `<taskname> - <model name>|<effort>`, for example `api_builder - gpt-6.1-sol|medium`. Use the child's requested model/effort, including an explicit `inherit` selector when used; the label does not confirm backend identity. Use `default` for a deliberately omitted setting and `unknown` when it is not known. Do not copy the parent's model or effort into a child label without evidence of inheritance.

Use the current runtime schema to distinguish the display label, reusable agent type and returned instance ID:

- Claude Code: put the full label in `Agent.description` for the task label; keep `subagent_type` pointing to the intended existing agent definition. For a separately launched CLI session, `--name` sets its session title. Do not set `Agent.name` or enable agent teams solely for naming: that can change execution/isolation semantics.
- Antigravity: put the full label in `invoke_subagent.Role`; keep `TypeName` pointing to the intended existing definition. A custom type name alone does not set the role shown for the instance. Do not redefine a reusable agent solely to rename one invocation.
- Codex: when `task_name` allows only lowercase letters, digits and underscores, use a compliant unique ID such as `api_builder_gpt_6_1_sol_medium`. Show the full label in dispatch updates and reports and retain its ID mapping.

Use these fields only when present in the actual tool schema; otherwise use the supported display-name field or the report-label fallback. Pass names as literal structured values or quoted CLI arguments, never as unquoted shell text: `|` must not become a pipeline. Preserve the label-to-ID mapping and address later messages by the returned runtime ID. Verify accepted labels from task/role metadata when exposed; do not infer a native UI rename from the agent repeating the text. For replacement workers update the label and record the new ID without losing task history.

Classify failures before escalating: repair context, implementation or missing tools at their source. Escalate only a demonstrated reasoning limit, one supported effort step, then a more capable available model when justified, within the same provider and authorized billing path. Preserve repair counts across workers; no provider switch, paid API call or parent-session model change is implied. Validate integrated results rather than accepting worker claims.

## Implement and prove the outcome

1. Classify risk as LOW, MEDIUM or HIGH and quality as STANDARD, HIGH or VERY_HIGH, reusing established classifications. Consequential security, destructive data and breaking external-contract changes are HIGH risk. Implement only the work needed for acceptance; do not add adjacent cleanup or features.
   For an unclear fault, capture expected/actual behavior and environment, minimize the reproducer, trace the first failing boundary and compare plausible causes with discriminating probes. Separate a supported cause from a hypothesis or workaround; stop diagnosis at the requested endpoint. Use available logs/traces without exposing sensitive data, and preserve evidence before changes.
2. Add meaningful tests for changed behavior. For a bug, reproduce the regression and verify it passes after repair; disclose when reproduction is unavailable. Run affected checks during iteration and required project checks on the final content. Inspect unfamiliar commands before execution and preserve unrelated work.
3. Exercise the relevant user journey through the integrated components, from its input to an observable result, with important failure cases. For non-UI work use an appropriate interface, such as an API, CLI or artifact consumer. Identify the environment, commands/actions, expected and observed outcomes, and simulated boundaries. Unit tests, builds and mocks alone do not establish an untested live integration. When live access is unavailable, finish useful authorized work and report the unmet acceptance; do not silently replace required end-to-end evidence with a simulation.
4. Review the final diff, including new files, after deterministic validation. LOW permits an acceptance self-check; MEDIUM requires focused correctness/regression review; HIGH requires a fresh independent reviewer. Quality HIGH requires at least MEDIUM review and VERY_HIGH requires HIGH. Required independence without authorized, available tools is BLOCKED, not a self-issued independent PASS.
5. Repair in-scope failures, rerun affected checks and renew review of changed content. Reuse evidence only when its inputs, relevant environment and acceptance are unchanged and project rules allow it. Maintain the requested destination as part of delivery; local success alone does not satisfy an authorized PR or deployment request.

When no specialized companion is available, handle the affected boundary directly: for security, map protected data, entry points, trust transitions and permissions, then verify relevant abuse cases with bounded local probes and evidence-backed findings. For a release, identify the exact artifact and environment, preflight dependencies/configuration and migration compatibility, establish health criteria and an authorized recovery path before mutation, verify deployment and the agreed observation window, and inspect actual state before retrying uncertain operations. Never infer a destructive data restore from permission to roll back application code. A failed release followed by successful recovery remains a failed release with successful recovery, not DONE for shipping the requested revision.

## Keep progress finite

- Advance as soon as the current stage has sufficient evidence. Never stop at a plan, research result, worker report or review PASS when implementation or delivery remains authorized and unfinished.
- Reopen a settled decision only for a new requirement or contradictory evidence. Update the affected acceptance and work; do not restart unrelated discovery. New material decisions may still require a targeted user answer mid-task.
- Research must have a decision question and a stopping condition. Stop when evidence supports the decision, or return the concrete missing fact; do not widen the investigation without a task-relevant reason.
- Each repair attempt must state the new evidence or hypothesis and the check that will distinguish it. Stop repeating an approach that yields no new information. A suspected flaky check permits at most two unchanged retries, disclosed in the result.
- Count review REWORK results across the whole task, including companion calls and resumed work. After the second REWORK, allow one final fix-only pass and its verification/review; if mandatory findings remain, stop with FAILED and the unresolved findings. A missing prerequisite is BLOCKED. Never reset counters by re-invoking a skill or starting a nested workflow.
- Do not weaken acceptance, disable checks or omit mandatory work to claim success. Separate unrelated failures and seek scope direction only when their repair would expand the request. Continue any independent authorized work before reporting a blocker.

## Close with evidence

Match every acceptance item, including delivery, to evidence for the current state. Record commands/actions, working directory or environment, outcomes, review coverage and any limits. Keep progress updates short and tied to changed facts; do not ask "shall I continue?" for already authorized work.

Return DONE only when all mandatory acceptance, validation, review and delivery conditions hold. Return BLOCKED for missing prerequisites and FAILED for demonstrated unresolved failures, identifying affected acceptance, completed work and the exact next action. READY and PASS from a companion describe that stage only. Never call the whole request complete with mandatory work still outstanding. These are agent-run procedures, not enforced hooks or a guarantee of success on every task.
