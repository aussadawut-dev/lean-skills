"""Retain old closure and apply the remaining repair after a demonstrated gap."""
from pathlib import Path
import hashlib,json,shutil
root=Path(__file__).resolve().parent;trial=root/'round-1/critical'
def read(path):return json.loads(path.read_text())
def write(path,value):path.write_text(json.dumps(value,indent=2)+'\n')
progress=read(root/'progress.json')
assert progress['state']=='NEEDS_COORDINATOR' and progress['round']==2 and progress['level']=='critical'
result=read(trial/'result.json');assert result['status']=='TIMEOUT' and result['quality_status']=='PASS' and result['repair_rounds']==1
counter=read(root/'round-1-final-before-counter-trigger-counter.json')
assert counter['failed_cases']==4 and counter['source_sha256']==hashlib.sha256((trial/'workspace/vault.py').read_bytes()).hexdigest()
assessment=trial/'assessment-2.json';a=read(assessment)
f={'id':'COORD-TRIGGER-COUNTER','severity':'MEDIUM','location':'_integrity.py effect observer bookkeeping','requirement':'Existing benign triggers retain observable SQLite behavior; valid public transfers succeed.','evidence':'A BEFORE credit trigger raises only if total_changes()!=1. Direct SQLite on the same schema accepts the two updates; new round-1 final API and CLI reject in both DELETE and WAL. Observer bookkeeping writes inflate the connection counter. See ../../round-1-final-before-counter-trigger-counter.json. Same diagnostic also fails all three prior finals.','suggested_fix':'Keep effect observation free of extra SQL row writes visible to existing triggers. Retain storage types, malformed-foreign-text isolation, no foreign SELECTs, hidden UNIQUE/rowid deletion tracking, ignored and unchanged replacements, and exact rollback/replay. Do not rewrite the user counter expression. Add a small public regression against the native control.'}
unicode=read(root/'round-1-final-before-unicode-space-unicode-space.json')
assert unicode['failed_cases']==4
unicode_f={'id':'COORD-UNICODE-SPACE-TRIGGER','severity':'MEDIUM','location':'_integrity.py trigger tokenizer','requirement':'Preserve valid stored SQLite triggers with all accepted unquoted identifiers.','evidence':'SQLite accepts a trigger whose name is U+00A0. When a valid identical replacement would suppress that existing DELETE trigger under native nonrecursive behavior, this candidate fires it and rejects the transfer. API/CLI reproduce in both DELETE/WAL; the quoted control succeeds. Same root cause independently found in round 2. See ../../round-1-final-before-unicode-space-unicode-space.json.','suggested_fix':'Use SQLite whitespace rules, not Python Unicode whitespace; preserve valid non-ASCII identifiers. Confirm the unquoted and quoted controls and still reject destructive replacements.'}
prior=trial/'assessment-2-before-counter.json';assert not prior.exists();shutil.copyfile(assessment,prior)
a['coordinator_findings']=[f,unicode_f];a['blockers'].append('coordinator_contract_finding');write(assessment,a)
write(trial/'posthoc-review.json',{'status':'REWORK','findings':[f,unicode_f],'method':'Independent native/API/CLI control, applied to all prior/new final candidates.'})
write(trial/'repair-2-request.json',{'findings':[f,unicode_f],'notes':'Final fix only. Revisit due to a demonstrated new bounded counter probe; preserve original cap and existing successful effect, trigger and scope checks.'})
write(trial/'assessment-2-coordinator.json',{'status':'REWORK','previous_assessment':prior.name,'reason':'New actual counter and Unicode-space compatibility failures; original closure retained.'})
(trial/'result.json').rename(trial/'result-before-counter-followup.json')
print('Round 1 reopened for its final allowed repair; original result and assessment retained.')
