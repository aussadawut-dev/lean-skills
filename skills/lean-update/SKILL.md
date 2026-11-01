---
name: lean-update
description: Update installed standalone Lean skills from their source while preserving local customizations and installation scope.
license: MIT
---

# lean-update

This is a standalone skill. Use the current request or explicit invocation arguments as input. Read existing project instructions and only the context needed for this task. No Lean installation, CLI, configuration, or other skill is required. Do not install a workflow or create workflow files as a prerequisite. Existing project rules still apply.

Use the user's requested procedure depth; otherwise use standard depth. High adds boundary cases and stronger evidence; ultra adds cross-part consistency and contradictory evidence where relevant. Depth does not change model reasoning settings. Keep decisions in the conversation unless the project already has a suitable record or the user requests persistence.

This updates skills, not a project runtime. Source: https://github.com/aussadawut-dev/lean-skills. It works when only this skill is installed.

1. Inspect which standalone skills are actually installed, their source/version metadata and installation scope. Resolve symlinks to canonical locations. Do not assume every core skill is installed or confuse project-local workflow skills with this standalone collection.
2. Read the installed skills CLI help and current upstream documentation before choosing commands. Fetch candidate content into a temporary directory without replacing the installed copy. Pin the candidate revision and compare only the requested installed skills; note local customizations and missing source/version evidence.
3. Show the concrete update plan, conflicts, source revision and preserved files. Keep modified skills unchanged until the user chooses how to handle the conflict. A preview-only request stops here; an explicit update request authorizes a matching conflict-free update, not installing extra skills or changing project configuration.
4. Back up each affected canonical directory and its installation metadata before replacement, recording a usable restore path. Use the existing installer when it supports the intended scope and pinned revision. Do not use a bulk update that also changes unrelated skills. If pinning or backup cannot be verified, stop before mutation and explain the missing capability.
5. Validate installed frontmatter, file completeness, references and discovery links. Restore from the backup on a failed update only while affected files have not changed since this operation; otherwise preserve state and report the conflict. Report updated skills, revision, checks, preserved changes and rollback location.

Never install the full workflow as part of a skill update. Do not commit, push or alter model/provider permissions as an incidental update step.
