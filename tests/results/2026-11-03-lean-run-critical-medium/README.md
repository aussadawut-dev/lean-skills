# lean-run: Critical integrity and Medium implementation — 2026-11-03

**Requested target: NOT MET.** Final quality: **7/9 passing trials**, **2 FAILED**, **2 remaining independent findings**. Every launched phase and failed attempt remains in the recorded costs.

The new candidate ran the original medium/high/critical questions three times each, with fresh initial implementation and independent-review contexts. It is compared to the **latest cohort's three observations per level**, including its failed Critical attempts. The prior cohort is retained unchanged. This is a descriptive comparison, not a causal or statistical guarantee.

Incomplete execution/usage records: **round-1/critical, round-2/critical, round-3/critical**. A TIMEOUT can have passing artifact-quality checks while its execution and token measurement remain incomplete. Unknown usage is never zero or an imputed value. A token mean is UNKNOWN unless all three observations are known; a mean of the remaining observations is not substituted.

## Time and uncached means

Times sum CLI implementation, review, every repair and renewed review. Uncached input = reported input minus cached input. Output (including reasoning) is added only in the separate composite measure. Positive changes are increases.

| Level | Previous mean → new mean | Time change | Uncached input: previous → new | Change | Uncached input + output: previous → new | Change |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| medium | 6:35 → 5:53 | -10.7% | 34,418 → 26,312 | -23.6% | 47,109 → 37,386 | -20.6% |
| high | 7:44 → 6:56 | -10.4% | 55,564 → 46,350 | -16.6% | 72,129 → 61,038 | -15.4% |
| critical | 30:54 → 48:04 | +55.6% | 197,938 → UNKNOWN | UNKNOWN | 266,082 → UNKNOWN | UNKNOWN |

Medium's initial implementation mean: **282.154 → 233.944 seconds (-17.1%)**. This is measured separately from review; full-workflow time above still includes all required work.

| Level | Time SD: previous → new (seconds) | New time min–max | Total tokens: previous mean → new mean | Change |
| --- | ---: | ---: | ---: | ---: |
| medium | 47.3 → 30.3 | 318.2–374.0 | 287,067 → 227,338 | -20.8% |
| high | 76.7 → 54.1 | 358.5–466.0 | 348,011 → 285,337 | -18.0% |
| critical | 256.9 → 180.3 | 2679.7–3021.0 | 1,746,658 → UNKNOWN | UNKNOWN |

Medians, token variance and all min/max values are in [comparison.csv](comparison.csv).

## Individual outcomes and quality

| Round | Level | Outcome | Time | Uncached input | Uncached input + output | Total tokens | Independent findings by review | Repairs |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | medium | DONE | 5:18 | 30,196 | 40,307 | 217,075 | 0 | 0 |
| 1 | high | DONE | 7:46 | 57,231 | 72,805 | 260,965 | 0 | 0 |
| 1 | critical | FAILED | 44:40 | UNKNOWN | UNKNOWN | UNKNOWN | 1 → 1 → 1 | 2 |
| 2 | medium | DONE | 6:14 | 16,636 | 27,638 | 197,622 | 0 | 0 |
| 2 | high | DONE | 7:03 | 37,487 | 52,562 | 351,570 | 0 | 0 |
| 2 | critical | FAILED | 50:21 | UNKNOWN | UNKNOWN | UNKNOWN | 1 → 1 → 1 | 2 |
| 3 | medium | DONE | 6:07 | 32,105 | 44,212 | 267,316 | 0 | 0 |
| 3 | high | DONE | 5:59 | 44,331 | 57,747 | 243,475 | 0 | 0 |
| 3 | critical | TIMEOUT | 49:11 | UNKNOWN | UNKNOWN | UNKNOWN | 0 → 1 → 0 | 2 |

Final original-grader failures: **0**; remaining independent findings: **2**; remaining explicit coordinator findings: **0**; failed predeclared additional-probe cases: **0**; failed posthoc follow-up cases: **6**. These signals overlap and must not be added into a globally unique bug count. Original grade categories remain 4/6/9 (57 final category checks across three rounds). Protected files and review-workspace integrity remain mandatory.

All previously discovered Critical probes were frozen before the first model phase: four original silent-write checks and twelve additional cases covering required effects, audit-history preservation, historical receipts/unrelated accounts, valid rowid movement, ignored inserts/updates and foreign malformed-text isolation. They run after every Critical independent review, starting with the first assessment. Passing the original grader cannot waive their failure. [Manifest](manifest.json) lists the exact copied scripts; each assessment retains the full reports and source hashes. Historical regression suites from all three previous final workspaces also run against every candidate; reverse cross-regressions remain visible. Contract-external assertions require a retained evidence-backed adjudication and cannot waive a real finding.

The previous cohort ended with 7/9 passing trials and 2 remaining independent findings. Its probes were discovered during follow-up; they are available from the start in this new experiment. Critical cost comparisons therefore describe recorded work, including different repair paths and unsuccessful attempts, **not equal-quality time to successful completion**.

New independent findings also produced bounded posthoc diagnostics, applied uniformly to all three previous and new Critical final workspaces. The frame probe has six cases: identical foreign replacements, a replacement-based rowid swap, and hidden account/receipt victims from extra UNIQUE indexes. The trigger-compatibility probe executes its cases through API and CLI in DELETE and WAL modes: hidden audit replacement loss, its successful IGNORE control, benign keyword/Unicode trigger names, a quoted control and legal VALUES/WITH bodies with WHEN. Unicode cases were added after round-2 review-3; VALUES/WITH cases followed round-3 review-2. Prior v1/v2 scripts and reports remain archived. The table below reports exact execution counts. These are disclosed follow-ups to demonstrated findings, not predeclared or held-out tests. [Protocol](followup-protocol.json) and the per-workspace reports retain their timing, source hashes and evidence.

| Posthoc probe | Executed cases per trial | Previous failed cases, rounds 1/2/3 | New failed cases, rounds 1/2/3 |
| --- | ---: | --- | --- |
| frame-followup | 6 | 2 / 3 / 4 | 2 / 0 / 0 |
| trigger-compatibility | 28 | 0 / 0 / 0 | 0 / 4 / 0 |

The strict account-read scope was checked separately against the original contract: returning only an aggregate or mismatch flag does not authorize foreign account lookups. Storage checks of actual write effects can preserve the frame without fetching foreign stored accounts. [Contract triage](contract-triage.json) and [round-2 follow-up](contract-triage-round-2.json) retain the independent adjudication.

A [uniform bounded scope trace](account-scope-comparison.json) also checks all three prior and new final workspaces under that same interpretation. It confirms the prior round-2 global account-count query and prior round-3 unscoped rowid-lookup guard; these demonstrated patterns are absent from the three new final candidates. This is source/trace confirmation of specific patterns, not an exhaustive SQL analyzer or a new independent review. The historical stored 7/9 outcome remains unchanged, and these additional historical gaps are disclosed separately.

Round-3 Critical initially received independent PASS. Its raw PASS and assessment remain retained; a separately traced public-transfer account-read violation blocked completion and triggered measured repair. Coordinator finding histories are recorded separately in [all trials](trials.csv), including scope findings batched into earlier repair requests. A reviewer PASS cannot waive an actual original-contract failure.

Failed trials exhausted the [frozen skill repair limit](round-1/medium/initial/.agents/skills/lean-run/SKILL.md): “After the second REWORK, allow one final fix-only pass plus verification/review; unresolved mandatory findings mean FAILED.” They were retained and not replaced with favorable samples.

Remaining findings: [round-1/critical](round-1/critical/review-3/final.txt).

Remaining findings: [round-2/critical](round-2/critical/review-3/final.txt).

## Actual recorded consumption

The nine new trials used **182:38 recorded agent time**, **UNKNOWN total tokens**, **UNKNOWN uncached input**, and **UNKNOWN uncached input + output**. The previous nine trials used **135:39**, **7,145,208 total tokens**, **863,759 uncached input**, and **1,155,960 uncached input + output**. These totals include failed attempts and every measured repair; means are reported separately above. Timed-out elapsed durations are bounded observed costs, not completed-phase latencies.

Known consumption lower bound (excluding every unknown phase's unreported token usage): **5,787,923 total tokens**, **656,512 uncached input**, **883,859 uncached input + output**. This lower bound is not an exact total when any usage is unknown. Raw timeout records and any measurement amendment remain in the archive.

Coordinator chat, static skill review, preparation, graders, cross-regressions, diagnostic probes and reporting are excluded from agent time/token totals. Their model token usage is unavailable. Counts are usage observations, not billing-price estimates; cached input is a subset of input and reasoning is already included in output.

## Changes, controls and limits

- Entry instructions were shortened and bounded implementation now favors one focused discovery pass, a targeted reproducer, the smallest complete edit, compact gap tests and final verification. Source stays on disk for diffs instead of being reprinted in base64/serialized snapshots. Required checks, public journeys, independent review and the repair limit remain mandatory.
- A conditional write-integrity reference makes required effects, preservation outside the allowed write set and valid no-op counterexamples explicit before implementation. It retains scoped reads and covers effective changes, ignored conflicts, replacement collisions, internal rowids, rollback and durable replay. It is procedure guidance, not fixture-specific application code.
- Initial application files, contracts, public tests, AGENTS.md, implementation/first-review prompts and graders are byte-identical to the prior tasks. Each new trial uses the same frozen skill package. No skill edits occur inside the cohort. [Controls](controls.json) and [manifest](manifest.json) retain hashes and settings.
- Requested model/effort remain **gpt-6-astra / max**, standard procedure depth, 900-second per-phase timeout and existing ChatGPT authentication. Backend identity is not independently attested. Order remains medium/high/critical, high/critical/medium, critical/medium/high; one active worker at a time.
- No synthetic warmup; cache state, remote load and host contention were not controlled. Development knowledge informs this version and the fixed quality probes, so the known tasks are not a held-out benchmark. Repairs use demonstrated findings and final quality may differ from the historical failed candidates.
- Data is synthetic/local. Runtime coverage is limited to the recorded Python/SQLite/CLI environment; evaluator read boundaries are instructional. Neither this sample nor passing tests establishes production behavior or guarantees future model decisions.

## Evidence

[Summary](summary.json), [all trials](trials.csv), [all phases](phases.csv), [comparison](comparison.csv), [usage integrity](metric-integrity.json), [control audit](control-audit.json), [static skill review](skill-review.json), [repository validation](validation.json), [archive hashes](archive-sha256.json), and [previous report](../2026-11-03-lean-run-repeated/README.md).

Every round retains initial/final workspaces, prompts, events, usage, grades, probe reports, independent findings, source hashes and all repairs. Unsuccessful observations remain part of this record.
