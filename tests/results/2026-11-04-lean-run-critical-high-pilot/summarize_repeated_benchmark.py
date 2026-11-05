"""Verify raw usage and summarize selected opt-in trials; no model calls."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import statistics

METRICS=('measured_seconds','total_tokens','input_tokens','cached_input_tokens',
         'uncached_input_tokens','output_tokens','uncached_input_plus_output')


def read(path):return json.loads(path.read_text())

def write(path,value):path.write_text(json.dumps(value,indent=2)+'\n')

def describe(values):
    known=[value for value in values if value is not None]
    complete=len(known)==len(values)
    return {'n':len(known),'requested_n':len(values),'unknown_count':len(values)-len(known),
            'mean':statistics.mean(known) if complete else None,
            'median':statistics.median(known) if complete else None,
            'sample_sd':statistics.stdev(known) if complete and len(known)>1 else None,
            'min':min(known) if complete else None,'max':max(known) if complete else None,
            'known_sum':sum(known)}


def complete_sum(values):
    values=list(values)
    return sum(values) if all(value is not None for value in values) else None


def change_percent(after,before):
    return (after/before-1)*100 if after is not None and before not in (None,0) else None


def usage_for_phase(path):
    metrics=read(path);raw=path.with_name('events.jsonl').read_bytes()
    events=[json.loads(line) for line in raw.decode().splitlines()]
    usages=[e['usage'] for e in events if e.get('type')=='turn.completed' and 'usage' in e]
    usage={k:sum(v.get(k,0) for v in usages) for k in set().union(*(v.keys() for v in usages))} if usages else None
    assert usage==metrics['usage'],path
    if usage is None:
        assert metrics['timed_out'] and metrics['exit_code']!=0,path
    else:
        assert usage['cached_input_tokens']<=usage['input_tokens'],path
        assert metrics['total_tokens']==usage['input_tokens']+usage['output_tokens'],path
        assert metrics['exit_code']==0 and not metrics['timed_out'],path
    commands=[e['item'] for e in events if e.get('type')=='item.completed' and e.get('item',{}).get('type')=='command_execution']
    logs=read(path.with_name('captured-logs.json'))
    return {'phase':metrics['phase'],'started_unix':metrics['started_unix'],'measured_seconds':metrics['elapsed_seconds'],
            **{k:usage[k] if usage is not None else None for k in ('input_tokens','cached_input_tokens','output_tokens')},
            'uncached_input_tokens':usage['input_tokens']-usage['cached_input_tokens'] if usage is not None else None,
            'uncached_input_plus_output':usage['input_tokens']-usage['cached_input_tokens']+usage['output_tokens'] if usage is not None else None,
            'total_tokens':metrics.get('total_tokens'),'command_count':len(commands),
            'tool_output_characters':sum(len(c.get('aggregated_output','')) for c in commands),
            'captured_log_count':sum('archived' in v for v in logs),
            'unavailable_log_count':sum('archived' not in v for v in logs),
            'raw_events_sha256':hashlib.sha256(raw).hexdigest(),'raw_usage_verified':usage is not None,
            'usage_known':usage is not None,'timed_out':metrics['timed_out'],'exit_code':metrics['exit_code']}


def digest(path):
    return {str(p.relative_to(path)):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(path.rglob('*')) if p.is_file() and '__pycache__' not in p.parts}


def baseline_trial(archive,level,number=1):
    repeated=archive/f'round-{number}'/level
    return repeated if repeated.is_dir() else archive/level


def baseline_metrics(row):
    if 'statistics' in row:
        return {key:row['statistics'][key]['mean'] for key in METRICS}
    return {'measured_seconds':row['measured_agent_seconds'],'total_tokens':row['total_tokens'],
            'input_tokens':row['usage']['input_tokens'],'cached_input_tokens':row['usage']['cached_input_tokens'],
            'uncached_input_tokens':row['usage']['input_tokens']-row['usage']['cached_input_tokens'],
            'output_tokens':row['usage']['output_tokens'],'uncached_input_plus_output':row['uncached_input_plus_output']}


def phase_means(trials):
    """Include zero cost for repairs that were never needed, not unknown usage."""
    groups={'implementation':lambda phase:phase=='implementation',
            'repair-1':lambda phase:phase=='repair-1',
            'repair-2':lambda phase:phase=='repair-2',
            'reviews':lambda phase:phase.startswith('review')}
    return {name:statistics.mean(sum(seconds for phase,seconds in trial if selected(phase))
                                 for trial in trials) for name,selected in groups.items()}


def summarize(root):
    root=root.resolve();manifest=read(root/'manifest.json');baseline=Path(manifest['baseline_archive'])
    old={v['level']:v for v in read(baseline/'summary.json')['levels']}
    trials=[];phases=[];controls=read(root/'controls.json')
    orders=manifest['orders']
    selected_levels=list(dict.fromkeys(level for order in orders for level in order))
    for number,order in enumerate(orders,1):
        for level in order:
            trial=root/f'round-{number}'/level;result=read(trial/'result.json')
            assert result['status'] in ('DONE','FAILED','TIMEOUT'),trial
            assessment=read(trial/f"assessment-{result['final_assessment']}.json")
            assert digest(trial/'workspace')==assessment['candidate_sha256'],trial
            grade=read(trial/result['final_grade'])
            passed=result['status']=='DONE' or result.get('quality_status')=='PASS'
            assert result['final_review_issues']==len(assessment['review']['findings']),trial
            if passed:
                assert grade['issues']==0 and not grade['protected_files_changed'],trial
                assert assessment['review']['status']=='PASS' and not assessment['review']['findings'],trial
                assert not assessment.get('coordinator_findings'),trial
            else:
                assert result['repair_rounds']==2 and assessment['blockers'],trial
            added_failures=0;posthoc_probes={}
            if level=='critical':
                if passed:assert assessment['supplemental_issue_count']==0
                if (root/'quality-followup-plan.json').exists():
                    followup=read(root/f'after-trigger-round-{number}-final.json')
                    assert followup['source_sha256']==hashlib.sha256((trial/'workspace/vault.py').read_bytes()).hexdigest(),trial
                    audit=read(root/f'audit-followup-round-{number}-final.json')
                    assert audit['source_sha256']==followup['source_sha256'],trial
                    preservation=read(root/f'preservation-round-{number}-final.json')
                    assert preservation['source_sha256']==followup['source_sha256'],trial
                    noop=read(root/f'noop-round-{number}-final.json')
                    assert noop['source_sha256']==followup['source_sha256'],trial
                    isolation=read(root/f'read-isolation-round-{number}-final.json')
                    assert isolation['source_sha256']==followup['source_sha256'],trial
                    ignored_update=read(root/f'ignored-update-round-{number}-final.json')
                    assert ignored_update['source_sha256']==followup['source_sha256'],trial
                    added_failures=sum(probe['failed_cases'] for probe in (followup,audit,preservation,noop,isolation,ignored_update))
                    if passed:assert added_failures==0,trial
                elif manifest.get('known_quality_probes'):
                    probes=assessment['critical_probes']
                    assert set(probes)==set(manifest['known_quality_probes']),trial
                    for probe in probes.values():
                        report=probe['report']
                        if report and 'source_sha256' in report:
                            assert report['source_sha256']==hashlib.sha256((trial/'workspace/vault.py').read_bytes()).hexdigest(),trial
                    added_failures=sum((p['report'] or {}).get('failed_cases',0) for name,p in probes.items() if name!='supplemental_probe.py')
                    if passed:assert all(p['passed'] for p in probes.values()),trial
                if (root/'followup-protocol.json').exists():
                    for name in ('frame-followup','trigger-compatibility'):
                        report=read(root/f'{name}-round-{number}-final.json')
                        assert report['source_sha256']==hashlib.sha256((trial/'workspace/vault.py').read_bytes()).hexdigest(),trial
                        posthoc_probes[name]={'failed_cases':report['failed_cases'],
                                             'executed_cases':len(report['cases']),
                                             'finding_groups':report['finding_groups']}
                diagnostics = {
                    'dollar': 'dollar_identifier', 'counter': 'trigger_counter',
                    'unicode-space': 'unicode_space', 'separator': 'trigger_separator',
                    'malformed-effect': 'malformed_effect',
                    'storage-encoding': 'storage_encoding',
                    'ignore-scope': 'trigger_ignore_scope',
                    'recursive-setting': 'recursive_setting',
                }
                for name, probe in diagnostics.items():
                    if not (root/f'{name}-protocol.json').exists():
                        continue
                    report=read(trial/f"assessment-{result['final_assessment']}-{probe}_probe.json")
                    assert report['source_sha256']==hashlib.sha256((trial/'workspace/vault.py').read_bytes()).hexdigest(),trial
                    posthoc_probes[name]={'failed_cases':report['failed_cases'],
                                         'executed_cases':len(report['cases']),
                                         'finding_groups':report.get('finding_groups',{})}
                for name, probe in assessment.get('coordinator_probes', {}).items():
                    assert name not in manifest.get('known_quality_probes', []), (trial, name)
                    assert name not in posthoc_probes, (trial, name)
                    report = probe['report']
                    assert report['source_sha256'] == assessment['candidate_sha256']['vault.py'], (trial, name)
                    for source, value in probe.get('application_sha256', {}).items():
                        assert assessment['candidate_sha256'].get(source) == value, (trial, name, source)
                    assert not passed or probe['passed'], (trial, name)
                    posthoc_probes[name] = {
                        'failed_cases': report['failed_cases'],
                        'executed_cases': len(report['cases']),
                        'finding_groups': report.get('finding_groups', {}),
                    }
                if passed:assert all(p['failed_cases']==0 for p in posthoc_probes.values()),trial
            controls[f'round-{number}/{level}']['first_review_prompt_identical']=(trial/'review/prompt.txt').read_bytes()==(baseline_trial(baseline,level,number)/'review/prompt.txt').read_bytes()
            assert all(controls[f'round-{number}/{level}'].values())
            local=[]
            for path in trial.glob('*/metrics.json'):
                phase=usage_for_phase(path);phase.update(round=number,level=level);local.append(phase);phases.append(phase)
            local.sort(key=lambda p:p['started_unix'])
            assert len(local)==2+2*result['repair_rounds'],trial
            review_history=[len(read(trial/f'assessment-{index}.json')['review']['findings'])
                            for index in range(1,result['final_assessment']+1)]
            coordinator_history=[]
            for index in range(1,result['final_assessment']+1):
                findings=read(trial/f'assessment-{index}.json').get('coordinator_findings',[])
                request=trial/f'repair-{index}-request.json'
                if request.exists():findings=findings+read(request)['findings']
                coordinator_history.append(len({f['id'] for f in findings if f['id'].startswith('COORD-')}))
            record={'round':number,'level':level,'status':result['status'],
                    **{k:complete_sum(p[k] for p in local) for k in METRICS},
                    'quality_passed':passed,
                    'execution_complete':all(p['usage_known'] and not p['timed_out'] for p in local),
                    'known_consumption':{k:sum(p[k] for p in local if p[k] is not None) for k in METRICS},
                    'incomplete_phases':[p['phase'] for p in local if not p['usage_known'] or p['timed_out']],
                    'phase_count':len(local),'repair_rounds':result['repair_rounds'],
                    'first_review_issues':result['initial_review_issues'],'final_review_issues':result['final_review_issues'],
                    'posthoc_review_issues':len(read(trial/'posthoc-review.json')['findings']) if (trial/'posthoc-review.json').exists() else 0,
                    'review_issue_history':review_history,'renewed_review_issues':sum(review_history[1:]),
                    'coordinator_issue_history':coordinator_history,
                    'final_coordinator_findings':len(assessment.get('coordinator_findings',[])),
                    'final_contract_categories':grade['checks'],'final_contract_issues':grade['issues'],
                    'changed_protected_files':len(grade['protected_files_changed']),
                    'final_added_probe_failed_cases':added_failures,
                    'posthoc_probes':posthoc_probes,
                    'final_posthoc_probe_failed_cases':sum(p['failed_cases'] for p in posthoc_probes.values()),
                    'final_original_supplemental_issues':assessment['supplemental_issue_count'] or 0,
                    'workflow_span_seconds':local[-1]['started_unix']+local[-1]['measured_seconds']-local[0]['started_unix'],
                    'first_pass_seconds':sum(p['measured_seconds'] for p in local if p['phase'] in ('implementation','review')),
                    'implementation_seconds':next(p['measured_seconds'] for p in local if p['phase']=='implementation'),
                    'implementation_uncached_input_tokens':next(p['uncached_input_tokens'] for p in local if p['phase']=='implementation'),
                    'first_pass_uncached_input_plus_output':complete_sum(p['uncached_input_plus_output'] for p in local if p['phase'] in ('implementation','review')),
                    'candidate_tests_on_historical_exit':assessment['cross'][1]['exit_code'],
                    'candidate_tests_on_historical_exits':[r['exit_code'] for r in assessment['cross'] if r['direction']=='candidate_tests_on_historical']}
            trials.append(record)
    summaries=[]
    for level in selected_levels:
        cases=[t for t in trials if t['level']==level];prior=old[level]
        before=baseline_metrics(prior)
        stats={k:describe([t[k] for t in cases]) for k in METRICS}
        baseline_n=prior.get('candidate_n',1)
        implementation_before=[read(baseline_trial(baseline,level,n)/'implementation/metrics.json')['elapsed_seconds'] for n in range(1,baseline_n+1)]
        old_phases=[[ (m['phase'],m['elapsed_seconds']) for m in
                      (read(p) for p in baseline_trial(baseline,level,n).glob('*/metrics.json'))]
                    for n in range(1,baseline_n+1)]
        new_phases=[[(p['phase'],p['measured_seconds']) for p in phases if p['round']==n and p['level']==level]
                    for n in sorted({t['round'] for t in cases})]
        summaries.append({'level':level,'baseline_n':baseline_n,'candidate_n':len(cases),'baseline':before,'statistics':stats,
            'baseline_phase_means':phase_means(old_phases),'candidate_phase_means':phase_means(new_phases),
            'baseline_implementation_seconds':describe(implementation_before),
            'implementation_seconds':describe([t['implementation_seconds'] for t in cases]),
            'implementation_time_change_percent':(statistics.mean(t['implementation_seconds'] for t in cases)/statistics.mean(implementation_before)-1)*100,
            'mean_change_percent':{k:change_percent(stats[k]['mean'],before[k]) for k in METRICS},
            'first_review_issues':[t['first_review_issues'] for t in cases],
            'posthoc_review_issues':[t['posthoc_review_issues'] for t in cases],
            'renewed_review_issues':[t['renewed_review_issues'] for t in cases],
            'final_review_issues':[t['final_review_issues'] for t in cases],
            'repair_rounds':[t['repair_rounds'] for t in cases]})
    baseline_summary=read(baseline/'summary.json')
    total={'actual_trial_consumption':{k:complete_sum(t[k] for t in trials) for k in METRICS},
           'known_consumption_lower_bound':{k:sum(t['known_consumption'][k] for t in trials) for k in METRICS},
           'baseline_actual_consumption':baseline_summary.get('totals',{}).get('actual_nine_trial_consumption'),
           'baseline_one_of_each_level':{k:complete_sum(t['baseline'][k] for t in summaries) for k in METRICS},
           'candidate_sum_of_level_means':{k:complete_sum(t['statistics'][k]['mean'] for t in summaries) for k in METRICS}}
    if len(trials)==9:total['actual_nine_trial_consumption']=total['actual_trial_consumption']
    total['normalized_change_percent']={k:change_percent(total['candidate_sum_of_level_means'][k],total['baseline_one_of_each_level'][k]) for k in METRICS}
    followup=None
    if (root/'quality-followup-plan.json').exists():
        followup={'plan':'quality-followup-plan.json',
                  'historical_failing_added_cases':read(root/'after-trigger-historical.json')['failed_cases']+read(root/'audit-followup-historical.json')['failed_cases'],
                  'historical_total_added_cases':12,
                  'candidate_posthoc_finding_occurrences':sum(t['posthoc_review_issues'] for t in trials),
                  'candidate_renewed_review_finding_occurrences':sum(t['renewed_review_issues'] for t in trials),
                  'final_candidate_remaining_independent_findings':sum(t['final_review_issues'] for t in trials),
                  'final_added_probe_failed_cases':sum(t['final_added_probe_failed_cases'] for t in trials),
                  'comparison_limit':'Historical cost excludes newly demonstrated trigger failures and any repair. Failed candidate costs also do not represent time-to-completion.'}
        followup['historical_failing_added_cases']+=read(root/'preservation-historical.json')['failed_cases']
        followup['historical_failing_added_cases']+=read(root/'noop-historical.json')['failed_cases']
        followup['historical_failing_added_cases']+=read(root/'read-isolation-historical.json')['failed_cases']
        followup['historical_failing_added_cases']+=read(root/'ignored-update-historical.json')['failed_cases']
    quality={'status':'PASS' if all(t['quality_passed'] for t in trials) else 'FAILED',
             'passed_trials':sum(t['quality_passed'] for t in trials),
             'failed_trials':[f"round-{t['round']}/{t['level']}" for t in trials if t['status']=='FAILED'],
             'incomplete_execution_trials':[f"round-{t['round']}/{t['level']}" for t in trials if not t['execution_complete']],
             'fully_completed_trials':sum(t['quality_passed'] and t['execution_complete'] for t in trials),
             'final_contract_issues':sum(t['final_contract_issues'] for t in trials),
             'final_independent_findings':sum(t['final_review_issues'] for t in trials),
             'final_coordinator_findings':sum(t['final_coordinator_findings'] for t in trials),
             'final_original_supplemental_issues':sum(t['final_original_supplemental_issues'] for t in trials),
             'final_added_probe_failed_cases':sum(t['final_added_probe_failed_cases'] for t in trials),
             'final_posthoc_probe_failed_cases':sum(t['final_posthoc_probe_failed_cases'] for t in trials)}
    target_level=manifest.get('optimization_level',selected_levels[0])
    target_row=next(row for row in summaries if row['level']==target_level)
    compared=('measured_seconds',) if target_level=='critical' else ('measured_seconds','uncached_input_tokens','uncached_input_plus_output')
    target_checks={key:target_row['mean_change_percent'][key] is not None and target_row['mean_change_percent'][key]<0
                   for key in compared}
    for level in manifest.get('additional_speed_targets',[]):
        row=next(row for row in summaries if row['level']==level)
        change=row['mean_change_percent']['measured_seconds']
        target_checks[f'{level}_workflow_time_reduced']=change is not None and change<0
    target_checks['all_trial_quality_passed']=quality['status']=='PASS'
    target_checks['all_measurements_complete']=all(t['execution_complete'] for t in trials)
    if target_level=='medium':target_checks['medium_implementation_time_reduced']=target_row['implementation_time_change_percent']<0
    target={'level':target_level,'checks':target_checks,'met_in_observed_sample':all(target_checks.values()),
            'interpretation':f"Descriptive new n={target_row['candidate_n']} versus historical n={target_row['baseline_n']}; no causal or statistical guarantee."}
    telemetry={'status':'COMPLETE' if all(p['usage_known'] for p in phases) else 'INCOMPLETE',
               'phase_count':len(phases),'known_usage_phases':sum(p['usage_known'] for p in phases),
               'unknown_usage_phases':[{k:p[k] for k in ('round','level','phase','measured_seconds')} for p in phases if not p['usage_known']]}
    posthoc_followup=None
    if (root/'followup-protocol.json').exists():
        posthoc_followup={'protocol':'followup-protocol.json','probes':{}}
        for name in ('frame-followup','trigger-compatibility'):
            historical=[read(root/f'{name}-baseline-{number}.json') for number in (1,2,3)]
            candidates=[t['posthoc_probes'][name] for t in trials if t['level']=='critical']
            posthoc_followup['probes'][name]={
                'executed_cases_per_trial':len(historical[0]['cases']),
                'baseline_failed_cases':[p['failed_cases'] for p in historical],
                'candidate_failed_cases':[p['failed_cases'] for p in candidates],
                'baseline_finding_groups':[p['finding_groups'] for p in historical],
                'candidate_finding_groups':[p['finding_groups'] for p in candidates]}
    write(root/'summary.json',{'levels':summaries,'totals':total,'trials':trials,'telemetry':telemetry,
                             'optimization_target':target,'quality':quality,'quality_followup':followup,
                             'posthoc_followup':posthoc_followup,
                             'baseline_quality':baseline_summary.get('quality')})
    write(root/'metric-integrity.json',[{k:p[k] for k in ('round','level','phase','raw_events_sha256','raw_usage_verified')} for p in phases])
    write(root/'controls.json',controls)
    for name,data in [('trials.csv',trials),('phases.csv',phases)]:
        with (root/name).open('w',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=list(data[0]));writer.writeheader();writer.writerows(data)
    comparison=[]
    for row in summaries:
        for key in METRICS:
            comparison.append({'level':row['level'],'metric':key,'baseline_n':row['baseline_n'],'baseline':row['baseline'][key],
                **row['statistics'][key],'mean_change_percent':row['mean_change_percent'][key]})
    with (root/'comparison.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(comparison[0]));writer.writeheader();writer.writerows(comparison)
    print(json.dumps({'levels':summaries,'totals':total},indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('directory',type=Path);args=parser.parse_args();summarize(args.directory)
