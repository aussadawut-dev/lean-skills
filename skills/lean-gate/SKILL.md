---
name: lean-gate
description: Check acceptance, tests, validation and review evidence before declaring work complete, using the project’s own tools.
license: MIT
---

# lean-gate

This is a standalone skill. Use the current request or explicit invocation arguments as input. Read existing project instructions and only the context needed for this task. No Lean installation, CLI, configuration, or other skill is required. Do not install a workflow or create workflow files as a prerequisite. Existing project rules still apply.

Use the user's requested procedure depth; otherwise use standard depth. High adds boundary cases and stronger evidence; ultra adds cross-part consistency and contradictory evidence where relevant. Depth does not change model reasoning settings. Keep decisions in the conversation unless the project already has a suitable record or the user requests persistence.

1. Identify acceptance and the final shipping state, including new files. Find required checks in project instructions, manifests and CI. Inspect commands before execution. Missing checks are a gap, not an automatic pass; for prose-only work explain the applicable content/link validation.
2. Run relevant deterministic checks, or reuse verified results only when their inputs have not changed and project rules allow reuse. Preserve failures. Do not weaken tests, change acceptance or waive mandatory checks merely to pass.
3. Verify meaningful tests for behavior changes and regression evidence for bug fixes. Review must cover the final diff after validation: LOW self-check, MEDIUM focused review, HIGH fresh independent review; quality HIGH requires at least MEDIUM and VERY_HIGH requires HIGH. Report unavailable required independence as BLOCKED.
4. Fix failures within the authorized scope, rerun affected checks and renew review after code changes. Missing tools or material design decisions block dependent work. Report unrelated failures and seek scope direction where fixing them would expand the task. A suspected flaky check gets at most two unchanged retries; disclose them.
5. Match each acceptance item to current evidence and synchronize existing task records. DONE requires all mandatory acceptance, validation and review conditions. BLOCKED means missing prerequisites; FAILED means demonstrated unresolved failures. List command outcomes, review coverage, skips and the next action when incomplete.

This is an agent-run completion assessment, not an automatic Stop hook, cryptographic receipt or permission guard. Never claim those enforcement guarantees. Invocation authorizes the relevant safe local checks, not deployments or unrelated external writes.
