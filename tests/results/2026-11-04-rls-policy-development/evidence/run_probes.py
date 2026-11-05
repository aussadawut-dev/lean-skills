#!/usr/bin/env python3
"""Run the 23 archived probes against workspaces: run_probes.py ARCHIVE OUT WS..."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys

NAMES = ('supplemental after_trigger audit_followup preservation noop read_isolation ignored_update '
         'frame_followup trigger_compatibility dollar_identifier trigger_counter unicode_space '
         'trigger_separator malformed_effect storage_encoding trigger_ignore_scope recursive_setting '
         'critical_final_findings name_resolution in_source foreign_guard review2_guard final_guard').split()

archive, out = Path(sys.argv[1]), Path(sys.argv[2])
workspaces = [Path(w) for w in sys.argv[3:]]


def run(job):
    workspace, name = job
    target = out / workspace.name
    target.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, PYTHONPATH=str(workspace), PYTHONDONTWRITEBYTECODE='1')
    done = subprocess.run([sys.executable, '-B', str(archive / f'{name}_probe.py'), str(workspace)],
                          capture_output=True, text=True, timeout=900, cwd=workspace, env=env)
    (target / f'{name}.json').write_text(done.stdout)
    (target / f'{name}.err').write_text(done.stderr)
    try:
        report = json.loads(done.stdout)
    except ValueError:
        report = None
    # Same rule as repeated_benchmark.assess: exit 0 AND no reported failures.
    ok = (done.returncode == 0 and isinstance(report, dict)
          and report.get('issue_count', report.get('failed_cases')) == 0 and report.get('failed_cases', 0) == 0)
    return workspace.name, name, 0 if ok else (done.returncode or 99)


with ThreadPoolExecutor(8) as pool:
    results = list(pool.map(run, [(w, n) for w in workspaces for n in NAMES]))
summary = {}
for workspace, name, code in results:
    summary.setdefault(workspace, {})[name] = code
for workspace, codes in summary.items():
    failed = [n for n, c in codes.items() if c]
    print(workspace, f'pass={len(codes) - len(failed)}/{len(codes)}', 'failed=', failed)
(out / 'summary.json').write_text(json.dumps(summary, indent=1))
