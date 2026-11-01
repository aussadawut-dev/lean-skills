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
2. Select available models and efforts from verified runtime capabilities and user preferences. Never invent model availability or silently substitute an explicitly requested model. Report unsupported settings; use inherited settings only when no explicit choice requires otherwise.
3. Pass each worker the task, relevant instructions, owned files, acceptance and minimum necessary context. Give independent reviewers a fresh context containing requirements and the shipping diff, not the author's conclusions. Do not bypass permissions or silently start metered API work.
4. Record requested and actual runtime settings when observable. Monitor blockers, resolve ownership conflicts and integrate only reviewed worker changes. Never reset or overwrite another worker's uncommitted work.
5. Validate the integrated final state with project checks and review against acceptance. Worker claims alone are not evidence. Report assignments, results, checks and remaining blockers.

If no delegation tools exist, report the limitation. Continue directly only when delegation is optional; a request requiring independent or parallel execution remains BLOCKED until that requirement can be met or changed by the user.
