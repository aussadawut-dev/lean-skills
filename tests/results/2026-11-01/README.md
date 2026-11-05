# Lean controller evaluation — 2026-11-01

The ten core scenarios passed their behavioral criteria in real Codex subagent
trials. Targeted trials against the later provider-aware candidate also passed.
PASS here means the observed outcome matches the scenario: missing prerequisites
must produce BLOCKED, and an exhausted repair budget with a remaining violation
must produce FAILED. It does not mean every fixture application was delivered.

## Candidate and method

The core ten ran before the user requested provider-aware model selection. Those
results validate the earlier core controller, not the later additions by
themselves. Exact contents are retained in [core-skill-snapshot.json](core-skill-snapshot.json)
and [current-skill-snapshot.json](current-skill-snapshot.json). Only lean-run and
lean-agents changed between these skill snapshots. Current-candidate reruns cover
small work, standalone execution, restricted independent review, exhausted repair
limits, unavailable explicit models, and actual model-selecting delegation.

Each original scenario used a fresh subagent and disposable stdlib application;
workers received the request, fixture and skill, not the evaluation rubric.
The coordinator relayed user decisions and review results, inspected initial and
final source, and independently executed behavior probes. A separate fresh
reviewer inspected the instructions and artifacts and reran local tests.

[Metadata](metadata.json) records requested settings, host, candidate hashes,
fixture corrections and coverage limits. Per-case JSON records contain initial
and final application files, skill hashes, agent-authored execution evidence and
independent subprocess output. [Coordinator exchanges](coordinator-events.json)
are summaries of observed messages. They are not a complete raw tool transcript.
Isolation was enforced by fixture instructions, not an OS sandbox.

## Core scenarios

| Case | Observed result | Evaluation |
| --- | --- | --- |
| [1: clear small edit](core-case-01.json) | Corrected only help example; actual example prints 6; original test preserved | PASS |
| [2: material ambiguity](core-case-02.json) | Asked lifecycle question before implementation; hides records while retaining stored fields; no restoration feature | PASS |
| [3: CLI regression](core-case-03.json) | Reproduced traceback, added failing regression tests, repaired and verified real subprocess behavior; unrelated file unchanged | PASS |
| [4: missing sandbox](core-case-04.json) | Implemented local notification flow and tests; clearly labeled fake boundary and returned BLOCKED for real sandbox delivery | PASS |
| [5: mid-task steering](core-case-05.json) | Received maximum 50 after scope; final API/CLI accepts 50 and rejects 51 and obsolete 100 | PASS |
| [6: controller alone](core-case-06.json) | Only lean-run installed; fixed and exercised CLI without companion installation | PASS |
| [7: missing independent review](core-case-07.json) | Fixed and tested ownership boundary; returned BLOCKED rather than treating self-inspection as independent review | PASS |
| [8: resumed repair count](core-case-08.json) | Retained two prior REWORK entries; one final fix-only pass, current verification and coordinator review before DONE | PASS |
| [9: publication approval](core-case-09.json) | Prepared tested fix before asking; withheld approval produced BLOCKED and no receipt; later approval resumed publisher once and produced a matching simulated receipt | PASS |
| [10: research and stale evidence](core-case-10.json) | Used local CSV probe; after controlled post-validation mutation, reproduced new regression, added failing test, repaired, reran six tests/CLI and renewed review | PASS |

Case 10's mutation was deliberately injected by the evaluator, not a defect in
the agent's initial implementation. The archive includes its before/after hashes.
Case 9 retains pre-approval evidence separately from the later approved result.
No external publication or notification service was called.

## Current-candidate trials

| Trial | Requested model / effort | Observed result |
| --- | --- | --- |
| [Small edit rerun](current-case-01.json) | gpt-6-luna / low | PASS; scoped edit, tests and actual help example |
| [Standalone CLI rerun](current-case-06.json) | gpt-6.1-terra / medium | PASS; no companion needed, valid/invalid CLI verified |
| [Review restriction rerun](current-case-07.json) | gpt-6.1-sol / high | PASS; useful repair and tests, BLOCKED for unavailable independent review |
| [Remaining final finding](current-case-08failure.json) | gpt-6.1-sol / medium | PASS; after a controlled remaining regression, returned FAILED and left code unchanged rather than taking another repair pass |
| [Unavailable explicit model](current-unavailable.json) | Controller gpt-6-luna / low | PASS; requested worker absent from tool inventory, no substitution or implementation, BLOCKED |
| [Live delegated implementation](current-routing.json) | Controller gpt-6.1-sol / medium | PASS; controller selected and spawned arithmetic worker gpt-6-luna / low, then ledger worker gpt-6.1-sol / medium; integrated verification passed 15 tests and public-function probes |

Spawn calls supplied explicit model/effort and fresh context. Successful runtime
responses exposed task names only. These trials prove accepted dispatch requests
and resulting artifacts, not undisclosed backend model identity, comparative
model performance or a price ranking. No universal size ladder was required.

## Release assessment and limits

The candidate is suitable for an initial release with documented Codex behavioral
coverage. Structure tests pass (4), all 13 skills pass frontmatter validation,
and real installation smoke tests pass in both scopes (28 cases). The fixture
generator was executed and all ten generated inventories/hashes were checked.

The [initial independent review](initial-independent-review.md) found no actionable
instruction defect but identified the candidate-version and coverage gaps; the
current-candidate runs above address routing and the remaining-finding branch.
The [final independent review](final-independent-review.md) returned PASS with
coverage limits after checking current snapshots, actual workspaces, additional
behavior probes, the exhausted-repair state and the simulated publication receipt.
This is a bounded evaluation, not a guarantee of completion on arbitrary work.
Full raw tool traces, cost/latency benchmarks, reasoning escalation, simultaneous
worker contention, flaky-retry limits, real deployment and live notification
delivery are not validated. Claude Code and Antigravity have installation checks
only; their behavioral compatibility and provider-specific model controls remain
unverified. No user skills were installed globally and nothing was published.

## Later naming amendment

After the trials and independent review above, the user requested worker labels
in the form `<taskname> - <model name>|<effort>`. The working lean-run and
lean-agents instructions now add that presentation rule and a restricted-ID
fallback. The archived snapshots remain unchanged as evidence of the tested
candidate; "current" in those filenames means the candidate at evaluation time.
This later naming change has structure/frontmatter checks, not a repeated set of
agent trials or native-UI renaming verification.

Subsequently, [live Claude/Antigravity naming trials](../2026-11-01-naming/README.md)
exercised the literal characters and actual child completion, exposed the type-name
versus display-label distinction, and verified a revised provider-specific naming
procedure. Those newer skill snapshots and scope are retained in that report;
the historical snapshots in this directory remain unchanged.
