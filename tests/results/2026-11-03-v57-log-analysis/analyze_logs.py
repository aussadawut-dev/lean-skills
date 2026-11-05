"""Derive trace counts and token deltas without model calls or token estimates.

Only turn.completed.usage supplies token counts. Command-output characters and
native CLI invocation counts are separate trace descriptors, not token charges.
"""
from collections import Counter
import csv
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
import shlex

ROOT=Path(__file__).resolve().parents[3]
OUT=Path(__file__).resolve().parent
SOURCES={
    'v57':ROOT.parent/'lean-workflow-agent-by-asdw/docs/benchmarks/2026-11-03-three-level-v5.7',
    'lean_original':ROOT/'tests/results/2026-11-03-level-benchmark',
    'lean_optimized':ROOT/'tests/results/2026-11-03-lean-run-optimized',
}

def write_json(name,value): (OUT/name).write_text(json.dumps(value,indent=2)+'\n')
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def shell_body(command):
    try:
        args=shlex.split(command)
        if len(args)==3 and args[1] in ('-lc','-c'): return args[2]
    except ValueError: pass
    return command

phases=[];commands=[];native=Counter();native_help=Counter();identities=[]
for variant,root in SOURCES.items():
    for level in ('medium','high','critical'):
        for path in sorted((root/level).glob('*/metrics.json')):
            metrics=json.loads(path.read_text());log=path.parent/'events.jsonl'
            if not log.exists(): continue
            events=[json.loads(line) for line in log.read_text().splitlines() if line.strip()]
            usages=[e['usage'] for e in events if e.get('type')=='turn.completed' and 'usage' in e]
            usage={key:sum(u.get(key,0) for u in usages) for key in set().union(*(u.keys() for u in usages))}
            assert usage==metrics['usage'],path
            assert metrics['total_tokens']==usage['input_tokens']+usage['output_tokens']
            identities.append({'path':str(log),'sha256':sha(log)})
            records=[]
            for line,event in enumerate(events,1):
                item=event.get('item',{})
                if event.get('type')!='item.completed' or item.get('type')!='command_execution':continue
                body=shell_body(item.get('command',''))
                # Avoid treating source strings inside a Python heredoc as shell
                # invocations. This intentionally undercounts dynamic invocations.
                shell_part=body.split('\n',1)[0] if '<<' in body.split('\n',1)[0] else body
                matches=re.findall(r'python(?:3(?:\.\d+)?)?(?:\s+-[A-Za-z]+)*\s+\.lean/bin/lean\s+([a-z-]+)([^;&\n]*)',shell_part)
                families=[m[0] for m in matches]
                is_help=bool(matches) and all('--help' in m[1] for m in matches)
                for family,tail in matches:
                    native[(variant,family)]+=1
                    if '--help' in tail:native_help[(variant,family)]+=1
                is_instruction_read=bool(re.match(r'\s*(?:cat|sed|rg|head|tail)\b',body) and re.search(r'(?:AGENTS\.md|CLAUDE\.md|CONTRACT\.md|PROJECT\.md|SKILL\.md|\.lean/(?:policy|README)|docs/tracking/(?:README|TEMPLATE))',body))
                record={'variant':variant,'level':level,'phase':metrics['phase'],'log':str(log),'line':line,
                    'command':body,'exit_code':item.get('exit_code'),
                    'output_characters':len(item.get('aggregated_output','')),
                    'native_cli_families':families,'native_cli_help_only':is_help,
                    'instruction_read_heuristic':is_instruction_read,
                    'mentions_tracker':bool(re.search(r'docs/tracking|\blean tracker\b',body)),
                    'command_note':'One completed command_execution event; may contain multiple shell commands.'}
                records.append(record);commands.append(record)
            assert len(records)==metrics['command_count']
            phases.append({'variant':variant,'level':level,'phase':metrics['phase'],
                'seconds':metrics['elapsed_seconds'], 'input_tokens':usage['input_tokens'],
                'cached_input_tokens':usage.get('cached_input_tokens',0),'output_tokens':usage['output_tokens'],
                'reasoning_output_tokens':usage.get('reasoning_output_tokens',0),
                'total_tokens':metrics['total_tokens'],
                'uncached_input_plus_output':metrics['total_tokens']-usage.get('cached_input_tokens',0),
                'command_records':len(records),
                'native_cli_command_records':sum(bool(r['native_cli_families']) for r in records),
                'native_cli_invocations_lower_bound':sum(len(r['native_cli_families']) for r in records),
                'native_cli_help_records':sum(r['native_cli_help_only'] for r in records),
                'instruction_read_records_heuristic':sum(r['instruction_read_heuristic'] for r in records),
                'instruction_read_output_characters':sum(r['output_characters'] for r in records if r['instruction_read_heuristic']),
                'all_command_output_characters':sum(r['output_characters'] for r in records),
                'tracker_file_change_events':sum(e.get('type')=='item.completed' and e.get('item',{}).get('type')=='file_change' and any('/docs/tracking/' in c['path'] for c in e['item'].get('changes',[])) for e in events),
                'metrics_file':str(path)})

fields=('seconds','input_tokens','cached_input_tokens','output_tokens','reasoning_output_tokens','total_tokens','uncached_input_plus_output','command_records','native_cli_command_records','native_cli_invocations_lower_bound','native_cli_help_records','instruction_read_records_heuristic','instruction_read_output_characters','all_command_output_characters','tracker_file_change_events')
totals={}
for variant in SOURCES:
    rows=[r for r in phases if r['variant']==variant]
    totals[variant]={field:round(sum(r[field] for r in rows),3) for field in fields}
    totals[variant]['measured_phases']=len(rows)
    totals[variant]['first_pass_command_records']=sum(r['command_records'] for r in rows if r['phase'] in ('implementation','review'))
    totals[variant]['first_pass_seconds']=round(sum(r['seconds'] for r in rows if r['phase'] in ('implementation','review')),3)
    totals[variant]['first_pass_tokens']=sum(r['total_tokens'] for r in rows if r['phase'] in ('implementation','review'))

old=totals['lean_original'];new=totals['v57'];delta={field:round(new[field]-old[field],3) for field in fields}
decomposition={'delta':delta,'input_share_of_total_token_increase_percent':round(delta['input_tokens']/delta['total_tokens']*100,3),
    'cached_input_share_of_total_token_increase_percent':round(delta['cached_input_tokens']/delta['total_tokens']*100,3),
    'uncached_input_plus_output_increase_percent':round((new['uncached_input_plus_output']/old['uncached_input_plus_output']-1)*100,3)}
write_json('command-inventory.json',commands)
write_json('source-identities.json',identities)
write_json('analysis.json',{'totals':totals,'v57_vs_original':decomposition,
    'native_cli_invocations_lower_bound':{variant:{family:count for (v,family),count in sorted(native.items()) if v==variant} for variant in SOURCES},
    'native_help_invocations':{variant:{family:count for (v,family),count in sorted(native_help.items()) if v==variant} for variant in SOURCES},
    'limitations':['Usage is phase-level, not per-command; no causal token amount is assigned to a command category.',
        'CLI regex excludes heredoc bodies and can miss dynamic subprocess calls; counts are lower bounds.',
        'Instruction-read counts are heuristic and can include mixed requirement/source reads; character counts are not tokens.',
        'One trial per version/level; policy/context and stated quality floors differ; caches/server load not controlled.',
        'Excluded invalid-setup pilot is not included in corrected workflow comparisons.']})
with (OUT/'phase-analysis.csv').open('w',newline='') as stream:
    writer=csv.DictWriter(stream,fieldnames=list(phases[0]));writer.writeheader();writer.writerows(phases)
current=ROOT/'skills/lean-run/SKILL.md';frozen=SOURCES['lean_optimized']/'medium/initial/.agents/skills/lean-run/SKILL.md'
write_json('current-skill-identity.json',{'checked_utc':datetime.now(UTC).isoformat(),'current_skill_sha256':sha(current),'optimized_benchmark_skill_sha256':sha(frozen),'matches':sha(current)==sha(frozen),'characters':len(current.read_text()),'optimized_benchmark_characters':len(frozen.read_text()),'current_target_skills':{name:sha(ROOT/'skills'/name/'SKILL.md') for name in ('lean-run','lean-task','lean-review','lean-gate')}})
print(json.dumps({'totals':totals,'decomposition':decomposition,'current_skill_matches_optimized':sha(current)==sha(frozen)},indent=2))
