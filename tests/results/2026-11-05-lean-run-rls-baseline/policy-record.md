# Critical tenant-isolation policy: row-level security (development evidence)

Recorded 2026-11-04. Model-free local work after the
[SQL-source and phase-budget pilot](../2026-11-04-lean-run-in-source-budget/README.md).
No measured benchmark phase ran. The archived trial stays **FAILED** and is not
relabeled; nothing in earlier archives changed (462 hashes re-verified).

## Finding: the accumulated Critical gates contradict each other

The final review's F2 requires that outcomes never depend on another tenant's
values. The earlier F1 expectations (`critical_final_findings_probe.py`, and
historical tests that encode the same policy) require the opposite: reject when
a trigger's net write changes a foreign row, succeed when it restores it. Whether
the net value changed depends on the foreign row's original value.

`evidence/f1_pair_probe.py` replays the three F1 trigger sets with the foreign
balance seeded at 77 (the archived oracle) and 78. The archived candidate, which
passes F1, returns different outcomes for every pair, so it leaks the foreign
value through success/failure. No implementation can satisfy F1 as written and
F2 in general. Part of the Critical FAILED history is therefore attributable to
contradictory gates, not only to the skill or model. The lexical-rewrite
mechanism and the skill guidance that encouraged it remain real defects.

## Decision (user, 2026-11-04): hide foreign rows (row-level security)

During one tenant's transfer, other tenants' `accounts`, `transfers` and `audit`
rows behave as if absent. User SQL in triggers and views neither sees nor changes
them. New rows for another tenant, or any effect beyond the expected transfer,
reject the whole transaction. This is PostgreSQL row-level-security semantics:
invisible rows are skipped by reads/updates/deletes and new rows must pass the
policy check. `audit` is included because its rows copy receipt payloads and the
contract applies read isolation to receipts; leaving it visible let new rowids
and counters reveal other tenants' history.

Superseded expectations (record, do not silently waive):

All are listed exactly in [`superseded-expectations.json`](superseded-expectations.json):

- 75 historical failing subtests from the five prior final Critical workspaces
  (pilot, three critical-high rounds and the in-source-budget candidate). Each
  writes, deletes, counts or uniquely constrains other tenants' rows, so its
  native expectation depends on foreign data. Every one was read; none is a
  tenant-local path. The earlier triage of three TEXT→BLOB assertions is one
  instance of this class.
- 16 failed cases in six archived probes: `critical_final_findings` F1 net
  change; `audit_followup` and `preservation` foreign history/balance writes;
  `frame_followup` identical replacements of foreign rows and cross-tenant UNIQUE
  victims; `trigger_compatibility` foreign audit REPLACE victims; and
  `trigger_ignore_scope`, whose guard fires only on foreign rows.

Superseded entries are exact unittest headers or probe case identifiers, not
whole functions or probes. The runner reports a suite or probe whose failures are
all listed as policy-superseded, separately and never as passed; any unlisted
failure, import error or uncountable failure still blocks.

Replacement gate: [`tests/probes/rls_policy_probe.py`](../../probes/rls_policy_probe.py).
It runs 24 scenarios (A/B/R3 forms, the F1 trigger sets, foreign writes, deletes,
moves, inserts, counts and counters, cross-tenant UNIQUE REPLACE, own-row moves
into hidden rowids, local valid/aborting controls) with the foreign row at 777,
778 and absent, through the API and CLI. Its oracle is independent of the
candidate: native SQLite on a copy with foreign rows removed, then the policy
check in Python. Outcomes must match the oracle and be identical across the
triple; foreign rows must stay byte-, type- and rowid-identical.

Out of scope, disclosed rather than asserted: schema-level UNIQUE constraints
across tenants on value columns (restoring the hidden row can conflict), storage
size and timing channels. These are inherent; PostgreSQL RLS documents the same
class of covert channel.

## Evidence (SQLite 3.50.4, Python 3.14)

| Workspace | A/B/R3 repro | RLS probe | F1 pairs leak | Archived 23 probes |
| --- | --- | --- | --- | --- |
| archived candidate | fail | fail | 3/3 | 22/23 (`final_guard`) |
| + lexical patch (`lexical-patch/`) | pass | fail (81) | 3/3 | 23/23 |
| RLS prototype (`prototype/`) | pass | **pass** | **0/3** | 17/23; the 6 failing probes fail only superseded cases |

- The 4-point lexical patch makes every archived gate pass, its own suite 45/45
  and the original grader report zero issues, yet still leaks through all three F1
  pairs. Passing the accumulated gates did not establish isolation.
- The prototype (`prototype/vault_guard.py`, ~140 lines replacing 509) rewrites
  no user SQL. Inside the IMMEDIATE transaction it moves foreign rows into TEMP
  storage with CREATE TABLE AS (types preserved, counters untouched), recreates
  the original trigger definitions, compares typed visible effects with the
  expected transfer, relocates any own row occupying a hidden rowid, restores
  foreign rows with original rowids and the exact definitions. Foreign values
  never reach Python; any failure rolls back everything. Cost is O(foreign rows)
  per transfer, acceptable for the fixture; real systems should use engine RLS or
  per-tenant databases.
- Measurement correction: an earlier draft of this record reported the prototype
  at 22/23 archived probes. That count used exit codes only; several probes exit
  0 while reporting failed cases. With the runner's rule (exit 0 and no reported
  failures) the result is 17/23. The archived candidate and lexical patch counts
  are unchanged under that rule.
- These are development artifacts. They do not show that lean-run improved; only
  a fresh same-task benchmark from the original `initial/` fixture can.

## New Critical baseline (user decision, 2026-11-04)

The Critical `CONTRACT.md` in `tests/level_benchmark.py` now states the policy,
so implementers and reviewers receive it. That changes the task: the next
Critical cohort starts a new baseline and is not compared like-for-like with
earlier Critical quality or cost. High is unchanged and remains comparable.

`tests/repeated_benchmark.py prepare` supports this explicitly:

- `--contract-change critical --policy-record README.md` permits only
  `CONTRACT.md` to differ for that level and records both hashes; prompts and
  graders stay frozen, and an undeclared change is refused.
- `--superseded superseded-expectations.json` freezes the exact superseded list.
- The manifest inherits `regression_archives`, `coordinator_gate_levels` and the
  optimization target from the baseline, adding the baseline itself.
- The summarizer and pilot renderer mark the changed level as a new baseline
  and print no percentage change for it.

The original grader passes the prototype 9/9 under the changed contract.

Reproduce: `evidence/run_probes.py`, `evidence/abr3_probe.py`,
`evidence/f1_pair_probe.py` and `evidence/cross.py` take the archive and workspace
paths shown in their docstrings.
