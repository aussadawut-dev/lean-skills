# Benchmark gate design (contract gate policy)

Recorded 2026-11-05. Model-free work; no measured phase ran for this change.

## Why

Earlier Critical cohorts promoted every new finding into a permanent blocking
probe and every earlier candidate's own tests into blocking historical suites.
Those gates were never checked for satisfiability. They grew to 24 probes and
five historical suites, mixed expectations from different reviewers, encoded
earlier candidates' private choices (error wording, exception classes, rowids),
and in at least one case required an outcome the contract forbids
([F1 versus F2](../results/2026-11-04-rls-policy-development/README.md)).
Repairs spent against them bought no contract quality.

## Policy

`tests/repeated_benchmark.py prepare --mandatory-probe PROBE --critical-reference DIR`
selects the contract gate policy:

- **Blocking:** the original grader, protected-file and review-workspace
  integrity, the independent review, and the mandatory probes.
- **Advisory:** every inherited probe and all historical suites. They still run
  at each assessment and are reported in `assessment-N.json` under `advisory`,
  but they never block.
- **Satisfiability:** `prepare` copies the reference solution to
  `reference/<level>` and refuses the cohort unless the reference passes the
  grader and every mandatory probe while the initial fixture fails at least one.
  The result is frozen in `reference-check.json`. The reference never enters a
  trial workspace.
- **Admission rule for findings and gates:** a reviewer finding or a new gate
  blocks only when it traces to a contract sentence, reproduces against native
  SQLite with valid controls, and the reference passes it. Otherwise the
  coordinator may set the finding aside in `assessment-N-adjudication.json` under
  `rejected_findings`, each with its own reason and evidence; the runner accepts
  that only under the contract policy and only when every finding is covered.
  Rejected findings remain in the raw review and are reported separately.

## Iteration protocol and cost metric

A cohort of one High and one Critical trial costs about 4,000 s and several
million total tokens. To iterate on the skill cheaply, run High alone first
(`prepare --levels high` with one repetition): the gate is `first_review_issues`
of 0, since one repair cycle made every High trial 2.3 to 2.8 times more
expensive. Run Critical only after High passes its first review. Any candidate
workspace can be checked offline, without a model call, against the contract
oracle: `PYTHONPATH=<workspace> python3 tests/probes/critical_contract_probe.py <workspace>`.

`summary.json` now also reports `cost_weighted_tokens` per phase, trial and
level: uncached input, plus cached input at 0.1 and output at 4.0
(`COST_WEIGHTS` in `tests/summarize_repeated_benchmark.py`). The weights are
approximate price ratios, not a bill; the metric exists so that a change that
trims uncached input by adding turns or context cannot look like a win. The
primary metrics are unchanged.

## Critical contract probe

[`tests/probes/critical_contract_probe.py`](../probes/critical_contract_probe.py)
replaces hand-written expectations with an oracle: native SQLite on a copy that
contains only this tenant's ledger rows, with the original trigger order, followed
by the contract's final-effect rule. Its 41 scenarios are distilled from earlier
findings and historical tests (equivalent SQL forms, renamed columns and tables,
foreign writes and counters, required-effect failures, trigger order, rowid
shape, multirow `RAISE(IGNORE)`, `INSTEAD OF` views, UTF-16, recursion, side
tables). Foreign scenarios run with the other tenant's balance at 777, 778 and
absent. Only contract-traceable properties fail: physical rowid movement of
other tenants' rows and the exception class of a policy rejection are recorded
as advisory observations, because the contract states neither.

## Reference solution

[`reference/critical`](reference/critical) is the row-hiding prototype from the
RLS record plus one change: required writes are judged by final effects, not by
an outer statement's rowcount. It passes the grader 9/9 and the contract probe
with zero failures and zero advisory observations.

## Evidence (SQLite 3.50.4, Python 3.14)

This probe and `rls_policy_probe.py` pass an expression to `RAISE()`. SQLite
3.45.1, which Ubuntu 24.04 and GitHub-hosted runners ship, rejects that, so
`prepare` refuses the cohort with the probe's error instead of recording a failed
reference, and the four unit tests that run these probes are skipped there with
the SQLite version in the reason.

| Workspace | Contract probe failures | Advisory |
| --- | ---: | ---: |
| reference solution | 0 | 0 |
| initial broken fixture | 168 | 4 |
| in-source-budget final candidate (lexical rewrite) | 80 | 4 |
| same + A/B/R3 lexical patch | 75 | 4 |
| row-hiding prototype before the rowcount change | 2 | 0 |
| 2026-11-05 Critical rerun, first implementation (corrected contract) | 0 | 90 |

The 2026-11-05 Critical rerun candidate passed the grader 9/9 and this probe with
no failures on its first implementation, without repair. Under the frozen
protocol of that cohort it was blocked by one MEDIUM review finding (R1), 73
`rls_policy_probe` cases (exception class and rowids), and 77 unsuperseded
historical assertions. R1, a trigger that creates, copies and deletes its own
foreign-tenant row, is scenario `transient_foreign_observed`: the oracle accepts
the transfer with the same side-table contents, so it is not contract-traceable.
This is a posthoc re-evaluation; that trial's official status is unchanged
(stopped after the first assessment by plan) and it is not counted as a PASS.

## First cohort under this policy (2026-11-05)

[2026-11-05-lean-run-contract-gates](https://github.com/aussadawut-dev/lean-skills/blob/benchmark-archives/tests/results/2026-11-05-lean-run-contract-gates/README.md):
one High and one Critical trial, `gpt-6-astra` / `max`, 900 s per phase, no timeouts.

- **High: DONE** after one repair (1,111.8 s, 79,286 uncached input; +130.8% and
  +129.6% against the in-source-budget pilot). As in the previous cohort, the
  first implementation kept a caller's `dict` subclass (`Counter`), so batch commit
  added balances; review caught it and one repair fixed it.
- **Critical: FAILED** after two repairs (3,079.4 s, 185,599 uncached input; new
  baseline, not comparable). Admitted findings: F1 renumbered tenant rowids, F2
  UTF-16, C1 table-name case (mandatory probe), F3 temporary column rename
  breaking views. All four were fixed. The remaining blocker is C2: the repair
  stored a per-tenant rowid mapping in a persistent `_vault_rowids_*` table. The
  contract does not literally forbid added schema objects and no leak was
  demonstrated; treating it as a defect for the final pass was a disclosed
  coordinator interpretation approved by the user. The mandatory probe's schema
  check reports it in 180 cases.
- In the final pass the candidate declined C2 under lean-run's rule for
  mutually exclusive findings, arguing that dropping the durable mapping changes
  rowids after reopening. The reference meets both F1 and C2, so the conflict came
  from the candidate's architecture, not from the contract.

Lessons, both applied after this cohort by user decision: the Critical contract
now states schema immutability explicitly, since the probe already enforced it
([amendment](../results/2026-11-04-rls-policy-development/README.md#schema-immutability-amendment-2026-11-05));
and lean-run now tells implementers to copy caller-supplied containers into owned
plain built-in values and to include a subclass in boundary cases, a general form
of the repeated `dict`-subclass defect. Both change the frozen inputs, so the next
cohort is not comparable with this one.

## Second cohort under this policy (2026-11-05)

[2026-11-05-lean-run-schema-skill](https://github.com/aussadawut-dev/lean-skills/blob/benchmark-archives/tests/results/2026-11-05-lean-run-schema-skill/coordinator-notes.md):
High DONE after one repair (1,619.3 s, 97,672 uncached input; the first
implementation fixed the container defect but kept scalar subclasses). Critical
FAILED after two repairs (2,704.6 s, 176,611 uncached input; new baseline): the
mandatory probe went from 4 failures to 0 after the first repair, and the final
fix-only repair introduced a trigger-visible `last_insert_rowid()` that depends on
another tenant's audit rowid. Two findings were not contract-decided
(`sqlite_stat1`, new-row rowids); the contract now decides both.
