---
name: lean-target
description: Select or add a separate application repository for work, preserving its own Git history and project instructions.
license: MIT
---

# lean-target

Standalone skill: use the current request or explicit arguments. Read applicable project instructions and only task-relevant context. No Lean installation, CLI, configuration or companion skill is required; do not install a workflow or create workflow files as prerequisites. Existing project rules apply.

Use requested procedure depth, or standard by default. High adds relevant boundary cases and stronger evidence; ultra adds cross-part consistency and contradictory evidence where relevant. Depth does not change model reasoning settings. Keep decisions in conversation unless a suitable project record exists or the user requests persistence.

Accept an existing path or remote URL. Reuse an explicitly requested destination. Without a specified layout, prefer a separate clone; use a submodule only when the user or project explicitly wants parent-repository tracking.

DONE means the requested selection/clone and any explicitly requested setup are verified at the reported path; give repository identity, branch/commit (or unborn state), dirty state, relevant instructions and checks. Selection alone does not require application changes or a passing application build. Return BLOCKED for ambiguous identity/destination, missing access or an unsafe collision, and FAILED for an unresolved executed setup failure. Report partial state before a retry, including whether an operation ran or its outcome is uncertain; never erase it to simulate a clean start.

1. Inspect current repository, requested target, existing checkout and Git status. Read the target's own instructions before work. Reject ambiguous destinations, credentials embedded in URLs, collisions and unexpected symlink boundaries. Pass URLs/paths as literal arguments, not interpolated shell code.
2. Reuse an existing matching checkout without resetting, cleaning or moving its branch. For an authorized new clone, choose a non-conflicting destination and run Git clone. For an explicitly requested submodule, inspect pending .gitmodules changes, then add only that target. Never update other gitlinks or remove Git metadata to repair a partial failure.
3. Record the target's absolute path, remote, branch and commit in the conversation. Keep all application commands, edits and Git operations rooted there. Keep work coordination in the conversation or an agreed existing record; do not install workflow files in the application.
4. Discover build/test commands from target evidence and verify the requested setup. Cloning success is not application validation. Report both statuses for a submodule, pending changes, command outcomes and missing checks. Resolve partial failures from observed state before retrying.
5. Selection lasts for this conversation; it is not a persistent CLI registry. Do not commit, push or implement unrelated application work unless requested. Stop when the requested target is ready or a concrete blocker is reported.
