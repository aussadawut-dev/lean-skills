"""Render verified repeated-cohort results, including failed attempts and limits."""
import argparse
import json
import os
from pathlib import Path

from repeated_benchmark import archive_path


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


def render_pilot(root, summary, manifest, prior, baseline):
    levels = summary['levels']
    trials = summary['trials']
    quality = summary['quality']
    target = summary['optimization_target']
    baseline_trials = [t for t in prior['trials'] if t['level'] in {row['level'] for row in levels}]
    single_pair = all(row['baseline_n'] == row['candidate_n'] == 1 for row in levels)
    phase_label = 'time' if single_pair else 'mean'
    target_labels = {
        'measured_seconds': 'workflow time reduced',
        'uncached_input_tokens': 'uncached input reduced',
        'uncached_input_plus_output': 'uncached input plus output reduced',
    }
    text = [
        '# lean-run ' + ' and '.join(row['level'].title() for row in levels) + ' pilot',
        '',
        f"**Requested target {'met' if target['met_in_observed_sample'] else 'not met'} in this sample.** "
        f"{quality['passed_trials']}/{len(trials)} trials passed quality, "
        f"{quality['fully_completed_trials']}/{len(trials)} passed quality with complete telemetry.",
        '',
        ('Each level has one archived observation and one new observation. ' if single_pair
         else 'Historical means include failed attempts and elapsed time at the timeout cap. ') +
        'The pilot is descriptive. Differences also reflect the observed repair paths, quality outcomes and gate coverage.',
        '',
        f"Target checks for {target['level'].title()} and the shared gates. "
        + ', '.join(f"{target_labels.get(key, key.replace('_', ' '))} {'PASS' if passed else 'UNMET'}"
                    for key, passed in target['checks'].items()) + '.',
        '',
        '## Workflow comparison',
        '',
        '| Level | Baseline n → pilot n | Workflow time | Change | Uncached input | Change | Uncached input + output | Change |',
        '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |',
    ]
    comparison_metrics = (
        ('measured_seconds', clock), ('uncached_input_tokens', number),
        ('uncached_input_plus_output', number),
    )
    for row in levels:
        comparable = row.get('comparison_valid', True)
        cells = [row['level'].title() + ('' if comparable else ' (new baseline)'), f"{row['baseline_n']} → {row['candidate_n']}"]
        for key, fmt in comparison_metrics:
            cells.extend((f"{fmt(row['baseline'][key])} → {fmt(row['statistics'][key]['mean'])}",
                          delta(row['mean_change_percent'][key]) if comparable else 'not comparable'))
        text.append('| ' + ' | '.join(cells) + ' |')
    text.extend([
        '',
        'Workflow time sums implementation, all reviews and any repairs. Uncached input is input minus cached input. '
        'Reported output already includes reasoning. Unknown usage makes the corresponding total and mean unknown. '
        'A single observation has no sample standard deviation.',
        '',
        f'| Level | Phase | Baseline {phase_label} (s) | Pilot {phase_label} (s) | Difference (s) |',
        '| --- | --- | ---: | ---: | ---: |',
    ])
    for row in levels:
        for phase, before in row['baseline_phase_means'].items():
            after = row['candidate_phase_means'][phase]
            text.append(f"| {row['level'].title()} | {phase} | {before:.1f} | {after:.1f} | {after-before:+.1f} |")
    text.extend([
        '',
        'Repairs that did not run contribute zero time. The review row combines initial and renewed reviews.',
        '',
        '## Quality and execution',
        '',
        '| Trial | Outcome | Quality | Final blockers | Incomplete phases | Independent findings by review | Repairs |',
        '| --- | --- | --- | --- | --- | --- | ---: |',
    ])
    for trial in trials:
        location = f"round-{trial['round']}/{trial['level']}"
        result = read(root / location / 'result.json')
        assessment = f"{location}/assessment-{result['final_assessment']}.json"
        blockers = ', '.join(read(root / assessment)['blockers']) or 'None'
        history = ' → '.join(map(str, trial['review_issue_history']))
        incomplete = ', '.join(trial['incomplete_phases']) or 'None'
        text.append(f"| [{location}]({assessment}) | {trial['status']} | "
                    f"{'PASS' if trial['quality_passed'] else 'FAILED'} | {blockers} | "
                    f"{incomplete} | {history} | {trial['repair_rounds']} |")
    text.extend(['', '| Final quality signal | Historical selected levels | Pilot |', '| --- | ---: | ---: |'])
    quality_metrics = (
        ('Original grader category failures', 'final_contract_issues'),
        ('Independent findings', 'final_review_issues'),
        ('Coordinator findings', 'final_coordinator_findings'),
        ('Original supplemental issues', 'final_original_supplemental_issues'),
        ('Additional mandatory probe failed cases', 'final_added_probe_failed_cases'),
        ('Post-run probe failed cases', 'final_posthoc_probe_failed_cases'),
    )
    if manifest.get('gate_policy') == 'contract':
        quality_metrics += (('Advisory probe failed cases (not gates)', 'final_advisory_probe_failed_cases'),)
    for label, key in quality_metrics:
        text.append(f"| {label} | {sum(t.get(key, 0) for t in baseline_trials)} | {sum(t.get(key, 0) for t in trials)} |")
    for row in levels:
        level = row['level']
        baseline_checks = sum(t['final_contract_categories'] for t in baseline_trials if t['level'] == level)
        pilot_checks = sum(t['final_contract_categories'] for t in trials if t['level'] == level)
        text.append(f"| {level.title()} original grader category checks | {baseline_checks} | {pilot_checks} |")
    text.extend([
        '',
        f"Historical quality passes by level were "
        + ', '.join(f"{row['level'].title()} "
                    f"{sum(t['quality_passed'] for t in baseline_trials if t['level'] == row['level'])}/{row['baseline_n']}"
                    for row in levels) + '.',
        '',
        'Findings and failed cases are different units and can overlap. '
        + ('The original benchmark tasks, public tests, initial implementation/review prompts and graders are unchanged. '
           if not manifest.get('contract_changed_levels') else
           'The ' + ', '.join(level.title() for level in manifest['contract_changed_levels'])
           + ' CONTRACT.md changed by a recorded policy decision ([policy record](policy-record.md)); that level starts a new '
           'baseline, so its comparison with the prior archive is not like-for-like. Other initial files, public tests, '
           'prompts and graders are unchanged. Historical expectations superseded by that policy are listed in '
           '[superseded expectations](superseded-expectations.json) and reported separately, never as passed. ')
        + ('Under the [contract gate policy](../../benchmark/README.md), the original grader, independent review, '
           'protected-file integrity and the mandatory probes ('
           + ', '.join(manifest.get('mandatory_probes', [])) + ') block; '
           f"the other {len(manifest.get('advisory_probes', []))} probes and the historical suites run as advisory reports. "
           'A reference solution passed every mandatory gate before launch ([reference check](reference-check.json)). '
           if manifest.get('gate_policy') == 'contract' else
           'Independent review, protected-file integrity and historical regressions remain '
           f"mandatory. Critical runs {len(manifest.get('known_quality_probes', []))} frozen probe scripts at each assessment. ")
        + 'A clean original grade alone cannot pass the expanded gates. [Manifest](manifest.json)',
    ])
    if manifest.get('targeted_probes'):
        text.extend(['', 'The quality table reports each run’s original gate outcomes. '
                     'The targeted replays below apply the same new cases to both workspaces.'])
    if 'regression_archives' in manifest:
        sources = ', '.join(
            f"[{archive_path(path).name}]({os.path.relpath(archive_path(path) / 'README.md', root)})"
            for path in manifest['regression_archives'])
        text.extend(['', 'Every assessment runs historical tests against the candidate and candidate tests against '
                     f'each retained historical workspace for the same level. Sources are {sources}. '
                     + ('Under the contract gate policy these suites are advisory. ' if manifest.get('gate_policy') == 'contract'
                        else 'Historical tests on the candidate are a mandatory gate. ')
                     + 'The reverse runs are diagnostic.'])
        text.extend(['', '| Final assessment | Historical suites failing on candidate | Candidate suite failing on historical workspaces |',
                     '| --- | ---: | ---: |'])
        for trial in trials:
            location = f"round-{trial['round']}/{trial['level']}"
            result = read(root / location / 'result.json')
            assessment = read(root / location / f"assessment-{result['final_assessment']}.json")
            cross = assessment['cross']
            counts = []
            for direction in ('historical_tests_on_candidate', 'candidate_tests_on_historical'):
                exits = [row['exit_code'] for row in cross if row['direction'] == direction]
                counts.append(f'{sum(code != 0 for code in exits)}/{len(exits)}')
            text.append(f"| {trial['level'].title()} round {trial['round']} | {' | '.join(counts)} |")
    if (root / 'historical-assertion-triage.json').is_file():
        text.extend(['', 'The three failed final historical assertions expected an exception for foreign TEXT-to-BLOB updates. '
                     'The candidate instead scoped those updates to zero rows, committed the required transfer and preserved '
                     'the old typed values, schema and replay. These are recorded outcome incompatibilities, not evidence '
                     'of persisted corruption in those three cases. The historical failures remain unwaived; '
                     'the independent findings still block acceptance. '
                     '[Typed-state triage](historical-assertion-triage.json), [raw comparison](typed_scope_triage.json).'])
    for trial in trials:
        location = f"round-{trial['round']}/{trial['level']}"
        result = read(root / location / 'result.json')
        assessment = read(root / location / f"assessment-{result['final_assessment']}.json")
        for finding in assessment['review']['findings']:
            text.extend(['', f"Remaining **{trial['level'].title()} {finding['id']} ({finding['severity']})** "
                         f"at `{finding['location']}`. {finding['requirement']} "
                         f"[Reproduction and suggested fix]({location}/{result['final_review']}/final.txt)"])
    if any(trial['status'] == 'FAILED' and trial['repair_rounds'] == 2 for trial in trials):
        text.extend(['', 'The frozen lean-run procedure permits two repairs, including a final fix-only pass. '
                     'It states “unresolved mandatory findings mean FAILED”. The remaining mandatory findings '
                     'keep the trial FAILED after the final review.'])
    probes = {name: Path(name).stem for name in manifest.get('targeted_probes', [])}
    earlier_probe = 'critical_final_findings_probe.py'
    if (earlier_probe in manifest.get('known_quality_probes', [])
            and earlier_probe not in read(baseline / 'manifest.json')['known_quality_probes']):
        probes[earlier_probe] = 'critical-final-findings'
    for probe, filename in probes.items():
        text.extend(['', f'| [{probe}]({probe}) | Failed cases / executed |',
                     '| --- | ---: |'])
        for historical in (t for t in baseline_trials if t['level'] == 'critical'):
            n = historical['round']
            path = f'baseline-{n}-{filename}.json'
            report = read(root / path)
            text.append(f"| [Historical Critical round {n}]({path}) | {report['failed_cases']}/{len(report['cases'])} |")
        for trial in (t for t in trials if t['level'] == 'critical'):
            location = f"round-{trial['round']}/critical"
            result = read(root / location / 'result.json')
            path = f"{location}/assessment-{result['final_assessment']}.json"
            report = read(root / path)['critical_probes'][probe]['report']
            count = f"{report['failed_cases']}/{len(report['cases'])}" if report else 'UNKNOWN'
            text.append(f"| [Pilot Critical round {trial['round']}]({path}) | {count} |")
        if probe == 'in_source_probe.py':
            text.extend(['', 'This probe replays the immediately preceding pilot’s final Critical finding '
                         'for plain and schema-qualified SQLite IN table sources and NOT INDEXED, '
                         'with aborting and harmless audit guards.'])
        text.extend(['', 'The historical replays are separate from the archived baseline grades.'])
    if 'name_resolution_probe.py' in manifest.get('known_quality_probes', []) and manifest.get('gate_policy') != 'contract':
        text.extend(['', 'The previously post-run [name-resolution probe](name_resolution_probe.py) '
                     'is now mandatory at every Critical assessment.'])
    protocol = 'name-resolution-protocol.json'
    if (root / protocol).is_file():
        text.extend([
            '',
            '### Name-resolution follow-up',
            '',
            'A command in the first Critical repair log exposed name-resolution errors involving CTEs '
            'and schema-qualified pragmas. The coordinator reproduced the cases after discovery. '
            'This follow-up is separate from the frozen Critical probes and the archived baseline grades. '
            f'[Discovery and replay protocol]({protocol})',
            '',
            '| Workspace | Failed cases / executed |',
            '| --- | ---: |',
        ])
        critical = next(row for row in levels if row['level'] == 'critical')
        reports = [(f'Historical Critical round {n}', f'baseline-{n}-name-resolution.json')
                   for n in range(1, critical['baseline_n'] + 1)]
        reports.append(('Pilot Critical after first repair', 'repair-1-name-resolution.json'))
        for label, path in reports:
            report = read(root / path)
            text.append(f"| [{label}]({path}) | {report['failed_cases']}/{len(report['cases'])} |")
        for trial in (t for t in trials if t['level'] == 'critical'):
            location = f"round-{trial['round']}/critical"
            result = read(root / location / 'result.json')
            path = f"{location}/assessment-{result['final_assessment']}.json"
            report = trial['posthoc_probes'].get('name_resolution_probe.py')
            count = f"{report['failed_cases']}/{report['executed_cases']}" if report else 'UNKNOWN'
            text.append(f"| [Pilot Critical round {trial['round']} final]({path}) | {count} |")
    foreign_guard_protocol = 'foreign-guard-discovery.json'
    if (root / foreign_guard_protocol).is_file():
        discovery = read(root / foreign_guard_protocol)
        text.extend([
            '',
            '### Foreign-account guard follow-up',
            '',
            f"Initial independent review discovered Critical {discovery['finding']} after the run started. "
            'The replay reproduced the observable foreign-account predicate in the archived baseline and the initial candidate. '
            'The independent finding is mandatory. Its replay was added after launch. '
            f"[Discovery protocol]({foreign_guard_protocol}), [probe]({discovery['probe']}).",
            '',
            '| Workspace | Failed checks |',
            '| --- | ---: |',
        ])
        reports = [('Archived Critical baseline', discovery['baseline_report']),
                   ('Initial Critical candidate', discovery['initial_candidate_report'])]
        for trial in (t for t in trials if t['level'] == 'critical'):
            path = f"round-{trial['round']}/critical/final-foreign_guard_probe.json"
            if (root / path).is_file():
                reports.append((f"Final Critical candidate, round {trial['round']}", path))
        for label, path in reports:
            report = read(root / path)
            text.append(f"| [{label}]({path}) | {report['failed_cases']} |")
        text.extend(['', 'The API and CLI privacy comparisons are separate checks for the same finding. '
                     'Matching outcomes are necessary. Independent review must also verify that the implementation '
                     'prevents the foreign SELECT and preserves valid tenant-local guards.'])
    review2_guard_protocol = 'review2-guard-discovery.json'
    if (root / review2_guard_protocol).is_file():
        discovery = read(root / review2_guard_protocol)
        text.extend([
            '',
            '### Second Critical review follow-up',
            '',
            'Matched replays found foreign-account dependence in a DML predicate in both the archived baseline '
            'and the candidate before repair. The rowid source-shape and table-default REPLACE cases began failing '
            'after the first repair.',
            '',
            'These replays were added after launch and are separate from the original frozen grades. '
            'Case groups can overlap the independent findings. Each linked report includes hashes for the application files. '
            f"[Discovery protocol]({review2_guard_protocol}), [probe]({discovery['probe']}).",
            '',
            '| Workspace | Failed case groups | vault.py SHA-256 prefix |',
            '| --- | ---: | --- |',
        ])
        reports = [('Archived Critical baseline', discovery['baseline']),
                   ('Critical candidate before repair', discovery['pre_repair']),
                   ('Critical candidate after first repair', discovery['after_first_repair'])]
        for trial in (t for t in trials if t['level'] == 'critical'):
            path = f"round-{trial['round']}/critical/final-review2_guard_probe.json"
            if (root / path).is_file():
                reports.append((f"Final Critical candidate, round {trial['round']}", path))
        for label, path in reports:
            report = read(root / path)
            text.append(f"| [{label}]({path}) | {report['failed_cases']} | `{report['source_sha256'][:12]}` |")
    final_guard_protocol = 'final-guard-discovery.json'
    if (root / final_guard_protocol).is_file():
        discovery = read(root / final_guard_protocol)
        text.extend([
            '',
            '### Final Critical guard replay',
            '',
            'This post-launch replay reports fixture outcomes and paired privacy checks for two independent findings. '
            'The table gives the total failure count and highlights four outcomes. The replay is separate from the frozen grades. '
            'Each linked report records the application hashes. '
            f"[Discovery protocol]({final_guard_protocol}), [probe]({discovery['probe']}).",
            '',
            '| Workspace | Failed groups / executed | Unqualified foreign predicate | Qualified foreign predicate | NATURAL JOIN harmless guard | NATURAL JOIN aborting guard | vault.py SHA-256 prefix |',
            '| --- | ---: | --- | --- | --- | --- | --- |',
        ])
        groups = ('accounts_privacy_pair', 'main.accounts_privacy_pair',
                  'natural_join_harmless', 'natural_join_abort')
        reports = [('Archived Critical baseline', discovery['baseline_report']),
                   ('Final Critical candidate', discovery['final_report'])]
        for label, path in reports:
            report = read(root / path)
            failed = set(report['failed_case_names'])
            outcomes = ' | '.join('FAIL' if name in failed else 'PASS' for name in groups)
            text.append(f"| [{label}]({path}) | {report['failed_cases']}/{len(report['cases'])} | "
                        f"{outcomes} | `{report['source_sha256'][:12]}` |")
    actual = summary['totals']['actual_trial_consumption']
    known = summary['totals']['known_consumption_lower_bound']
    phases = summary['telemetry']
    text.extend([
        '',
        '## Recorded consumption',
        '',
        f"The {len(trials)} pilot trials launched {phases['phase_count']} measured phases. They used "
        f"**{clock(actual['measured_seconds'])} agent time**, **{number(actual['total_tokens'])} total tokens**, "
        f"**{number(actual['uncached_input_tokens'])} uncached input** and "
        f"**{number(actual['uncached_input_plus_output'])} uncached input + output**. "
        'All launched implementation, review and repair phases count, including failed or timed-out work.',
    ])
    if phases['unknown_usage_phases']:
        text.extend([
            '',
            'Unknown usage phases are ' + ', '.join(
                f"round-{p['round']}/{p['level']}/{p['phase']} ({clock(p['measured_seconds'])})"
                for p in phases['unknown_usage_phases']) + '. '
            f"Reported usage gives a lower bound of {number(known['total_tokens'])} total tokens, "
            f"{number(known['uncached_input_tokens'])} uncached input and "
            f"{number(known['uncached_input_plus_output'])} uncached input + output.",
        ])
    if single_pair:
        text.extend(['', '| Trial | Baseline timeouts | Pilot timeouts |',
                     '| --- | --- | --- |'])
        for trial in trials:
            location = f"round-{trial['round']}/{trial['level']}"
            timed_out = []
            for directory in (baseline, root):
                phases_by_name = [read(path) for path in sorted((directory / location).glob('*/metrics.json'))]
                phase_names = [p['phase'] for p in phases_by_name if p['timed_out']]
                timed_out.append(', '.join(phase_names) or 'None')
            text.append(f"| {trial['level'].title()} | {' | '.join(timed_out)} |")
    launches = [read(path) for path in root.glob('round-*/*/*/running.json')]
    if launches and all('budget_environment' in phase for phase in launches):
        text.extend(['', 'The candidate harness exposed each phase’s existing deadline to the agent. '
                     'The frozen skill’s budget helper can report the remaining time and advise when to narrow work or finish. '
                     'The helper is cooperative. The harness still enforces the same process timeout.'])
        if (root / 'budget-observations.json').is_file():
            text.extend(['', 'Recorded helper calls and remaining-time observations are available in the '
                         '[phase budget evidence](budget-observations.json).'])
    if (root / 'timeout-retention.json').is_file():
        text.extend(['', 'The timed-out repair was retained and independently assessed without relaunching it. '
                     'Its elapsed cost remains included and its unreported usage remains unknown. The final repair brief '
                     'explicitly restated the existing 900-second cap after that timeout. '
                     '[Timeout continuation](timeout-retention.json)'])
    text.extend([
        '',
        f"Both cohorts requested **{manifest['requested_model']} / {manifest['requested_effort']}** "
        f"with a **{manifest['timeout_seconds']}-second per-phase cap**. "
        'Phases ran serially with fresh implementation and independent review contexts. Cache state and remote load were uncontrolled. '
        'Coordinator time, preparation, evaluation probes and reporting sit outside the CLI phase totals.',
        '',
        '[Summary](summary.json), [comparison CSV](comparison.csv), [trials](trials.csv), [phases](phases.csv), '
        '[usage integrity](metric-integrity.json), [control audit](control-audit.json), [controls](controls.json), '
        f"[previous report]({os.path.relpath(baseline / 'README.md', root)}).",
    ])
    if (root / 'experiment-notes.json').is_file():
        text.extend(['', 'The candidate adds SQL source-resolution guidance, avoids duplicate source/diff and fixture reads, '
                     'and exposes the unchanged phase deadline through a cooperative helper. '
                     '[Experiment changes and limits](experiment-notes.json), [instruction diff](skill-change.diff), '
                     '[preparation validation](validation.json). Preparation validation is separate from measured task quality.'])
    if (root / 'assessment-reporting-amendment.json').is_file():
        text.extend(['', 'Independent finding histories are derived from the untouched raw review outputs. '
                     'A derived-assessment bookkeeping correction separates coordinator findings from independent findings; '
                     'measured prompts, outputs and metrics are unchanged. '
                     '[Reporting correction](assessment-reporting-amendment.json).'])
    (root / 'README.md').write_text('\n'.join(text) + '\n')


def render(root):
    root=root.resolve();summary=read(root/'summary.json');manifest=read(root/'manifest.json')
    quality=summary['quality'];target=summary['optimization_target'];baseline=archive_path(manifest['baseline_archive'])
    prior=read(baseline/'summary.json');old={row['level']:row for row in prior['levels']}
    if {row['level']: row['candidate_n'] for row in summary['levels']} != dict.fromkeys(
            ('medium', 'high', 'critical'), 3):
        render_pilot(root, summary, manifest, prior, baseline)
        print('Rendered pilot comparison with terminal outcomes and actual consumption.')
        return
    critical_target=target['level']=='critical'
    separator_gate='trigger_separator_probe.py' in manifest.get('known_quality_probes',[])
    if separator_gate:
        title='Critical completion and High workflow time'
    else:
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
    category_checks = sum(trial['final_contract_categories'] for trial in summary['trials'])
    text+=f'''
Final original-grader failures: **{quality['final_contract_issues']}**; remaining independent findings: **{quality['final_independent_findings']}**; remaining explicit coordinator findings: **{quality['final_coordinator_findings']}**; failed predeclared additional-probe cases: **{quality['final_added_probe_failed_cases']}**; failed posthoc follow-up cases: **{quality['final_posthoc_probe_failed_cases']}**. These signals overlap and must not be added into a globally unique bug count. The final original graders ran {category_checks} category checks across these trials. Protected files and review-workspace integrity remain mandatory.

All previously discovered Critical probes were frozen before the first model phase: four original silent-write checks and twelve additional cases covering required effects, audit-history preservation, historical receipts/unrelated accounts, valid rowid movement, ignored inserts/updates and foreign malformed-text isolation. They run after every Critical independent review, starting with the first assessment. Passing the original grader cannot waive their failure. [Manifest](manifest.json) lists the exact copied scripts; each assessment retains the full reports and source hashes. Historical regression suites from all three previous final workspaces also run against every candidate; reverse cross-regressions remain visible. Contract-external assertions require a retained evidence-backed adjudication and cannot waive a real finding.

The previous cohort ended with {prior['quality']['passed_trials']}/9 passing trials and {prior['quality']['final_independent_findings']} remaining independent findings. Its probes were discovered during follow-up; they are available from the start in this new experiment. Critical cost comparisons therefore describe recorded work, including different repair paths and unsuccessful attempts, **not equal-quality time to successful completion**.
'''
    if critical_target:
        if separator_gate:
            text+='\nThe frame and trigger compatibility probes remain mandatory. The comparison uses the final assessments of the latest cohort.\n'
        else:
            text+='\nThe preceding cohort’s frame and trigger compatibility probes are now mandatory from the first assessment.\n'
        text+='''
These probes cover extra UNIQUE account, receipt and audit victims, ignored conflicts, valid replacements, unquoted keyword and Unicode names, and conditional VALUES or WITH bodies. The same scripts ran on all three previous final workspaces. Case failures may overlap independent findings.

| Targeted probe | Executions per workspace | Previous failed cases (rounds 1/2/3) | New failed cases (rounds 1/2/3) |
| --- | ---: | --- | --- |
'''
        for name in ('frame_followup_probe','trigger_compatibility_probe'):
            before=[];after=[]
            for n in (1,2,3):
                if separator_gate:
                    old_trial=baseline/f'round-{n}/critical'
                    old_result=read(old_trial/'result.json')
                    old_assessment=read(old_trial/f"assessment-{old_result['final_assessment']}.json")
                    before.append(old_assessment['critical_probes'][name+'.py']['report'])
                else:
                    before.append(read(root/f'baseline-{n}-{name}.json'))
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
        if separator_gate:
            text+='''
The previous cohort's five effect and trigger diagnostics now run as mandatory checks at every Critical assessment. The separator check covers vertical tab, token-boundary U+FEFF and an ASCII control via API and CLI in DELETE and WAL modes. All three historical final workspaces were checked with the same probe.

| Promoted probe | Previous failures (rounds 1/2/3) | New failures (rounds 1/2/3) |
| --- | --- | --- |
'''
        else:
            text+='''
Findings during the run added posthoc probes. Each probe exercised API and CLI calls in DELETE and WAL modes against all three previous and new final workspaces. Round 1 reopened for the remaining bounded repair after the trigger-counter and NBSP findings. Its original closure, subsequent repair and renewed review are retained, with every phase counted in the elapsed cost.

| Posthoc probe | Previous failures (rounds 1/2/3) | New failures (rounds 1/2/3) |
| --- | --- | --- |
'''
        for label,protocol,baseline_suffix,candidate_prefix in diagnostics:
            previous=[];candidate=[]
            for n in (1,2,3):
                trial=root/f'round-{n}/critical';result=read(trial/'result.json')
                if separator_gate:
                    old_trial=baseline/f'round-{n}/critical'
                    old_index=read(old_trial/'result.json')['final_assessment']
                    previous.append(read(old_trial/f'assessment-{old_index}-{candidate_prefix}_probe.json')['failed_cases'])
                    assessment=read(trial/f"assessment-{result['final_assessment']}.json")
                    report=assessment['critical_probes'][candidate_prefix+'_probe.py']['report']
                else:
                    previous.append(read(root/f'baseline-{n}-{baseline_suffix}.json')['failed_cases'])
                    report=read(trial/f"assessment-{result['final_assessment']}-{candidate_prefix}_probe.json")
                candidate.append(report['failed_cases'] if report else 'UNKNOWN')
                if result['status']=='DONE' or result.get('quality_status')=='PASS':
                    assert report and report['failed_cases']==0, trial
            source=f'{candidate_prefix}_probe.py' if separator_gate else f'{protocol}-protocol.json'
            text+=f"| [{label}]({source}) | {' / '.join(map(str,previous))} | {' / '.join(map(str,candidate))} |\n"
        if (root/'measurement-amendment.json').exists():
            text+='\nCopied probes initially could not import a local helper module in round 1. The coordinator supplied the workspace import path and reran those probes. The archive includes the raw import failures and the evaluator amendment. [Evaluator amendment](measurement-amendment.json)\n'
        if separator_gate:
            text+='\nThe skill now asks implementers to establish the hardest write effect early, check SQL token boundaries against the installed engine, and map public signatures to validation cases before editing. Phase caps and mandatory review requirements are unchanged.\n'
        for probe,reason in (('storage-encoding','a valid UTF-16 transfer was rejected'),
                             ('ignore-scope','an ignored row suppressed a later trigger abort'),
                             ('recursive-setting','instrumentation changed the setting read by an audit guard')):
            if (root/f'{probe}-protocol.json').exists():
                previous=[read(root/f'baseline-{n}-{probe}.json')['failed_cases'] for n in (1,2,3)]
                candidate=[trial['posthoc_probes'][probe]['failed_cases']
                           for trial in summary['trials'] if trial['level']=='critical']
                text+=f"\nThe {probe} probe was added after {reason}. Failures were {' / '.join(map(str,previous))} before and {' / '.join(map(str,candidate))} after, in round order. [Probe protocol]({probe}-protocol.json)\n"
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
                if trial['final_coordinator_findings']:
                    result=read(root/location/'result.json')
                    text+=f"\nRemaining findings: [{location}]({location}/assessment-{result['final_assessment']}.json).\n"
                else:
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
    if (root/'cyber-notice-observation.json').exists():
        text+='''
The user reported a Codex chat notice that hid content while Critical round 3 was running. The screenshot identified the type of safeguard. The available records did not identify the message, case, or command that triggered it. The CLI continued, finished its implementation phase, and recorded usage. The reported timeouts are documented separately as 900-second phase deadlines. [Notice observation](cyber-notice-observation.json)
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
