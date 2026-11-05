"""Offline independent control/mean audit; no model calls and no candidate writes."""
import csv
import hashlib
import json
from pathlib import Path
import statistics
import sys


def read(path):return json.loads(path.read_text())
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def digest(root):return {str(p.relative_to(root)):sha(p) for p in sorted(root.rglob('*'))
                         if p.is_file() and '__pycache__' not in p.parts}
def same(a,b):
    assert a==b if a is None or b is None else abs(a-b)<1e-6,(a,b)


root=Path(sys.argv[1]).resolve();manifest=read(root/'manifest.json')
baseline=Path(manifest['baseline_archive']);summary=read(root/'summary.json')
prior_hashes=read(baseline/'archive-sha256.json')
assert all(sha(baseline/name)==value for name,value in prior_hashes.items())
assert set(digest(baseline))==set(prior_hashes)|{'archive-sha256.json'}
assert sha(root/'harness-frozen.py')==manifest['harness_sha256']
metric_names=('measured_seconds','total_tokens','input_tokens','cached_input_tokens',
              'uncached_input_tokens','output_tokens','uncached_input_plus_output')
raw_trials=[];phase_intervals=[];unknown=[]
for number in (1,2,3):
    for level in ('medium','high','critical'):
        trial=root/f'round-{number}'/level;old=baseline/f'round-{number}'/level
        result=read(trial/'result.json');assert result['status'] in ('DONE','FAILED','TIMEOUT')
        initial=digest(trial/'initial');previous=digest(old/'initial')
        assert {k:v for k,v in initial.items() if not k.startswith('.agents/')}=={k:v for k,v in previous.items() if not k.startswith('.agents/')}
        assert (trial/'implementation/prompt.txt').read_bytes()==(old/'implementation/prompt.txt').read_bytes()
        assert (trial/'review/prompt.txt').read_bytes()==(old/'review/prompt.txt').read_bytes()
        assert (root/f'round-{number}/grader.py').read_bytes()==(baseline/f'round-{number}/grader.py').read_bytes()
        for folder in ('initial','workspace','reviewspace'):
            assert digest(trial/folder/'.agents/skills/lean-run')==manifest['skill_sha256']
        assessment=read(trial/f"assessment-{result['final_assessment']}.json")
        assert digest(trial/'workspace')==assessment['candidate_sha256']
        grade=read(trial/result['final_grade']);assert grade['issues']==0 and not grade['protected_files_changed']
        integrity=assessment['review_integrity'];assert not integrity['changed_or_removed'] and not integrity['unexpected_additions']
        rows=[]
        for path in trial.glob('*/metrics.json'):
            m=read(path);assert (m['requested_model'],m['requested_effort'])==('gpt-6-astra','max')
            events=[json.loads(line) for line in path.with_name('events.jsonl').read_text().splitlines()]
            usage=[e['usage'] for e in events if e.get('type')=='turn.completed' and 'usage' in e]
            phase={'measured_seconds':m['elapsed_seconds']}
            if usage:
                sums={k:sum(u.get(k,0) for u in usage) for k in set().union(*(u.keys() for u in usage))}
                assert sums==m['usage'];assert not m['timed_out'] and m['exit_code']==0
                phase.update(input_tokens=sums['input_tokens'],cached_input_tokens=sums['cached_input_tokens'],output_tokens=sums['output_tokens'])
                phase['total_tokens']=phase['input_tokens']+phase['output_tokens']
                phase['uncached_input_tokens']=phase['input_tokens']-phase['cached_input_tokens']
                phase['uncached_input_plus_output']=phase['uncached_input_tokens']+phase['output_tokens']
            else:
                assert m['usage'] is None and m['timed_out'] and m['exit_code']!=0
                phase.update({k:None for k in metric_names if k!='measured_seconds'})
                unknown.append(str(path.parent.relative_to(root)))
            rows.append(phase);phase_intervals.append((m['started_unix'],m['started_unix']+m['elapsed_seconds']))
        assert len(rows)==2+2*result['repair_rounds']
        totals={k:sum(p[k] for p in rows) if all(p[k] is not None for p in rows) else None for k in metric_names}
        totals.update(round=number,level=level);raw_trials.append(totals)
        reported=next(t for t in summary['trials'] if t['round']==number and t['level']==level)
        for key in metric_names:same(totals[key],reported[key])
for start_end,next_start_end in zip(sorted(phase_intervals),sorted(phase_intervals)[1:]):
    assert start_end[1]<=next_start_end[0]+0.05,(start_end,next_start_end)
for row in summary['levels']:
    cases=[t for t in raw_trials if t['level']==row['level']]
    assert len(cases)==row['candidate_n']==row['baseline_n']==3
    for key in metric_names:
        expected=statistics.mean(t[key] for t in cases) if all(t[key] is not None for t in cases) else None
        same(expected,row['statistics'][key]['mean'])
with (root/'comparison.csv').open(newline='') as stream:
    for entry in csv.DictReader(stream):
        level=next(v for v in summary['levels'] if v['level']==entry['level']);expected=level['statistics'][entry['metric']]['mean']
        assert entry['mean']=='' if expected is None else abs(float(entry['mean'])-expected)<1e-6
for name in manifest['known_quality_probes']:assert (root/name).read_bytes()==(baseline/name).read_bytes()
record={'status':'PASS','baseline_files_verified':len(prior_hashes),'trials_verified':len(raw_trials),
        'phase_count':len(phase_intervals),'sequential_phases_verified':True,'raw_usage_unknown_phases':unknown,
        'controls':'Original tasks/prompts/graders, all frozen skill copies, final source/review integrity, known probes and n=3 means/CSV independently verified.',
        'limit':'A control audit PASS does not imply benchmark quality PASS or complete telemetry.'}
(root/'control-audit.json').write_text(json.dumps(record,indent=2)+'\n')
print(json.dumps(record,indent=2))
