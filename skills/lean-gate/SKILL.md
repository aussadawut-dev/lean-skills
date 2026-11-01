---
name: lean-gate
description: Check acceptance, tests, validation and review evidence before declaring work complete, using the project’s own tools.
license: MIT
---

# lean-gate

Standalone skill: use the current request or explicit arguments. Read applicable project instructions and only task-relevant context. No Lean installation, CLI, configuration or companion skill is required; do not install a workflow or create workflow files as prerequisites. Existing project rules apply.

Use requested procedure depth, or standard by default. High adds relevant boundary cases and stronger evidence; ultra adds cross-part consistency and contradictory evidence where relevant. Depth does not change model reasoning settings. Keep decisions in conversation unless a suitable project record exists or the user requests persistence.

1. Reuse the existing acceptance and delivery agreement; do not reopen settled scope without new evidence. Identify acceptance and the final shipping state, including new files. Find required checks in project instructions, manifests and CI. Inspect commands before execution. Missing checks are a gap, not an automatic pass; for prose-only work explain the applicable content/link validation.
2. Run relevant deterministic checks, or reuse verified results only when their inputs have not changed and project rules allow reuse. Preserve failures. Do not weaken tests, change acceptance or waive mandatory checks merely to pass.
3. Check evidence for the integrated user journey and agreed delivery destination. Identify simulated boundaries and missing end-to-end coverage; a build or unit-test pass alone does not prove an untested integration. Verify meaningful tests for behavior changes and regression evidence for bug fixes. Review must cover the final diff after validation: LOW self-check, MEDIUM focused review, HIGH fresh independent review; quality HIGH requires at least MEDIUM and VERY_HIGH requires HIGH. Report unavailable required independence as BLOCKED.
4. When called within an implementation workflow, return unmet acceptance and evidence gaps to its controller, which owns repairs and retry counts; do not start a nested repair loop. When used alone with repair authorization, fix in-scope failures, rerun affected checks and renew review. Across the task, after a second review REWORK allow one final fix-only pass and checks/review, then stop if violations remain. Missing tools or material design decisions block dependent work. Report unrelated failures and seek scope direction where fixing them would expand the task. A suspected flaky check gets at most two unchanged retries; disclose them.
5. Match each acceptance item to current evidence and synchronize existing task records. DONE requires all mandatory acceptance, validation, review and delivery conditions. BLOCKED means missing prerequisites; FAILED means demonstrated unresolved failures. List command outcomes, review coverage, skips and the next action when incomplete.

This is an agent-run completion assessment, not an automatic Stop hook, cryptographic receipt or permission guard. Never claim those enforcement guarantees. Invocation authorizes the relevant safe local checks, not deployments or unrelated external writes.
