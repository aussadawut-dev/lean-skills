# lean-run before/after benchmark — 2026-11-03

The optimized entrypoint is **46.50% shorter in characters**. In this measured comparison, full workflow time fell **3.02%** and total input-plus-output tokens fell **9.21%**, with the same final contract and independent-review outcomes. Results are mixed: medium became slower and used more total tokens, while **uncached input plus output increased 17.23% overall**. These data do not establish a billing-cost reduction or a statistically reliable speedup.

The candidate was frozen before testing. All three original tasks, initial files, first implementation/review prompts, model/effort (`gpt-6-astra / max`), runtime controls and frozen graders were retained. Eight fresh measured phases ran sequentially, including critical repair and renewed review in both versions.

## Full workflow results

Time includes implementation, review and required repair/review. Token totals include cached input. A negative change means a reduction.

| Level | Time before → after | Change | Total tokens before → after | Change |
| --- | ---: | ---: | ---: | ---: |
| medium | 6:06 → 6:19 | +3.61% | 287,370 → 314,570 | +9.47% |
| high | 8:14 → 7:23 | -10.34% | 323,414 → 290,617 | -10.14% |
| critical | 19:00 → 18:37 | -1.97% | 1,142,053 → 986,158 | -13.65% |
| **Total** | **33:19 → 32:19** | **-3.02%** | **1,752,837 → 1,591,345** | **-9.21%** |

Medium implementation fell from 233.859 to 213.351 seconds, but independent review rose from 132.076 to 165.803 seconds and consumed more tokens. Both high phases improved in elapsed time and total tokens. Critical first-pass implementation/review improved, while its repair and renewed review together took longer. The aggregate gain therefore does not apply to every level or phase.

## Cache-sensitive counts

Cached input is already included in total input; reasoning output is already included in output. Do not add either again. The cache mix differed between runs and was not controlled. Uncached input plus output is a count, not a price estimate.

| Level | Cached input before → after | Uncached input + output before → after | Change in uncached + output |
| --- | ---: | ---: | ---: |
| medium | 229,504 → 257,920 | 57,866 → 56,650 | -2.10% |
| high | 267,136 → 218,624 | 56,278 → 71,993 | +27.92% |
| critical | 993,024 → 806,272 | 149,029 → 179,886 | +20.71% |
| **Total** | **1,489,664 → 1,282,816** | **263,173 → 308,529** | **+17.23%** |

## Quality and repairs

| Level | Frozen categories | Initial → final failing categories, both versions | Independent issues first → final, before | Independent issues first → final, after |
| --- | ---: | ---: | ---: | ---: |
| medium | 4 | 3 → 0 | 0 → 0 | 0 → 0 |
| high | 6 | 5 → 0 | 0 → 0 | 0 → 0 |
| critical | 9 | 8 → 0 | 1 → 0 | 1 → 0 |

All 19 frozen categories passed in each final candidate; protected files and review workspaces remained unchanged. Fresh independent reviewers ended with PASS and no remaining findings. Counts are requirement categories or distinct reviewer root causes, not raw assertions; overlapping counts must not be added.

Critical had the **same HIGH-severity F1** in both first passes: SQLite `RAISE(IGNORE)` could silently suppress a required write while the operation returned success. Both versions required one repair. The optimized run retained its failed first candidate and repaired all four required writes with affected-row checks. The exact historical supplemental probe then passed for debit, credit, receipt and audit; a new independent reviewer verified rollback, preserved triggers, CLI behavior and durable replay.

Critical first-pass time changed **13:19 → 12:23**, and tokens **654,045 → 537,802**. Repair plus renewed review changed **5:41 → 6:14**, and tokens **488,008 → 448,356**. All of that repair cost is included above.

Historical regression suites also ran against the new final implementations, and new suites against the historical final implementations. High and critical passed in both directions. Medium's historical suite retained four failing subcase assertions requiring the literal word `argument`; the new useful arity message says `expected exactly one comma-separated integer list`. The contract requires useful stderr and correct exit/stdout/traceback behavior, all of which passed, but specifies no keyword. [The raw failure](medium/old_tests_on_new_code.log) and [contract-based adjudication](medium/cross-assessment.json) remain intact. No test or candidate was changed to hide it. The reverse medium suite passed.

## What changed in the skill

- Reduced the entrypoint from 16,484 to 8,819 characters (2,365 to 1,159 whitespace-delimited words). These are source-size measurements, not token estimates.
- Moved detailed exploratory questioning and provider delegation into references read only for those tasks. The handoff reference is unchanged; the package still works alone.
- Added guidance for bounded logs, focused reads, batching independent work, compact requirement-based regression checks and observable state/failure evidence.
- Retained authorization boundaries, integrated validation, fresh independent review for HIGH risk, task-wide repair limits and delivery requirements. An [independent static review](skill-review.json) found no substantive regression; live benchmark outcomes above provide the separate behavioral evidence.

## Evidence and limitations

One measured run per level and version gives no estimate of variance. Order, server load and prompt caches were not randomized or reset. A 3.02% observed time reduction is not proof of a repeatable speedup. No tested acceptance or review threshold was relaxed; successful results cover these tasks, not all future workloads. These trials do not exercise autonomous nested delegation or real deployments.

Measured totals exclude coordinator chat, static skill review, preparation, grading, cross-regression checks and reporting. Coordinator token usage is unavailable. These are workflow-agent metrics, not total chat elapsed time or full account usage. All phase metrics were recomputed from raw usage events; all eight processes completed without timeout. Requested backend model identity is not independently attested.

- [Detailed methods](methods.md), [comparison CSV](comparison.csv), [comparison JSON](comparison.json), [per-phase CSV](phases.csv), [candidate summary](summary.json).
- [Unchanged-input controls](comparison-controls.json), [frozen manifest](manifest.json), [raw-usage verification](metric-integrity.json), [unchanged baseline archive check](baseline-integrity.json), [repository validation](validation.json).
- [Original baseline report](../2026-11-03-level-benchmark/README.md).
- Critical: [first review](critical/review/final.txt), [first-pass supplemental failure](critical/supplemental-post-implementation.json), [repaired supplemental result](critical/supplemental-final.json), [final review](critical/review-2/final.txt), [repair history](critical/repair-history.json).
- Each level retains initial and final workspaces, exact prompts, skill copies, grading output, raw events, stderr and metrics. Critical additionally retains `first-pass-workspace/` and `reviewspace-first/`; its `workspace/` contains the repaired final code.
