# lean-run: three repeats per level — 2026-11-03

Nine frozen validation tasks, using the original medium/high/critical contracts. Each level ran three times with fresh implementation and independent-review contexts. The comparison baseline is the prior optimized version with **one measured observation per level**, as requested; it is not a second n=3 cohort.

**Requested optimization target NOT MET:** Medium mean time +4.2%, uncached input -22.3%, and uncached input + output -16.8%. Final quality: **7/9 passed**; failed trials: **round-1/critical, round-3/critical**. All failed attempts remain in the means and actual costs. These observations do not establish a causal improvement.

## Per-level means versus the prior version

Time includes all implementation, review, repair and renewed-review phases. Uncached input = reported input minus cached input. Uncached input + output is reported separately; neither count is a billing-price estimate. Positive changes mean increases.

| Level | Time: baseline → new mean | Time change | Uncached input: baseline → new mean | Change | Uncached input + output: baseline → new mean | Change |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| medium | 6:19 → 6:35 | +4.2% | 44,321 → 34,418 | -22.3% | 56,650 → 47,109 | -16.8% |
| high | 7:23 → 7:44 | +4.9% | 55,827 → 55,564 | -0.5% | 71,993 → 72,129 | +0.2% |
| critical | 18:37 → 30:54 | +65.9% | 141,772 → 197,938 | +39.6% | 179,886 → 266,082 | +47.9% |

## Medium phase breakdown

| Phase | Baseline seconds → new mean | Uncached input: baseline → new mean | Commands: baseline → new mean |
| --- | ---: | ---: | ---: |
| implementation | 213.351 → 282.154 | 34,823 → 16,621 | 10 → 13.33 |
| review | 165.803 → 112.986 | 9,498 → 17,797 | 12 → 10.67 |

The observed implementation-time increase exceeds the review-time reduction. These phase measurements identify where time was spent in this sample; they do not prove the instruction change caused the difference. Cache behavior also varies by phase and trial.

The main SKILL.md changed from 8,819 characters / 1,159 whitespace-delimited words to 10,504 characters / 1,376 words. It adds explicit assessment and bounded-log procedures while moving reusable execution logic into an optional helper. These file-size counts are not token estimates; the real usage above is the basis for the comparison.

## Spread of the three observations

Sample standard deviation describes only this new cohort. The historical baseline has no measured variance estimate. Times below are seconds; token means can be fractional.

| Level | Time mean ± sample SD | Time min–max | Uncached input mean ± SD | Uncached input + output mean ± SD |
| --- | ---: | ---: | ---: | ---: |
| medium | 395.1 ± 47.3 | 351.6–445.5 | 34418.0 ± 11298.6 | 47109.3 ± 11588.5 |
| high | 464.1 ± 76.7 | 376.0–516.5 | 55564.0 ± 1853.2 | 72128.7 ± 319.6 |
| critical | 1853.9 ± 256.9 | 1693.2–2150.2 | 197937.7 ± 9232.6 | 266082.0 ± 10878.2 |

All medians and min/max values for each token measure are in [comparison.csv](comparison.csv).

| Level | Total input + output: baseline → new mean | Change | Mean output tokens |
| --- | ---: | ---: | ---: |
| medium | 314,570 → 287,067 | -8.7% | 12,691 |
| high | 290,617 → 348,011 | +19.7% | 16,565 |
| critical | 986,158 → 1,746,658 | +77.1% | 68,144 |


## Individual trials and quality

| Round | Level | Outcome | Agent time | Total tokens | Cached input | Uncached input | Uncached input + output | Independent findings by review | Later probe findings | Repairs |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | medium | DONE | 7:26 | 270,899 | 223,616 | 35,705 | 47,283 | 0 | 0 | 0 |
| 1 | high | DONE | 8:36 | 294,827 | 222,976 | 55,126 | 71,851 | 0 | 0 | 0 |
| 1 | critical | FAILED | 28:13 | 1,617,728 | 1,344,384 | 207,804 | 273,344 | 0 → 2 → 1 | 1 | 2 |
| 2 | medium | DONE | 6:28 | 328,427 | 292,992 | 22,531 | 35,435 | 0 | 0 | 0 |
| 2 | high | DONE | 8:20 | 351,993 | 279,936 | 53,969 | 72,057 | 0 | 0 | 0 |
| 2 | critical | DONE | 28:38 | 1,748,999 | 1,495,424 | 189,507 | 253,575 | 0 → 1 → 0 | 3 | 2 |
| 3 | medium | DONE | 5:52 | 261,874 | 203,264 | 45,018 | 58,610 | 0 | 0 | 0 |
| 3 | high | DONE | 6:16 | 397,214 | 324,736 | 57,597 | 72,478 | 0 | 0 | 0 |
| 3 | critical | FAILED | 35:50 | 1,873,247 | 1,601,920 | 196,502 | 271,327 | 0 → 1 → 1 | 3 | 2 |

The original frozen categories (4/6/9, 57 final category checks across the three rounds), protected files, independent findings and later probes are separate quality signals. Passing the original grader does not override a demonstrated independent finding. The exact historical critical silent-write probe checks debit, credit, receipt and audit effects separately. Every failed attempt and repair remains in the evidence and measured totals. Repeated or related findings across reviews/trials are not globally unique bugs. Category failures, reviewer findings and failed assertions overlap and must not be added.

Historical regression tests run against each new candidate; new tests also run against the historical final implementation. Raw cross-test failures are retained. Any assertion outside the contract or inert review artifact must have an evidence-backed coordinator record; it cannot waive a failed frozen check, changed protected source, required independent finding or supplemental write failure.

Medium rounds 2 and 3 each had four reverse-cross assertion failures requiring the literal words `usage` or `argument` in historical stderr. The historical error is useful and the contract specifies no exact wording, so these are not application issues; each trial retains a classification record. Critical round 3's original cross suites disagreed on the exception class for integer overflow (`ValueError` versus `OverflowError`). Independent evidence confirmed rejection with every table unchanged in both versions; the contract does not prescribe the overflow exception class. Its raw failures and adjudication are retained.

Final frozen-category failures: **0**; remaining independent findings: **2**; failed added-probe cases: **3**. Fully passing trials: **7/9**.

Each failed trial reached the [frozen lean-run repair limit](round-1/critical/initial/.agents/skills/lean-run/SKILL.md): “After the second REWORK, allow one final fix-only pass plus verification/review; unresolved mandatory findings mean FAILED.” Remaining findings and measured consumption are retained; failed outcomes were not relabeled as PASS or rerun as fresh trials.

Remaining evidence: [round-1/critical](round-1/critical/review-3/final.txt).

Remaining evidence: [round-3/critical](round-3/critical/review-3/final.txt).

The historical critical task required one repair plus renewed review: **742.982 seconds** first pass and **374.359 seconds** repair/review overhead. The new critical first-pass mean is **662.638 seconds**; repair counts are **[2, 2, 2]**. The full-workflow increase includes the added repairs and renewed reviews; initial first-pass costs are reported separately. The historical recorded review counts were 0 → 0 for medium/high and 1 → 0 for critical.

### Additional defect discovered by cross-regression

Round 2's critical candidate added AFTER-trigger checks. Four assertions failed against the historical final implementation. An independent coordinator probe confirmed one root cause: successful SQL row counts can coexist with missing credit/receipt/audit effects or duplicate audit rows. This violates the original atomic-effects contract; the original fixed grader and reviews did not catch it.

The first repair's renewed independent review then found incomplete audit-history preservation and a new regression: requiring an unchanged internal rowid rejected a valid trigger that relocates the audit row without altering its contracted values. A second three-case probe was applied to the historical version and every critical trial. Confirmed findings were added to pending repairs; round 2 also required repair. Each trial retained its own bounded REWORK count.

The final review of round 1 then demonstrated deletion of another tenant's historical receipt (allowing double execution on replay) and changes to its unrelated balance. That trial exhausted its repair limit and remains FAILED. The same two-case preservation probe was applied to the historical version and all critical candidates; confirmed findings were added to the pending first repairs for rounds 2 and 3.

Round 2's first repair then introduced a no-op regression: an unconditional BEFORE INSERT guard rejected a harmless conflict-ignored `INSERT OR IGNORE`. A fourth probe confirmed the historical version and rounds 1/3 accepted that valid operation. Round 2 received its final fix-only pass; the same valid-operation constraint was added to round 3's pending repair.

Round 3's first repair used unscoped account/receipt snapshots. Its independent review confirmed that a malformed TEXT value belonging to another tenant made an otherwise valid transfer fail and placed foreign text in the API error. A fifth probe confirmed this regression was absent from the historical version and final rounds 1/2. Round 3 received its final fix-only pass to restore the original tenant-read boundary.

Round 3's final review found a remaining ignored-update regression: a BEFORE collision guard rejected a harmless `UPDATE OR IGNORE` of rowid. The trial reached its repair limit and remains FAILED. The same case passes on the historical version and final rounds 1/2. This is distinct from the earlier ignored-insert regression that round 2 repaired.

Across the twelve added cases, the historical final version fails **8/12**: missing required effects, altered history and unrelated receipt/account changes. Its valid rowid-relocation, ignored-insert, ignored-update and foreign-text isolation cases pass. New trials generated **7 coordinator finding occurrences** and **6 renewed-review finding occurrences**. These include repeated manifestations of related integrity gaps and regressions; they are not a summed count of globally unique bugs. Final added-probe failures: **3**, with **2** mandatory independent findings remaining. Every repair and renewed review is included in measured totals. Original PASS assessments and results are retained alongside later findings; the original prompts, contracts, graders and skill package were not changed.

Consequently, critical timing compares observed costs against the requested historical record, **not equal-quality time to completion**: the old record contains neither this follow-up nor its necessary repair, and failed new trials did not reach completion. It would be misleading to claim unchanged quality was established. See the [follow-up plan](quality-followup-plan.json), [required-effects probe](after_trigger_probe.py), [audit follow-up probe](audit_followup_probe.py), [preservation probe](preservation_probe.py), [no-op probe](noop_probe.py), [read-isolation probe](read_isolation_probe.py), [ignored-update probe](ignored_update_probe.py), [historical effects evidence](after-trigger-historical.json), [historical audit evidence](audit-followup-historical.json), [historical preservation evidence](preservation-historical.json), and each affected trial's `posthoc-review.json` and measured repair/review phases.


## Total usage and normalization

The sum of the three level means represents one medium + one high + one critical task: **32:19 → 45:13** agent time, **1,591,345 → 2,381,736** total tokens, and **308,529 → 385,320** uncached input + output. This normalized bundle is not the actual consumption of all nine tasks.

Actual consumption of the nine validation tasks: **135:39** agent time, **7,145,208** total tokens, **863,759** uncached input and **1,155,960** uncached input + output.

## Development candidate retained separately

An initial planned cohort was stopped after two completed tasks and one additional completed implementation phase. It exposed a real log-metadata defect (a stripped trailing newline incorrectly made complete output appear truncated), plus redundant reads of successful logs. Its model phases were allowed to finish before the coordinator stopped; no launched model phase has unknown usage. The corrected helper was regression-tested, and independent review verified the narrower assessment workflow preserves acceptance and independence.

The entire abandoned variant is excluded from the final n=3 means, rather than selectively retaining its better observations. Its five measured phases cost **29:51**, **1,230,129 total tokens**, **151,930 uncached input tokens**, and **208,305 uncached input + output**. Its critical implementation had no independent review and is not presented as a completed task. See [development summary](development-candidate/development-summary.json) and retained raw artifacts. Development and validation both used the same known tasks, so this is not a held-out benchmark.

Combined recorded development + validation consumption: **165:30** agent time, **8,375,337** total tokens, **1,015,689** uncached input, and **1,364,265** uncached input + output. This excludes the unmeasured coordinator/static-review work listed below.


## Controls, changes and limits

- Requested model/effort stayed **gpt-6-astra / max**; procedure depth standard; 900-second timeout per phase. CLI 0.166.0, Python 3.14.3, SQLite 3.50.4, macOS 27.0.1 arm64. Backend identity is not independently attested. Existing ChatGPT authentication was reused.
- Initial application files, contracts, AGENTS.md, public tests, implementation/review prompts and the frozen graders match the historical tasks. Each validation trial uses the same frozen skill package. No skill changes occurred within the nine validation tasks.
- Order: medium/high/critical, high/critical/medium, critical/medium/high. One active worker at a time. Cache state and remote service load were not controlled; there was no synthetic cache warmup. Prior development calls may affect cache state.
- Initial phases used fresh contexts. Later repair briefs incorporated demonstrated findings discovered in earlier trials, so the full workflows are not independent replicates. Their means and sample spread are descriptive; initial first-pass costs remain separately available.
- Skill changes: preserve full logs with bounded excerpts and truthful status; avoid reading a complete passing log again when its completion evidence is clear; use verified project/library primitives; focus assessment on acceptance, current source/tests and independent probes for remaining gaps. No mandatory quality gate was removed.
- Time is monotonic CLI process elapsed time, summed over every phase including later repairs and renewed reviews. Tokens are recomputed from raw usage events; cached input is included in input, and reasoning is included in output. Coordinator chat, skill reviews, fixture setup, graders, cross-regressions, coordinator diagnostic probes and reporting are excluded. Their token usage is unavailable, so this is not full-account usage or total chat time. Per-trial workflow spans can include time spent on other trials before a later repair and are not used for the speed comparison.
- All data is synthetic/local. Read boundaries are instructional, not an OS-enforced secrecy barrier. The tests do not establish production durability or behavior on unseen tasks. n=3 versus a historical n=1 baseline does not establish a causal or statistically reliable speedup.

## Artifacts

[Summary JSON](summary.json), [comparison CSV](comparison.csv), [individual trials](trials.csv), [all phases](phases.csv), [usage integrity](metric-integrity.json), [fixed-input controls](controls.json), [frozen manifest](manifest.json), [skill review](skill-review.json), [repository validation](validation.json), and [baseline integrity](baseline-integrity.json).

Each round retains initial/final workspaces, skill copies, prompts, model events, metrics, helper logs, grades, independent findings and any repairs. The [prior optimized report](../2026-11-03-lean-run-optimized/README.md) remains unchanged. The root [archive hashes](archive-sha256.json) cover all retained evidence.
