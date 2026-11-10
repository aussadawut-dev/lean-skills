# Structured diagnosis

## When to use

- **Unclear faults.** Use for a fault whose cause is unclear, intermittent or spread across components.
- **Known regressions.** A simple known regression can use a short reproduce/fix/check cycle.
- **Diagnosis only.** Respect a diagnosis-only request; do not change application files, dependencies or live systems to make a proposal more concrete.

## Steps

1. **Establish the facts.** Establish expected and observed behavior, failing input, relevant revision/environment and the last known good state when available. Record impact and what is still unknown. Inspect existing failures and recent relevant changes; avoid collecting unrelated logs or secrets.
2. **Reproduce.** Reproduce through the actual affected interface. Reduce input, state and dependencies enough to distinguish the failure while preserving its essential conditions. Record exact commands/actions and outcomes. If reproduction is unavailable, use existing artifacts to bound hypotheses and state the missing observation; never label a historical log a fresh reproduction.
3. **Trace.** Trace the input across component boundaries and locate the first divergence from the expected contract. Use relevant source, logs, traces or authorized instrumentation. Separate application defects from configuration, environment, dependency or data problems. Preserve useful evidence before any repair.
4. **Probe hypotheses.** Keep a small set of plausible causes and choose the next probe by what it can distinguish. State the hypothesis, expected observation and result. Change one relevant variable when practical. A failed probe can eliminate a cause; repeated unchanged attempts without new evidence are not progress.
5. **Support the cause.** Call a cause supported only when evidence explains the failure mechanism and a targeted counterexample or repair check distinguishes it from alternatives. Label a workaround and its residual risk. For intermittent faults, report the observed sample and remaining uncertainty rather than claiming that one clean run proves absence.
6. **Repair if requested.** If repair is requested, make the smallest causal change, retain a regression check and verify both the formerly failing case and preserved valid behavior through the relevant interface. Apply the controller's existing review and retry budget; do not reset it on entering diagnosis. If diagnosis alone was requested, deliver the evidence and proposed next step without implementing it.

## Result

- **Conclusion.** Conclude with the scoped result, expected/actual behavior, reproducer or missing prerequisite, supported cause versus remaining hypotheses, checks and limits.
- **DONE and BLOCKED.** DONE for diagnosis means the requested question is answered with evidence; an indispensable unobservable fact is BLOCKED.
- **Repair DONE.** A repair is DONE only when its acceptance, checks, required review and delivery hold.
- **FAILED.** Report demonstrated unresolved mandatory failures as FAILED and retain independent completed work.
