"""Preserve initial results and queue measured repairs for verified later findings."""
import hashlib
import json
from pathlib import Path
import shutil
import time

root = Path(__file__).resolve().parent
read = lambda path: json.loads(path.read_text())


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


assert read(root / 'progress.json')['state'] == 'COMPLETE', 'Initial nine trials must finish first'
assert not (root / 'followup-queued.json').exists(), 'Follow-up already queued'
initial = {}
affected = []
for number in range(1, 4):
    for level in ('medium', 'high', 'critical'):
        trial = root / f'round-{number}' / level
        result = read(trial / 'result.json')
        assert result['status'] == 'DONE'
        initial[f'round-{number}/{level}'] = result
        if not (trial / 'posthoc-review.json').exists():
            continue
        finding = read(trial / 'posthoc-review.json')
        assert finding['status'] == 'REWORK' and finding['findings']
        assert finding['source_sha256'] == hashlib.sha256((trial / 'workspace/vault.py').read_bytes()).hexdigest()
        assert result['final_assessment'] == 1 and result['repair_rounds'] == 0
        for name in ('result-before-posthoc.json', 'assessment-1-before-posthoc.json', 'repair-1-request.json'):
            assert not (trial / name).exists(), (trial, name)
        affected.append((trial, finding))

write(root / 'initial-cohort-results.json', initial)
for trial, finding in affected:
    shutil.copyfile(trial / 'result.json', trial / 'result-before-posthoc.json')
    shutil.copyfile(trial / 'assessment-1.json', trial / 'assessment-1-before-posthoc.json')
    assessment = read(trial / 'assessment-1.json')
    assessment['blockers'].append('posthoc_effect_validation')
    assessment['posthoc_review'] = 'posthoc-review.json'
    assessment['original_assessment_preserved'] = 'assessment-1-before-posthoc.json'
    write(trial / 'assessment-1.json', assessment)
    write(trial / 'repair-1-request.json', {'findings':finding['findings'], 'source':'posthoc-review.json'})
    (trial / 'result.json').unlink()

write(root / 'followup-queued.json', {'unix':time.time(), 'affected_trials':[str(t.relative_to(root)) for t,_ in affected],
    'model_phase_policy':'Frozen runner; same model/effort; repair and renewed independent review measured and included.'})
print(json.dumps({'queued':[str(t.relative_to(root)) for t,_ in affected]}))
