# Provider-aware delegation

Read before dispatching a worker. The controller retains scope, integration, task-wide repair counts and delivery.

## When to delegate

- **Selective use.** This workflow requests selective delegation when it materially helps completion or supplies required independent review, subject to user and host restrictions.
- **Small work inline.** Finish small work directly when briefing a cold worker and integrating its result would cost more.
- **Worker count.** Default to at most one active worker; an explicit parallel-work request may use more within user, project and runtime limits. Use exclusive file ownership and serialize dependencies.

## Model and effort

- **Classify the work.** Classify each delegated task by the work it needs: mechanical lookup/edit, bounded implementation, ordinary implementation/review, or difficult reasoning across security, data or component boundaries. Use the provider's own supported models, effort controls and project conventions; no universal size ladder or cross-provider equivalence is required.
- **Start light.** Start with the lightest setting supported by evidence for this work. Complex reasoning may justify stronger settings; file count, task length and procedure depth alone do not. Required independent review means a fresh reviewer, not automatically the largest model.
- **Precedence.** Honor explicit user model/effort first, then an existing project mapping. Otherwise choose a task-local model/effort from verified runtime capabilities and descriptions, using the smallest capable option; do not invent a model catalog, benchmark ranking or persistent configuration.
- **Record and pass.** Record task, work classification, selection reason, requested model/effort and context mode before dispatch. Pass model and effort explicitly when supported; use fresh context plus a self-contained brief when overrides require it (Codex spawn_agent uses fork_turns="none").
- **Disclose settings.** Report backend settings only when runtime metadata actually exposes them. If selection controls are absent, disclose the known default or unknown setting; do not pretend inheritance is verified workload-based routing.
- **Unavailable settings.** An unavailable explicit or mapped setting must not be silently replaced. If delegation is optional, finish directly when permitted; if a requested setting or independent execution is required, report the unmet requirement.

## Worker names

Name each worker for the user as `<taskname> - <model name>|<effort>`, for example `api_builder - gpt-6.1-sol|medium`. Use the child's requested model/effort, including an explicit `inherit` selector when used; the label does not confirm backend identity. Use `default` for a deliberately omitted setting and `unknown` when it is not known. Do not copy the parent's model or effort into a child label without evidence of inheritance.

Use the current runtime schema to distinguish the display label, reusable agent type and returned instance ID:

- Claude Code: put the full label in `Agent.description` for the task label; keep `subagent_type` pointing to the intended existing agent definition. For a separately launched CLI session, `--name` sets its session title. Do not set `Agent.name` or enable agent teams solely for naming: that can change execution/isolation semantics.
- Antigravity: put the full label in `invoke_subagent.Role`; keep `TypeName` pointing to the intended existing definition. A custom type name alone does not set the role shown for the instance. Do not redefine a reusable agent solely to rename one invocation.
- Codex: when `task_name` allows only lowercase letters, digits and underscores, use a compliant unique ID such as `api_builder_gpt_6_1_sol_medium`. Show the full label in dispatch updates and reports and retain its ID mapping.

Use these fields only when present in the actual tool schema; otherwise use the supported display-name field or the report-label fallback. Pass names as literal structured values or quoted CLI arguments, never as unquoted shell text: `|` must not become a pipeline. Preserve the label-to-ID mapping and address later messages by the returned runtime ID. Verify accepted labels from task/role metadata when exposed; do not infer a native UI rename from the agent repeating the text. For replacement workers update the label and record the new ID without losing task history.

## Failures and escalation

Classify failures before escalating: repair context, implementation or missing tools at their source. Escalate only a demonstrated reasoning limit, one supported effort step, then a more capable available model when justified, within the same provider and authorized billing path. Preserve repair counts across workers; no provider switch, paid API call or parent-session model change is implied. Validate integrated results rather than accepting worker claims.

