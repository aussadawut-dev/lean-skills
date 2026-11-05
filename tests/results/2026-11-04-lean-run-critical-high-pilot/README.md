# lean-run High and Critical pilot

**Requested target not met in this sample.** 1/2 trials passed quality, 1/2 passed quality with complete telemetry.

Historical means include failed attempts and elapsed time at the timeout cap. The pilot is descriptive. Differences also reflect the observed repair paths, quality outcomes and gate coverage.

## Workflow comparison

| Level | Baseline n → pilot n | Workflow time | Change | Uncached input | Change | Uncached input + output | Change |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| High | 3 → 1 | 9:48 → 8:00 | -18.3% | 43,579 → 46,162 | +5.9% | 60,820 → 62,295 | +2.4% |
| Critical | 3 → 1 | 53:35 → 48:11 | -10.1% | UNKNOWN → UNKNOWN | UNKNOWN | UNKNOWN → UNKNOWN | UNKNOWN |

Workflow time sums implementation, all reviews and any repairs. Uncached input is input minus cached input. Reported output already includes reasoning. Unknown usage makes the corresponding total and mean unknown. A single observation has no sample standard deviation.

| Level | Phase | Baseline mean (s) | Pilot mean (s) | Difference (s) |
| --- | --- | ---: | ---: | ---: |
| High | implementation | 440.5 | 314.9 | -125.6 |
| High | repair-1 | 0.0 | 0.0 | +0.0 |
| High | repair-2 | 0.0 | 0.0 | +0.0 |
| High | reviews | 147.3 | 165.1 | +17.7 |
| Critical | implementation | 741.7 | 570.2 | -171.5 |
| Critical | repair-1 | 900.0 | 900.0 | -0.0 |
| Critical | repair-2 | 636.5 | 426.7 | -209.8 |
| Critical | reviews | 936.6 | 993.6 | +57.0 |

Repairs that did not run contribute zero time. The review row combines initial and renewed reviews.

## Quality and execution

| Trial | Outcome | Quality | Final blockers | Incomplete phases | Independent findings by review | Repairs |
| --- | --- | --- | --- | --- | --- | ---: |
| [round-1/high](round-1/high/assessment-1.json) | DONE | PASS | None | None | 0 | 0 |
| [round-1/critical](round-1/critical/assessment-3.json) | FAILED | FAILED | independent_review | repair-1 | 1 → 2 → 1 | 2 |

| Final quality signal | Historical selected levels | Pilot |
| --- | ---: | ---: |
| Original grader category failures | 0 | 0 |
| Independent findings | 3 | 1 |
| Coordinator findings | 1 | 0 |
| Original supplemental issues | 0 | 0 |
| Additional mandatory probe failed cases | 0 | 0 |
| Post-run probe failed cases | 6 | 0 |

Historical quality passes by level were High 3/3, Critical 0/3.

Findings and failed cases are different units and can overlap. The original benchmark tasks, public tests, initial implementation/review prompts and graders are unchanged. Independent review, protected-file integrity and historical regressions remain mandatory. Critical runs 18 frozen probe scripts at each assessment. A clean original grade alone cannot pass the expanded gates. [Manifest](manifest.json)

Remaining **Critical R3-F1 (HIGH)** at `integrity.py:181-220 (_native_mode), integrity.py:351`. Preserve native recursive_triggers visibility and SQL name resolution. Audit failures must propagate and roll back all transfer effects; harmless guards must succeed. [Reproduction and suggested fix](round-1/critical/review-3/final.txt)

The frozen lean-run procedure permits two repairs, including a final fix-only pass. It states “unresolved mandatory findings mean FAILED”. The remaining finding therefore keeps this trial FAILED after the final review. [Frozen skill](round-1/critical/initial/.agents/skills/lean-run/SKILL.md)

| [critical_final_findings_probe.py](critical_final_findings_probe.py) | Failed cases / executed |
| --- | ---: |
| [Historical Critical round 1](baseline-1-critical-final-findings.json) | 5/6 |
| [Historical Critical round 2](baseline-2-critical-final-findings.json) | 4/6 |
| [Historical Critical round 3](baseline-3-critical-final-findings.json) | 3/6 |
| [Pilot Critical round 1](round-1/critical/assessment-3.json) | 0/6 |

This probe reproduces findings from the preceding cohort. The historical replays are separate from the archived baseline grades.

### Name-resolution follow-up

A command in the first Critical repair log exposed name-resolution errors involving CTEs and schema-qualified pragmas. The coordinator reproduced the cases after discovery. This follow-up is separate from the frozen Critical probes and the archived baseline grades. [Discovery and replay protocol](name-resolution-protocol.json)

| Workspace | Failed cases / executed |
| --- | ---: |
| [Historical Critical round 1](baseline-1-name-resolution.json) | 2/4 |
| [Historical Critical round 2](baseline-2-name-resolution.json) | 1/4 |
| [Historical Critical round 3](baseline-3-name-resolution.json) | 0/4 |
| [Pilot Critical after first repair](repair-1-name-resolution.json) | 3/4 |
| [Pilot Critical round 1 final](round-1/critical/assessment-3.json) | 0/4 |

## Recorded consumption

The 2 pilot trials launched 8 measured phases. They used **56:10 agent time**, **UNKNOWN total tokens**, **UNKNOWN uncached input** and **UNKNOWN uncached input + output**. All launched implementation, review and repair phases count, including failed or timed-out work.

Unknown usage phases are round-1/critical/repair-1 (15:00). Reported usage gives a lower bound of 2,038,394 total tokens, 249,047 uncached input and 320,762 uncached input + output.

The timed-out repair was retained and independently assessed without relaunching it. Its elapsed cost remains included and its unreported usage remains unknown. The final repair brief explicitly restated the existing 900-second cap after that timeout. [Timeout continuation](timeout-retention.json)

Both cohorts requested **gpt-6-astra / max** with a **900-second per-phase cap**. Phases ran serially with fresh implementation and independent review contexts. Cache state and remote load were uncontrolled. Coordinator time, preparation, evaluation probes and reporting sit outside the CLI phase totals.

[Summary](summary.json), [comparison CSV](comparison.csv), [trials](trials.csv), [phases](phases.csv), [usage integrity](metric-integrity.json), [control audit](control-audit.json), [controls](controls.json), [previous report](../2026-11-04-lean-run-critical-high/README.md).
