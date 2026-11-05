# lean-run: Critical speed and integrity

**Requested target: NOT MET.** Final quality: **8/9 passing trials**, **1 FAILED**, **1 remaining independent findings**. Every launched phase and failed attempt remains in the recorded costs.

The new candidate ran the original medium/high/critical questions three times each, with fresh initial implementation and independent-review contexts. It is compared to the **latest cohort's three observations per level**, including its failed Critical attempts. The prior cohort is retained unchanged. This is a descriptive comparison, not a causal or statistical guarantee.

Incomplete execution/usage records: **round-1/critical, round-3/critical**. A TIMEOUT can have passing artifact-quality checks while its execution and token measurement remain incomplete. Unknown usage is never zero or an imputed value. A token mean is UNKNOWN unless all three observations are known; a mean of the remaining observations is not substituted.

## Time and uncached means

Times sum CLI implementation, review, every repair and renewed review. Uncached input = reported input minus cached input. Output (including reasoning) is added only in the separate composite measure. Positive changes are increases.

| Level | Previous mean → new mean | Time change | Uncached input: previous → new | Change | Uncached input + output: previous → new | Change |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| medium | 5:53 → 5:19 | -9.5% | 26,312 → 25,507 | -3.1% | 37,386 → 36,700 | -1.8% |
| high | 6:56 → 9:12 | +32.9% | 46,350 → 42,634 | -8.0% | 61,038 → 61,676 | +1.0% |
| critical | 48:04 → 35:26 | -26.3% | UNKNOWN → UNKNOWN | UNKNOWN | UNKNOWN → UNKNOWN | UNKNOWN |

The preceding Critical cohort has incomplete uncached usage. Its three-trial mean and percentage difference are UNKNOWN, even if the new mean is complete. Observed elapsed costs include the fixed timeout durations.

| Critical phase | Previous mean (seconds) | New mean (seconds) | Difference |
| --- | ---: | ---: | ---: |
| implementation | 866.7 | 738.3 | -128.4 |
| repair-1 | 762.9 | 527.0 | -235.8 |
| repair-2 | 374.5 | 229.7 | -144.8 |
| reviews | 879.9 | 631.4 | -248.5 |

Unused repairs contribute zero elapsed cost. Each review is included in the review total.

Medium's initial implementation mean: **233.944 → 220.929 seconds (-5.6%)**. This is measured separately from review; full-workflow time above still includes all required work.

| Level | Time SD: previous → new (seconds) | New time min–max | Total tokens: previous mean → new mean | Change |
| --- | ---: | ---: | ---: | ---: |
| medium | 30.3 → 17.1 | 299.6–329.7 | 227,338 → 224,391 | -1.3% |
| high | 54.1 → 204.2 | 417.2–787.4 | 285,337 → 381,676 | +33.8% |
| critical | 180.3 → 292.1 | 1913.8–2459.6 | UNKNOWN → UNKNOWN | UNKNOWN |

Medians, token variance and all min/max values are in [comparison.csv](comparison.csv).

## Individual outcomes and quality

| Round | Level | Outcome | Time | Uncached input | Uncached input + output | Total tokens | Independent findings by review | Repairs |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | medium | DONE | 5:29 | 27,600 | 39,260 | 202,076 | 0 | 0 |
| 1 | high | DONE | 6:57 | 39,463 | 55,189 | 286,613 | 0 | 0 |
| 1 | critical | FAILED | 41:00 | UNKNOWN | UNKNOWN | UNKNOWN | 2 → 0 → 1 | 2 |
| 2 | medium | DONE | 5:00 | 20,625 | 32,520 | 254,856 | 0 | 0 |
| 2 | high | DONE | 7:33 | 25,158 | 41,836 | 310,124 | 0 | 0 |
| 2 | critical | DONE | 33:26 | 143,419 | 215,702 | 1,648,662 | 1 → 1 → 0 | 2 |
| 3 | medium | DONE | 5:30 | 28,295 | 38,320 | 216,240 | 0 | 0 |
| 3 | high | DONE | 13:07 | 63,282 | 88,003 | 548,291 | 0 → 0 | 1 |
| 3 | critical | TIMEOUT | 31:54 | UNKNOWN | UNKNOWN | UNKNOWN | 2 → 0 | 1 |

Final original-grader failures: **0**; remaining independent findings: **1**; remaining explicit coordinator findings: **0**; failed predeclared additional-probe cases: **0**; failed posthoc follow-up cases: **8**. These signals overlap and must not be added into a globally unique bug count. Original grade categories remain 4/6/9 (57 final category checks across three rounds). Protected files and review-workspace integrity remain mandatory.

All previously discovered Critical probes were frozen before the first model phase: four original silent-write checks and twelve additional cases covering required effects, audit-history preservation, historical receipts/unrelated accounts, valid rowid movement, ignored inserts/updates and foreign malformed-text isolation. They run after every Critical independent review, starting with the first assessment. Passing the original grader cannot waive their failure. [Manifest](manifest.json) lists the exact copied scripts; each assessment retains the full reports and source hashes. Historical regression suites from all three previous final workspaces also run against every candidate; reverse cross-regressions remain visible. Contract-external assertions require a retained evidence-backed adjudication and cannot waive a real finding.

The previous cohort ended with 7/9 passing trials and 2 remaining independent findings. Its probes were discovered during follow-up; they are available from the start in this new experiment. Critical cost comparisons therefore describe recorded work, including different repair paths and unsuccessful attempts, **not equal-quality time to successful completion**.

The preceding cohort's frame and trigger compatibility probes are now mandatory from the first assessment. These include extra UNIQUE account/receipt/audit victims, ignored conflicts and valid replacements, unquoted keyword/Unicode names, and conditional VALUES/WITH bodies. The same scripts ran on all three previous final workspaces. Case failures may overlap independent findings.

| Targeted probe | Executions per workspace | Previous failed cases (rounds 1/2/3) | New failed cases (rounds 1/2/3) |
| --- | ---: | --- | --- |
| frame_followup_probe | 6 | 2 / 0 / 0 | 0 / 0 / 0 |
| trigger_compatibility_probe | 28 | 0 / 4 / 0 | 0 / 0 / 0 |

Findings during the run added posthoc probes. Each probe exercised API and CLI calls in DELETE and WAL modes against all three previous and new final workspaces. Round 1 reopened for the remaining bounded repair after the trigger-counter and NBSP findings. Its original closure, subsequent repair and renewed review are retained, with every phase counted in the elapsed cost.

| Posthoc probe | Previous failures (rounds 1/2/3) | New failures (rounds 1/2/3) |
| --- | --- | --- |
| [Dollar identifier](dollar-protocol.json) | 0 / 0 / 0 | 0 / 0 / 0 |
| [Trigger counter](counter-protocol.json) | 4 / 4 / 4 | 0 / 0 / 0 |
| [Unquoted NBSP](unicode-space-protocol.json) | 0 / 4 / 4 | 0 / 0 / 0 |
| [VT and BOM separators](separator-protocol.json) | 0 / 4 / 4 | 8 / 0 / 0 |
| [Malformed foreign TEXT no-op](malformed-effect-protocol.json) | 0 / 0 / 0 | 0 / 0 / 0 |

Copied probes initially could not import a local helper module in round 1. The coordinator supplied the workspace import path and reran those probes. The archive includes the raw import failures and the evaluator amendment. [Evaluator amendment](measurement-amendment.json)

Failed trials exhausted the [frozen skill repair limit](round-1/medium/initial/.agents/skills/lean-run/SKILL.md): “After the second REWORK, allow one final fix-only pass plus verification/review; unresolved mandatory findings mean FAILED.” They were retained and not replaced with favorable samples.

Remaining findings: [round-1/critical](round-1/critical/review-3/final.txt).

## Actual recorded consumption

The nine new trials used **149:55 recorded agent time**, **UNKNOWN total tokens**, **UNKNOWN uncached input**, and **UNKNOWN uncached input + output**. The previous nine trials used **182:38**, **UNKNOWN total tokens**, **UNKNOWN uncached input**, and **UNKNOWN uncached input + output**. These totals include failed attempts and every measured repair; means are reported separately above. Timed-out elapsed durations are bounded observed costs, not completed-phase latencies.

Known consumption lower bound (excluding every unknown phase's unreported token usage): **6,049,143 total tokens**, **614,149 uncached input**, **863,607 uncached input + output**. This lower bound is not an exact total when any usage is unknown. Raw timeout records and any measurement amendment remain in the archive.

Coordinator chat, static skill review, preparation, graders, cross-regressions, diagnostic probes and reporting are excluded from agent time/token totals. Their model token usage is unavailable. Counts are usage observations, not billing-price estimates; cached input is a subset of input and reasoning is already included in output.

## Changes, controls and limits

- The write-integrity reference directs one small mechanism proof before implementation, covering effective changes and hidden UNIQUE replacement victims. It preserves scoped reads, rollback, replay, concurrency and independent review.
- Trigger instrumentation, if needed, preserves SQL spans and requires early checks for unquoted Unicode, keyword identifiers and conditional compound bodies. The guide contains no fixture implementation.
- Initial application files, contracts, public tests, AGENTS.md, implementation/first-review prompts and graders are byte-identical to the prior tasks. Each new trial uses the same frozen skill package. No skill edits occur inside the cohort. [Controls](controls.json) and [manifest](manifest.json) retain hashes and settings.
- Requested model/effort remain **gpt-6-astra / max**, standard procedure depth, 900-second per-phase timeout and existing ChatGPT authentication. Backend identity is not independently attested. Order remains medium/high/critical, high/critical/medium, critical/medium/high; one active worker at a time.
- No synthetic warmup; cache state, remote load and host contention were not controlled. Development knowledge informs this version and the fixed quality probes, so the known tasks are not a held-out benchmark. Repairs use demonstrated findings and final quality may differ from the historical failed candidates.
- Data is synthetic/local. Runtime coverage is limited to the recorded Python/SQLite/CLI environment; evaluator read boundaries are instructional. Neither this sample nor passing tests establishes production behavior or guarantees future model decisions.

## Evidence

[Summary](summary.json), [all trials](trials.csv), [all phases](phases.csv), [comparison](comparison.csv), [usage integrity](metric-integrity.json), [control audit](control-audit.json), [static skill review](skill-review.json), [repository validation](validation.json), [archive hashes](archive-sha256.json), and [previous report](../2026-11-03-lean-run-critical-medium/README.md).

Every round retains initial/final workspaces, prompts, events, usage, grades, probe reports, independent findings, source hashes and all repairs. Unsuccessful observations remain part of this record.

## Warning and interruption

The captured CLI events, stderr and relevant chat events do not identify a cybersecurity warning, its triggering command or a policy rejection. The observed CLI warnings reported a local rollout-state lookup fallback. The chat recorded an interruption while round-3 Critical repair 1 was running. Its existing CLI process finished with exit code 0 and a raw usage event. The coordinator recovered elapsed time from the original launch and a Darwin process-exit observation, then continued at the renewed review. The repair ran once under the original 900-second deadline. Coordinator wait time remains outside measured workflow cost. The earlier Critical implementation timeout still has unknown usage. [Warning investigation](warning-investigation.json), [recovery record](interruption-recovery.json), [observed exit](recovered-exit-status.json).
