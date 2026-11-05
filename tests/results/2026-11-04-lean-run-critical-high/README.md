# lean-run: Critical completion and High workflow time

**Requested target: NOT MET.** Final quality: **6/9 passing trials**, **3 FAILED**, **3 remaining independent findings**. Every launched phase and failed attempt remains in the recorded costs.

The new candidate ran the original medium/high/critical questions three times each, with fresh initial implementation and independent-review contexts. It is compared to the **latest cohort's three observations per level**, including its failed Critical attempts. The prior cohort is retained unchanged. This is a descriptive comparison, not a causal or statistical guarantee.

Incomplete execution/usage records: **round-1/critical, round-2/critical, round-3/critical**. A TIMEOUT can have passing artifact-quality checks while its execution and token measurement remain incomplete. Unknown usage is never zero or an imputed value. A token mean is UNKNOWN unless all three observations are known; a mean of the remaining observations is not substituted.

## Time and uncached means

Times sum CLI implementation, review, every repair and renewed review. Uncached input = reported input minus cached input. Output (including reasoning) is added only in the separate composite measure. Positive changes are increases.

| Level | Previous mean → new mean | Time change | Uncached input: previous → new | Change | Uncached input + output: previous → new | Change |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| medium | 5:19 → 7:00 | +31.6% | 25,507 → 37,698 | +47.8% | 36,700 → 49,952 | +36.1% |
| high | 9:12 → 9:48 | +6.4% | 42,634 → 43,579 | +2.2% | 61,676 → 60,820 | -1.4% |
| critical | 35:26 → 53:35 | +51.2% | UNKNOWN → UNKNOWN | UNKNOWN | UNKNOWN → UNKNOWN | UNKNOWN |

The preceding Critical cohort has incomplete uncached usage. Its three-trial mean and percentage difference are UNKNOWN, even if the new mean is complete. Observed elapsed costs include the fixed timeout durations.

| Critical phase | Previous mean (seconds) | New mean (seconds) | Difference |
| --- | ---: | ---: | ---: |
| implementation | 738.3 | 741.7 | +3.4 |
| repair-1 | 527.0 | 900.0 | +373.0 |
| repair-2 | 229.7 | 636.5 | +406.8 |
| reviews | 631.4 | 936.6 | +305.2 |

Unused repairs contribute zero elapsed cost. Each review is included in the review total.

Medium's initial implementation mean: **220.929 → 298.423 seconds (+35.1%)**. This is measured separately from review; full-workflow time above still includes all required work.

| Level | Time SD: previous → new (seconds) | New time min–max | Total tokens: previous mean → new mean | Change |
| --- | ---: | ---: | ---: | ---: |
| medium | 17.1 → 13.2 | 407.7–433.9 | 224,391 → 266,315 | +18.7% |
| high | 204.2 → 106.8 | 464.6–655.3 | 381,676 → 327,956 | -14.1% |
| critical | 292.1 → 346.0 | 2871.7–3563.7 | UNKNOWN → UNKNOWN | UNKNOWN |

Medians, token variance and all min/max values are in [comparison.csv](comparison.csv).

## Individual outcomes and quality

| Round | Level | Outcome | Time | Uncached input | Uncached input + output | Total tokens | Independent findings by review | Repairs |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | medium | DONE | 6:59 | 22,266 | 34,173 | 221,181 | 0 | 0 |
| 1 | high | DONE | 10:43 | 39,422 | 57,162 | 328,778 | 0 | 0 |
| 1 | critical | FAILED | 47:52 | UNKNOWN | UNKNOWN | UNKNOWN | 1 → 2 → 0 | 2 |
| 2 | medium | DONE | 6:48 | 51,312 | 63,333 | 252,133 | 0 | 0 |
| 2 | high | DONE | 10:55 | 51,669 | 69,798 | 321,830 | 0 | 0 |
| 2 | critical | FAILED | 59:24 | UNKNOWN | UNKNOWN | UNKNOWN | 1 → 1 → 1 | 2 |
| 3 | medium | DONE | 7:14 | 39,515 | 52,351 | 325,631 | 0 | 0 |
| 3 | high | DONE | 7:45 | 39,646 | 55,500 | 333,260 | 0 | 0 |
| 3 | critical | FAILED | 53:29 | UNKNOWN | UNKNOWN | UNKNOWN | 1 → 2 → 2 | 2 |

Final original-grader failures: **0**; remaining independent findings: **3**; remaining explicit coordinator findings: **1**; failed predeclared additional-probe cases: **0**; failed posthoc follow-up cases: **6**. These signals overlap and must not be added into a globally unique bug count. Original grade categories remain 4/6/9 (57 final category checks across three rounds). Protected files and review-workspace integrity remain mandatory.

All previously discovered Critical probes were frozen before the first model phase: four original silent-write checks and twelve additional cases covering required effects, audit-history preservation, historical receipts/unrelated accounts, valid rowid movement, ignored inserts/updates and foreign malformed-text isolation. They run after every Critical independent review, starting with the first assessment. Passing the original grader cannot waive their failure. [Manifest](manifest.json) lists the exact copied scripts; each assessment retains the full reports and source hashes. Historical regression suites from all three previous final workspaces also run against every candidate; reverse cross-regressions remain visible. Contract-external assertions require a retained evidence-backed adjudication and cannot waive a real finding.

The previous cohort ended with 8/9 passing trials and 1 remaining independent findings. Its probes were discovered during follow-up; they are available from the start in this new experiment. Critical cost comparisons therefore describe recorded work, including different repair paths and unsuccessful attempts, **not equal-quality time to successful completion**.

The frame and trigger compatibility probes remain mandatory. The comparison uses the final assessments of the latest cohort.

These probes cover extra UNIQUE account, receipt and audit victims, ignored conflicts, valid replacements, unquoted keyword and Unicode names, and conditional VALUES or WITH bodies. The same scripts ran on all three previous final workspaces. Case failures may overlap independent findings.

| Targeted probe | Executions per workspace | Previous failed cases (rounds 1/2/3) | New failed cases (rounds 1/2/3) |
| --- | ---: | --- | --- |
| frame_followup_probe | 6 | 0 / 0 / 0 | 0 / 0 / 0 |
| trigger_compatibility_probe | 28 | 0 / 0 / 0 | 0 / 0 / 0 |

The previous cohort's five effect and trigger diagnostics now run as mandatory checks at every Critical assessment. The separator check covers vertical tab, token-boundary U+FEFF and an ASCII control via API and CLI in DELETE and WAL modes. All three historical final workspaces were checked with the same probe.

| Promoted probe | Previous failures (rounds 1/2/3) | New failures (rounds 1/2/3) |
| --- | --- | --- |
| [Dollar identifier](dollar_identifier_probe.py) | 0 / 0 / 0 | 0 / 0 / 0 |
| [Trigger counter](trigger_counter_probe.py) | 0 / 0 / 0 | 0 / 0 / 0 |
| [Unquoted NBSP](unicode_space_probe.py) | 0 / 0 / 0 | 0 / 0 / 0 |
| [VT and BOM separators](trigger_separator_probe.py) | 8 / 0 / 0 | 0 / 0 / 0 |
| [Malformed foreign TEXT no-op](malformed_effect_probe.py) | 0 / 0 / 0 | 0 / 0 / 0 |

The skill now asks implementers to establish the hardest write effect early, check SQL token boundaries against the installed engine, and map public signatures to validation cases before editing. Phase caps and mandatory review requirements are unchanged.

The storage-encoding probe was added after a valid UTF-16 transfer was rejected. Failures were 0 / 0 / 0 before and 0 / 0 / 0 after, in round order. [Probe protocol](storage-encoding-protocol.json)

The ignore-scope probe was added after an ignored row suppressed a later trigger abort. Failures were 0 / 0 / 0 before and 0 / 0 / 0 after, in round order. [Probe protocol](ignore-scope-protocol.json)

The recursive-setting probe was added after instrumentation changed the setting read by an audit guard. Failures were 4 / 4 / 4 before and 4 / 2 / 0 after, in round order. [Probe protocol](recursive-setting-protocol.json)

Failed trials exhausted the [frozen skill repair limit](round-1/medium/initial/.agents/skills/lean-run/SKILL.md): “After the second REWORK, allow one final fix-only pass plus verification/review; unresolved mandatory findings mean FAILED.” They were retained and not replaced with favorable samples.

Remaining findings: [round-1/critical](round-1/critical/assessment-3.json).

Remaining findings: [round-2/critical](round-2/critical/review-3/final.txt).

Remaining findings: [round-3/critical](round-3/critical/review-3/final.txt).

## Actual recorded consumption

The nine new trials used **211:08 recorded agent time**, **UNKNOWN total tokens**, **UNKNOWN uncached input**, and **UNKNOWN uncached input + output**. The previous nine trials used **149:55**, **UNKNOWN total tokens**, **UNKNOWN uncached input**, and **UNKNOWN uncached input + output**. These totals include failed attempts and every measured repair; means are reported separately above. Timed-out elapsed durations are bounded observed costs, not completed-phase latencies.

Known consumption lower bound (excluding every unknown phase's unreported token usage): **6,257,929 total tokens**, **715,761 uncached input**, **972,169 uncached input + output**. This lower bound is not an exact total when any usage is unknown. Raw timeout records and any measurement amendment remain in the archive.

Coordinator chat, static skill review, preparation, graders, cross-regressions, diagnostic probes and reporting are excluded from agent time/token totals. Their model token usage is unavailable. Counts are usage observations, not billing-price estimates; cached input is a subset of input and reasoning is already included in output.

## Changes, controls and limits

- The write-integrity reference directs one small mechanism proof before implementation, covering effective changes and hidden UNIQUE replacement victims. It preserves scoped reads, rollback, replay, concurrency and independent review.
- Trigger instrumentation, if needed, preserves SQL spans and requires early checks for unquoted Unicode, keyword identifiers and conditional compound bodies. The guide contains no fixture implementation.
- Initial application files, contracts, public tests, AGENTS.md, implementation/first-review prompts and graders are byte-identical to the prior tasks. Each new trial uses the same frozen skill package. No skill edits occur inside the cohort. [Controls](controls.json) and [manifest](manifest.json) retain hashes and settings.
- Requested model/effort remain **gpt-6-astra / max**, standard procedure depth, 900-second per-phase timeout and existing ChatGPT authentication. Backend identity is not independently attested. Order remains medium/high/critical, high/critical/medium, critical/medium/high; one active worker at a time.
- No synthetic warmup; cache state, remote load and host contention were not controlled. Development knowledge informs this version and the fixed quality probes, so the known tasks are not a held-out benchmark. Repairs use demonstrated findings and final quality may differ from the historical failed candidates.
- Data is synthetic/local. Runtime coverage is limited to the recorded Python/SQLite/CLI environment; evaluator read boundaries are instructional. Neither this sample nor passing tests establishes production behavior or guarantees future model decisions.

## Evidence

[Summary](summary.json), [all trials](trials.csv), [all phases](phases.csv), [comparison](comparison.csv), [usage integrity](metric-integrity.json), [control audit](control-audit.json), [static skill review](skill-review.json), [repository validation](validation.json), [archive hashes](archive-sha256.json), and [previous report](../2026-11-04-lean-run-critical-speed/README.md).

Every round retains initial/final workspaces, prompts, events, usage, grades, probe reports, independent findings, source hashes and all repairs. Unsuccessful observations remain part of this record.

The user reported a Codex chat notice that hid content while Critical round 3 was running. The screenshot identified the type of safeguard. The available records did not identify the message, case, or command that triggered it. The CLI continued, finished its implementation phase, and recorded usage. The reported timeouts are documented separately as 900-second phase deadlines. [Notice observation](cyber-notice-observation.json)
