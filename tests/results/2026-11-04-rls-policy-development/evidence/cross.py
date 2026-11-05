#!/usr/bin/env python3
"""Replay runner-frozen cross regressions: cross.py WORKSPACE...  (prints failing test ids)."""
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

R = Path('/Users/x10/Workspace/Me/Github/lean-skills/tests/results')
BASELINES = [R / '2026-11-04-lean-run-critical-high-pilot/round-1/critical/workspace'] + [
    R / f'2026-11-04-lean-run-critical-high/round-{n}/critical/workspace' for n in (1, 2, 3)]
GRADER = R / '2026-11-04-lean-run-in-source-budget/round-1/grader.py'


def run(application, tests):
    with tempfile.TemporaryDirectory(prefix='cross-') as tmp:
        target = Path(tmp)
        for source in application.glob('*.py'):
            if not source.name.startswith('test_'):
                shutil.copyfile(source, target / source.name)
        for source in tests.glob('test_*.py'):
            shutil.copyfile(source, target / source.name)
        p = subprocess.run([sys.executable, '-B', '-m', 'unittest', 'discover', '-v'], cwd=target,
                           capture_output=True, text=True, timeout=300)
    out = p.stdout + p.stderr
    fails = sorted(set(re.findall(r'^(?:FAIL|ERROR): (.+)$', out, re.M)))
    ran = re.search(r'Ran (\d+) tests', out)
    return p.returncode, ran.group(1) if ran else '?', fails


for ws in map(Path, sys.argv[1:]):
    print('==', ws.name)
    code, ran, fails = run(ws, ws)
    print(f'  own suite: exit={code} ran={ran} fails={len(fails)}')
    for f in fails:
        print('    ', f)
    for base in BASELINES:
        label = '/'.join(base.parts[-5:-2])
        for direction, app, tests in (('hist_on_cand', ws, base), ('cand_on_hist', base, ws)):
            code, ran, fails = run(app, tests)
            print(f'  {direction} {label}: exit={code} ran={ran} fails={len(fails)}')
            for f in fails:
                print('    ', f[:170])
