# lean-run Critical rerun with corrected RLS wording (stopped after first assessment)

Recorded 2026-11-05. Critical only, prepared from the
[SQL-source and phase-budget pilot](../2026-11-04-lean-run-in-source-budget/README.md)
after the contract wording amendment in the [policy record](policy-record.md).

- Implementation 596.8 s (26,221 uncached input), review 619.9 s (19,798); no timeout.
  Original grader 9/9.
- Frozen gates blocked it on one MEDIUM review finding (R1), 73 `rls_policy_probe`
  cases (exception class and rowid expectations the contract does not state) and
  77 unsuperseded historical assertions.
- By plan the trial **stopped after the first assessment** with no repair
  ([record](round-1/critical/coordinator-stop.json)). It is neither DONE nor
  FAILED and is not counted as a PASS.
- Posthoc only: the same candidate passes the later
  [oracle contract probe](../../probes/critical_contract_probe.py) with zero
  failures, and R1 is its `transient_foreign_observed` scenario, which the oracle
  accepts. That evidence motivated the [contract gate policy](../../benchmark/README.md).
