# Coordinator notes

Cohort prepared 2026-11-05 from [contract-gates](../2026-11-05-lean-run-contract-gates/README.md)
with two frozen-input changes: the Critical contract states schema immutability
(new baseline, [amendment](../2026-11-04-rls-policy-development/README.md#schema-immutability-amendment-2026-11-05)),
and lean-run asks for owned plain built-in copies of caller-supplied containers.
Contract gate policy; `gpt-6-astra` / `max`; 900 s per phase; no timeouts.

## High: DONE, one repair

The first implementation passed the grader 6/6 and no longer kept a `dict`
subclass. Review found R1 (an `int` subclass overriding `__le__` let amount -1
through) and R2 (a `UserString` field name raised `TypeError`). Both reproduced
on the candidate and on the initial fixture and trace to "amount a positive int"
and "Reject invalid values ... with ValueError"; both were admitted
([request](round-1/high/repair-1-request.json)). One repair fixed both.
The new skill rule named containers only; the candidate followed it literally.

## Critical: FAILED after two repairs

- Assessment 1 ([record](round-1/critical/assessment-1-coordinator.json)):
  grader 9/9; mandatory probe 4 failures (`renamed_table_case`, foreign rows
  changed) admitted as C1; R2 (sparse rowids) and R3 (external-content FTS5)
  admitted; R1 (`sqlite_stat1` population) rejected, because the native
  tenant-only oracle and the reference behave like the candidate.
- Assessment 2 ([record](round-1/critical/assessment-2-coordinator.json)):
  mandatory probe 0 failures; renewed R2 admitted only for existing sparse
  rowids in `transfers`/`audit`. Its new-audit-rowid collision manifestation
  was set aside as the F1/F2 class, with a scope note in the request.
- Assessment 3 ([record](round-1/critical/assessment-3-coordinator.json)):
  mandatory probe 0 failures; R3 admitted. The final repair kept globally
  allocated rowids visible to triggers, so `last_insert_rowid()` logged 1,42
  with a foreign audit row at rowid 40 (1,2 without one). The pre-repair
  candidate and the reference log 1,2 in every variant. Unresolved after the
  fix-only pass, so the trial is FAILED.

## Changes made after this cohort

lean-run's rule now covers every caller-supplied value (scalars, keys and field
names as well as containers). The Critical contract now states that non-ledger
tables, including statistics tables, are native; existing rows keep their
rowids; the physical rowid of a new row is outside scope, but rowids, counters
and outcomes that triggers observe must not depend on other tenants' rows
([scope amendment](../2026-11-04-rls-policy-development/README.md#scope-amendment-2026-11-05)).
