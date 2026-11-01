---
name: lean-scope
description: Turn a non-trivial request into bounded scope and observable acceptance, without requiring a separate workflow.
license: MIT
---

# lean-scope

This is a standalone skill. Use the current request or explicit invocation arguments as input. Read existing project instructions and only the context needed for this task. No Lean installation, CLI, configuration, or other skill is required. Do not install a workflow or create workflow files as a prerequisite. Existing project rules still apply.

Use the user's requested procedure depth; otherwise use standard depth. High adds boundary cases and stronger evidence; ultra adds cross-part consistency and contradictory evidence where relevant. Depth does not change model reasoning settings. Keep decisions in the conversation unless the project already has a suitable record or the user requests persistence.

1. Read the request, closest source files and existing decisions. Reuse settled choices. Skip a formal specification for trivial mechanical work unless requested.
2. Reuse an existing delivery agreement rather than generating a second specification. Include the verification method and delivery destination (workspace by default, or the requested PR/deployment). State the goal, included behavior, exclusions, acceptance criteria, constraints, assumptions and likely affected components. For multi-part work, list bounded tasks and dependencies; do not silently expand into adjacent improvements.
3. Distinguish reversible implementation choices from unresolved material decisions about security, ownership, business rules, data lifecycle or external contracts. Ask only for decisions that change the result, explaining the options and their consequences.
4. A clear implementation request already approves matching scope: present it and continue. A specification-only request stops at the specification. Wait for missing material decisions or approval explicitly required by project instructions; elapsed time is not approval.
5. When called within an implementation workflow, return the agreed scope and unresolved decisions to its controller; a scope result does not complete that implementation request. Keep scope current as requirements arrive. Record replacements instead of quietly dropping acceptance items. Material expansions need a user decision before dependent work. At completion, map each acceptance item to evidence and disclose deferred work.

At high depth, cover actors, normal flows, boundaries and recovery. At ultra depth, check states, cross-feature interactions and rollout/rollback constraints where relevant. Stop when acceptance is observable and remaining uncertainty is explicit.
