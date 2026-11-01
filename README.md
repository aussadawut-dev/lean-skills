# Lean Skills

Twelve independent agent skills for scoping, implementation, research, delegation,
review and evidence-backed completion. Install once globally and use in any
project. **No Lean runtime, Python CLI, `.lean` directory, hooks or companion
skills are needed.** Each folder includes its own instructions and MIT license.

Adapted from [Lean Workflow Agent by ASDW](https://github.com/aussadawut-dev/lean-workflow-agent-by-asdw).
This repository distributes the skills-only edition; it does not install the
original workflow or provide its automatic enforcement.

## Install once

Requires Node.js/npm for `npx` and your agent installed separately. Use the
[Skills CLI](https://github.com/vercel-labs/skills) to install all twelve globally
for Codex, Claude Code and Antigravity:

```sh
npx skills add aussadawut-dev/lean-skills -g --skill '*' -a codex claude-code antigravity -y
```

Keep only the agents you use in `-a`. Omit `-a` and `-y` for interactive selection.
Quote `'*'` so your shell does not expand it. Global installation affects future
projects; it does not copy workflow files into them. Restart/reload your agent's
skill discovery if the new skills do not appear in an existing session.

Install just one skill, independently:

```sh
npx skills add aussadawut-dev/lean-skills -g --skill lean-review -a codex -y
```

Inspect available skills without installing:

```sh
npx skills add aussadawut-dev/lean-skills --list
```

These remote commands use the published default branch. Before this change is
merged/pushed there, test the checkout locally instead:

```sh
npx skills add ./ -g --skill '*' -a codex claude-code antigravity -y
```

Installation may replace same-named global skills. Check existing `lean-*` skills
and preserve local edits before installing. This collection deliberately retains
the original skill names; project-local skills with those names can also affect
which edition your agent discovers.

## Use

In Codex, invoke `$lean-task Add pagination with tests`; in Claude Code, use
`/lean-task Add pagination with tests`. In other compatible agents, ask to use
`lean-task` by name. Each skill can also be discovered by its description.

| Skill | What it does independently |
| --- | --- |
| [lean-init](skills/lean-init/SKILL.md) | Discover project commands and agree how to work; no scaffold installation |
| [lean-task](skills/lean-task/SKILL.md) | Scope, implement, test, review and finish against acceptance |
| [lean-scope](skills/lean-scope/SKILL.md) | Bound the work and define observable acceptance |
| [lean-research](skills/lean-research/SKILL.md) | Compare options with traceable evidence |
| [lean-grill](skills/lean-grill/SKILL.md) | Resolve consequential gaps in a requirement or plan |
| [lean-agents](skills/lean-agents/SKILL.md) | Delegate with ownership and integration checks when tools are available |
| [lean-review](skills/lean-review/SKILL.md) | Review the shipping diff at the required depth |
| [lean-gate](skills/lean-gate/SKILL.md) | Assess completion using actual project checks and review evidence |
| [lean-effort](skills/lean-effort/SKILL.md) | Set conversation-level procedure depth, not model reasoning effort |
| [lean-model-update](skills/lean-model-update/SKILL.md) | Research/evaluate models and propose an approved configuration change |
| [lean-target](skills/lean-target/SKILL.md) | Select or clone a separate application repository |
| [lean-update](skills/lean-update/SKILL.md) | Preview and update installed standalone skills, preserving local edits |

## Boundaries

- Skills are instructions executed by the host agent, not background processes or
  permission controls. Quality gates and review are agent-run assessments, not
  automatic Stop hooks or signed receipts.
- Your project's instructions and your explicit request remain authoritative.
  Skills use existing project tools and records; none requires another skill.
- Procedure preferences and selected targets stay in the conversation unless you
  request persistence. There is no global model registry, task queue or lease system.
- Delegation and model evaluations require host capabilities and authorization.
  No benchmark bank is bundled. Missing tools or required independent review are
  reported as limitations/blockers rather than silently simulated.
- Installing skills does not authorize commits, pushes, deployments, paid APIs or
  changes to provider permissions. Update only the skills you intend to replace.

## Validate this repository

The offline check uses Python's standard library. The installation smoke test
uses `skills@1.7.4` through `npx` (registry access or an existing cache is needed).
It installs all twelve together and each one alone for the three supported agents
into temporary homes, verifies installed content and ensures an empty project
stays untouched. It does not modify your real global skills or call an LLM.

```sh
python3 -m unittest discover -s tests -v
python3 tests/install_smoke.py
```

CI runs both checks. These tests verify packaging and installation, not guaranteed
agent behavior; semantic review of the instructions is also necessary.

MIT licensed. Keep the license when redistributing a skill independently.
