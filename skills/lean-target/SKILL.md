---
name: lean-target
description: Select or add a separate application repository for work, preserving its own Git history and project instructions.
license: MIT
---

# lean-target

This is a standalone skill. Use the current request or explicit invocation arguments as input. Read existing project instructions and only the context needed for this task. No Lean installation, CLI, configuration, or other skill is required. Do not install a workflow or create workflow files as a prerequisite. Existing project rules still apply.

Use the user's requested procedure depth; otherwise use standard depth. High adds boundary cases and stronger evidence; ultra adds cross-part consistency and contradictory evidence where relevant. Depth does not change model reasoning settings. Keep decisions in the conversation unless the project already has a suitable record or the user requests persistence.

Accept an existing path or remote URL. Reuse an explicitly requested destination. Without a specified layout, prefer a separate clone; use a submodule only when the user or project explicitly wants parent-repository tracking.

1. Inspect current repository, requested target, existing checkout and Git status. Read the target's own instructions before work. Reject ambiguous destinations, credentials embedded in URLs, collisions and unexpected symlink boundaries. Pass URLs/paths as literal arguments, not interpolated shell code.
2. Reuse an existing matching checkout without resetting, cleaning or moving its branch. For an authorized new clone, choose a non-conflicting destination and run Git clone. For an explicitly requested submodule, inspect pending .gitmodules changes, then add only that target. Never update other gitlinks or remove Git metadata to repair a partial failure.
3. Record the target's absolute path, remote, branch and commit in the conversation. Keep all application commands, edits and Git operations rooted there. Keep work coordination in the conversation or an agreed existing record; do not install workflow files in the application.
4. Discover build/test commands from target evidence and verify the requested setup. Cloning success is not application validation. Report both statuses for a submodule, pending changes, command outcomes and missing checks. Resolve partial failures from observed state before retrying.
5. Selection lasts for this conversation; it is not a persistent CLI registry. Do not commit, push or implement unrelated application work unless requested. Stop when the requested target is ready or a concrete blocker is reported.
