"""Verify raw usage and summarize all nine opt-in trials; no model calls."""
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
    return {'n':len(values),'mean':statistics.mean(values),'median':statistics.median(values),
            'sample_sd':statistics.stdev(values) if len(values)>1 else None,'min':min(values),'max':max(values)}


def usage_for_phase(path):
    metrics=read(path);raw=path.with_name('events.jsonl').read_bytes()
    events=[json.loads(line) for line in raw.decode().splitlines()]
    usages=[e['usage'] for e in events if e.get('type')=='turn.completed' and 'usage' in e]
    if not usages:raise ValueError('Missing usage is unknown, not zero: '+str(path))
    usage={k:sum(v.get(k,0) for v in usages) for k in set().union(*(v.keys() for v in usages))}
    assert usage==metrics['usage'],path
    assert usage['cached_input_tokens']<=usage['input_tokens'],path
    assert metrics['total_tokens']==usage['input_tokens']+usage['output_tokens'],path
    assert metrics['exit_code']==0 and not metrics['timed_out'],path
    commands=[e['item'] for e in events if e.get('type')=='item.completed' and e.get('item',{}).get('type')=='command_execution']
    logs=read(path.with_name('captured-logs.json'))
    return {'phase':metrics['phase'],'started_unix':metrics['started_unix'],'measured_seconds':metrics['elapsed_seconds'],
            **{k:usage[k] for k in ('input_tokens','cached_input_tokens','output_tokens')},
            'uncached_input_tokens':usage['input_tokens']-usage['cached_input_tokens'],
            'uncached_input_plus_output':usage['input_tokens']-usage['cached_input_tokens']+usage['output_tokens'],
            'total_tokens':metrics['total_tokens'],'command_count':len(commands),
            'tool_output_characters':sum(len(c.get('aggregated_output','')) for c in commands),
            'captured_log_count':sum('archived' in v for v in logs),
            'unavailable_log_count':sum('archived' not in v for v in logs),
            'raw_events_sha256':hashlib.sha256(raw).hexdigest(),'raw_usage_verified':True}


def digest(path):
    return {str(p.relative_to(path)):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(path.rglob('*')) if p.is_file() and '__pycache__' not in p.parts}


def summarize(root):
    root=root.resolve();manifest=read(root/'manifest.json');baseline=Path(manifest['baseline_archive'])
    old={v['level']:v for v in read(baseline/'summary.json')['levels']}
    trials=[];phases=[];controls=read(root/'controls.json')
    for number in range(1,4):
        for level in ('medium','high','critical'):
            trial=root/f'round-{number}'/level;result=read(trial/'result.json')
            assert result['status'] in ('DONE','FAILED'),trial
            assessment=read(trial/f"assessment-{result['final_assessment']}.json")
            assert digest(trial/'workspace')==assessment['candidate_sha256'],trial
            grade=read(trial/result['final_grade'])
            passed=result['status']=='DONE'
            assert result['final_review_issues']==len(assessment['review']['findings']),trial
            if passed:
                assert grade['issues']==0 and not grade['protected_files_changed'],trial
                assert assessment['review']['status']=='PASS' and not assessment['review']['findings'],trial
            else:
                assert result['repair_rounds']==2 and assessment['blockers'],trial
            added_failures=0
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
            controls[f'round-{number}/{level}']['first_review_prompt_identical']=(trial/'review/prompt.txt').read_bytes()==(baseline/level/'review/prompt.txt').read_bytes()
            assert all(controls[f'round-{number}/{level}'].values())
            local=[]
            for path in trial.glob('*/metrics.json'):
                phase=usage_for_phase(path);phase.update(round=number,level=level);local.append(phase);phases.append(phase)
            local.sort(key=lambda p:p['started_unix'])
            assert len(local)==2+2*result['repair_rounds'],trial
            review_history=[len(read(trial/f'assessment-{index}.json')['review']['findings'])
                            for index in range(1,result['final_assessment']+1)]
            record={'round':number,'level':level,'status':result['status'],
                    **{k:sum(p[k] for p in local) for k in METRICS},
                    'phase_count':len(local),'repair_rounds':result['repair_rounds'],
                    'first_review_issues':result['initial_review_issues'],'final_review_issues':result['final_review_issues'],
                    'posthoc_review_issues':len(read(trial/'posthoc-review.json')['findings']) if (trial/'posthoc-review.json').exists() else 0,
                    'review_issue_history':review_history,'renewed_review_issues':sum(review_history[1:]),
                    'final_contract_categories':grade['checks'],'final_contract_issues':grade['issues'],
                    'changed_protected_files':len(grade['protected_files_changed']),
                    'final_added_probe_failed_cases':added_failures,
                    'final_original_supplemental_issues':assessment['supplemental_issue_count'] or 0,
                    'workflow_span_seconds':local[-1]['started_unix']+local[-1]['measured_seconds']-local[0]['started_unix'],
                    'first_pass_seconds':sum(p['measured_seconds'] for p in local if p['phase'] in ('implementation','review')),
                    'first_pass_uncached_input_plus_output':sum(p['uncached_input_plus_output'] for p in local if p['phase'] in ('implementation','review')),
                    'candidate_tests_on_historical_exit':assessment['cross'][1]['exit_code']}
            trials.append(record)
    summaries=[]
    for level in ('medium','high','critical'):
        cases=[t for t in trials if t['level']==level];prior=old[level]
        before={'measured_seconds':prior['measured_agent_seconds'],'total_tokens':prior['total_tokens'],
                'input_tokens':prior['usage']['input_tokens'],'cached_input_tokens':prior['usage']['cached_input_tokens'],
                'uncached_input_tokens':prior['usage']['input_tokens']-prior['usage']['cached_input_tokens'],
                'output_tokens':prior['usage']['output_tokens'],'uncached_input_plus_output':prior['uncached_input_plus_output']}
        stats={k:describe([t[k] for t in cases]) for k in METRICS}
        summaries.append({'level':level,'baseline_n':1,'candidate_n':3,'baseline':before,'statistics':stats,
            'mean_change_percent':{k:(stats[k]['mean']/before[k]-1)*100 for k in METRICS},
            'first_review_issues':[t['first_review_issues'] for t in cases],
            'posthoc_review_issues':[t['posthoc_review_issues'] for t in cases],
            'renewed_review_issues':[t['renewed_review_issues'] for t in cases],
            'final_review_issues':[t['final_review_issues'] for t in cases],
            'repair_rounds':[t['repair_rounds'] for t in cases]})
    total={'actual_nine_trial_consumption':{k:sum(t[k] for t in trials) for k in METRICS},
           'baseline_one_of_each_level':{k:sum(t['baseline'][k] for t in summaries) for k in METRICS},
           'candidate_sum_of_level_means':{k:sum(t['statistics'][k]['mean'] for t in summaries) for k in METRICS}}
    total['normalized_change_percent']={k:(total['candidate_sum_of_level_means'][k]/total['baseline_one_of_each_level'][k]-1)*100 for k in METRICS}
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
    quality={'status':'PASS' if all(t['status']=='DONE' for t in trials) else 'FAILED',
             'passed_trials':sum(t['status']=='DONE' for t in trials),
             'failed_trials':[f"round-{t['round']}/{t['level']}" for t in trials if t['status']=='FAILED'],
             'final_contract_issues':sum(t['final_contract_issues'] for t in trials),
             'final_independent_findings':sum(t['final_review_issues'] for t in trials),
             'final_original_supplemental_issues':sum(t['final_original_supplemental_issues'] for t in trials),
             'final_added_probe_failed_cases':sum(t['final_added_probe_failed_cases'] for t in trials)}
    medium=next(row for row in summaries if row['level']=='medium')
    target_checks={key:medium['mean_change_percent'][key]<0
                   for key in ('measured_seconds','uncached_input_tokens','uncached_input_plus_output')}
    target_checks['all_trial_quality_passed']=quality['status']=='PASS'
    target={'level':'medium','checks':target_checks,'met_in_observed_sample':all(target_checks.values()),
            'interpretation':'Descriptive n=3 versus historical n=1; no causal or statistical guarantee.'}
    write(root/'summary.json',{'levels':summaries,'totals':total,'trials':trials,
                             'optimization_target':target,'quality':quality,'quality_followup':followup})
    write(root/'metric-integrity.json',[{k:p[k] for k in ('round','level','phase','raw_events_sha256','raw_usage_verified')} for p in phases])
    write(root/'controls.json',controls)
    for name,data in [('trials.csv',trials),('phases.csv',phases)]:
        with (root/name).open('w',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=list(data[0]));writer.writeheader();writer.writerows(data)
    comparison=[]
    for row in summaries:
        for key in METRICS:
            comparison.append({'level':row['level'],'metric':key,'baseline_n':1,'baseline':row['baseline'][key],
                **row['statistics'][key],'mean_change_percent':row['mean_change_percent'][key]})
    with (root/'comparison.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(comparison[0]));writer.writeheader();writer.writerows(comparison)
    print(json.dumps({'levels':summaries,'totals':total},indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('directory',type=Path);args=parser.parse_args();summarize(args.directory)
