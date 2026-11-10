---
name: lean-task
description: Diagnose a fault or carry a bounded implementation task through tests, review and evidence-backed completion in any project.
license: MIT
---

# lean-task

## Ground rules

- **Standalone.** Standalone skill: use the current request or explicit arguments. Read applicable project instructions and only task-relevant context.
- **No prerequisites.** No Lean installation, CLI, configuration or companion skill is required; do not install a workflow or create workflow files as prerequisites. Existing project rules apply.
- **Depth.** Use requested procedure depth, or standard by default. High adds relevant boundary cases and stronger evidence; ultra adds cross-part consistency and contradictory evidence where relevant. Depth does not change model reasoning settings.
- **Records.** Keep decisions in conversation unless a suitable project record exists or the user requests persistence.

## Input and result

- **Input.** Input is the requested behavior or fault, expected versus observed outcome, available evidence and requested endpoint. Reuse agreed acceptance; ask only for missing material facts.
- **Diagnosis only.** A diagnosis-only request concludes with the supported cause or narrowed hypotheses, reproducer/probes, limitations and next action, without editing the application.
- **DONE, BLOCKED, FAILED.** Use DONE for a completed requested diagnosis or implementation; BLOCKED for an indispensable missing observation/access/decision, and FAILED for a demonstrated unresolved mandatory failure.
- **Diagnosis.** Diagnose unclear or non-trivial faults using [structured diagnosis](references/diagnosis.md). A diagnosis result does not complete a requested repair.

## Steps

1. **Reuse the agreement.** Reuse supplied acceptance, decisions and classifications instead of repeating intake. State risk (LOW, MEDIUM or HIGH), quality (STANDARD, HIGH or VERY_HIGH), and observable acceptance before edits. Use HIGH risk for consequential security, destructive data or breaking external-contract changes. Respect the project's own contract format if present.
2. **Settle scope.** Use the agreed scope; draft only missing scope needed to satisfy the request.
   - **Explore.** For broad or unclear work or materially different directions, reflect the goal, draft a few unconfirmed use cases or before/after scenarios, offer useful work sizes and trade-offs, and ask small related batches.
   - **Question format.** Number questions or confirmations and label options a, b, c, etc.; recommend supported choices with reasons and provide a copyable suggested reply such as `1a 2b`. Accept codes, natural language and mixed replies; unanswered choices are not consent. Follow up on material omissions.
   - **Question dialog.** Prefer the host's structured question dialog whenever a suitable tool is available in the current mode; follow its schema and limits, splitting batches when needed. Keep use-case context in chat and make each dialog question self-contained, retaining numbered questions and lettered choices where supported. Include brief recommendation reasons and allow free-text corrections. A preselected recommendation is not a submitted answer. Fall back to numbered, lettered chat questions and copyable replies when no suitable dialog is available; do not claim unsupported input prefilling.
   - **Recap.** Distinguish agreements, open decisions and proposals; recap and ask what is missing before converting exploration to scope. If something is added, explore its goal and relevant use case, update the recap and ask again until the user says it is complete.
   - **Research.** Research current external facts with sources when needed.
   - **Skip when clear.** Skip unnecessary exploration and this loop for small or clear work or when told to proceed, but ask indispensable material decisions. A clear implementation request authorizes matching work. Continue independent work and use existing project records when required, otherwise keep the plan in chat.
3. **Implement.** Implement within scope. When called within a larger workflow, its controller owns delivery and repair counts; return results to it without asking the user to invoke another stage. Report progress at meaningful phase transitions: scope, implement, test, validate, review, complete. Delegate only when authorized and available, with exclusive file ownership and a bounded assignment; otherwise work directly unless delegation is mandatory.
4. **Test.** Add meaningful tests for behavior changes. For a bug, demonstrate the regression before the fix and passing afterward. Map acceptance and important boundaries to the smallest reliable unit, contract, integration or end-to-end checks; choose expected outcomes from requirements rather than copying the implementation. Use controlled fixtures and state why a live boundary is required or simulated. When no suitable harness exists, establish only the minimal in-scope check or report the missing capability; do not introduce unrelated tooling. Run affected checks during iteration, then required project checks on the final content. Do not weaken checks to make them pass.
5. **Validate and review.** Exercise the relevant integrated user journey to its observable outcome and important failure cases using the project's UI, API, CLI or artifact interface. Record the environment, actions and results; identify mocks and untested boundaries. Required end-to-end coverage cannot be replaced silently by unit tests or a build. Review the final diff including new files after deterministic validation. LOW uses an acceptance self-check; MEDIUM uses a focused correctness/regression review; HIGH requires a fresh independent reviewer. Quality HIGH has at least MEDIUM review; VERY_HIGH has HIGH review. If required independence is unavailable, report BLOCKED rather than claim completion. Review fixes require renewed affected validation and review.
   - **UI work.** For UI work, exercise relevant keyboard/focus and feedback behavior, screen sizes and loading/empty/error/recovery states against agreed usability/accessibility acceptance. A source inspection alone does not prove browser or assistive-technology behavior.
   - **Security and data.** For changed security or data boundaries, verify the corresponding authorization, abuse or migration/recovery cases; do not turn unrelated work into a full audit.
6. **Complete.** Keep one repair history across calls: after a second review REWORK, allow one final fix-only pass and renewed checks/review, then report remaining violations as FAILED. Missing prerequisites are BLOCKED. Check every acceptance item against current evidence, disclose skips and limitations, and synchronize existing records. DONE requires acceptance, validation, required review and the agreed delivery destination; missing prerequisites mean BLOCKED, demonstrated unresolved failures mean FAILED. Report outcome, changes, tests, review and remaining work. A commit, push or publication requires matching user authorization.
