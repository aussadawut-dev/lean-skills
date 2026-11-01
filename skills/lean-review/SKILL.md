---
name: lean-review
description: Review a shipping diff for requirement violations and regressions at a risk-appropriate depth.
license: MIT
---

# lean-review

This is a standalone skill. Use the current request or explicit invocation arguments as input. Read existing project instructions and only the context needed for this task. No Lean installation, CLI, configuration, or other skill is required. Do not install a workflow or create workflow files as a prerequisite. Existing project rules still apply.

Use the user's requested procedure depth; otherwise use standard depth. High adds boundary cases and stronger evidence; ultra adds cross-part consistency and contradictory evidence where relevant. Depth does not change model reasoning settings. Keep decisions in the conversation unless the project already has a suitable record or the user requests persistence.

1. Establish the exact change: base revision, final working-tree content and new files. Read acceptance and relevant project standards. Confirm deterministic checks have passed for this content; missing checks remain unverified.
2. Determine review depth from risk and quality: LOW self-check, MEDIUM focused correctness/regression review, HIGH fresh independent reviewer. Quality HIGH requires at least MEDIUM depth; VERY_HIGH requires HIGH. If independence is required but unavailable, report BLOCKED rather than a self-issued independent PASS.
3. Check requirements, correctness, preservation of valid behavior and relevant boundary/failure cases. For consequential guarantees, execute targeted probes rather than trusting the author's report. Include command, working directory, outcome and limitations. Do not mistake skipped tests or checks of a different checkout for evidence.
4. Report actionable findings with severity, location, violated requirement, demonstrated behavior and suggested repair. Distinguish introduced violations from pre-existing unrelated issues. Skip style preferences that do not affect meaning.
5. Return PASS or REWORK for a completed review; missing coverage is BLOCKED/unverified. A mandatory demonstrated violation requires REWORK. After repairs, rerun affected validation and review the final content. After a second REWORK, allow one last fix-only pass, then stop with unresolved findings for the user's decision.
6. State the reviewed revision/diff and coverage limits. Changes after PASS require renewed review. Keep existing project review records current if applicable; this skill neither creates a signed receipt nor grants publication permission.
