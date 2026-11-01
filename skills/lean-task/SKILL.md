---
name: lean-task
description: Carry an implementation task from acceptance through tests, review and evidence-backed completion in any project.
license: MIT
---

# lean-task

This is a standalone skill. Use the current request or explicit invocation arguments as input. Read existing project instructions and only the context needed for this task. No Lean installation, CLI, configuration, or other skill is required. Do not install a workflow or create workflow files as a prerequisite. Existing project rules still apply.

Use the user's requested procedure depth; otherwise use standard depth. High adds boundary cases and stronger evidence; ultra adds cross-part consistency and contradictory evidence where relevant. Depth does not change model reasoning settings. Keep decisions in the conversation unless the project already has a suitable record or the user requests persistence.

1. State risk (LOW, MEDIUM or HIGH), quality (STANDARD, HIGH or VERY_HIGH), and observable acceptance before edits. Use HIGH risk for consequential security, destructive data or breaking external-contract changes. Respect the project's own contract format if present.
2. Draft the smallest scope that satisfies the request. A clear implementation request authorizes matching work. Clarify material ambiguity before dependent work; continue independent work. Use existing project records when required, otherwise keep the plan in chat.
3. Implement within scope. Report progress at meaningful phase transitions: scope, implement, test, validate, review, complete. Delegate only when authorized and available, with exclusive file ownership and a bounded assignment; otherwise work directly unless delegation is mandatory.
4. Add meaningful tests for behavior changes. For a bug, demonstrate the regression before the fix and passing afterward. Run affected checks during iteration, then required project checks on the final content. Do not weaken checks to make them pass.
5. Review the final diff including new files after deterministic validation. LOW uses an acceptance self-check; MEDIUM uses a focused correctness/regression review; HIGH requires a fresh independent reviewer. Quality HIGH has at least MEDIUM review; VERY_HIGH has HIGH review. If required independence is unavailable, report BLOCKED rather than claim completion. Review fixes require renewed affected validation and review.
6. Check every acceptance item against current evidence, disclose skips and limitations, and synchronize existing records. DONE requires acceptance, validation and required review; missing prerequisites mean BLOCKED, demonstrated unresolved failures mean FAILED. Report outcome, changes, tests, review and remaining work. A commit, push or publication requires matching user authorization.
