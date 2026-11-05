"""Verify repeated benchmark controls and aggregates from retained files offline."""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import statistics


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


def verify_trial(trial, old, manifest):
    initial = digest(trial / 'initial')
    previous = digest(old / 'initial')
    assert initial == read(trial / 'initial-hashes.json'), trial
    skill_prefix = '.agents/skills/lean-run/'
    assert {k: v for k, v in initial.items() if not k.startswith(skill_prefix)} == {
        k: v for k, v in previous.items() if not k.startswith(skill_prefix)}, trial
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
    baseline = Path(manifest['baseline_archive'])
    prior = read(baseline / 'manifest.json')
    summary = read(root / 'summary.json')
    controls = ('requested_model', 'requested_effort', 'timeout_seconds', 'procedure_depth')
    assert tuple(manifest[key] for key in controls) == ('gpt-6-astra', 'max', 900, 'standard')
    assert all(manifest[key] == prior[key] for key in controls)
    prior_hashes = read(baseline / 'archive-sha256.json')
    actual_hashes = digest(baseline)
    actual_hashes.pop('archive-sha256.json')
    assert actual_hashes == prior_hashes, baseline
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
    if 'critical_final_findings_probe.py' in probes:
        for number, order in enumerate(prior['orders'], 1):
            if 'critical' in order:
                report = read(root / f'baseline-{number}-critical-final-findings.json')
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
            rows = verify_trial(root / relative, baseline / relative, manifest)
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
    (root / 'control-audit.json').write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(record, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    audit(parser.parse_args().directory)
