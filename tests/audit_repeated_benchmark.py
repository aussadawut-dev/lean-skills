"""Verify repeated benchmark controls and aggregates from retained files offline."""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import statistics

from repeated_benchmark import archive_path


METRICS = ('measured_seconds', 'total_tokens', 'input_tokens', 'cached_input_tokens',
           'uncached_input_tokens', 'output_tokens', 'uncached_input_plus_output')
PHASE_GROUPS = {
    'implementation': ('implementation',),
    'repair-1': ('repair-1',),
    'repair-2': ('repair-2',),
    'reviews': ('review', 'review-2', 'review-3'),
}


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def digest(root):
    return {str(p.relative_to(root)): sha(p) for p in sorted(root.rglob('*'))
            if p.is_file() and '__pycache__' not in p.parts}


def verify_archive(root):
    expected = read(root / 'archive-sha256.json')
    actual = digest(root)
    actual.pop('archive-sha256.json')
    assert actual == expected, root
    return expected


def same(actual, expected):
    if actual is None or expected is None:
        assert actual == expected, (actual, expected)
    else:
        assert math.isclose(actual, expected, rel_tol=0, abs_tol=1e-6), (actual, expected)


def complete_sum(values):
    return None if None in values else sum(values)


def verify_phase(path, manifest):
    metrics = read(path)
    launch = read(path.with_name('running.json'))
    assert metrics['phase'] == path.parent.name, path
    assert (metrics['started_unix'], metrics['command']) == (launch['started_unix'], launch['command']), path
    controls = manifest['requested_model'], manifest['requested_effort']
    assert ('budget_environment' in launch) == ('budget_environment' in metrics), path
    if 'budget_environment' in launch:
        budget = launch['budget_environment']
        assert budget == metrics['budget_environment'], path
        same(float(budget['LEAN_RUN_DEADLINE_UNIX']) - launch['started_unix'], manifest['timeout_seconds'])
        same(float(budget['LEAN_RUN_PHASE_SECONDS']), manifest['timeout_seconds'])
    assert (metrics['requested_model'], metrics['requested_effort']) == controls, path
    command = launch['command']
    assert command[command.index('--model') + 1] == controls[0], path
    assert f'model_reasoning_effort="{controls[1]}"' in command, path
    elapsed = metrics['elapsed_seconds']
    cap = manifest['timeout_seconds']
    # A timed-out process can take up to ten seconds to exit after SIGTERM.
    assert (cap <= elapsed <= cap + 11) if metrics['timed_out'] else (0 < elapsed <= cap + 1), path
    raw = path.with_name('events.jsonl').read_bytes()
    events = [json.loads(line) for line in raw.splitlines()]
    usage = [event['usage'] for event in events if event.get('type') == 'turn.completed' and 'usage' in event]
    sums = {k: sum(item.get(k, 0) for item in usage) for k in set().union(*usage)} if usage else None
    assert sums == metrics['usage'] and len(usage) == metrics['completed_turns'], path
    row = {key: None for key in METRICS}
    row.update(measured_seconds=elapsed, started_unix=launch['started_unix'], phase=metrics['phase'],
               raw_events_sha256=hashlib.sha256(raw).hexdigest(), timed_out=metrics['timed_out'],
               exit_code=metrics['exit_code'])
    if sums is None:
        assert metrics['timed_out'] and metrics['exit_code'] != 0 and metrics.get('total_tokens') is None, path
    else:
        assert not metrics['timed_out'] and metrics['exit_code'] == 0, path
        input_tokens = sums['input_tokens']
        cached = sums['cached_input_tokens']
        output = sums['output_tokens']
        assert 0 <= cached <= input_tokens and output >= 0, path
        row.update(input_tokens=input_tokens, cached_input_tokens=cached, output_tokens=output,
                   total_tokens=input_tokens + output, uncached_input_tokens=input_tokens - cached,
                   uncached_input_plus_output=input_tokens - cached + output)
        assert row['total_tokens'] == metrics['total_tokens'], path
        assert row['uncached_input_tokens'] == metrics['uncached_input_tokens'], path
    return row


def verify_cross_regressions(trial, assessment, sources):
    directions = ('historical_tests_on_candidate', 'candidate_tests_on_historical')
    expected = {(archive, n, direction) for archive, orders in sources.items()
                for n, order in enumerate(orders, 1) if trial.name in order for direction in directions}
    cross = assessment['cross']
    recorded = {(row['baseline_archive'], row['baseline_round'], row['direction']) for row in cross}
    assert recorded == expected and len(cross) == len(expected), trial
    assert cross == read(trial / f"{assessment['phase']}-cross.json"), trial
    assert len({row['log'] for row in cross}) == len(cross), trial
    assert all((trial / row['log']).is_file() for row in cross), trial


def verify_trial(trial, old, manifest, regression_sources):
    initial = digest(trial / 'initial')
    previous = digest(old / 'initial')
    assert initial == read(trial / 'initial-hashes.json'), trial
    skill_prefix = '.agents/skills/lean-run/'
    # A declared new-baseline contract change may alter CONTRACT.md only.
    allowed = {'CONTRACT.md'} if trial.name in manifest.get('contract_changed_levels', []) else set()
    current = {k: v for k, v in initial.items() if not k.startswith(skill_prefix)}
    prior = {k: v for k, v in previous.items() if not k.startswith(skill_prefix)}
    differing = {k for k in current.keys() | prior.keys() if current.get(k) != prior.get(k)}
    assert differing <= allowed, (trial, sorted(differing))
    if 'CONTRACT.md' in differing:
        control = read(trial.parent.parent / 'controls.json')[f'{trial.parent.name}/{trial.name}']
        assert control['candidate_contract_sha256'] == current['CONTRACT.md'], trial
        assert control['baseline_contract_sha256'] == prior['CONTRACT.md'], trial
    for phase in ('implementation', 'review'):
        assert (trial / phase / 'prompt.txt').read_bytes() == (old / phase / 'prompt.txt').read_bytes(), trial
    assert sha(trial.parent / 'grader.py') == sha(old.parent / 'grader.py'), trial
    for folder in ('initial', 'workspace', 'reviewspace'):
        assert digest(trial / folder / skill_prefix) == manifest['skill_sha256'], (trial, folder)

    result = read(trial / 'result.json')
    assert result['status'] in ('DONE', 'FAILED', 'TIMEOUT'), trial
    assessment = read(trial / f"assessment-{result['final_assessment']}.json")
    workspace = digest(trial / 'workspace')
    grade = read(trial / result['final_grade'])
    assert workspace == assessment['candidate_sha256'] == grade['workspace_sha256'], trial
    protected = {name for name in initial if name in ('CONTRACT.md', 'AGENTS.md', 'test_public.py')
                 or name.startswith('.agents/')}
    assert all(workspace.get(name) == initial[name] for name in protected), trial
    assert not grade['protected_files_changed'], trial
    before = read(trial / f"{result['final_review']}-hashes.json")
    after = digest(trial / 'reviewspace')
    added = sorted(after.keys() - before.keys())
    assert all(after.get(name) == value for name, value in before.items()), trial
    assert all(name.endswith('.log') for name in added), trial
    assert assessment['review_integrity'] == {
        'changed_or_removed': [], 'unexpected_additions': [], 'added_logs': added}, trial
    if trial.name == 'critical':
        assert set(assessment['critical_probes']) == set(manifest['known_quality_probes']), trial
        for probe in assessment['critical_probes'].values():
            report = probe['report']
            if report and 'source_sha256' in report:
                assert report['source_sha256'] == workspace['vault.py'], trial
        for probe in assessment.get('coordinator_probes', {}).values():
            assert probe['report']['source_sha256'] == workspace['vault.py'], trial
            assert all(workspace.get(name) == value for name, value in probe.get('application_sha256', {}).items()), trial
    phases = sorted((verify_phase(path, manifest) for path in trial.glob('*/metrics.json')),
                    key=lambda row: row['started_unix'])
    expected_phases = ['implementation', 'review']
    for n in range(1, result['repair_rounds'] + 1):
        expected_phases.extend([f'repair-{n}', f'review-{n + 1}'])
    assert [row['phase'] for row in phases] == expected_phases, trial
    if regression_sources:
        for index in range(1, result['final_assessment'] + 1):
            verify_cross_regressions(trial, read(trial / f'assessment-{index}.json'), regression_sources)
    return phases


def totals(phases):
    return {key: complete_sum([row[key] for row in phases]) for key in METRICS}


def csv_rows(path, keys):
    with path.open(newline='') as stream:
        rows = list(csv.DictReader(stream))
    indexed = {tuple(row[key] for key in keys): row for row in rows}
    assert len(indexed) == len(rows), path
    return indexed


def verify_csv_number(value, expected):
    same(float(value) if value else None, expected)


def audit(root):
    root = root.resolve()
    manifest = read(root / 'manifest.json')
    baseline = archive_path(manifest['baseline_archive'])
    prior = read(baseline / 'manifest.json')
    summary = read(root / 'summary.json')
    controls = ('requested_model', 'requested_effort', 'timeout_seconds', 'procedure_depth')
    assert tuple(manifest[key] for key in controls) == ('gpt-6-astra', 'max', 900, 'standard')
    assert all(manifest[key] == prior[key] for key in controls)
    prior_hashes = verify_archive(baseline)
    regression_sources = {}
    regression_counts = {}
    archive_references = manifest.get('regression_archives', [])
    archive_hashes = manifest.get('regression_archive_sha256', {})
    if archive_hashes:
        assert set(archive_hashes) == set(archive_references)
    for reference in archive_references:
        archive = archive_path(reference)
        if archive_hashes:
            assert sha(archive / 'archive-sha256.json') == archive_hashes[reference], archive
        hashes = prior_hashes if archive == baseline else verify_archive(archive)
        regression_counts[reference] = len(hashes)
        regression_sources[reference] = read(archive / 'manifest.json')['orders']
    assert sha(root / 'harness-frozen.py') == manifest['harness_sha256']
    probes = set(manifest['known_quality_probes'])
    assert set(prior['known_quality_probes']) <= probes
    probe_hashes = manifest.get('probe_sha256', {})
    assert not probe_hashes or set(probe_hashes) == probes
    for name in probes:
        actual = sha(root / name)
        if name in probe_hashes:
            assert actual == probe_hashes[name], name
        if name in prior['known_quality_probes']:
            assert actual == prior_hashes[name], name
        else:
            assert name in probe_hashes, name
            if name in prior_hashes:
                assert actual == prior_hashes[name], name
    targeted_probes = {name: Path(name).stem for name in manifest.get('targeted_probes', [])}
    assert set(targeted_probes) <= probes
    earlier_probe = 'critical_final_findings_probe.py'
    if earlier_probe in probes and earlier_probe not in prior['known_quality_probes']:
        targeted_probes[earlier_probe] = 'critical-final-findings'
    for filename in targeted_probes.values():
        for number, order in enumerate(prior['orders'], 1):
            if 'critical' in order:
                report = read(root / f'baseline-{number}-{filename}.json')
                source = f'round-{number}/critical/workspace/vault.py'
                assert report['source_sha256'] == prior_hashes[source], source

    summary_trials = {(t['round'], t['level']): t for t in summary['trials']}
    trial_csv = csv_rows(root / 'trials.csv', ('round', 'level'))
    phase_csv = csv_rows(root / 'phases.csv', ('round', 'level', 'phase'))
    comparison = csv_rows(root / 'comparison.csv', ('level', 'metric'))
    recorded_hashes = {(p['round'], p['level'], p['phase']): p for p in read(root / 'metric-integrity.json')}
    trial_phases = {}
    intervals = []
    unknown = []
    for number, order in enumerate(manifest['orders'], 1):
        for level in order:
            relative = Path(f'round-{number}') / level
            rows = verify_trial(root / relative, baseline / relative, manifest, regression_sources)
            trial_phases[number, level] = rows
            reported = summary_trials.pop((number, level))
            csv_trial = trial_csv.pop((str(number), level))
            for key, expected in totals(rows).items():
                same(reported[key], expected)
                verify_csv_number(csv_trial[key], expected)
            for row in rows:
                phase = row['phase']
                csv_phase = phase_csv.pop((str(number), level, phase))
                integrity = recorded_hashes.pop((number, level, phase))
                assert row['raw_events_sha256'] == integrity['raw_events_sha256'] == csv_phase['raw_events_sha256']
                assert integrity['raw_usage_verified'] == (row['total_tokens'] is not None)
                assert csv_phase['timed_out'] == str(row['timed_out'])
                for key in (*METRICS, 'started_unix', 'exit_code'):
                    verify_csv_number(csv_phase[key], row[key])
                start = row['started_unix']
                intervals.append((start, start + row['measured_seconds']))
                if row['total_tokens'] is None:
                    unknown.append(dict(round=number, level=level, phase=phase,
                                        measured_seconds=row['measured_seconds']))
    assert not (summary_trials or trial_csv or phase_csv or recorded_hashes)
    for (_, end), (next_start, _) in zip(intervals, intervals[1:]):
        assert end <= next_start + 0.05, (end, next_start)

    prior_orders = prior['orders']
    level_rows = {row['level']: row for row in summary['levels']}
    assert set(level_rows) == {level for _, level in trial_phases}
    for level, row in level_rows.items():
        new = [phases for (_, key), phases in trial_phases.items() if level == key]
        old = [list(verify_phase(path, prior) for path in (baseline / f'round-{n}' / level).glob('*/metrics.json'))
               for n, order in enumerate(prior_orders, 1) if level in order]
        assert all(old)
        assert len(new) == row['candidate_n'] == manifest['repetitions_per_level']
        assert len(old) == row['baseline_n'] == manifest['baseline_repetitions_per_level']
        for cohort, field in ((old, 'baseline_phase_means'), (new, 'candidate_phase_means')):
            for group, phases in PHASE_GROUPS.items():
                same(row[field][group], statistics.mean(
                    sum(p['measured_seconds'] for p in trial if p['phase'] in phases) for trial in cohort))
        for key in METRICS:
            entry = comparison.pop((level, key))
            assert int(entry['baseline_n']) == len(old) and int(entry['requested_n']) == len(new)
            before = [totals(phases)[key] for phases in old]
            after = [totals(phases)[key] for phases in new]
            old_mean = statistics.mean(before) if None not in before else None
            known = [value for value in after if value is not None]
            complete = len(known) == len(new)
            stats = {
                'n': len(known), 'requested_n': len(new), 'unknown_count': len(new) - len(known),
                'known_sum': sum(known), 'mean': statistics.mean(known) if complete else None,
                'median': statistics.median(known) if complete else None,
                'min': min(known) if complete else None, 'max': max(known) if complete else None,
                'sample_sd': statistics.stdev(known) if complete and len(known) > 1 else None,
            }
            mean = stats['mean']
            change = (mean / old_mean - 1) * 100 if mean is not None and old_mean not in (None, 0) else None
            same(row['baseline'][key], old_mean)
            same(row['mean_change_percent'][key], change)
            verify_csv_number(entry['baseline'], old_mean)
            verify_csv_number(entry['mean_change_percent'], change)
            for field, value in stats.items():
                same(row['statistics'][key][field], value)
                verify_csv_number(entry[field], value)
    assert not comparison

    all_phases = [phase for phases in trial_phases.values() for phase in phases]
    reported_totals = summary['totals']
    actual = reported_totals.get('actual_trial_consumption', reported_totals.get('actual_nine_trial_consumption'))
    for key, value in totals(all_phases).items():
        same(actual[key], value)
        same(reported_totals['known_consumption_lower_bound'][key],
             sum(phase[key] for phase in all_phases if phase[key] is not None))
    telemetry = summary['telemetry']
    assert telemetry['phase_count'] == len(all_phases)
    assert telemetry['known_usage_phases'] == len(all_phases) - len(unknown)
    assert telemetry['unknown_usage_phases'] == unknown
    assert telemetry['status'] == ('INCOMPLETE' if unknown else 'COMPLETE')
    record = {
        'status': 'PASS', 'baseline_files_verified': len(prior_hashes), 'trials_verified': len(trial_phases),
        'phase_count': len(all_phases), 'sequential_phases_verified': True,
        'raw_usage_unknown_phases': unknown,
        'controls': 'Frozen tasks, prompts, graders, skill, probes, protected files and final source/review integrity. '
                    'Raw events and launch records checked against elapsed and usage metrics, means and CSVs.',
        'limit': 'A control audit PASS does not imply benchmark quality PASS or complete telemetry.',
    }
    if regression_counts:
        record['regression_archive_files_verified'] = regression_counts
    (root / 'control-audit.json').write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(record, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    audit(parser.parse_args().directory)
