# lean-run High and Critical pilot

**Requested target not met in this sample.** 1/2 trials passed quality, 1/2 passed quality with complete telemetry.

Each level has one archived observation and one new observation. The pilot is descriptive. Differences also reflect the observed repair paths, quality outcomes and gate coverage.

Target checks for High and the shared gates. uncached input reduced PASS, all trial quality passed UNMET, all measurements complete PASS.

## Workflow comparison

| Level | Baseline n → pilot n | Workflow time | Change | Uncached input | Change | Uncached input + output | Change |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| High | 1 → 1 | 8:00 → 8:02 | +0.3% | 46,162 → 34,527 | -25.2% | 62,295 → 49,045 | -21.3% |
| Critical | 1 → 1 | 48:11 → 63:20 | +31.5% | UNKNOWN → 229,009 | UNKNOWN | UNKNOWN → 324,637 | UNKNOWN |

Workflow time sums implementation, all reviews and any repairs. Uncached input is input minus cached input. Reported output already includes reasoning. Unknown usage makes the corresponding total and mean unknown. A single observation has no sample standard deviation.

| Level | Phase | Baseline time (s) | Pilot time (s) | Difference (s) |
| --- | --- | ---: | ---: | ---: |
| High | implementation | 314.9 | 310.4 | -4.5 |
| High | repair-1 | 0.0 | 0.0 | +0.0 |
| High | repair-2 | 0.0 | 0.0 | +0.0 |
| High | reviews | 165.1 | 171.2 | +6.1 |
| Critical | implementation | 570.2 | 503.6 | -66.6 |
| Critical | repair-1 | 900.0 | 884.6 | -15.5 |
| Critical | repair-2 | 426.7 | 814.0 | +387.3 |
| Critical | reviews | 993.6 | 1597.6 | +604.0 |

Repairs that did not run contribute zero time. The review row combines initial and renewed reviews.

## Quality and execution

| Trial | Outcome | Quality | Final blockers | Incomplete phases | Independent findings by review | Repairs |
| --- | --- | --- | --- | --- | --- | ---: |
| [round-1/high](round-1/high/assessment-1.json) | DONE | PASS | None | None | 0 | 0 |
| [round-1/critical](round-1/critical/assessment-3.json) | FAILED | FAILED | independent_review, historical_regressions, posthoc_quality_probes | None | 2 → 3 → 2 | 2 |

| Final quality signal | Historical selected levels | Pilot |
| --- | ---: | ---: |
| Original grader category failures | 0 | 0 |
| Independent findings | 1 | 2 |
| Coordinator findings | 0 | 0 |
| Original supplemental issues | 0 | 0 |
| Additional mandatory probe failed cases | 0 | 0 |
| Post-run probe failed cases | 0 | 3 |
| High original grader category checks | 6 | 6 |
| Critical original grader category checks | 9 | 9 |

Historical quality passes by level were High 1/1, Critical 0/1.

Findings and failed cases are different units and can overlap. The original benchmark tasks, public tests, initial implementation/review prompts and graders are unchanged. Independent review, protected-file integrity and historical regressions remain mandatory. Critical runs 20 frozen probe scripts at each assessment. A clean original grade alone cannot pass the expanded gates. [Manifest](manifest.json)

The quality table reports each run’s original gate outcomes. The targeted replays below apply the same new cases to both workspaces.

Every assessment runs historical tests against the candidate and candidate tests against each retained historical workspace for the same level. Sources are [2026-11-04-lean-run-critical-high-pilot](../2026-11-04-lean-run-critical-high-pilot/README.md), [2026-11-04-lean-run-critical-high](../2026-11-04-lean-run-critical-high/README.md). Historical tests on the candidate are a mandatory gate. The reverse runs are diagnostic.

| Final assessment | Historical suites failing on candidate | Candidate suite failing on historical workspaces |
| --- | ---: | ---: |
| High round 1 | 0/4 | 0/4 |
| Critical round 1 | 2/4 | 4/4 |

The three failed final historical assertions expected an exception for foreign TEXT-to-BLOB updates. The candidate instead scoped those updates to zero rows, committed the required transfer and preserved the old typed values, schema and replay. These are recorded outcome incompatibilities, not evidence of persisted corruption in those three cases. The historical failures remain unwaived; the independent findings still block acceptance. [Typed-state triage](historical-assertion-triage.json), [raw comparison](typed_scope_triage.json).

Remaining **Critical F2 (HIGH)** at `vault_guard.py:222-236 and vault_guard.py:394-404`. Every account read, including trigger expressions and write predicates, must remain within the authenticated tenant. [Reproduction and suggested fix](round-1/critical/review-3/final.txt)

Remaining **Critical R3 (MEDIUM)** at `vault_guard.py:161-177`. Preserve valid tenant-local trigger behavior and successful transfers. [Reproduction and suggested fix](round-1/critical/review-3/final.txt)

The frozen lean-run procedure permits two repairs, including a final fix-only pass. It states “unresolved mandatory findings mean FAILED”. The remaining mandatory findings keep the trial FAILED after the final review.

| [in_source_probe.py](in_source_probe.py) | Failed cases / executed |
| --- | ---: |
| [Historical Critical round 1](baseline-1-in_source_probe.json) | 6/6 |
| [Pilot Critical round 1](round-1/critical/assessment-3.json) | 0/6 |

This probe replays the immediately preceding pilot’s final Critical finding for plain and schema-qualified SQLite IN table sources and NOT INDEXED, with aborting and harmless audit guards.

The historical replays are separate from the archived baseline grades.

The previously post-run [name-resolution probe](name_resolution_probe.py) is now mandatory at every Critical assessment.

### Foreign-account guard follow-up

Initial independent review discovered Critical F2 after the run started. The replay reproduced the observable foreign-account predicate in the archived baseline and the initial candidate. The independent finding is mandatory. Its replay was added after launch. [Discovery protocol](foreign-guard-discovery.json), [probe](foreign_guard_probe.py).

| Workspace | Failed checks |
| --- | ---: |
| [Archived Critical baseline](baseline-1-foreign_guard_probe.json) | 2 |
| [Initial Critical candidate](round-1/critical/review-foreign_guard_probe.json) | 2 |
| [Final Critical candidate, round 1](round-1/critical/final-foreign_guard_probe.json) | 0 |

The API and CLI privacy comparisons are separate checks for the same finding. Matching outcomes are necessary. Independent review must also verify that the implementation prevents the foreign SELECT and preserves valid tenant-local guards.

### Second Critical review follow-up

Matched replays found foreign-account dependence in a DML predicate in both the archived baseline and the candidate before repair. The rowid source-shape and table-default REPLACE cases began failing after the first repair.

These replays were added after launch and are separate from the original frozen grades. Case groups can overlap the independent findings. Each linked report includes hashes for the application files. [Discovery protocol](review2-guard-discovery.json), [probe](review2_guard_probe.py).

| Workspace | Failed case groups | vault.py SHA-256 prefix |
| --- | ---: | --- |
| [Archived Critical baseline](baseline-1-review2_guard_probe.json) | 1 | `b01a72948335` |
| [Critical candidate before repair](round-1/critical/review2_guard_pre_repair.json) | 1 | `58cbf6c35757` |
| [Critical candidate after first repair](round-1/critical/review-2-review2_guard_probe.json) | 5 | `7769ba98c409` |
| [Final Critical candidate, round 1](round-1/critical/final-review2_guard_probe.json) | 0 | `7769ba98c409` |

### Final Critical guard replay

This post-launch replay reports fixture outcomes and paired privacy checks for two independent findings. The table gives the total failure count and highlights four outcomes. The replay is separate from the frozen grades. Each linked report records the application hashes. [Discovery protocol](final-guard-discovery.json), [probe](final_guard_probe.py).

| Workspace | Failed groups / executed | Unqualified foreign predicate | Qualified foreign predicate | NATURAL JOIN harmless guard | NATURAL JOIN aborting guard | vault.py SHA-256 prefix |
| --- | ---: | --- | --- | --- | --- | --- |
| [Archived Critical baseline](baseline-1-final_guard_probe.json) | 2/8 | FAIL | FAIL | PASS | PASS | `b01a72948335` |
| [Final Critical candidate](round-1/critical/final-final_guard_probe.json) | 3/8 | PASS | FAIL | FAIL | FAIL | `7769ba98c409` |

## Recorded consumption

The 2 pilot trials launched 8 measured phases. They used **71:21 agent time**, **3,129,266 total tokens**, **263,536 uncached input** and **373,682 uncached input + output**. All launched implementation, review and repair phases count, including failed or timed-out work.

| Trial | Baseline timeouts | Pilot timeouts |
| --- | --- | --- |
| High | None | None |
| Critical | repair-1 | None |

The candidate harness exposed each phase’s existing deadline to the agent. The frozen skill’s budget helper can report the remaining time and advise when to narrow work or finish. The helper is cooperative. The harness still enforces the same process timeout.

Recorded helper calls and remaining-time observations are available in the [phase budget evidence](budget-observations.json).

Both cohorts requested **gpt-6-astra / max** with a **900-second per-phase cap**. Phases ran serially with fresh implementation and independent review contexts. Cache state and remote load were uncontrolled. Coordinator time, preparation, evaluation probes and reporting sit outside the CLI phase totals.

[Summary](summary.json), [comparison CSV](comparison.csv), [trials](trials.csv), [phases](phases.csv), [usage integrity](metric-integrity.json), [control audit](control-audit.json), [controls](controls.json), [previous report](../2026-11-04-lean-run-critical-high-pilot/README.md).

The candidate adds SQL source-resolution guidance, avoids duplicate source/diff and fixture reads, and exposes the unchanged phase deadline through a cooperative helper. [Experiment changes and limits](experiment-notes.json), [instruction diff](skill-change.diff), [preparation validation](validation.json). Preparation validation is separate from measured task quality.

Independent finding histories are derived from the untouched raw review outputs. A derived-assessment bookkeeping correction separates coordinator findings from independent findings; measured prompts, outputs and metrics are unchanged. [Reporting correction](assessment-reporting-amendment.json).
