# lean-run High and Critical pilot

**Requested target not met in this sample.** 1/2 trials passed quality, 1/2 passed quality with complete telemetry.

Each level has one archived observation and one new observation. The pilot is descriptive. Differences also reflect the observed repair paths, quality outcomes and gate coverage.

Target checks for High and the shared gates. uncached input reduced UNMET, all trial quality passed UNMET, all measurements complete PASS.

## Workflow comparison

| Level | Baseline n → pilot n | Workflow time | Change | Uncached input | Change | Uncached input + output | Change |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| High | 1 → 1 | 8:02 → 18:32 | +130.8% | 34,527 → 79,286 | +129.6% | 49,045 → 109,114 | +122.5% |
| Critical (new baseline) | 1 → 1 | 63:20 → 51:19 | not comparable | 229,009 → 185,599 | not comparable | 324,637 → 290,949 | not comparable |

Workflow time sums implementation, all reviews and any repairs. Uncached input is input minus cached input. Reported output already includes reasoning. Unknown usage makes the corresponding total and mean unknown. A single observation has no sample standard deviation.

| Level | Phase | Baseline time (s) | Pilot time (s) | Difference (s) |
| --- | --- | ---: | ---: | ---: |
| High | implementation | 310.4 | 257.3 | -53.1 |
| High | repair-1 | 0.0 | 465.8 | +465.8 |
| High | repair-2 | 0.0 | 0.0 | +0.0 |
| High | reviews | 171.2 | 388.7 | +217.5 |
| Critical | implementation | 503.6 | 739.7 | +236.1 |
| Critical | repair-1 | 884.6 | 703.1 | -181.5 |
| Critical | repair-2 | 814.0 | 501.9 | -312.1 |
| Critical | reviews | 1597.6 | 1134.7 | -462.9 |

Repairs that did not run contribute zero time. The review row combines initial and renewed reviews.

## Quality and execution

| Trial | Outcome | Quality | Final blockers | Incomplete phases | Independent findings by review | Repairs |
| --- | --- | --- | --- | --- | --- | ---: |
| [round-1/high](round-1/high/assessment-2.json) | DONE | PASS | None | None | 1 → 0 | 1 |
| [round-1/critical](round-1/critical/assessment-3.json) | FAILED | FAILED | independent_review, mandatory_probes | None | 2 → 1 → 1 | 2 |

| Final quality signal | Historical selected levels | Pilot |
| --- | ---: | ---: |
| Original grader category failures | 0 | 0 |
| Independent findings | 2 | 1 |
| Coordinator findings | 0 | 0 |
| Original supplemental issues | 0 | 0 |
| Additional mandatory probe failed cases | 0 | 180 |
| Post-run probe failed cases | 3 | 0 |
| Advisory probe failed cases (not gates) | 0 | 141 |
| High original grader category checks | 6 | 6 |
| Critical original grader category checks | 9 | 9 |

Historical quality passes by level were High 1/1, Critical 0/1.

Findings and failed cases are different units and can overlap. The Critical CONTRACT.md changed by a recorded policy decision ([policy record](policy-record.md)); that level starts a new baseline, so its comparison with the prior archive is not like-for-like. Other initial files, public tests, prompts and graders are unchanged. Historical expectations superseded by that policy are listed in [superseded expectations](superseded-expectations.json) and reported separately, never as passed. Under the [contract gate policy](../../benchmark/README.md), the original grader, independent review, protected-file integrity and the mandatory probes (critical_contract_probe.py) block; the other 24 probes and the historical suites run as advisory reports. A reference solution passed every mandatory gate before launch ([reference check](reference-check.json)). A clean original grade alone cannot pass the expanded gates. [Manifest](manifest.json)

Every assessment runs historical tests against the candidate and candidate tests against each retained historical workspace for the same level. Sources are [2026-11-04-lean-run-in-source-budget](../2026-11-04-lean-run-in-source-budget/README.md), [2026-11-04-lean-run-critical-high-pilot](../2026-11-04-lean-run-critical-high-pilot/README.md), [2026-11-04-lean-run-critical-high](../2026-11-04-lean-run-critical-high/README.md). Under the contract gate policy these suites are advisory. The reverse runs are diagnostic.

| Final assessment | Historical suites failing on candidate | Candidate suite failing on historical workspaces |
| --- | ---: | ---: |
| High round 1 | 0/5 | 2/5 |
| Critical round 1 | 5/5 | 5/5 |

Remaining **Critical C2 (MEDIUM)** at `vault.py:215-221 (_merge_ledger)`. Under the user-approved C2 interpretation, transfers must not add persistent schema objects. [Reproduction and suggested fix](round-1/critical/review-3/final.txt)

The frozen lean-run procedure permits two repairs, including a final fix-only pass. It states “unresolved mandatory findings mean FAILED”. The remaining mandatory findings keep the trial FAILED after the final review.

## Recorded consumption

The 2 pilot trials launched 10 measured phases. They used **69:51 agent time**, **3,624,639 total tokens**, **264,885 uncached input** and **400,063 uncached input + output**. All launched implementation, review and repair phases count, including failed or timed-out work.

| Trial | Baseline timeouts | Pilot timeouts |
| --- | --- | --- |
| High | None | None |
| Critical | None | None |

The candidate harness exposed each phase’s existing deadline to the agent. The frozen skill’s budget helper can report the remaining time and advise when to narrow work or finish. The helper is cooperative. The harness still enforces the same process timeout.

Both cohorts requested **gpt-6-astra / max** with a **900-second per-phase cap**. Phases ran serially with fresh implementation and independent review contexts. Cache state and remote load were uncontrolled. Coordinator time, preparation, evaluation probes and reporting sit outside the CLI phase totals.

[Summary](summary.json), [comparison CSV](comparison.csv), [trials](trials.csv), [phases](phases.csv), [usage integrity](metric-integrity.json), [control audit](control-audit.json), [controls](controls.json), [previous report](../2026-11-04-lean-run-in-source-budget/README.md).
