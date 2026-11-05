# lean-run High and Critical pilot

**Requested target not met in this sample.** 1/2 trials passed quality, 1/2 passed quality with complete telemetry.

Each level has one archived observation and one new observation. The pilot is descriptive. Differences also reflect the observed repair paths, quality outcomes and gate coverage.

Target checks for High and the shared gates. uncached input reduced UNMET, all trial quality passed UNMET, all measurements complete PASS.

## Workflow comparison

| Level | Baseline n → pilot n | Workflow time | Change | Uncached input | Change | Uncached input + output | Change |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| High | 1 → 1 | 18:32 → 26:59 | +45.7% | 79,286 → 97,672 | +23.2% | 109,114 → 141,996 | +30.1% |
| Critical (new baseline) | 1 → 1 | 51:19 → 45:05 | not comparable | 185,599 → 176,611 | not comparable | 290,949 → 265,859 | not comparable |

Workflow time sums implementation, all reviews and any repairs. Uncached input is input minus cached input. Reported output already includes reasoning. Unknown usage makes the corresponding total and mean unknown. A single observation has no sample standard deviation.

| Level | Phase | Baseline time (s) | Pilot time (s) | Difference (s) |
| --- | --- | ---: | ---: | ---: |
| High | implementation | 257.3 | 334.7 | +77.4 |
| High | repair-1 | 465.8 | 347.9 | -117.9 |
| High | repair-2 | 0.0 | 0.0 | +0.0 |
| High | reviews | 388.7 | 936.7 | +548.1 |
| Critical | implementation | 739.7 | 798.1 | +58.4 |
| Critical | repair-1 | 703.1 | 539.4 | -163.7 |
| Critical | repair-2 | 501.9 | 247.0 | -254.9 |
| Critical | reviews | 1134.7 | 1120.2 | -14.5 |

Repairs that did not run contribute zero time. The review row combines initial and renewed reviews.

## Quality and execution

| Trial | Outcome | Quality | Final blockers | Incomplete phases | Independent findings by review | Repairs |
| --- | --- | --- | --- | --- | --- | ---: |
| [round-1/high](round-1/high/assessment-2.json) | DONE | PASS | None | None | 2 → 0 | 1 |
| [round-1/critical](round-1/critical/assessment-3.json) | FAILED | FAILED | independent_review | None | 3 → 1 → 1 | 2 |

| Final quality signal | Historical selected levels | Pilot |
| --- | ---: | ---: |
| Original grader category failures | 0 | 0 |
| Independent findings | 1 | 1 |
| Coordinator findings | 0 | 0 |
| Original supplemental issues | 0 | 0 |
| Additional mandatory probe failed cases | 180 | 0 |
| Post-run probe failed cases | 0 | 0 |
| Advisory probe failed cases (not gates) | 141 | 25 |
| High original grader category checks | 6 | 6 |
| Critical original grader category checks | 9 | 9 |

Historical quality passes by level were High 1/1, Critical 0/1.

Findings and failed cases are different units and can overlap. The Critical CONTRACT.md changed by a recorded policy decision ([policy record](policy-record.md)); that level starts a new baseline, so its comparison with the prior archive is not like-for-like. Other initial files, public tests, prompts and graders are unchanged. Historical expectations superseded by that policy are listed in [superseded expectations](superseded-expectations.json) and reported separately, never as passed. Under the [contract gate policy](../../benchmark/README.md), the original grader, independent review, protected-file integrity and the mandatory probes (critical_contract_probe.py) block; the other 24 probes and the historical suites run as advisory reports. A reference solution passed every mandatory gate before launch ([reference check](reference-check.json)). A clean original grade alone cannot pass the expanded gates. [Manifest](manifest.json)

Every assessment runs historical tests against the candidate and candidate tests against each retained historical workspace for the same level. Sources are [2026-11-05-lean-run-contract-gates](../2026-11-05-lean-run-contract-gates/README.md), [2026-11-04-lean-run-in-source-budget](../2026-11-04-lean-run-in-source-budget/README.md), [2026-11-04-lean-run-critical-high-pilot](../2026-11-04-lean-run-critical-high-pilot/README.md), [2026-11-04-lean-run-critical-high](../2026-11-04-lean-run-critical-high/README.md). Under the contract gate policy these suites are advisory. The reverse runs are diagnostic.

| Final assessment | Historical suites failing on candidate | Candidate suite failing on historical workspaces |
| --- | ---: | ---: |
| High round 1 | 0/6 | 6/6 |
| Critical round 1 | 6/6 | 6/6 |

Remaining **Critical R3 (HIGH)** at `vault.py:95-101 (_isolate), vault.py:222-223 (receipt/audit import)`. No trigger-visible counter or transfer outcome may depend on another tenant's rows. [Reproduction and suggested fix](round-1/critical/review-3/final.txt)

The frozen lean-run procedure permits two repairs, including a final fix-only pass. It states “unresolved mandatory findings mean FAILED”. The remaining mandatory findings keep the trial FAILED after the final review.

## Recorded consumption

The 2 pilot trials launched 10 measured phases. They used **72:04 agent time**, **3,076,015 total tokens**, **274,283 uncached input** and **407,855 uncached input + output**. All launched implementation, review and repair phases count, including failed or timed-out work.

| Trial | Baseline timeouts | Pilot timeouts |
| --- | --- | --- |
| High | None | None |
| Critical | None | None |

The candidate harness exposed each phase’s existing deadline to the agent. The frozen skill’s budget helper can report the remaining time and advise when to narrow work or finish. The helper is cooperative. The harness still enforces the same process timeout.

Both cohorts requested **gpt-6-astra / max** with a **900-second per-phase cap**. Phases ran serially with fresh implementation and independent review contexts. Cache state and remote load were uncontrolled. Coordinator time, preparation, evaluation probes and reporting sit outside the CLI phase totals.

[Summary](summary.json), [comparison CSV](comparison.csv), [trials](trials.csv), [phases](phases.csv), [usage integrity](metric-integrity.json), [control audit](control-audit.json), [controls](controls.json), [previous report](../2026-11-05-lean-run-contract-gates/README.md).
