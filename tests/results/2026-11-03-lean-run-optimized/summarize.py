"""Recompute usage and compare to the retained three-level baseline."""
import csv
import hashlib
import json
from pathlib import Path

BASE=Path(__file__).resolve().parent
META=json.loads((BASE/'metadata.json').read_text())
OLD=Path(META['baseline_archive'])
previous={v['level']:v for v in json.loads((OLD/'summary.json').read_text())['levels']}

def load(path):
    text=path.read_text().strip()
    if text.startswith('```'): text='\n'.join(text.splitlines()[1:-1])
    return json.loads(text)

def percent(before,after): return round(100*(before-after)/before,2)

def phases(base,level):
    out=[]
    for path in (base/level).glob('*/metrics.json'):
        m=load(path); raw=path.with_name('events.jsonl').read_bytes()
        events=[json.loads(line) for line in raw.decode().splitlines()]
        usages=[e['usage'] for e in events if e.get('type')=='turn.completed']
        actual={k:sum(u.get(k,0) for u in usages) for k in set().union(*(u.keys() for u in usages))}
        assert actual==m['usage'],path
        assert m['exit_code']==0 and not m['timed_out'] and usages,path
        assert m['total_tokens']==actual['input_tokens']+actual['output_tokens']
        commands=[e['item'] for e in events if e.get('type')=='item.completed' and e.get('item',{}).get('type')=='command_execution']
        m['tool_output_characters']=sum(len(c.get('aggregated_output','')) for c in commands)
        m['raw_events_sha256']=hashlib.sha256(raw).hexdigest()
        m['raw_usage_verified']=True
        out.append(m)
    return sorted(out,key=lambda m:m['started_unix'])

rows=[]; phase_rows=[]; integrity=[]; summaries=[]
for level in ('medium','high','critical'):
    trial=BASE/level; old=previous[level]; ms=phases(BASE,level)
    usage={k:sum(m['usage'].get(k,0) for m in ms) for k in set().union(*(m['usage'].keys() for m in ms))}
    total=usage['input_tokens']+usage['output_tokens']
    uncached=total-usage['cached_input_tokens']
    seconds=round(sum(m['elapsed_seconds'] for m in ms),3)
    first=[m for m in ms if m['phase'] in ('implementation','review')]
    first_seconds=round(sum(m['elapsed_seconds'] for m in first),3)
    first_tokens=sum(m['total_tokens'] for m in first)
    reviews=[m for m in ms if m['phase'].startswith('review')]
    first_review=load(trial/'review/final.txt'); final_review=load(trial/reviews[-1]['phase']/'final.txt')
    grade=load(trial/'final-grade.json'); cross=load(trial/'cross-regressions.json')
    assert grade['issues']==0 and not grade['protected_files_changed'],level
    assert final_review['status']=='PASS' and not final_review['findings'],level
    if not all(r['exit_code']==0 for r in cross):
        assessment=load(trial/'cross-assessment.json')
        assert assessment['distinct_contract_issues']==0 and assessment['raw_failure_preserved'],level
    if level=='critical': assert load(trial/'supplemental-final.json')['issue_count']==0
    record={'level':level,'status':'DONE','phase_names':[m['phase'] for m in ms],
        'measured_agent_seconds':seconds,'total_tokens':total,'usage':usage,
        'uncached_input_plus_output':uncached,'first_pass_agent_seconds':first_seconds,
        'first_pass_tokens':first_tokens,'first_review_issues':len(first_review['findings']),
        'final_review_issues':len(final_review['findings']),
        'repair_rounds':sum(m['phase'].startswith('repair') for m in ms),
        'final_issue_categories':grade['issues'],'contract_category_checks':grade['checks'],
        'workflow_span_seconds':round(ms[-1]['started_unix']+ms[-1]['elapsed_seconds']-ms[0]['started_unix'],3),
        'tool_output_characters':sum(m['tool_output_characters'] for m in ms)}
    summaries.append(record)
    rows.append({'level':level,'before_seconds':old['measured_agent_seconds'],'after_seconds':seconds,
        'time_reduction_percent':percent(old['measured_agent_seconds'],seconds),
        'before_total_tokens':old['total_tokens'],'after_total_tokens':total,
        'token_reduction_percent':percent(old['total_tokens'],total),
        'before_cached_input':old['usage']['cached_input_tokens'],'after_cached_input':usage['cached_input_tokens'],
        'before_uncached_input_plus_output':old['uncached_input_plus_output'],'after_uncached_input_plus_output':uncached,
        'uncached_reduction_percent':percent(old['uncached_input_plus_output'],uncached),
        'before_first_pass_seconds':old['first_pass_agent_seconds'],'after_first_pass_seconds':first_seconds,
        'before_first_pass_tokens':old['first_pass_tokens'],'after_first_pass_tokens':first_tokens,
        'before_first_review_issues':old['first_review_issues'],'after_first_review_issues':len(first_review['findings']),
        'before_final_review_issues':old['final_review_issues'],'after_final_review_issues':len(final_review['findings']),
        'before_repair_rounds':old['repair_rounds'],'after_repair_rounds':record['repair_rounds']})
    for m in ms:
        phase_rows.append({'level':level,'phase':m['phase'],'elapsed_seconds':m['elapsed_seconds'],
            'total_tokens':m['total_tokens'],'input_tokens':m['usage']['input_tokens'],
            'cached_input_tokens':m['usage']['cached_input_tokens'],'output_tokens':m['usage']['output_tokens'],
            'command_count':m['command_count'],'tool_output_characters':m['tool_output_characters']})
        integrity.append({'level':level,'phase':m['phase'],'raw_usage_verified':True,'raw_events_sha256':m['raw_events_sha256']})

totals={k:sum(r[k] for r in rows) for k in ('before_seconds','after_seconds','before_total_tokens','after_total_tokens','before_cached_input','after_cached_input','before_uncached_input_plus_output','after_uncached_input_plus_output','before_first_pass_seconds','after_first_pass_seconds','before_first_pass_tokens','after_first_pass_tokens','before_first_review_issues','after_first_review_issues','before_final_review_issues','after_final_review_issues','before_repair_rounds','after_repair_rounds')}
for k in ('before_seconds','after_seconds','before_first_pass_seconds','after_first_pass_seconds'):totals[k]=round(totals[k],3)
for name,before,after in [('time','before_seconds','after_seconds'),('token','before_total_tokens','after_total_tokens'),('uncached','before_uncached_input_plus_output','after_uncached_input_plus_output')]:
    totals[name+'_reduction_percent']=percent(totals[before],totals[after])
for filename,data in [('comparison.json',{'levels':rows,'totals':totals}),('summary.json',{'levels':summaries}),('metric-integrity.json',integrity)]:
    (BASE/filename).write_text(json.dumps(data,indent=2)+'\n')
for filename,data in [('comparison.csv',rows),('phases.csv',phase_rows)]:
    with (BASE/filename).open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(data[0]));w.writeheader();w.writerows(data)
print(json.dumps({'levels':rows,'totals':totals},indent=2))
