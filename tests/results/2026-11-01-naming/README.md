# Live Claude and Antigravity worker naming — 2026-11-01

PASS: both installed CLIs spawned real child agents with literal spaces, hyphens
and `|` preserved. Six successful native runs cover full custom type identifiers,
explicit display fields, and final trials applying the revised skill. Every child
returned `NAMING_CHILD_OK`; verification uses native task events and child output,
not just a parent's claim that it spawned something.

## What changed after testing

The initial generic instruction did not identify each provider's display field.
First probes retained the full custom type name but used a generic task description
or Role. A custom type name alone therefore did not satisfy the requested instance
label. The revised lean-run and lean-agents instructions now distinguish:

| Runtime | Full label destination | Separate identity |
| --- | --- | --- |
| Claude Code Agent | `description` | Existing `subagent_type`, returned task/agent ID |
| Claude Code separate CLI session | `--name` | Session ID |
| Antigravity `invoke_subagent` | `Role` | Existing `TypeName`, returned conversation ID |
| Codex restricted task names | Dispatch/report label; safe internal `task_name` | Returned runtime ID |

Use fields only when supported by the current schema. Do not enable Claude teams
or use `Agent.name` solely for presentation, redefine a reusable agent solely to
rename one instance, or pass `|` as unquoted shell text. Child labels describe
requested settings, not verified backend identity. An explicit `inherit` selector
and omitted effort are honestly shown as `inherit|default` rather than assuming
the parent's settings apply to the child.

## Executed trials

| Trial | Native evidence | Result |
| --- | --- | --- |
| [Claude literal type](claude.json) | `session_title_changed.title` and `task_started.subagent_type` preserve `naming_probe - haiku\|low`; completed child task | PASS |
| [agy literal type](agy.json) | `subagent_info.type_name` preserves `naming_probe - gemini-3.8-flash-low\|low`; child transcript contains sentinel | PASS |
| [Claude display field](claude-display.json) | Task `description` equals the full label, task type `local_agent`, completed notification | PASS |
| [agy display field](agy-display.json) | Returned `role` and `type_name` equal the full label; child completes | PASS |
| [Claude revised skill](claude-skills.json) | Given revised lean-agents and ordinary delegation request, used `description=naming_probe - haiku\|low`, existing type `naming_probe`; completed notification | PASS |
| [agy revised skill](agy-skills.json) | Given revised lean-agents, used `Role=naming_probe - inherit\|default`, existing type `naming_probe`; `manage_subagents` reports exact role and idle child; child transcript contains sentinel | PASS |

The two final trials did not prescribe the provider's display-field parameter in
the task prompt: that routing came from the revised skill. The initial full-model
agy labels were literal compatibility probes, not evidence that the child used
the parent's model or effort. The final agy trial deliberately names the requested
inheritance/defaults instead.

## Evidence and reproduction

[Verification](verification.json) records child IDs, outcomes, Claude Code version
2.1.316 and the installed agy executable hash. Per-trial JSON preserves argument
arrays, disposable working directory, custom agent definition, selected native
events and completion status. Invocation names were separate argv/JSON values;
no shell interpreted `|`. Records omit reasoning traces and unrelated account
data. Final skill bytes are retained as [lean-agents](lean-agents-snapshot.txt)
and [lean-run](lean-run-snapshot.txt); both contain the same naming procedure.

To reproduce, create a fresh disposable directory, recreate the recorded agent
definition and invoke the recorded CLI argv with its file paths updated. Use
the existing authorized login and do not introduce metered API credentials.
Full literal types use the supplied definition's exact name; final trials use
the stable type `naming_probe` and put the full instance label in the display field.
Wait for completion and match the returned task/conversation ID to the child's
result. Names echoed in a model's final prose alone are not sufficient evidence.

One harness attempt failed before model execution: agy rejected timeout value
`100` because it requires a duration unit. After correction to `100s`, its runs
completed without timeout. No runtime name rejection or shell pipeline occurred.

## Limits and references

This verifies real native subagent execution and accepted task/role metadata.
It does not verify graphical UI rendering via screenshot, every installed runtime
version, resolved child model/effort, or the entire end-to-end workflow suite on
Claude/Antigravity. No global agent definitions or provider settings were changed;
temporary definitions and normal session logs were created for these tests.

Current provider documentation: [Claude custom subagents](https://code.claude.com/docs/en/sub-agents)
and [Antigravity custom subagents](https://antigravity.google/docs/subagents?tab=cli).
The runtime field recommendations above are corroborated by the executed traces,
not inferred solely from those documentation pages.
