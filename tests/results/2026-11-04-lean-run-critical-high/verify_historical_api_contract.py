"""Rerun retained historical suites with known non-contractual API error labels relaxed."""
import difflib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

root=Path(__file__).resolve().parent
round_number,index=map(int,sys.argv[1:])
trial=root/f'round-{round_number}'/'critical'
archive=Path(json.loads((root/'manifest.json').read_text())['baseline_archive'])
logs=[]
for previous in (1,2,3):
    old=archive/f'round-{previous}'/'critical'/'workspace'
    with tempfile.TemporaryDirectory(prefix='lean-api-contract-only-') as temporary:
        workspace=Path(temporary)
        for source in (trial/'workspace').glob('*.py'):
            if not source.name.startswith('test_'):
                shutil.copyfile(source,workspace/source.name)
        changes=[]
        for source in sorted(old.glob('test_*.py')):
            original=source.read_text()
            updated=original.replace("'^unexpected transfer effects$'","'^unexpected (?:transfer|storage) effects$'")
            updated=re.sub(r"assertRaisesRegex\(ValueError, '(key conflict|account unavailable|account not found)'\)",
                           r"assertRaisesRegex(ValueError, '^(?:\1|invalid request)$')",updated)
            function=re.search(r'(?m)^    def test_integer_boundaries_are_exact_and_overflow_is_rejected\([^\n]*\n[\s\S]*?(?=^    def |\Z)',updated)
            if function:
                block=function.group()
                replaced=block.replace('with self.assertRaises(ValueError):',
                                       'with self.assertRaises((ValueError, OverflowError)):')
                updated=updated[:function.start()]+replaced+updated[function.end():]
            (workspace/source.name).write_text(updated)
            changes.extend(difflib.unified_diff(original.splitlines(keepends=True),updated.splitlines(keepends=True),
                                               fromfile=source.name,tofile=source.name))
        result=subprocess.run([sys.executable,'-B','-m','unittest','discover','-v'],cwd=workspace,
                              capture_output=True,text=True,timeout=120)
    log=f'assessment-{index}-baseline-{previous}-contract-only.log'
    (trial/log).write_text(result.stdout+result.stderr)
    diff=f'assessment-{index}-baseline-{previous}-contract-only.diff'
    (trial/diff).write_text(''.join(changes))
    logs.append(dict(baseline_round=previous,exit_code=result.returncode,log=log,assertion_diff=diff))
    print(previous,result.returncode, (result.stdout+result.stderr).splitlines()[-3:])
(trial/f'assessment-{index}-historical-api-contract.json').write_text(json.dumps(logs,indent=2)+'\n')
raise SystemExit(any(row['exit_code'] for row in logs))
