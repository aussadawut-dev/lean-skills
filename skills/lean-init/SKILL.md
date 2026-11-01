---
name: lean-init
description: Discover project commands and establish a lightweight working agreement without installing a workflow.
license: MIT
---

# lean-init

This is a standalone skill. Use the current request or explicit invocation arguments as input. Read existing project instructions and only the context needed for this task. No Lean installation, CLI, configuration, or other skill is required. Do not install a workflow or create workflow files as a prerequisite. Existing project rules still apply.

Use the user's requested procedure depth; otherwise use standard depth. High adds boundary cases and stronger evidence; ultra adds cross-part consistency and contradictory evidence where relevant. Depth does not change model reasoning settings. Keep decisions in the conversation unless the project already has a suitable record or the user requests persistence.

1. Inspect project instructions, manifests, test configuration, CI and the relevant documentation. Identify the actual project root, languages, entry points and existing work records; leave unknown facts explicitly unknown.
2. Identify safe build, lint, type-check and test commands from repository evidence. Inspect unfamiliar scripts before running them. Run the relevant fast checks and record results; do not invent passing checks for missing tooling.
3. Reuse the user's workflow preferences. Otherwise start with direct work and conversation records. Ask only about choices that affect this task; do not require a mode-selection questionnaire.
4. Agree how acceptance, validation and review will be reported. Small changes need a short acceptance statement; consequential changes need a bounded plan, meaningful tests and review of the final diff. Use independent review when project rules or risk require it, and disclose unavailable review.
5. Report the project map, verified commands, current failures, working agreement and next action. This is discovery, not application implementation. Write project documentation only when requested; preserve existing instructions and unrelated files.
