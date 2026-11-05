"""Bounded repair and fresh review with unchanged runtime controls."""
import importlib.util,json,shutil,subprocess,sys,time
from pathlib import Path
BASE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('benchmark',BASE/'harness-at-prepare.py');b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)
t=BASE/'critical';old=Path(json.loads((BASE/'metadata.json').read_text())['baseline_archive'])
def status(phase,state):
 (BASE/'progress.json').write_text(json.dumps({'level':'critical','phase':phase,'state':state,'unix':time.time()},indent=2)+'\n');print(phase,state,flush=True)
def verify(phase):
 m=json.loads((t/phase/'metrics.json').read_text());assert m['exit_code']==0 and not m['timed_out'] and m['usage']
status('repair-1','RUNNING');b.run(BASE,'critical','repair-1',900,'gpt-6-astra','max');verify('repair-1')
b.grade(BASE,'critical','post-repair-1')
p=subprocess.run([sys.executable,'-B',str(BASE/'supplemental_probe.py'),str(t/'workspace')],capture_output=True,text=True,check=True)
(t/'supplemental-post-repair-1.json').write_text(p.stdout)
subprocess.run([sys.executable,'-B',str(BASE/'cross-regressions.py'),'critical'],check=True)
(t/'reviewspace').rename(t/'reviewspace-first')
for name in ('review-initial-hashes.json','review-prompt.txt'):
 shutil.copyfile(t/name,t/('first-'+name))
b.prepare_review(BASE,'critical')
pre=t/'reviewspace/.pre-repair';pre.mkdir()
for source in (t/'first-pass-workspace').glob('*.py'):shutil.copyfile(source,pre/source.name)
(t/'review-2-initial-hashes.json').write_text(json.dumps(b.digest_tree(t/'reviewspace'),indent=2)+'\n')
finding=json.loads((t/'review/final.txt').read_text())['findings'][0]
prior=(old/'critical/review-2/prompt.txt').read_text();prefix=prior.split('{',1)[0]
(t/'review-prompt.txt').write_text(prefix+json.dumps(finding,indent=2)+'\n')
status('review-2','RUNNING');b.run(BASE,'critical','review-2',900,'gpt-6-astra','max');verify('review-2')
before=json.loads((t/'review-2-initial-hashes.json').read_text());after=b.digest_tree(t/'reviewspace')
(t/'review-2-integrity.json').write_text(json.dumps({'unchanged':before==after,'changed':[k for k in set(before)|set(after) if before.get(k)!=after.get(k)]},indent=2)+'\n')
status('assessment','AWAITING_COORDINATOR_CLOSE')
