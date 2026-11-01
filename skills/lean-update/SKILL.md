---
name: lean-update
description: Update Lean skills and install missing skills from the collection while preserving local changes and installation scope.
license: MIT
---

# lean-update

Standalone skill: use the current request or explicit arguments. Read applicable project instructions and only task-relevant context. No Lean installation, CLI, configuration or companion skill is required; do not install a workflow or create workflow files as prerequisites. Existing project rules apply.

Use requested procedure depth, or standard by default. High adds relevant boundary cases and stronger evidence; ultra adds cross-part consistency and contradictory evidence where relevant. Depth does not change model reasoning settings. Keep decisions in conversation unless a suitable project record exists or the user requests persistence.

This updates skills, not a project runtime. Source: https://github.com/aussadawut-dev/lean-skills. It works when only this skill is installed.

1. Inspect which standalone skills are installed, their source/version metadata, installation scope and agent discovery links. Resolve symlinks to canonical locations. Do not confuse project-local workflow skills or similarly named skills from another source with this collection.
2. Read the installed skills CLI help and current upstream documentation. Fetch the source into a temporary directory and pin its revision. For a request to update the Lean collection, compare the full upstream skill inventory with the installed collection in the same scope: update installed skills and identify missing upstream skills to install, including skills added since the last installation. Missing does not prove newly added; report it as missing when history is unavailable. A request naming specific skills limits changes to those names; install a named missing upstream skill if requested. Do not infer authorization to fill the collection from a request to update only named skills.
3. Show the concrete update plan, including additions, updates, conflicts, source revision, destination, agent links and preserved files. A preview-only request stops here. An explicit collection update authorizes conflict-free additions and updates in the existing scope; do not install into another scope or modify unrelated skills. If the same collection exists in multiple scopes and the intended scope is unclear, ask which to update. Keep locally modified skills and colliding destinations unchanged until the user chooses how to resolve them; continue independent conflict-free work.
4. Back up affected existing canonical directories and relevant installation metadata before replacement, recording a usable restore path and which paths are new. Use the installer only when it supports the intended scope, agents and pinned revision without changing unrelated skills or overwriting conflicts. If pinning, backup or the destination cannot be verified, stop before the affected mutation and explain the missing capability. Ensure resulting installation metadata identifies a usable source for future updates: do not leave it pointing to a temporary snapshot that will be removed. If the installer records a local snapshot as the source, retain that snapshot and record its pinned revision and location, or use a supported durable source. If this cannot be assured, stop before mutation. Do not replace an existing unrelated skill or change global configuration as a side effect.
5. Validate all affected skills' frontmatter, file completeness, references, metadata and discovery links, including newly installed skills. On failure restore backups or remove newly created paths only if they have not changed since this operation; otherwise preserve state and report the conflict. Report added and updated skills, revision, scope, checks, conflicts and rollback location.

Do not install a project workflow, commit, push or alter model/provider permissions as an incidental update step.
