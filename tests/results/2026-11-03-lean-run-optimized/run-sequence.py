"""Sequential frozen trials. Halt for coordinator assessment on any failure."""
import importlib.util, json, subprocess, sys, time
from pathlib import Path
BASE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('benchmark', BASE/'harness-at-prepare.py')
b=importlib.util.module_from_spec(spec); spec.loader.exec_module(b)
old=Path(json.loads((BASE/'metadata.json').read_text())['baseline_archive'])
def status(level,phase,state):
    (BASE/'progress.json').write_text(json.dumps({'level':level,'phase':phase,'state':state,'unix':time.time()},indent=2)+'\n')
    print(level,phase,state,flush=True)
def result(phase):
    m=json.loads(phase.joinpath('metrics.json').read_text())
    if m['exit_code'] or m['timed_out'] or m['usage'] is None: raise RuntimeError('Incomplete measured phase: '+str(phase))
for level in b.LEVELS:
    trial=BASE/level
    status(level,'implementation','RUNNING')
    b.run(BASE,level,'implementation',900,'gpt-6-astra','max'); result(trial/'implementation')
    grade=b.grade(BASE,level,'post-implementation')
    b.prepare_review(BASE,level)
    assert (trial/'review-prompt.txt').read_bytes()==(old/level/'review-prompt.txt').read_bytes()
    status(level,'review','RUNNING')
    b.run(BASE,level,'review',900,'gpt-6-astra','max'); result(trial/'review')
    before=json.loads((trial/'review-initial-hashes.json').read_text()); after=b.digest_tree(trial/'reviewspace')
    integrity={'unchanged':before==after,'changed':[k for k in set(before)|set(after) if before.get(k)!=after.get(k)]}
    (trial/'review-integrity.json').write_text(json.dumps(integrity,indent=2)+'\n')
    review_text=(trial/'review/final.txt').read_text().strip()
    if review_text.startswith('```'): review_text='\n'.join(review_text.splitlines()[1:-1])
    review=json.loads(review_text)
    supplemental=0
    if level=='critical':
        p=subprocess.run([sys.executable,'-B',str(BASE/'supplemental_probe.py'),str(trial/'workspace')],capture_output=True,text=True,check=True)
        (trial/'supplemental-post-implementation.json').write_text(p.stdout)
        supplemental=json.loads(p.stdout)['issue_count']
    if grade['issues'] or grade['protected_files_changed'] or not integrity['unchanged'] or review['status']!='PASS' or review['findings'] or supplemental:
        status(level,'assessment','NEEDS_COORDINATOR'); sys.exit(2)
    status(level,'assessment','AWAITING_COORDINATOR_CLOSE')
status('all','first-pass','COMPLETE')
