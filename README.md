# Lean Skills

**English** | [ภาษาไทย](README.th.md)

16 independent skills that help coding agents plan, build, test and review work.
Install all of them or just one. **No Lean runtime or `.lean` directory is required.**

They work with **Codex, Claude Code and Antigravity** through the
[Skills CLI](https://github.com/vercel-labs/skills).
For a Thai walkthrough with flow diagrams, read the [Thai usage guide](docs/guide.th.md).

## What it does

A skill is a set of instructions. Your agent reads it and does the work with your
project's own tools. Nothing runs in the background.

Each skill owns **one job** and ends on a stated result: a scope, a diagnosis, a
review, a verified change. So you can install one skill and get a complete
deliverable from it, without its siblings.

[`lean-run`](skills/lean-run/SKILL.md) is the **entry point**. It takes one request
from the first decisions through verified delivery, and calls the other skills
only when they help.

## Quick start

You need Node.js/npm (`npx`) and your coding agent.

### 1. Install

Pick where the skills live:

- **Every project.** Add `-g`. Your project stays untouched.
- **This project only.** Omit `-g` and run from the project's root.

```sh
npx skills add aussadawut-dev/lean-skills -g --skill '*' -a codex claude-code antigravity -y
```

To install one skill, name it. This installs `lean-review` for Codex in the current project:

```sh
npx skills add aussadawut-dev/lean-skills --skill lean-review -a codex -y
```

To fit the command to you:

- Keep only the agents you use after `-a`.
- `--skill '*'` selects all 16 skills. Keep the quotes around `'*'`.
- `-y` skips confirmation. Omit both `-a` and `-y` to choose agents interactively.
- Add `--list` to see the skills without installing anything.

A project install creates local skill folders and discovery links, such as
`.agents/skills/` and `.claude/skills/`, plus installer metadata where the host uses it.
Run `git status` to see them. Commit them to share with your team, or ignore them
for a personal setup. Global skills stay unchanged.

### 2. Ask for a skill

Name the skill, or use your agent's invocation syntax:

- **Codex:** `$lean-run Add pagination and verify the complete user flow`
- **Claude Code:** `/lean-run Add pagination and verify the complete user flow`
- **Other compatible agents:** `Use lean-run to add pagination and verify the complete user flow`

The agent can also pick a skill from its description. You don't need to run
`lean-init` first or install any companion skill.

### 3. Done

If a new skill doesn't appear, reload or restart your agent's session.

## Choose a skill

**Own the whole request**

- **[lean-run](skills/lean-run/SKILL.md)**: Own a request from the first decisions through verified delivery.

**Decide what to build**

- **[lean-scope](skills/lean-scope/SKILL.md)**: Define what is included and how to verify it.
- **[lean-grill](skills/lean-grill/SKILL.md)**: Find gaps in a requirement or plan before coding.
- **[lean-research](skills/lean-research/SKILL.md)**: Compare approaches with sources and trade-offs.

**Build and check**

- **[lean-task](skills/lean-task/SKILL.md)**: Diagnose a fault or implement a task through tested, reviewed completion.
- **[lean-agents](skills/lean-agents/SKILL.md)**: Delegate work to available agents.
- **[lean-review](skills/lean-review/SKILL.md)**: Review changes for problems and regressions.
- **[lean-gate](skills/lean-gate/SKILL.md)**: Check the evidence before calling a task done.
- **[lean-effort](skills/lean-effort/SKILL.md)**: Set how thoroughly to follow a procedure.

**Specialists**

- **[lean-security](skills/lean-security/SKILL.md)**: Assess a security boundary and verify authorized repairs.
- **[lean-release](skills/lean-release/SKILL.md)**: Plan or execute a release or recovery with verified outcomes.
- **[lean-model-update](skills/lean-model-update/SKILL.md)**: Evaluate model choices and propose a configuration update.

**Set up and maintain**

- **[lean-init](skills/lean-init/SKILL.md)**: Learn a project's commands and working conventions.
- **[lean-instructions](skills/lean-instructions/SKILL.md)**: Create or update repository-root `AGENTS.md` and `CLAUDE.md` instructions.
- **[lean-target](skills/lean-target/SKILL.md)**: Select or clone another application repository.
- **[lean-update](skills/lean-update/SKILL.md)**: Update Lean skills and add missing ones while keeping your local edits.

## One request, start to delivery

Use `lean-run` when you want the agent to own the whole task:

```text
Use lean-run to fix checkout creating a payment without an order.
Resolve material requirements first, reproduce the bug, implement the fix,
and verify the flow through a successfully created order. Deliver a PR.
```

It settles the important decisions early. Then it carries authorized work through
implementation, integrated verification, review and delivery, without asking you to
invoke each next skill. A new consequential fact can still need your answer.

The agreement it works to is the **contract**. Add or correct requirements at any
point: the next `Recap:` shows the updated contract, with earlier work still open and
work already verified. The agent continues from it and checks it again at delivery.

Delivery means what you asked for. With no destination named, it means verified
changes in the current workspace. A PR or a deployment needs matching authorization
and access.

`lean-run` can do the core procedure alone. [`lean-task`](skills/lean-task/SKILL.md)
is the same implementation procedure on its own; choose it when you want that
directly. Across stages the controller keeps decisions and repair counts, skips
repeated discovery and stops retries that aren't helping.

### Broad requests become question rounds

For a broad or unclear request, `lean-run`, `lean-task` and `lean-scope` explore the
goal before settling scope: example use cases, work-size choices, small batches of
questions.

- Questions are numbered, choices are lettered, and a suggested reply such as `1a 2b`
  comes with them where it fits. You can also answer in your own words.
- Leaving an item unanswered doesn't accept the suggestion.
- Before it closes the scope, the agent asks what is missing and explores additions.
- Small or clear requests, and instructions to proceed, skip the extra rounds. A
  decision the work can't go on without still needs your answer.

Where the host and mode support it, the agent uses a structured question dialog. Each
question carries enough context and accepts a free-text correction, and preselected
recommendations still need you to submit. Otherwise it asks numbered chat questions
with copyable replies; whether a reply is prefilled depends on the host.

### Auto or manual

By default the agent picks `lean-run` when it fits. To make it the default for
**every end-to-end implementation task**, keep implicit invocation on and add this to
the project's `AGENTS.md` (Codex) or `CLAUDE.md` (Claude Code):

```text
Invoke lean-run at the start of every new end-to-end implementation task.
Treat follow-up requirements as updates to the active run.
```

For **manual** mode, remove that rule and set the installed skill to manual:

- **Codex:** set `policy.allow_implicit_invocation: false` in the skill's
  `agents/openai.yaml`, then start a run with `$lean-run …`.
- **Claude Code:** merge `"skillOverrides": {"lean-run": "user-invocable-only"}` into
  the project's `.claude/settings.local.json`, then start a run with `/lean-run …`.
  See [Claude Code skill overrides](https://code.claude.com/docs/en/skills#override-skill-visibility-from-settings).

To go back to auto, set the Codex value to `true` or remove the Claude Code override,
then add the project rule again. On a host with no invocation setting, state your
choice in the project instructions. Start a fresh session to check the mode.

## How a result ends

Every skill defines its input, endpoint, evidence and what to do when it can't finish.
A finished discovery, diagnosis, scope, review or handoff is a deliverable in its own
right. It never claims an implementation or release you didn't ask for.

A result names what it assessed (content or environment), what it observed, its limits
and the next action, and ends on one **label**:

- **`READY`**: a plan is settled, or rests on stated reversible assumptions.
- **`PASS`** / **`REWORK`**: the verdict of a review.
- **`DONE`**: an authorized action finished, with current evidence for every mandatory condition.
- **`BLOCKED`**: a prerequisite is missing, and the result names it.
- **`FAILED`**: a demonstrated failure is still unresolved.

A label covers the stated scope, not the whole project. A release that fails and then
rolls back reports both outcomes. Simulated integrations and untested boundaries are
always disclosed, so `DONE` is never a guarantee that every task succeeds.

Some procedures have extra modes, each loaded only when needed: structured diagnosis in
`lean-task`, product and accessibility acceptance in `lean-scope`, focused UI checks in
implementation and review, and cross-session continuation in `lean-run` and `lean-agents`.
Each mode's reference ships inside its own skill and needs no sibling installed.

A **handoff** records decisions, exact work state, how fresh the evidence is, pending
operations and repair counts. Persistent checkpoints stay opt-in, unless the project
already keeps such a record.

### Specialists are optional

[`lean-security`](skills/lean-security/SKILL.md) runs a bounded security assessment or an
authorized remediation; its findings need traced evidence.
[`lean-release`](skills/lean-release/SKILL.md) plans or executes a release or recovery; it
needs the exact artifact, target health and the relevant migration and recovery checks.
Neither is a mandatory step for every task.

For a performance decision, use [`lean-research`](skills/lean-research/SKILL.md) with a
defined workload and a measured baseline, when a probe is authorized. No skill starts a
benchmark on its own.

## Delegating to other models

When delegation is authorized and useful, the controller picks a model and reasoning
effort for each task from the current provider's verified capabilities. Your explicit
choice and existing project mappings come first.

- Mechanical work, implementation and complex review need different capabilities, so
  there is no shared size ladder across providers.
- Small work can stay with the main agent. By default it uses at most one worker, unless
  you ask for parallel work.
- Procedure depth ([`lean-effort`](skills/lean-effort/SKILL.md)) is separate from model
  reasoning effort.

Workers are labelled `<taskname> - <model name>|<effort>`, for example
`api_builder - gpt-6.1-sol|medium`. Names are passed literally, so `|` is never a shell
pipeline.

- **Claude Code** uses the Agent task description, or `--name` for a separate CLI session.
- **Antigravity** uses the subagent Role.
- **A host with restricted internal IDs** shows the full label in dispatch updates and
  reports, next to the runtime ID. A native UI with no display-name control keeps its own name.

The reusable agent type and the returned instance ID stay separate from the label.

The report separates the settings requested from the backend settings the runtime actually
returned, and says so when controls or metadata are missing. Delegation never switches
provider, falls back to a paid API or changes model configuration on its own.

## What stays in your hands

Skills give the agent instructions and nothing else: no background services, automatic
hooks, permission guards or signed review receipts. Checks and reviews run through the
agent, with your project's tools and instructions.

- **Permission.** Installing a skill grants no permission to commit, push, deploy, use paid
  APIs or change provider permissions. Your explicit request and project rules decide.
- **Memory.** Preferences and selected repositories stay in the conversation unless you ask
  for them to persist.
- **Capabilities.** Delegation needs agent tools; model evaluation needs suitable tasks,
  tools and authorization. No model registry, benchmark bank or task queue is bundled. The
  agent reports a missing capability instead of acting as if it exists.

## It's working if

- Decisions the work depends on reach you early, as a few rounds of numbered questions, not
  one by one throughout.
- Each `Recap:` shows the contract, including what is still open and what is verified.
- The final report names its evidence and ends on one label for the scope you asked for.
- A `BLOCKED` or `FAILED` result tells you exactly what is missing or what broke.

## Common questions

**Do I have to install every skill?**
No. Every skill works alone, and `lean-run` can do the core procedure without companions.

**I already have `lean-*` skills. Will installing overwrite them?**
It installs over the same names, so preserve your local edits first, or use
[`lean-update`](skills/lean-update/SKILL.md). Project-local skills can also change which
edition your agent discovers.

**A skill I installed doesn't show up.**
Reload or restart the agent's session. Then check whether a project-local copy is shadowing it.

**Does `lean-run` guarantee the task succeeds?**
No. `DONE` needs current evidence for every mandatory condition. Otherwise you get
`BLOCKED` with the missing prerequisite, or `FAILED` with the unresolved failure.

**Which hosts are tested?**
See [Evidence](#evidence). Codex has the full scenario set; Claude Code and Antigravity
have live naming checks only so far.

## Evidence

The [2026-11-01 evaluation report](docs/results/2026-11-01/README.md) records ten core
Codex scenarios, plus targeted current-candidate routing and boundary trials. Claude Code
and Antigravity have [live subagent naming checks](docs/results/2026-11-01-naming/README.md),
including spaces, hyphens and `|`. Their full end-to-end workflow suite is not yet verified.
The report keeps requested model settings apart from what the runtime actually exposed.

The [2026-11-02 scoped-completion trials](docs/results/2026-11-02-scope-completion/README.md)
record five fresh Codex runs (security review, simulated release and recovery, diagnosis,
UX scope and handoff) plus packaging checks for the 16-skill candidate. They don't establish
live deployment, executed UI accessibility checks or full runtime coverage on the other hosts.

Recorded `lean-run` benchmark cohorts live on the
[`benchmark-archives`](https://github.com/aussadawut-dev/lean-skills/tree/benchmark-archives)
branch, so installs stay small. [docs/results/README.md](docs/results/README.md) indexes
them and shows how to restore one.

## For contributors

Clone this repository and install from its root to try local changes:

```sh
npx skills add ./ --skill '*' -a codex claude-code antigravity -y
```

Validate with Python and Node.js/npm. CI runs both:

```sh
python3 -m unittest discover -s tests -v
python3 tests/install_smoke.py
```

- **Unit tests** use only Python's standard library.
- **The smoke test** runs `skills@1.7.4` through `npx`, so it needs registry access or a
  cached package. It installs all 16 skills together and one by one, in both scopes:
  **34 scenarios** in temporary homes and projects. It checks every packaged reference, not
  only `SKILL.md` and `LICENSE`, and verifies scope isolation without touching your real
  global skills or calling an LLM. With an existing CLI it runs offline:
  `python3 tests/install_smoke.py --cli /path/to/skills/bin/cli.mjs`.

These tests cover packaging and installation, not agent behavior. For behavior, run the
[behavioral evaluation cases](docs/evaluation.md) as isolated agent trials and record the
actual host and model, artifacts and results. A static walkthrough is not an executed trial
and is no evidence of cross-agent reliability.

Keep the English and Thai guides aligned. Skill files stay in English. Write release notes
from the [release template](.github/release-template.md).

## License and origin

Adapted from [Lean Workflow Agent by ASDW](https://github.com/aussadawut-dev/lean-workflow-agent-by-asdw).
This is the skills-only edition, without the original workflow's automatic enforcement.

[MIT License](LICENSE). Each skill carries its own license; keep it when you redistribute
that skill on its own.
