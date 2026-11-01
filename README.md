# Lean Skills

**English** | [ภาษาไทย](README.th.md)

12 independent skills that help coding agents plan, build, test and review work.
Install all of them or pick just one. **No Lean runtime or `.lean` directory is required.**

Works with **Codex, Claude Code and Antigravity** through the
[Skills CLI](https://github.com/vercel-labs/skills).

## Quick start

You need Node.js/npm (`npx`) and your coding agent installed.
Choose where you want the skills:

| Installation | Use it when | Option |
| --- | --- | --- |
| Global | You want skills available across projects | Add `-g` |
| Project | You want skills only in the current project | Omit `-g` |

### Install for all projects

```sh
npx skills add aussadawut-dev/lean-skills -g --skill '*' -a codex claude-code antigravity -y
```

### Install for one project

Run from your project's root:

```sh
npx skills add aussadawut-dev/lean-skills --skill '*' -a codex claude-code antigravity -y
```

### Install just one skill

For example, install `lean-review` for Codex in the current project:

```sh
npx skills add aussadawut-dev/lean-skills --skill lean-review -a codex -y
```

Add `-g` to make this global. Every skill works independently.

### Adjust the command

- Keep only the agents you use after `-a`.
- `--skill '*'` selects all 12 skills; keep the quotes around `'*'`.
- `-y` skips confirmation prompts. Omit both `-a` and `-y` to choose agents interactively.
- To list available skills without installing, run:

```sh
npx skills add aussadawut-dev/lean-skills --list
```

Global installation leaves your project untouched. Project installation creates
local skill folders and discovery links, such as `.agents/skills/` and
`.claude/skills/`, plus installer metadata where applicable. It leaves global
skills unchanged. Review the generated files with `git status`; commit them to
share with your team, or ignore them for a personal setup.

Already have `lean-*` skills? Preserve local edits before installing over the same
names. Project-local skills can also affect which edition your agent discovers.
If new skills do not appear, reload or restart your agent's session.

## Start using a skill

Ask for the skill by name, or use your agent's invocation syntax:

| Agent | Example |
| --- | --- |
| Codex | `$lean-task Add pagination with tests` |
| Claude Code | `/lean-task Add pagination with tests` |
| Other compatible agents | `Use lean-task to add pagination with tests` |

The agent can also select a skill from its description. You do not need to run
`lean-init` first or install any companion skill.

## Choose a skill

| You want to… | Skill |
| --- | --- |
| Understand a project's commands and working conventions | [lean-init](skills/lean-init/SKILL.md) |
| Take a task from scope to tested, reviewed completion | [lean-task](skills/lean-task/SKILL.md) |
| Define what is included and how to verify it | [lean-scope](skills/lean-scope/SKILL.md) |
| Compare approaches with sources and trade-offs | [lean-research](skills/lean-research/SKILL.md) |
| Find gaps in a requirement or plan before coding | [lean-grill](skills/lean-grill/SKILL.md) |
| Delegate work to available agents | [lean-agents](skills/lean-agents/SKILL.md) |
| Review changes for problems and regressions | [lean-review](skills/lean-review/SKILL.md) |
| Check the evidence before calling a task done | [lean-gate](skills/lean-gate/SKILL.md) |
| Set how thoroughly to follow a procedure | [lean-effort](skills/lean-effort/SKILL.md) |
| Evaluate model choices and propose a configuration update | [lean-model-update](skills/lean-model-update/SKILL.md) |
| Select or clone another application repository | [lean-target](skills/lean-target/SKILL.md) |
| Update installed standalone skills while preserving local edits | [lean-update](skills/lean-update/SKILL.md) |

## What to expect

Skills give the agent instructions. They do not install background services,
automatic hooks, permission guards or signed review receipts. Checks and reviews
run through the agent using your project's tools and instructions.

Preferences and selected repositories stay in the conversation unless you request
persistence. Delegation needs available agent tools; model evaluations need suitable
tasks, tools and authorization. No model registry, benchmark bank or task queue is
bundled. The agent should report missing capabilities rather than pretend they exist.

Installing a skill does not grant permission to commit, push, deploy, use paid APIs
or change provider permissions. Your explicit request and project rules still apply.

## For contributors

Clone this repository and install from its root to try local changes:

```sh
npx skills add ./ --skill '*' -a codex claude-code antigravity -y
```

Validate with Python and Node.js/npm:

```sh
python3 -m unittest discover -s tests -v
python3 tests/install_smoke.py
```

The first check uses Python's standard library. The smoke test uses `skills@1.7.4`
through `npx` and needs registry access or a cached package. It checks all 12 skills
together and individually in both installation scopes: **26 scenarios** in temporary
homes and projects. It verifies content and scope isolation without modifying your
real global skills or calling an LLM. CI runs both checks.

These tests verify packaging and installation. Review the instructions themselves
to assess agent behavior. Keep the English and Thai guides aligned; skill files
remain in English.

## License and origin

Adapted from [Lean Workflow Agent by ASDW](https://github.com/aussadawut-dev/lean-workflow-agent-by-asdw).
This is the skills-only edition, without the original workflow's automatic enforcement.

[MIT License](LICENSE). Each skill includes its own license; retain it when
redistributing that skill independently.
