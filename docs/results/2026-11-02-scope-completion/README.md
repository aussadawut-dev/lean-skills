# Scoped completion and specialist trials — 2026-11-02

Five bounded, fresh-context Codex agent trials passed the scenario criteria for
the candidate archived in [trials.json](trials.json). This validates the observed
decisions below, not every task, skill mode or host. A correct REWORK or FAILED
result is a behavioral PASS when the fixture contains a mandatory failure.

| Trial | Observed endpoint | Coordinator verification |
| --- | --- | --- |
| lean-security, review only | REWORK with demonstrated cross-account invoice exposure; no repair | Repeated the cross-account probe, ran the passing own-account test, compared all application hashes. |
| lean-release, failed release and recovery | Release FAILED; recovery DONE | One deploy and one rollback in simulator history, resulting v1 healthy on two checks, all records preserved, artifact/source unchanged. The agent inspected state after a lost response instead of repeating the deploy. |
| lean-task, diagnosis only | DONE for a supported configuration-type diagnosis and bounded proposal | Repeated the failing CLI and numeric counterexample; all application/configuration files unchanged. The agent disclosed in-memory mocks and the separate floating-point presentation detail. |
| lean-scope, UX scope only | READY_WITH_ASSUMPTIONS with observable acceptance and verification plan | Read the complete scope against source/request, checked bounded keyboard/layout/feedback/recovery requirements and disclosed assumptions; source unchanged. Browser/assistive-technology checks were planned, not executed. |
| lean-run, handoff only | Handoff DONE; underlying repair FAILED | Repeated current failing tests/CLI, compared hashes, checked stale prior evidence was rejected and two REWORK results plus the remaining final fix-only pass were retained. |

The archive includes raw requests, supplied skill/reference contents, initial and
final fixture files and hashes, agent-authored evidence, and independent command
outputs. Spawn calls used `fork_turns="none"` without model/effort overrides.
Returned metadata did not expose backend model/effort; no backend identity or
model comparison is claimed. These are evidence reports and coordinator checks,
not complete raw tool transcripts. Fixture isolation was instructional, not an
OS sandbox. No real service or production deployment was contacted.

[validation.json](validation.json) records local validation:

- Nine standard-library unit/fixture tests passed, including actual simulator
  state transitions and standalone fixture inventory/resource checks.
- Skill Creator frontmatter validation passed all 16 packages.
- Skills CLI 1.7.4 passed 34 installation scenarios using an existing local CLI:
  collection plus each skill, in temporary global and project scopes. Checks
  covered full packaged resources, content and scope isolation. The user's real
  global skills were unchanged.
- The original collection-discovery test failed on `.DS_Store`; discovery now
  selects actual skill directories and leaves that file intact. The original
  core fixture generator uses the same entrypoint-based discovery.

A fresh independent reviewer inspected all entrypoints, references, EN/TH
documentation and changed test code against base
`75684772412b81d5f640b12abe2b66094b5bbe1d`, and returned PASS with no actionable
functional or authorization finding. The reviewer ran eight targeted offline
tests and all 16 schema checks; it did not run installation or the unchanged
update-fixture test. It identified one trailing blank line, which was removed.
The initial review preceded this evidence archive. A subsequent read-only
addendum review also returned PASS: all 35 candidate file hashes matched current
source, all five archived requests/reports/final states matched the surviving
fixtures, initial contents matched the generator, and EN/TH links and coverage
claims were consistent. It did not repeat broad tests or live operations.

Not validated here: Claude Code/Antigravity runtime behavior, live release or
data migration/recovery, security remediation with an independent final reviewer,
screen-reader/browser execution, actual continuation across host sessions,
production monitoring, performance benchmarks, or all paths through the other
skills. Historical reports remain evidence for their own candidates, not proof
that this entire candidate passed their complete suites. No source-repository
commit, push, publication or installation into real global skill directories was
part of this work.
