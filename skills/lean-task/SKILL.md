---
name: lean-task
description: Carry an implementation task from acceptance through tests, review and evidence-backed completion in any project.
license: MIT
---

# lean-task

Standalone skill: use the current request or explicit arguments. Read applicable project instructions and only task-relevant context. No Lean installation, CLI, configuration or companion skill is required; do not install a workflow or create workflow files as prerequisites. Existing project rules apply.

Use requested procedure depth, or standard by default. High adds relevant boundary cases and stronger evidence; ultra adds cross-part consistency and contradictory evidence where relevant. Depth does not change model reasoning settings. Keep decisions in conversation unless a suitable project record exists or the user requests persistence.

1. Reuse supplied acceptance, decisions and classifications instead of repeating intake. State risk (LOW, MEDIUM or HIGH), quality (STANDARD, HIGH or VERY_HIGH), and observable acceptance before edits. Use HIGH risk for consequential security, destructive data or breaking external-contract changes. Respect the project's own contract format if present.
2. Use the agreed scope; draft only missing scope needed to satisfy the request. A clear implementation request authorizes matching work. Clarify material ambiguity before dependent work; continue independent work. Use existing project records when required, otherwise keep the plan in chat.
3. Implement within scope. When called within a larger workflow, its controller owns delivery and repair counts; return results to it without asking the user to invoke another stage. Report progress at meaningful phase transitions: scope, implement, test, validate, review, complete. Delegate only when authorized and available, with exclusive file ownership and a bounded assignment; otherwise work directly unless delegation is mandatory.
4. Add meaningful tests for behavior changes. For a bug, demonstrate the regression before the fix and passing afterward. Run affected checks during iteration, then required project checks on the final content. Do not weaken checks to make them pass.
5. Exercise the relevant integrated user journey to its observable outcome and important failure cases using the project's UI, API, CLI or artifact interface. Record the environment, actions and results; identify mocks and untested boundaries. Required end-to-end coverage cannot be replaced silently by unit tests or a build. Review the final diff including new files after deterministic validation. LOW uses an acceptance self-check; MEDIUM uses a focused correctness/regression review; HIGH requires a fresh independent reviewer. Quality HIGH has at least MEDIUM review; VERY_HIGH has HIGH review. If required independence is unavailable, report BLOCKED rather than claim completion. Review fixes require renewed affected validation and review.
6. Keep one repair history across calls: after a second review REWORK, allow one final fix-only pass and renewed checks/review, then report remaining violations as FAILED. Missing prerequisites are BLOCKED. Check every acceptance item against current evidence, disclose skips and limitations, and synchronize existing records. DONE requires acceptance, validation, required review and the agreed delivery destination; missing prerequisites mean BLOCKED, demonstrated unresolved failures mean FAILED. Report outcome, changes, tests, review and remaining work. A commit, push or publication requires matching user authorization.
