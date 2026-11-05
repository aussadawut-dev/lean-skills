"""Render verified repeated-cohort results, including failed attempts and limits."""
import argparse
import json
import os
from pathlib import Path


def read(path):
    return json.loads(path.read_text())


def clock(seconds):
    if seconds is None:return 'UNKNOWN'
    value=round(seconds)
    return f'{value//60}:{value%60:02d}'


def number(value):
    return f'{value:,.0f}' if value is not None else 'UNKNOWN'


def delta(value):
    return f'{value:+.1f}%' if value is not None else 'UNKNOWN'


def render(root):
    root=root.resolve();summary=read(root/'summary.json');manifest=read(root/'manifest.json')
    quality=summary['quality'];target=summary['optimization_target'];baseline=Path(manifest['baseline_archive'])
    prior=read(baseline/'summary.json');old={row['level']:row for row in prior['levels']}
    critical_target=target['level']=='critical'
    title='Critical speed and integrity' if critical_target else 'Critical integrity and Medium implementation'
    text=f'''# lean-run: {title}

**Requested target: {'MET IN THIS SAMPLE' if target['met_in_observed_sample'] else 'NOT MET'}.** Final quality: **{quality['passed_trials']}/9 passing trials**, **{len(quality['failed_trials'])} FAILED**, **{quality['final_independent_findings']} remaining independent findings**. Every launched phase and failed attempt remains in the recorded costs.

The new candidate ran the original medium/high/critical questions three times each, with fresh initial implementation and independent-review contexts. It is compared to the **latest cohort's three observations per level**, including its failed Critical attempts. The prior cohort is retained unchanged. This is a descriptive comparison, not a causal or statistical guarantee.

Incomplete execution/usage records: **{', '.join(quality.get('incomplete_execution_trials',[])) or 'none'}**. A TIMEOUT can have passing artifact-quality checks while its execution and token measurement remain incomplete. Unknown usage is never zero or an imputed value. A token mean is UNKNOWN unless all three observations are known; a mean of the remaining observations is not substituted.

## Time and uncached means

Times sum CLI implementation, review, every repair and renewed review. Uncached input = reported input minus cached input. Output (including reasoning) is added only in the separate composite measure. Positive changes are increases.

| Level | Previous mean → new mean | Time change | Uncached input: previous → new | Change | Uncached input + output: previous → new | Change |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
'''
    for row in summary['levels']:
        before=row['baseline'];stats=row['statistics'];change=row['mean_change_percent']
        text+=f"| {row['level']} | {clock(before['measured_seconds'])} → {clock(stats['measured_seconds']['mean'])} | {delta(change['measured_seconds'])} | {number(before['uncached_input_tokens'])} → {number(stats['uncached_input_tokens']['mean'])} | {delta(change['uncached_input_tokens'])} | {number(before['uncached_input_plus_output'])} → {number(stats['uncached_input_plus_output']['mean'])} | {delta(change['uncached_input_plus_output'])} |\n"
    if critical_target:
        critical=next(row for row in summary['levels'] if row['level']=='critical')
        if critical['baseline']['uncached_input_tokens'] is None:
            text+='\nThe preceding Critical cohort has incomplete uncached usage. Its three-trial mean and percentage difference are UNKNOWN, even if the new mean is complete. Observed elapsed costs include the fixed timeout durations.\n'
        text+='''
| Critical phase | Previous mean (seconds) | New mean (seconds) | Difference |
| --- | ---: | ---: | ---: |
'''
        for phase in ('implementation','repair-1','repair-2','reviews'):
            previous=critical['baseline_phase_means'][phase];current=critical['candidate_phase_means'][phase]
            text+=f"| {phase} | {previous:.1f} | {current:.1f} | {current-previous:+.1f} |\n"
        text+='\nUnused repairs contribute zero elapsed cost. Each review is included in the review total.\n'
    medium=next(row for row in summary['levels'] if row['level']=='medium')
    text+=f'''
Medium's initial implementation mean: **{medium['baseline_implementation_seconds']['mean']:.3f} → {medium['implementation_seconds']['mean']:.3f} seconds ({delta(medium['implementation_time_change_percent'])})**. This is measured separately from review; full-workflow time above still includes all required work.

| Level | Time SD: previous → new (seconds) | New time min–max | Total tokens: previous mean → new mean | Change |
| --- | ---: | ---: | ---: | ---: |
'''
    for row in summary['levels']:
        stats=row['statistics'];previous=old[row['level']]['statistics']['measured_seconds']
        text+=f"| {row['level']} | {previous['sample_sd']:.1f} → {stats['measured_seconds']['sample_sd']:.1f} | {stats['measured_seconds']['min']:.1f}–{stats['measured_seconds']['max']:.1f} | {number(row['baseline']['total_tokens'])} → {number(stats['total_tokens']['mean'])} | {delta(row['mean_change_percent']['total_tokens'])} |\n"
    text+='''
Medians, token variance and all min/max values are in [comparison.csv](comparison.csv).

## Individual outcomes and quality

| Round | Level | Outcome | Time | Uncached input | Uncached input + output | Total tokens | Independent findings by review | Repairs |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
'''
    for trial in summary['trials']:
        history=' → '.join(str(value) for value in trial['review_issue_history'])
        text+=f"| {trial['round']} | {trial['level']} | {trial['status']} | {clock(trial['measured_seconds'])} | {number(trial['uncached_input_tokens'])} | {number(trial['uncached_input_plus_output'])} | {number(trial['total_tokens'])} | {history} | {trial['repair_rounds']} |\n"
    text+=f'''
Final original-grader failures: **{quality['final_contract_issues']}**; remaining independent findings: **{quality['final_independent_findings']}**; remaining explicit coordinator findings: **{quality['final_coordinator_findings']}**; failed predeclared additional-probe cases: **{quality['final_added_probe_failed_cases']}**; failed posthoc follow-up cases: **{quality['final_posthoc_probe_failed_cases']}**. These signals overlap and must not be added into a globally unique bug count. Original grade categories remain 4/6/9 (57 final category checks across three rounds). Protected files and review-workspace integrity remain mandatory.

All previously discovered Critical probes were frozen before the first model phase: four original silent-write checks and twelve additional cases covering required effects, audit-history preservation, historical receipts/unrelated accounts, valid rowid movement, ignored inserts/updates and foreign malformed-text isolation. They run after every Critical independent review, starting with the first assessment. Passing the original grader cannot waive their failure. [Manifest](manifest.json) lists the exact copied scripts; each assessment retains the full reports and source hashes. Historical regression suites from all three previous final workspaces also run against every candidate; reverse cross-regressions remain visible. Contract-external assertions require a retained evidence-backed adjudication and cannot waive a real finding.

The previous cohort ended with {prior['quality']['passed_trials']}/9 passing trials and {prior['quality']['final_independent_findings']} remaining independent findings. Its probes were discovered during follow-up; they are available from the start in this new experiment. Critical cost comparisons therefore describe recorded work, including different repair paths and unsuccessful attempts, **not equal-quality time to successful completion**.
'''
    if critical_target:
        text+='''
The preceding cohort's frame and trigger compatibility probes are now mandatory from the first assessment. These include extra UNIQUE account/receipt/audit victims, ignored conflicts and valid replacements, unquoted keyword/Unicode names, and conditional VALUES/WITH bodies. The same scripts ran on all three previous final workspaces. Case failures may overlap independent findings.

| Targeted probe | Executions per workspace | Previous failed cases (rounds 1/2/3) | New failed cases (rounds 1/2/3) |
| --- | ---: | --- | --- |
'''
        for name in ('frame_followup_probe','trigger_compatibility_probe'):
            before=[read(root/f'baseline-{n}-{name}.json') for n in (1,2,3)]
            after=[]
            for n in (1,2,3):
                trial=root/f'round-{n}/critical';result=read(trial/'result.json')
                assessment=read(trial/f"assessment-{result['final_assessment']}.json")
                after.append(assessment['critical_probes'][name+'.py']['report'])
            text+=f"| {name} | {len(before[0]['cases'])} | {' / '.join(str(v['failed_cases']) for v in before)} | {' / '.join(str(v['failed_cases']) if v is not None else 'UNKNOWN' for v in after)} |\n"
        diagnostics = (
            ('Dollar identifier', 'dollar', 'dollar-identifier', 'dollar_identifier'),
            ('Trigger counter', 'counter', 'trigger-counter', 'trigger_counter'),
            ('Unquoted NBSP', 'unicode-space', 'unicode-space', 'unicode_space'),
            ('VT and BOM separators', 'separator', 'trigger-separator', 'trigger_separator'),
            ('Malformed foreign TEXT no-op', 'malformed-effect', 'malformed-effect', 'malformed_effect'),
        )
        text+='''
Findings during the run added posthoc probes. Each probe exercised API and CLI calls in DELETE and WAL modes against all three previous and new final workspaces. Round 1 reopened for the remaining bounded repair after the trigger-counter and NBSP findings. Its original closure, subsequent repair and renewed review are retained, with every phase counted in the elapsed cost.

| Posthoc probe | Previous failures (rounds 1/2/3) | New failures (rounds 1/2/3) |
| --- | --- | --- |
'''
        for label,protocol,baseline_suffix,candidate_prefix in diagnostics:
            previous=[];candidate=[]
            for n in (1,2,3):
                previous.append(read(root/f'baseline-{n}-{baseline_suffix}.json')['failed_cases'])
                trial=root/f'round-{n}/critical';result=read(trial/'result.json')
                report=read(trial/f"assessment-{result['final_assessment']}-{candidate_prefix}_probe.json")
                candidate.append(report['failed_cases'])
                if result['status']=='DONE' or result.get('quality_status')=='PASS':
                    assert report['failed_cases']==0, trial
            text+=f"| [{label}]({protocol}-protocol.json) | {' / '.join(map(str,previous))} | {' / '.join(map(str,candidate))} |\n"
        text+='\nCopied probes initially could not import a local helper module in round 1. The coordinator supplied the workspace import path and reran those probes. The archive includes the raw import failures and the evaluator amendment. [Evaluator amendment](measurement-amendment.json)\n'
    if summary.get('posthoc_followup'):
        text+='''
New independent findings also produced bounded posthoc diagnostics, applied uniformly to all three previous and new Critical final workspaces. The frame probe has six cases: identical foreign replacements, a replacement-based rowid swap, and hidden account/receipt victims from extra UNIQUE indexes. The trigger-compatibility probe executes its cases through API and CLI in DELETE and WAL modes: hidden audit replacement loss, its successful IGNORE control, benign keyword/Unicode trigger names, a quoted control and legal VALUES/WITH bodies with WHEN. Unicode cases were added after round-2 review-3; VALUES/WITH cases followed round-3 review-2. Prior v1/v2 scripts and reports remain archived. The table below reports exact execution counts. These are disclosed follow-ups to demonstrated findings, not predeclared or held-out tests. [Protocol](followup-protocol.json) and the per-workspace reports retain their timing, source hashes and evidence.

| Posthoc probe | Executed cases per trial | Previous failed cases, rounds 1/2/3 | New failed cases, rounds 1/2/3 |
| --- | ---: | --- | --- |
'''
        for name,probe in summary['posthoc_followup']['probes'].items():
            text+=f"| {name} | {probe['executed_cases_per_trial']} | {' / '.join(map(str,probe['baseline_failed_cases']))} | {' / '.join(map(str,probe['candidate_failed_cases']))} |\n"
        text+='\nThe strict account-read scope was checked separately against the original contract: returning only an aggregate or mismatch flag does not authorize foreign account lookups. Storage checks of actual write effects can preserve the frame without fetching foreign stored accounts. [Contract triage](contract-triage.json) and [round-2 follow-up](contract-triage-round-2.json) retain the independent adjudication.\n'
        text+='\nA [uniform bounded scope trace](account-scope-comparison.json) also checks all three prior and new final workspaces under that same interpretation. It confirms the prior round-2 global account-count query and prior round-3 unscoped rowid-lookup guard; these demonstrated patterns are absent from the three new final candidates. This is source/trace confirmation of specific patterns, not an exhaustive SQL analyzer or a new independent review. The historical stored 7/9 outcome remains unchanged, and these additional historical gaps are disclosed separately.\n'
        text+='\nRound-3 Critical initially received independent PASS. Its raw PASS and assessment remain retained; a separately traced public-transfer account-read violation blocked completion and triggered measured repair. Coordinator finding histories are recorded separately in [all trials](trials.csv), including scope findings batched into earlier repair requests. A reviewer PASS cannot waive an actual original-contract failure.\n'
    if quality['failed_trials']:
        text+='\nFailed trials exhausted the [frozen skill repair limit](round-1/medium/initial/.agents/skills/lean-run/SKILL.md): “After the second REWORK, allow one final fix-only pass plus verification/review; unresolved mandatory findings mean FAILED.” They were retained and not replaced with favorable samples.\n'
        for trial in summary['trials']:
            if trial['status']=='FAILED':
                phase='review' if len(trial['review_issue_history'])==1 else f"review-{len(trial['review_issue_history'])}"
                location=f"round-{trial['round']}/{trial['level']}"
                text+=f"\nRemaining findings: [{location}]({location}/{phase}/final.txt).\n"
    actual=summary['totals']['actual_nine_trial_consumption'];previous=summary['totals']['baseline_actual_consumption']
    text+=f'''
## Actual recorded consumption

The nine new trials used **{clock(actual['measured_seconds'])} recorded agent time**, **{number(actual['total_tokens'])} total tokens**, **{number(actual['uncached_input_tokens'])} uncached input**, and **{number(actual['uncached_input_plus_output'])} uncached input + output**. The previous nine trials used **{clock(previous['measured_seconds'])}**, **{number(previous['total_tokens'])} total tokens**, **{number(previous['uncached_input_tokens'])} uncached input**, and **{number(previous['uncached_input_plus_output'])} uncached input + output**. These totals include failed attempts and every measured repair; means are reported separately above. Timed-out elapsed durations are bounded observed costs, not completed-phase latencies.

Known consumption lower bound (excluding every unknown phase's unreported token usage): **{number(summary['totals']['known_consumption_lower_bound']['total_tokens'])} total tokens**, **{number(summary['totals']['known_consumption_lower_bound']['uncached_input_tokens'])} uncached input**, **{number(summary['totals']['known_consumption_lower_bound']['uncached_input_plus_output'])} uncached input + output**. This lower bound is not an exact total when any usage is unknown. Raw timeout records and any measurement amendment remain in the archive.

Coordinator chat, static skill review, preparation, graders, cross-regressions, diagnostic probes and reporting are excluded from agent time/token totals. Their model token usage is unavailable. Counts are usage observations, not billing-price estimates; cached input is a subset of input and reasoning is already included in output.

## Changes, controls and limits

- {'The write-integrity reference directs one small mechanism proof before implementation, covering effective changes and hidden UNIQUE replacement victims. It preserves scoped reads, rollback, replay, concurrency and independent review.' if critical_target else 'Entry instructions were shortened and bounded implementation favors targeted reproduction, compact gap tests and final verification.'}
- {'Trigger instrumentation, if needed, preserves SQL spans and requires early checks for unquoted Unicode, keyword identifiers and conditional compound bodies. The guide contains no fixture implementation.' if critical_target else 'The conditional write-integrity reference covers frame conditions, valid no-op controls, replacement collisions and durable replay.'}
- Initial application files, contracts, public tests, AGENTS.md, implementation/first-review prompts and graders are byte-identical to the prior tasks. Each new trial uses the same frozen skill package. No skill edits occur inside the cohort. [Controls](controls.json) and [manifest](manifest.json) retain hashes and settings.
- Requested model/effort remain **gpt-6-astra / max**, standard procedure depth, 900-second per-phase timeout and existing ChatGPT authentication. Backend identity is not independently attested. Order remains medium/high/critical, high/critical/medium, critical/medium/high; one active worker at a time.
- No synthetic warmup; cache state, remote load and host contention were not controlled. Development knowledge informs this version and the fixed quality probes, so the known tasks are not a held-out benchmark. Repairs use demonstrated findings and final quality may differ from the historical failed candidates.
- Data is synthetic/local. Runtime coverage is limited to the recorded Python/SQLite/CLI environment; evaluator read boundaries are instructional. Neither this sample nor passing tests establishes production behavior or guarantees future model decisions.

## Evidence

[Summary](summary.json), [all trials](trials.csv), [all phases](phases.csv), [comparison](comparison.csv), [usage integrity](metric-integrity.json), [control audit](control-audit.json), [static skill review](skill-review.json), [repository validation](validation.json), [archive hashes](archive-sha256.json), and [previous report]({os.path.relpath(baseline/'README.md',root)}).

Every round retains initial/final workspaces, prompts, events, usage, grades, probe reports, independent findings, source hashes and all repairs. Unsuccessful observations remain part of this record.
'''
    if (root/'warning-investigation.json').is_file():
        text+='''
## Warning and interruption

The captured CLI events, stderr and relevant chat events do not identify a cybersecurity warning, its triggering command or a policy rejection. The observed CLI warnings reported a local rollout-state lookup fallback. The chat recorded an interruption while round-3 Critical repair 1 was running. Its existing CLI process finished with exit code 0 and a raw usage event. The coordinator recovered elapsed time from the original launch and a Darwin process-exit observation, then continued at the renewed review. The repair ran once under the original 900-second deadline. Coordinator wait time remains outside measured workflow cost. The earlier Critical implementation timeout still has unknown usage. [Warning investigation](warning-investigation.json), [recovery record](interruption-recovery.json), [observed exit](recovered-exit-status.json).
'''
    (root/'README.md').write_text(text)
    print('Rendered descriptive comparison with terminal outcomes and actual consumption.')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('directory',type=Path)
    render(parser.parse_args().directory)
