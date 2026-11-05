"""Small synthetic benchmark archives for the unit tests; no model calls.

The measured cohorts under tests/results/ keep only their reports and hash
manifests in the repository (tests/results/README.md says where the raw files
live). The tests build a look-alike lineage here, in a temporary directory,
from the frozen harness fixtures, the reference solution and a few
deliberately defective variants of a small candidate (tests/benchmark/fixtures).

Every control that the runner, summarizer, auditor and renderer check is
produced the way a real cohort produces it: initial fixtures, prompts, graders
and review workspaces come from level_benchmark, summaries from
summarize_repeated_benchmark. Measured phases, reviews and probe reports are
synthesized. A trial's outcome follows from the recorded probe OUTCOMES of its
candidate, so no archived report contradicts the code it describes; the test
suite verifies those outcomes against the real probes.
"""
import atexit
import contextlib
import hashlib
import io
import json
from pathlib import Path
import shutil
import tempfile

import level_benchmark as harness
import repeated_benchmark as cohort
import summarize_repeated_benchmark as reporter

ROOT = cohort.ROOT
FIXTURES = ROOT / 'tests/benchmark/fixtures'
REFERENCE = ROOT / 'tests/benchmark/reference/critical'
PROBES = ROOT / 'tests/probes'
POLICY = FIXTURES / 'rls-policy'
CONTRACTS = {'2026-11-03': FIXTURES / 'critical/CONTRACT-2026-11-03.md',
             '2026-11-05': FIXTURES / 'critical/CONTRACT-2026-11-05.md'}
FOREIGN_SUITE = 'test_foreign_counter.py'
FOREIGN_HEADER = ('test_counter_sees_all_tenants '
                  '(test_foreign_counter.ForeignCounterTests.test_counter_sees_all_tenants)')
GUARD_PROBES = ('foreign_guard_probe.py', 'review2_guard_probe.py', 'final_guard_probe.py')
RLS_CANDIDATES = {'reference'}
TIMEOUT = 900
START_UNIX = 1_800_000_000.0

# Each Critical variant is the base candidate with one deliberate defect.
HOOK = '''def _check_schema(con):
    """Hook for the defective fixture variants; the base candidate accepts any schema."""
    return None
'''
SCREENS = {
    'pragma-screen': '''def _check_schema(con):
    # Deliberate fixture defect: a lexical screen refuses any trigger or view
    # that mentions a pragma table instead of letting SQLite resolve it.
    for (sql,) in con.execute("SELECT sql FROM sqlite_schema WHERE type IN ('trigger','view') AND sql IS NOT NULL"):
        if 'pragma_' in sql.lower():
            raise sqlite3.IntegrityError('unsupported schema object')
''',
    'ignore-screen': '''def _check_schema(con):
    # Deliberate fixture defect: a lexical screen refuses conflict clauses in
    # triggers, so a harmless ignored write invalidates a valid transfer.
    for (sql,) in con.execute("SELECT sql FROM sqlite_schema WHERE type='trigger' AND sql IS NOT NULL"):
        if 'or ignore' in sql.lower():
            raise sqlite3.IntegrityError('unsupported conflict clause')
''',
    'separator-screen': '''def _check_schema(con):
    # Deliberate fixture defect: trigger headers are checked with a regular
    # expression whose whitespace class does not know every SQLite separator.
    header = re.compile(r'^\\s*CREATE\\s+(?:TEMP\\w*\\s+)?TRIGGER\\s+(?:IF\\s+NOT\\s+EXISTS\\s+)?'
                        r'(?:"(?:[^"]|"")*"|`[^`]*`|\\[[^\\]]*\\]|\\S+)\\s+'
                        r'(?:BEFORE|AFTER|INSTEAD\\s+OF|DELETE|INSERT|UPDATE)\\b', re.I | re.S)
    for (sql,) in con.execute("SELECT sql FROM sqlite_schema WHERE type='trigger' AND sql IS NOT NULL"):
        if not header.match(sql):
            raise sqlite3.IntegrityError('unsupported trigger')
''',
}

# Probe outcomes of each Critical candidate, measured with the real probes
# (tests/probes) and verified by test_synthetic_candidates_have_recorded_probe_outcomes.
# A list names the failed cases, an integer counts unnamed failed cases, and
# True records a failure whose count is not pinned. Absent probes pass.
_EFFECTS = {
    'critical_contract_probe.py': True,
    'rls_policy_probe.py': True,
    'final_guard_probe.py': ['accounts_privacy_pair', 'main.accounts_privacy_pair'],
    'foreign_guard_probe.py': 2,
    'review2_guard_probe.py': ['dml_scope_pair'],
}
_JOURNALS = [f'journal={journal}/interface={interface}' for journal in ('DELETE', 'WAL') for interface in ('API', 'CLI')]
OUTCOMES = {
    # The reference solution hides other tenants' rows; it fails exactly the
    # expectations the policy record supersedes.
    'reference': cohort.read(POLICY / 'superseded-expectations.json')['probe_cases'],
    # The base candidate verifies final effects but shows other tenants' rows.
    'effects': dict(_EFFECTS),
    'no-effects': {
        **_EFFECTS,
        'supplemental_probe.py': True,
        'after_trigger_probe.py': ['case=audit_duplicated', 'case=audit_removed', 'case=credit_undone', 'case=receipt_removed'],
        'audit_followup_probe.py': ['case=history_deleted_duplicate_added', 'case=history_rewritten'],
        'preservation_probe.py': ['case=old_receipt_deleted', 'case=unrelated_balance_changed'],
        'frame_followup_probe.py': ['case=unique_account_victim', 'case=unique_receipt_victim'],
        'trigger_compatibility_probe.py': [f'case=unique_audit_replace/{suffix}' for suffix in _JOURNALS],
        'critical_final_findings_probe.py': ['f1_foreign_corruption'],
    },
    'pragma-screen': {
        **_EFFECTS,
        'critical_final_findings_probe.py': ['f2_single_quoted_view', 'f2_unquoted_view_control'],
        'in_source_probe.py': ['in_main_abort', 'in_main_harmless', 'in_plain_abort', 'in_plain_harmless',
                               'not_indexed_abort', 'not_indexed_harmless'],
        'name_resolution_probe.py': ['cte-valid', 'qualified-valid'],
        'recursive_setting_probe.py': ['interface=API/should_fail=False', 'interface=API/should_fail=True',
                                       'interface=CLI/should_fail=False'],
    },
    'ignore-screen': {
        **_EFFECTS,
        'ignored_update_probe.py': 1,
        'noop_probe.py': 1,
        'trigger_compatibility_probe.py': [f'case=unique_audit_ignore/{suffix}' for suffix in _JOURNALS],
    },
    'separator-screen': {
        **_EFFECTS,
        'trigger_separator_probe.py': [f'case=bom_separator/{suffix}' for suffix in _JOURNALS],
        'unicode_space_probe.py': [f'case=benign_unicode_space_trigger/{suffix}' for suffix in _JOURNALS],
    },
}

ALL_PROBES = (*cohort.PROBE_NAMES, *cohort.FOLLOWUP_PROBE_NAMES, *cohort.EFFECT_PROBE_NAMES,
              *cohort.SETTING_PROBE_NAMES)
PILOT_PROBES = (*ALL_PROBES, 'critical_final_findings_probe.py')
BUDGET_PROBES = (*PILOT_PROBES, 'name_resolution_probe.py', 'in_source_probe.py')
GATE_PROBES = (*BUDGET_PROBES, 'rls_policy_probe.py', *GUARD_PROBES, 'critical_contract_probe.py')
LEVELS = ('medium', 'high', 'critical')
MEASURES = {'coordinator_gate_levels': ['critical'], 'optimization_level': 'critical'}
# Post-hoc diagnostic protocols of the effect probes, by the summarizer's protocol names.
EFFECT_DIAGNOSTICS = {'dollar': 'dollar_identifier_probe.py', 'counter': 'trigger_counter_probe.py',
                      'unicode-space': 'unicode_space_probe.py', 'separator': 'trigger_separator_probe.py',
                      'malformed-effect': 'malformed_effect_probe.py'}

# The lineage mirrors the measured cohorts: each archive is the next one's
# baseline, probes accumulate, and the Critical contract changes once.
ARCHIVES = (
    dict(name='synthetic-flat-baseline', layout='flat', repetitions=1, probes=('supplemental_probe.py',),
         contract='2026-11-03', critical=['effects']),
    dict(name='synthetic-repeated', baseline='synthetic-flat-baseline', probes=cohort.PROBE_NAMES,
         contract='2026-11-03', critical=['no-effects', 'effects', 'ignore-screen'], followup='plan'),
    dict(name='synthetic-critical-medium', baseline='synthetic-repeated',
         probes=(*cohort.PROBE_NAMES, *cohort.FOLLOWUP_PROBE_NAMES), contract='2026-11-03',
         critical=['no-effects', 'ignore-screen', 'effects'], repairs={(3, 'critical'): 2},
         timeouts={(3, 'critical'): 'repair-2'}, followup='protocol', diagnostics=EFFECT_DIAGNOSTICS,
         manifest=MEASURES),
    dict(name='synthetic-critical-speed', baseline='synthetic-critical-medium',
         probes=(*cohort.PROBE_NAMES, *cohort.FOLLOWUP_PROBE_NAMES, *cohort.EFFECT_PROBE_NAMES),
         contract='2026-11-03', critical=['separator-screen', 'effects', 'effects'],
         repairs={(3, 'critical'): 1, (3, 'high'): 1}, timeouts={(3, 'critical'): 'review-2'},
         diagnostics=EFFECT_DIAGNOSTICS,
         manifest={**MEASURES, 'additional_speed_targets': ['high']}),
    dict(name='synthetic-critical-high', baseline='synthetic-critical-speed',
         probes=(*cohort.PROBE_NAMES, *cohort.FOLLOWUP_PROBE_NAMES, *cohort.EFFECT_PROBE_NAMES),
         loose=cohort.SETTING_PROBE_NAMES, contract='2026-11-03',
         critical=['no-effects', 'ignore-screen', 'pragma-screen'], timeouts={(1, 'critical'): 'review-3'},
         diagnostics={'ignore-scope': 'trigger_ignore_scope_probe.py'},
         manifest={**MEASURES, 'additional_speed_targets': ['high']}),
    dict(name='synthetic-critical-high-pilot', baseline='synthetic-critical-high', levels=('high', 'critical'),
         repetitions=1, probes=PILOT_PROBES, loose=('name_resolution_probe.py',), contract='2026-11-03',
         critical=['pragma-screen'], coordinator_probe='name_resolution_probe.py',
         manifest={**MEASURES, 'additional_speed_targets': ['high']}),
    dict(name='synthetic-in-source-budget', baseline='synthetic-critical-high-pilot', levels=('high', 'critical'),
         repetitions=1, probes=BUDGET_PROBES, loose=GUARD_PROBES, contract='2026-11-03', critical=['effects'],
         regression=('synthetic-critical-high-pilot', 'synthetic-critical-high'),
         manifest={'coordinator_gate_levels': ['critical'], 'optimization_level': 'high',
                   'optimization_metrics': ['uncached_input_tokens'], 'targeted_probes': ['in_source_probe.py'],
                   'additional_speed_targets': []}),
    dict(name='synthetic-contract-gates', baseline='synthetic-in-source-budget', levels=('high', 'critical'),
         repetitions=1, probes=GATE_PROBES, contract='2026-11-05', contract_change=True, critical=['ignore-screen'],
         foreign_suite=False,
         gate_policy='contract', mandatory=('critical_contract_probe.py',), repairs={(1, 'high'): 1},
         regression=('synthetic-in-source-budget', 'synthetic-critical-high-pilot', 'synthetic-critical-high'),
         manifest={'coordinator_gate_levels': ['critical'], 'optimization_level': 'high',
                   'optimization_metrics': ['uncached_input_tokens']}),
)
NAMES = tuple(spec['name'] for spec in ARCHIVES)
SPECS = {spec['name']: spec for spec in ARCHIVES}


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + '\n')


def candidate_sources(level, candidate, foreign_suite=True):
    """Application and test files of one synthetic candidate, by file name."""
    if level == 'medium':
        return {name: (FIXTURES / 'medium' / name).read_text() for name in ('app.py', 'test_app.py')}
    if level == 'high':
        return {name: (FIXTURES / 'high' / name).read_text() for name in ('ledger.py', 'test_ledger.py')}
    files = {'app.py': (REFERENCE / 'app.py').read_text(),
             'test_regressions.py': (FIXTURES / 'critical/test_regressions.py').read_text()}
    if foreign_suite:
        files[FOREIGN_SUITE] = (FIXTURES / 'critical' / FOREIGN_SUITE).read_text()
    if candidate == 'reference':
        files['vault.py'] = (REFERENCE / 'vault.py').read_text()
        files['vault_guard.py'] = (REFERENCE / 'vault_guard.py').read_text()
        return files
    base = (FIXTURES / 'critical/vault.py').read_text()
    assert base.count(HOOK) == 1 and base.count('VERIFY_EFFECTS = True') == 1
    if candidate == 'effects':
        text = base
    elif candidate == 'no-effects':
        text = base.replace('VERIFY_EFFECTS = True', 'VERIFY_EFFECTS = False')
    else:
        text = base.replace(HOOK, SCREENS[candidate])
        if candidate == 'separator-screen':
            text = text.replace('from contextlib import closing\nimport sqlite3\n',
                                'from contextlib import closing\nimport re\nimport sqlite3\n')
    assert candidate == 'effects' or text != base, candidate
    files['vault.py'] = text
    return files


def failing(candidate, probes):
    """Recorded failures of a candidate among the given probe names."""
    return {name: OUTCOMES[candidate][name] for name in probes if name in OUTCOMES[candidate]}


def probe_report(candidate, name, source):
    """A probe report shaped like the real one: countable cases and the source hash."""
    outcome = OUTCOMES[candidate].get(name)
    report = {'workspace': 'synthetic', 'source_sha256': sha256(source)}
    if outcome is None:
        return {**report, 'issue_count': 0, 'failed_cases': 0, 'cases': []}
    if isinstance(outcome, list):
        return {**report, 'issue_count': len(outcome), 'failed_cases': len(outcome), 'failed_case_names': list(outcome),
                'cases': [{'case': case, 'passed': False} for case in outcome]}
    count = 1 if outcome is True else outcome
    return {**report, 'issue_count': count, 'failed_cases': count, 'cases': [], 'count_pinned': outcome is not True}


def finding(index):
    return {'id': f'R{index}', 'severity': 'MEDIUM', 'location': 'vault.py',
            'requirement': 'synthetic requirement', 'evidence': 'synthetic observation',
            'suggested_fix': 'synthetic repair'}


class Builder:
    def __init__(self, root):
        self.root = root
        self.archives = {}
        self.candidates = {}   # (archive, round, level) -> candidate name
        self.clock = START_UNIX
        self.index = 0
        self.grades = self._initial_grades()

    def _initial_grades(self):
        base = harness.prepare(self.root / '_initial')
        grades = {}
        with contextlib.redirect_stdout(io.StringIO()):
            for level in LEVELS:
                grades[level] = harness.grade(base, level, 'baseline')
        shutil.rmtree(base)
        return grades

    # ----- measured phases -------------------------------------------------
    def phase(self, trial, level, name, number, position, timed_out):
        base_seconds, base_input, base_cached, base_output = {
            'medium': (280.0, 24000, 9000, 3500), 'high': (400.0, 60000, 42000, 6000),
            'critical': (640.0, 240000, 190000, 16000)}[level]
        elapsed = TIMEOUT + 0.0 if timed_out else base_seconds + 13 * self.index + 7 * number + 23 * position + 0.25
        started = self.clock
        self.clock += elapsed + 3.0
        workspace = trial / ('reviewspace' if name.startswith('review') else 'workspace')
        folder = trial / name
        folder.mkdir()
        command = ['codex', '-a', 'never', 'exec', '--json', '--model', 'gpt-6-astra',
                   '-c', 'model_reasoning_effort="max"', '--cd', str(workspace), '-o', str(folder / 'final.txt'), '-']
        budget = {'LEAN_RUN_DEADLINE_UNIX': str(started + TIMEOUT), 'LEAN_RUN_PHASE_SECONDS': str(TIMEOUT)}
        write(folder / 'running.json', {'pid': 4242, 'started_unix': started, 'command': command,
                                        'budget_environment': budget})
        prompt = trial / ('review-prompt.txt' if name.startswith('review') else 'prompt.txt')
        (folder / 'prompt.txt').write_text(prompt.read_text())
        (folder / 'final.txt').write_text('Synthetic phase; no model call.\n')
        (folder / 'stderr.log').write_text('')
        usage = None if timed_out else {
            'input_tokens': base_input + 1000 * self.index + 500 * number + 2000 * position,
            'cached_input_tokens': base_cached + 800 * self.index + 300 * number + 1500 * position,
            'output_tokens': base_output + 100 * self.index + 50 * number + 200 * position,
            'cache_write_input_tokens': 0, 'reasoning_output_tokens': base_output // 2}
        events = [{'type': 'thread.started', 'thread_id': 'synthetic'}, {'type': 'turn.started'},
                  {'type': 'item.completed', 'item': {'type': 'command_execution',
                                                      'command': 'python3 -B -m unittest discover -v',
                                                      'aggregated_output': 'Ran 4 tests\n\nOK\n', 'exit_code': 0}},
                  {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'Synthetic phase.'}}]
        if usage is not None:
            events.append({'type': 'turn.completed', 'usage': usage})
        (folder / 'events.jsonl').write_text(''.join(json.dumps(event) + '\n' for event in events))
        write(folder / 'captured-logs.json', [])
        metrics = {'level': level, 'phase': name, 'started_unix': started, 'elapsed_seconds': elapsed,
                   'budget_environment': budget, 'exit_code': -15 if timed_out else 0, 'timed_out': timed_out,
                   'usage': usage, 'requested_model': 'gpt-6-astra', 'requested_effort': 'max',
                   'model_identity_evidence': 'synthetic fixture; no CLI ran', 'completed_turns': 0 if timed_out else 1,
                   'command': command, 'command_count': 1,
                   'event_types': sorted({event['type'] for event in events})}
        if usage is not None:
            metrics['total_tokens'] = usage['input_tokens'] + usage['output_tokens']
            metrics['uncached_input_tokens'] = usage['input_tokens'] - usage['cached_input_tokens']
        write(folder / 'metrics.json', metrics)
        return metrics

    def grade(self, trial, level, label):
        workspace = harness.digest_tree(trial / 'workspace')
        cases = [{'id': case['id'], 'status': 'PASS'} for case in self.grades[level]['cases']]
        write(trial / f'{label}-grade.json', {'level': level, 'cases': cases, 'checks': len(cases), 'issues': 0,
                                               'elapsed_seconds': 0.5, 'workspace_sha256': workspace,
                                               'protected_files_changed': []})

    # ----- cross regressions ---------------------------------------------
    def cross(self, spec, trial, level, phase, candidate, references):
        rows = []
        for archive_index, reference in enumerate(references):
            name = Path(reference).name
            prior = SPECS[name]
            for number in range(1, prior.get('repetitions', 3) + 1):
                historical = self.candidates[name, number, level]
                for direction in ('historical_tests_on_candidate', 'candidate_tests_on_historical'):
                    if level != 'critical':
                        failed = False
                    elif direction == 'historical_tests_on_candidate':
                        failed = prior.get('foreign_suite', True) and candidate in RLS_CANDIDATES
                    else:
                        failed = spec.get('foreign_suite', True) and historical in RLS_CANDIDATES
                    prefix = '' if archive_index == 0 else f'history-{archive_index}-'
                    log = f'{phase}-{prefix}baseline-{number}-{direction}.log'
                    (trial / log).write_text(f'FAIL: {FOREIGN_HEADER}\n\nRan 4 tests\n\nFAILED (failures=1)\n'
                                             if failed else 'Ran 4 tests\n\nOK\n')
                    rows.append({'direction': direction, 'baseline_round': number, 'baseline_archive': reference,
                                 'exit_code': int(failed), 'seconds': 0.05, 'log': log})
        write(trial / f'{phase}-cross.json', rows)
        return rows

    # ----- one trial -------------------------------------------------------
    def trial(self, spec, base, level, number, candidate, references):
        trial = base / level
        known = list(spec['probes'])
        mandatory = set(spec.get('mandatory', ()))
        contract_policy = spec.get('gate_policy') == 'contract'
        failures = failing(candidate, known) if level == 'critical' else {}
        gates = {name: value for name, value in failures.items() if name in mandatory} if contract_policy else failures
        timeout_phase = spec.get('timeouts', {}).get((number, level))
        failed = bool(gates)
        repairs = 2 if failed else spec.get('repairs', {}).get((number, level), 0)
        status = 'TIMEOUT' if timeout_phase else ('FAILED' if failed else 'DONE')
        if level == 'critical':
            (trial / 'workspace/CONTRACT.md').write_text(CONTRACTS[spec['contract']].read_text())
            (trial / 'initial/CONTRACT.md').write_text(CONTRACTS[spec['contract']].read_text())
            (trial / 'initial-hashes.json').write_text(json.dumps(harness.digest_tree(trial / 'initial'), indent=2))
        baseline = dict(self.grades[level], workspace_sha256=harness.digest_tree(trial / 'initial'),
                        protected_files_changed=[])
        write(trial / 'baseline-grade.json', baseline)
        shutil.copyfile(trial / 'prompt.txt', trial / 'original-prompt.txt')
        for name, text in candidate_sources(level, candidate, spec.get('foreign_suite', True)).items():
            (trial / 'workspace' / name).write_text(text)
        source = (trial / 'workspace/vault.py').read_bytes() if level == 'critical' else b''
        workspace_digest = harness.digest_tree(trial / 'workspace')
        position = 0
        first_blockers = None
        findings_history = []
        for index in range(1, repairs + 2):
            phase = 'review' if index == 1 else f'review-{index}'
            if index == 1:
                self.phase(trial, level, 'implementation', number, position, timeout_phase == 'implementation')
                position += 1
                grade_name = 'post-implementation-grade.json'
            else:
                repair = f'repair-{index - 1}'
                write(trial / f'{repair}-request.json', {'findings': findings_history[-1]})
                shutil.copytree(trial / 'workspace', trial / f'workspace-before-{repair}',
                                ignore=shutil.ignore_patterns('__pycache__'))
                self.phase(trial, level, repair, number, position, timeout_phase == repair)
                position += 1
                grade_name = f'post-{repair}-grade.json'
            self.grade(trial, level, grade_name.removesuffix('-grade.json'))
            if index > 1:
                (trial / 'reviewspace').rename(trial / f'reviewspace-before-{phase}')
            with contextlib.redirect_stdout(io.StringIO()):
                harness.prepare_review(base, level)
            if index > 1:
                pre = trial / 'reviewspace/.pre-repair'
                pre.mkdir()
                for path in (trial / f'workspace-before-repair-{index - 1}').glob('*.py'):
                    shutil.copyfile(path, pre / path.name)
                with (trial / 'review-prompt.txt').open('a') as prompt:
                    prompt.write(f'\nRenewed independent review after REWORK {index - 1}.\n')
            write(trial / f'{phase}-hashes.json', harness.digest_tree(trial / 'reviewspace'))
            self.phase(trial, level, phase, number, position, timeout_phase == phase)
            position += 1
            final = index == repairs + 1
            findings = [] if final else [finding(index)]
            findings_history.append(findings)
            review = {'status': 'PASS' if final else 'REWORK', 'findings': findings,
                      'checks': ['python3 -B -m unittest discover -v'], 'coverage_limits': ['synthetic review']}
            write(trial / phase / 'final.txt', review)
            integrity = {'changed_or_removed': [], 'added_logs': [], 'unexpected_additions': []}
            write(trial / f'{phase}-integrity.json', integrity)
            cross = self.cross(spec, trial, level, phase, candidate, references)
            probes = {}
            if level == 'critical':
                for name in known:
                    report = probe_report(candidate, name, source)
                    log = f'{phase}-{Path(name).stem}.log'
                    (trial / log).write_text(json.dumps(report) + '\n')
                    probes[name] = {'exit_code': int(name in failures), 'report': report, 'log': log,
                                    'passed': name not in failures, 'mandatory': name in mandatory}
                write(trial / f'{phase}-known-probes.json', probes)
            supplemental = None if level != 'critical' else int('supplemental_probe.py' in failures)
            blockers = []
            if findings:
                blockers.append('independent_review')
            if supplemental:
                blockers.append('critical_supplemental')
            if contract_policy:
                if gates:
                    blockers.append('mandatory_probes')
            elif failures:
                blockers.append('known_quality_probes')
            historical = [row for row in cross if row['direction'] == 'historical_tests_on_candidate' and row['exit_code']]
            if not contract_policy and historical:
                blockers.append('historical_regressions')
            advisory = None
            if contract_policy:
                advisory = {'probes': sorted(name for name in failures if name not in mandatory),
                            'historical_suites_failing': [{key: row[key] for key in ('baseline_archive', 'baseline_round', 'log')}
                                                          for row in historical]}
            assessment = {'advisory': advisory, 'policy_superseded': {'historical': [], 'probes': {}}, 'phase': phase,
                          'review': review, 'grade': grade_name, 'cross': cross,
                          'supplemental_issue_count': supplemental, 'blockers': blockers,
                          'review_integrity': integrity, 'critical_probes': probes,
                          'candidate_sha256': workspace_digest}
            if final and level == 'critical' and spec.get('coordinator_probe'):
                name = spec['coordinator_probe']
                assessment['coordinator_probes'] = {name: {
                    'report': probe_report(candidate, name, source), 'passed': name not in OUTCOMES[candidate],
                    'application_sha256': {'vault.py': workspace_digest['vault.py']}}}
            write(trial / f'assessment-{index}.json', assessment)
            if first_blockers is None:
                first_blockers = blockers
            if final and level == 'critical':
                for key, probe in spec.get('diagnostics', {}).items():
                    report = probe_report(candidate, probe, source)
                    write(trial / f'assessment-{index}-{Path(probe).stem}.json',
                          {**report, 'finding_groups': {key: probe in failures}})
        result = {'policy_superseded': {'historical': [], 'probes': {}}, 'status': status,
                  'final_assessment': repairs + 1, 'repair_rounds': repairs, 'final_grade': grade_name,
                  'final_review': phase, 'initial_review_issues': len(findings_history[0]),
                  'final_review_issues': 0, 'first_pass_blockers': first_blockers, 'adjudication': None}
        if status == 'TIMEOUT':
            result['quality_status'] = 'FAILED' if failed else 'PASS'
        if failed:
            result['remaining_blockers'] = blockers
        write(trial / 'result.json', result)
        return {'candidate': candidate, 'status': status, 'failures': failures}

    # ----- one archive -----------------------------------------------------
    def archive(self, spec):
        dest = self.root / spec['name']
        levels = tuple(spec.get('levels', LEVELS))
        repetitions = spec.get('repetitions', 3)
        orders = [tuple(levels[n % len(levels):]) + tuple(levels[:n % len(levels)]) for n in range(repetitions)]
        flat = spec.get('layout') == 'flat'
        baseline = self.archives[spec['baseline']] if spec.get('baseline') else None
        if flat:
            harness.prepare(dest, levels=levels)
        else:
            dest.mkdir()
            for number, order in enumerate(orders, 1):
                harness.prepare(dest / f'round-{number}', levels=order)
        probes = list(spec['probes'])
        for name in (*probes, *spec.get('loose', ())):
            shutil.copyfile(PROBES / name, dest / name)
        shutil.copyfile(ROOT / 'tests/level_benchmark.py', dest / 'harness-frozen.py')
        shutil.copyfile(ROOT / 'tests/repeated_benchmark.py', dest / 'runner-frozen.py')
        references = [str(self.archives[name]) for name in spec.get('regression', ())] or ([str(baseline)] if baseline else [])
        controls = {}
        summaries = {}
        for number, order in enumerate(orders, 1):
            base = dest if flat else dest / f'round-{number}'
            for position, level in enumerate(order):
                candidate = spec['critical'][number - 1] if level == 'critical' else level
                self.candidates[spec['name'], number, level] = candidate
                checks = {'non_skill_initial_files_identical': True, 'implementation_prompt_identical': True,
                          'grader_identical': True}
                if level == 'critical' and spec.get('contract_change'):
                    checks.update(non_skill_initial_files_identical=False, declared_contract_change_only=True,
                                  baseline_contract_sha256=sha256(CONTRACTS[SPECS[spec['baseline']]['contract']].read_bytes()),
                                  candidate_contract_sha256=sha256(CONTRACTS[spec['contract']].read_bytes()))
                controls[f'round-{number}/{level}'] = checks
                summaries[number, level] = self.trial(spec, base, level, number, candidate, references)
        if flat:
            self.flat_manifest(dest, spec, levels)
            self.flat_summary(dest, levels)
        else:
            self.manifest(dest, spec, baseline, orders, probes, references)
            write(dest / 'controls.json', controls)
            self.extras(dest, spec, baseline, summaries)
            with contextlib.redirect_stdout(io.StringIO()):
                reporter.summarize(dest)
        hashes = reporter.digest(dest)
        write(dest / 'archive-sha256.json', hashes)
        self.index += 1
        return dest

    def flat_manifest(self, dest, spec, levels):
        write(dest / 'manifest.json', {
            'source_revision': 'synthetic', 'skill_sha256': harness.digest_tree(ROOT / 'skills/lean-run'),
            'generator_sha256': sha256((ROOT / 'tests/level_benchmark.py').read_bytes()),
            'grader_sha256': sha256(harness.GRADER.encode()),
            'levels': {level: harness.FIXTURES[level]['title'] for level in levels},
            'issue_unit': 'one failed predefined contract category; not individual assertions',
            'repetitions_per_level': 1})

    def flat_summary(self, dest, levels):
        rows = []
        for level in levels:
            phases = sorted((reporter.read(path) for path in (dest / level).glob('*/metrics.json')),
                            key=lambda metric: metric['started_unix'])
            usage = {key: sum(phase['usage'][key] for phase in phases) for key in phases[0]['usage']}
            first = [phase for phase in phases if phase['phase'] in ('implementation', 'review')]
            rows.append({'level': level, 'status': 'DONE', 'phase_names': [phase['phase'] for phase in phases],
                         'measured_agent_seconds': sum(phase['elapsed_seconds'] for phase in phases),
                         'total_tokens': usage['input_tokens'] + usage['output_tokens'], 'usage': usage,
                         'uncached_input_plus_output': usage['input_tokens'] - usage['cached_input_tokens'] + usage['output_tokens'],
                         'first_pass_agent_seconds': sum(phase['elapsed_seconds'] for phase in first),
                         'first_pass_tokens': sum(phase['total_tokens'] for phase in first),
                         'first_review_issues': 0, 'final_review_issues': 0, 'repair_rounds': 0,
                         'final_issue_categories': 0, 'contract_category_checks': self.grades[level]['checks'],
                         'workflow_span_seconds': phases[-1]['started_unix'] + phases[-1]['elapsed_seconds'] - phases[0]['started_unix'],
                         'tool_output_characters': 0})
        write(dest / 'summary.json', {'levels': rows})

    def manifest(self, dest, spec, baseline, orders, probes, references):
        manifest = {**spec.get('manifest', {})}
        if spec.get('regression'):
            manifest['regression_archives'] = references
        if spec.get('contract_change'):
            shutil.copyfile(POLICY / 'README.md', dest / 'policy-record.md')
            shutil.copyfile(POLICY / 'superseded-expectations.json', dest / 'superseded-expectations.json')
            manifest.update(contract_changed_levels=['critical'],
                            comparison_valid_levels=[level for level in spec['levels'] if level != 'critical'],
                            policy_record='policy-record.md',
                            policy_record_sha256=sha256((dest / 'policy-record.md').read_bytes()),
                            superseded_expectations='superseded-expectations.json')
        if spec.get('gate_policy') == 'contract':
            mandatory = list(spec['mandatory'])
            shutil.copytree(REFERENCE, dest / 'reference/critical', ignore=shutil.ignore_patterns('__pycache__'))
            check = {'reference': {'grader': True, **{name: True for name in mandatory}},
                     'initial': {'grader': False, **{name: False for name in mandatory}}}
            check.update(reference_passes_all=True, initial_fails_some=True)
            write(dest / 'reference-check.json', {'critical': check})
            manifest.update(gate_policy='contract', mandatory_probes=mandatory,
                            advisory_probes=[name for name in probes if name not in mandatory],
                            reference_check='reference-check.json')
        manifest.update({
            'status': 'PREPARED', 'baseline_archive': str(baseline), 'requested_model': 'gpt-6-astra',
            'requested_effort': 'max', 'timeout_seconds': TIMEOUT, 'procedure_depth': 'standard',
            'repetitions_per_level': len(orders), 'baseline_repetitions_per_level': cohort.baseline_count(baseline),
            'known_quality_probes': probes,
            'probe_sha256': {name: sha256((dest / name).read_bytes()) for name in probes},
            'orders': [list(order) for order in orders], 'skill_sha256': harness.digest_tree(ROOT / 'skills/lean-run'),
            'budget_policy': 'Same 900-second cap made visible through deadline environment',
            'harness_sha256': sha256((dest / 'harness-frozen.py').read_bytes()),
            'primary_metrics': ['medium mean measured workflow seconds', 'medium mean uncached input'],
            'additional_metrics': ['uncached input', 'total input plus output', 'cached input'],
            'quality_gate': 'unchanged frozen categories, protected files, independent review, historical regressions and critical supplemental writes',
            'cache_policy': 'No synthetic warmup; cache state not controlled',
            'review_integrity_policy': 'All pre-review files immutable; newly created .log evidence allowed and recorded',
            'measurement_excludes': ['coordinator chat', 'skill review', 'preparation', 'grading', 'cross-regressions', 'reporting'],
            'synthetic': 'Built by tests/synthetic_cohorts.py for the unit tests; no model phase ran.'})
        write(dest / 'manifest.json', manifest)

    def extras(self, dest, spec, baseline, summaries):
        """Follow-up, diagnostic and targeted-probe records the summarizer and auditor read."""
        name = spec['name']
        prior = SPECS[spec['baseline']]
        rounds = range(1, spec.get('repetitions', 3) + 1)

        def source(archive, number):
            return (cohort.baseline_trial(archive, 'critical', number) / 'workspace/vault.py').read_bytes()

        def report(candidate, probe, data, **extra):
            return {**probe_report(candidate, probe, data), **extra}

        if spec.get('followup') == 'plan':
            labels = {'after-trigger': 'after_trigger_probe.py', 'audit-followup': 'audit_followup_probe.py',
                      'preservation': 'preservation_probe.py', 'noop': 'noop_probe.py',
                      'read-isolation': 'read_isolation_probe.py', 'ignored-update': 'ignored_update_probe.py'}
            write(dest / 'quality-followup-plan.json', {'probes': list(labels.values()), 'scope': 'synthetic follow-up'})
            historical = self.candidates[prior['name'], 1, 'critical']
            for label, probe in labels.items():
                write(dest / f'{label}-historical.json', report(historical, probe, source(baseline, 1)))
                for number in rounds:
                    write(dest / f'{label}-round-{number}-final.json',
                          report(self.candidates[name, number, 'critical'], probe, source(dest, number)))
        if spec.get('followup') == 'protocol':
            labels = {'frame-followup': 'frame_followup_probe.py', 'trigger-compatibility': 'trigger_compatibility_probe.py'}
            write(dest / 'followup-protocol.json', {'probes': list(labels.values()), 'scope': 'synthetic follow-up'})
            for label, probe in labels.items():
                for number in rounds:
                    write(dest / f'{label}-baseline-{number}.json',
                          report(self.candidates[prior['name'], number, 'critical'], probe, source(baseline, number),
                                 finding_groups={label: probe in OUTCOMES[self.candidates[prior['name'], number, 'critical']]}))
                    candidate = self.candidates[name, number, 'critical']
                    write(dest / f'{label}-round-{number}-final.json',
                          report(candidate, probe, source(dest, number), finding_groups={label: probe in OUTCOMES[candidate]}))
        for label, probe in spec.get('diagnostics', {}).items():
            write(dest / f'{label}-protocol.json', {'probe': probe, 'scope': 'synthetic diagnostic'})
            for number in range(1, prior.get('repetitions', 3) + 1):
                candidate = self.candidates[prior['name'], number, 'critical']
                write(dest / f'baseline-{number}-{label}.json',
                      report(candidate, probe, source(baseline, number), finding_groups={label: probe in OUTCOMES[candidate]}))
        for probe in spec.get('manifest', {}).get('targeted_probes', []):
            for number in range(1, prior.get('repetitions', 3) + 1):
                write(dest / f'baseline-{number}-{Path(probe).stem}.json',
                      report(self.candidates[prior['name'], number, 'critical'], probe, source(baseline, number)))
        earlier = 'critical_final_findings_probe.py'
        if earlier in spec['probes'] and earlier not in prior['probes']:
            for number in range(1, prior.get('repetitions', 3) + 1):
                write(dest / f'baseline-{number}-critical-final-findings.json',
                      report(self.candidates[prior['name'], number, 'critical'], earlier, source(baseline, number)))
        if spec.get('coordinator_probe'):
            probe = spec['coordinator_probe']
            write(dest / 'name-resolution-protocol.json', {'probe': probe, 'scope': 'synthetic coordinator probe'})
            for number in range(1, prior.get('repetitions', 3) + 1):
                write(dest / f'baseline-{number}-name-resolution.json',
                      report(self.candidates[prior['name'], number, 'critical'], probe, source(baseline, number)))
            write(dest / 'repair-1-name-resolution.json',
                  report(self.candidates[name, 1, 'critical'], probe, source(dest, 1)))


def build(root):
    """Build the whole lineage under root; returns archive name -> path."""
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    builder = Builder(root)
    for spec in ARCHIVES:
        builder.archives[spec['name']] = builder.archive(spec)
    return dict(builder.archives)


_BUILT = None


def archives():
    """The lineage, built once per process in a temporary directory."""
    global _BUILT
    if _BUILT is None:
        root = Path(tempfile.mkdtemp(prefix='lean-synthetic-cohorts-'))
        atexit.register(shutil.rmtree, root, True)
        _BUILT = build(root)
    return _BUILT


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path, help='new directory outside the repository')
    for name, path in build(parser.parse_args().directory).items():
        print(name, path)
