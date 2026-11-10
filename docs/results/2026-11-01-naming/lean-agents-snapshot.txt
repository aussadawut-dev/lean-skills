---
name: lean-agents
description: Delegate bounded independent tasks to available agents, with explicit ownership, concurrency limits and integration checks.
license: MIT
---

# lean-agents

This is a standalone skill. Use the current request or explicit invocation arguments as input. Read existing project instructions and only the context needed for this task. No Lean installation, CLI, configuration, or other skill is required. Do not install a workflow or create workflow files as a prerequisite. Existing project rules still apply.

Use the user's requested procedure depth; otherwise use standard depth. High adds boundary cases and stronger evidence; ultra adds cross-part consistency and contradictory evidence where relevant. Depth does not change model reasoning settings. Keep decisions in the conversation unless the project already has a suitable record or the user requests persistence.

Invocation requests delegation for the supplied task. An explicit model and xN mean up to N simultaneous workers using that model where supported; N is a ceiling, not a quota. Without a count, use only useful independent parallel tasks and obey runtime and project limits.

1. Split work into bounded tasks with acceptance checks, dependencies and exclusive file ownership. Keep planning, integration and final validation with the controller. If tasks overlap, serialize them or isolate worktrees. Show the assignment plan before dispatch.
2. Classify each task, including reviewers, by the work described below. Resolve its model and reasoning effort from the user's explicit choice, then an existing project mapping, otherwise verified runtime capabilities. Without a mapping, choose the smallest supported model/effort suited to the task using runtime descriptions and available evidence; record this as a task-local choice, not a benchmark result. Do not require a new model configuration or launch evaluations as a prerequisite. Never invent availability or silently substitute an explicitly requested model or a mapped setting that is unavailable.
3. Pass each worker the task, relevant instructions, owned files, acceptance and minimum necessary context. Give independent reviewers a fresh context containing requirements and the shipping diff, not the author's conclusions. Do not bypass permissions or silently start metered API work.
4. Before dispatch record task, work classification, selection reason, requested model/effort and context mode. Pass both model and effort explicitly when the tool supports them; for a tool requiring fresh context for overrides, use that mode with a self-contained brief (Codex spawn_agent uses fork_turns="none"). If controls are absent, disclose the limitation and known default, or mark it unknown; do not claim workload-based routing occurred. Honor explicit settings rather than silently falling back. Record actual backend settings only when returned by runtime metadata, not from a worker's self-identification or a UI banner. Monitor blockers, resolve ownership conflicts and integrate only reviewed worker changes. Never reset or overwrite another worker's uncommitted work.
5. Validate the integrated final state with project checks and review against acceptance. Worker claims alone are not evidence. Report assignments, results, checks and remaining blockers.

If no delegation tools exist, report the limitation. Continue directly only when delegation is optional; a request requiring independent or parallel execution remains BLOCKED until that requirement can be met or changed by the user.

## Worker names

Name each worker for the user as `<taskname> - <model name>|<effort>`, for example `api_builder - gpt-6.1-sol|medium`. Use the child's requested model/effort, including an explicit `inherit` selector when used; the label does not confirm backend identity. Use `default` for a deliberately omitted setting and `unknown` when it is not known. Do not copy the parent's model or effort into a child label without evidence of inheritance.

Use the current runtime schema to distinguish the display label, reusable agent type and returned instance ID:

- Claude Code: put the full label in `Agent.description` for the task label; keep `subagent_type` pointing to the intended existing agent definition. For a separately launched CLI session, `--name` sets its session title. Do not set `Agent.name` or enable agent teams solely for naming: that can change execution/isolation semantics.
- Antigravity: put the full label in `invoke_subagent.Role`; keep `TypeName` pointing to the intended existing definition. A custom type name alone does not set the role shown for the instance. Do not redefine a reusable agent solely to rename one invocation.
- Codex: when `task_name` allows only lowercase letters, digits and underscores, use a compliant unique ID such as `api_builder_gpt_6_1_sol_medium`. Show the full label in dispatch updates and reports and retain its ID mapping.

Use these fields only when present in the actual tool schema; otherwise use the supported display-name field or the report-label fallback. Pass names as literal structured values or quoted CLI arguments, never as unquoted shell text: `|` must not become a pipeline. Preserve the label-to-ID mapping and address later messages by the returned runtime ID. Verify accepted labels from task/role metadata when exposed; do not infer a native UI rename from the agent repeating the text. For replacement workers update the label and record the new ID without losing task history.

## Provider-aware selection and escalation

Use the provider's own model families, supported effort controls and existing project conventions. Do not require a universal size ladder or assume that similarly named tiers across providers are equivalent.

| Work | Selection guidance |
| --- | --- |
| Lookup or mechanical edit | Lightweight supported option; low effort when available |
| Small, well-specified implementation | Coding-capable option with modest effort |
| Ordinary implementation or focused review | General coding/reasoning option with enough effort for the dependencies |
| Conflicting evidence, entangled behavior, complex security/data boundaries | Stronger reasoning when justified by the actual uncertainty |

Use runtime descriptions and relevant observed results; label unbenchmarked selections as task-local judgments. File count and duration alone do not determine difficulty. Quality and risk set review requirements, not an automatic demand for the largest model. Keep procedure depth separate from reasoning effort. Prefer doing small work directly when a cold worker plus integration would cost more; do not split work merely to fill concurrency slots.

Classify a failure before escalating: fix missing context, implementation, tools or permissions at their source. For demonstrated reasoning limits, raise one supported effort step, then choose a more capable available model if justified, changing one variable at a time. Keep the same provider and authorized billing path; do not switch providers, use paid API credentials or alter host settings implicitly. Respect the controller's existing repair budget across replacements. If no available setting can meet the requirement, report the concrete blocker. Never claim to change the active parent session's model.
