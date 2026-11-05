# Three-level lean-run benchmark — 2026-11-03

Three synthetic tasks completed through independent review. Medium and high passed the first review; critical required one bounded repair after a HIGH-severity finding. This is one measured attempt per workload, not a statistical benchmark or a comparison against running without the skill.

Requested settings: **gpt-6-astra / max**, Codex CLI **0.166.0**, Python **3.14.3**, SQLite **3.50.4**, macOS. Procedure depth was standard for every level. Backend identity was not independently attested. The existing ChatGPT login was used; no API key or provider fallback was introduced.

| Level | Agent time (m:ss) | Input + output tokens | Cached input (included) | Reviewer issues: first → final | Repair rounds |
| --- | ---: | ---: | ---: | ---: | ---: |
| medium | 6:06 | 287,370 | 229,504 | 0 → 0 | 0 |
| high | 8:14 | 323,414 | 267,136 | 0 → 0 | 0 |
| critical | 19:00 | 1,142,053 | 993,024 | 1 → 0 | 1 |

Total: **33:19** measured agent time, **1,752,837** input-plus-output tokens, of which **1,489,664** were cached input. Uncached input plus output was **263,173**; this is a count, not a billing-price estimate.

## Workloads and issue counts

| Level | Task | Frozen checks | Failing categories before → after |
| --- | --- | ---: | ---: |
| medium | Strict integer-list CLI | 4 | 3 → 0 |
| high | Atomic, idempotent batch ledger | 6 | 5 → 0 |
| critical | Tenant isolation and transactional SQLite transfers | 9 | 8 → 0 |

A frozen check is a predefined contract category, which may contain several assertions. Reviewer findings are distinct demonstrated root causes. These measures overlap and must not be summed as if they represented disjoint bugs. All supplied files, contracts and skill copies remained intact.

## Critical: a real first-pass miss

The first candidate passed the frozen 9-category grader and its 29 tests. Independent review nevertheless returned **REWORK**, finding that `RAISE(IGNORE)` triggers could suppress a debit, receipt or audit write while the transfer returned success. This could create value, omit the audit record, or allow a replay to debit again. These manifestations were counted as **one HIGH-severity root cause (F1)**.

Critical's first implementation plus review took **13:19** and **654,045 tokens**. Repair plus renewed review added **5:41** and **488,008 tokens**. The initial miss is retained, rather than presenting critical as a first-pass success.

The coordinator independently reproduced suppression at all four write points using [the supplemental probe](critical/supplemental_probe.py). The repair checks affected-row counts and raises a storage error inside the transaction. All four supplemental probes then passed with complete rollback and unchanged triggers; 33 project tests passed, and a fresh reviewer returned PASS. The frozen grader was never changed to accommodate the result.

- [First review and F1](critical/review/final.txt)
- [Supplemental evidence before repair](critical/supplemental-before-repair.json)
- [Supplemental evidence after repair](critical/supplemental-after-repair.json)
- [Renewed independent review](critical/review-2/final.txt)
- [Final critical source](critical/final-workspace/vault.py)

## Measurement and evidence

Each phase used a fresh ephemeral CLI session with the same requested model/effort. Levels ran sequentially, with plugins/apps/nested agents disabled and one supplied standalone lean-run package. The coordinator supplied independent review outside each implementation session. Reviewers received requirements and source snapshots, not the author’s conclusions or hidden grader results. The renewed reviewer additionally received the previous independent finding. Task-wide REWORK count remained 1.

Time is measured with a monotonic clock around each CLI process and includes startup, model processing and tool execution. The main table sums implementation, review, repair and renewed review. It excludes coordinator chat, fixture preparation, grading, reporting and the transport preflight. The CSV also records the full span between first launch and final completion, including coordinator gaps. Thus the table is not total elapsed time for the entire user chat.

Tokens come from raw `turn.completed.usage` events, not estimates from text length. Total is input plus output; cached input is included in input, and reasoning output is not added again to output. See [Codex non-interactive usage events](https://learn.chatgpt.com/docs/non-interactive-mode) and [output token accounting](https://developers.openai.com/api/docs/guides/token-counting). All eight phase totals were recomputed directly from their archived events and matched the saved metrics. No phase timed out. A 900-second wall-time limit was configured; no hard token cap was enforced.

The separate transport preflight used 11,200 tokens and 6.214 seconds and is excluded from workload totals. An earlier launcher exited without runtime events; its usage is unavailable. Coordinator token usage is also unavailable and is not included.

## Artifacts and reproducibility

- [Summary JSON](summary.json), [summary CSV](summary.csv), [per-phase CSV](phases.csv), [raw-usage integrity checks](metric-integrity.json).
- [Frozen manifest](manifest.json), [exact preparation-time generator](generator-at-prepare.py), [frozen evaluator](grader.py), and [final harness snapshot](harness-final.py).
- Each level retains initial/final files, prompts, skill copies, hashes, grading output, CLI JSONL events, stderr, usage metrics and review results. For critical, `workspace/` preserves the first candidate and `final-workspace/` preserves the repaired candidate.
- [Harness validation](validation.json): 11 repository unit/fixture tests and 34 installation scenarios passed, including collection discovery after adding the archive; no LLM call is part of those tests. [Usage protocol](../../behavioral.md#three-level-time-token-and-defect-benchmark) and [reusable runner](../../level_benchmark.py).

The fixture definitions, evaluator and skill snapshot were frozen before measured execution. The runner subsequently gained review preparation and model/effort arguments without changing these fixtures or the frozen grader; exact commands are retained per phase.

## Limits

One run per level gives no estimate of variance. Order was medium → high → critical and prompt caches were not reset. The tasks differ in complexity, so elapsed/token differences do not establish skill efficiency or superiority over other workflows/models. The experiment tests standalone lean-run with coordinator-supplied review, not its autonomous nested delegation routing.

All applications and data were local synthetic fixtures. No production release, real payment, identity provider, disk-full test, abrupt process termination or power-loss recovery was exercised. Workspace-write sandboxing constrained writes; evaluator read boundaries were instructional, not an OS-enforced information barrier. Findings and PASS apply only to the assessed contracts and evidence.
