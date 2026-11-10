---
name: lean-instructions
description: Create or update repository-root AGENTS.md and CLAUDE.md instructions from verified evidence while preserving existing guidance.
license: MIT
---

# lean-instructions

## Ground rules

- **Standalone.** This standalone skill creates or updates project instructions when requested.
- **Targets.** Use the user's request to determine which root-level files to change; an explicit request for both authorizes both.
- **Existing rules.** Read applicable existing instructions before editing.
- **No prerequisites.** Do not install a workflow or require another skill.

## Input and result

- **Input.** Input is the target repository, requested root instruction files and intended change or proposal.
- **READY.** A proposal concludes READY with concrete text and supporting repository evidence.
- **DONE.** An edit concludes DONE only after checking the final diff, referenced paths and command accuracy; report unexecuted commands as unverified.
- **BLOCKED.** If a required root, material conflict or permission is unresolved, return BLOCKED with the affected file and needed decision.
- **FAILED.** A demonstrated unresolved edit/validation failure is FAILED.
- **Scope.** Neither result includes unrelated application changes.

## Steps

1. **Find the root.** Identify the repository root (for example, with `git rev-parse --show-toplevel`); if it cannot be determined, stop and report the blocker. Inspect existing `AGENTS.md`, `CLAUDE.md` and applicable parent or nested instructions, plus relevant manifests, scripts, CI and documentation. Respect their scope and precedence. Preserve unrelated work and user-authored guidance.
2. **Derive instructions.** Derive concise, actionable instructions from repository evidence and the user's stated preferences. Consider project purpose and structure, development commands, project-specific conventions, validation, constraints and links to relevant detailed guidance; include only what helps this repository, not every category by default. Inspect unfamiliar scripts before running them. Verify commands when safe and useful; label unverified details and omit guesses and secrets. Report test results and other time-sensitive observations in the task report, not as durable project instructions.
3. **Edit root files.** Create or update the requested files only at the repository root, even when invoked from a subdirectory. Treat nested instruction files as context, never as edit targets for this skill. If the user requests a different location, explain this boundary rather than editing there. Keep common guidance consistent across both files while retaining justified Codex- or Claude-specific instructions and existing organization. Aim for roughly 50–150 lines per file when useful, and review files over 200 lines for material that can be condensed or linked; these are guidance, not limits. Never remove useful existing rules merely to meet a length target. Do not replace an entire file or remove a rule merely to make the files match; surface substantive conflicts instead of choosing silently. Do not create additional instruction files or change global configuration without a request.
4. **Review and report.** Review the resulting diff for accuracy, duplication, contradictory instructions and unintended changes. Check referenced paths and commands against available evidence. Report files changed, significant decisions, checks performed and any unresolved or unverified details. A request for a proposal or review alone does not authorize edits.
