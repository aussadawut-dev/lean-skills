"""Resolve local application modules for copied probes only; no model changes."""
import json, os, runpy, subprocess, sys
from pathlib import Path
root=Path(__file__).resolve().parent
names=set(json.loads((root/'manifest.json').read_text())['known_quality_probes'])
names.update(('account_scope_trace.py','dollar_identifier_probe.py','error_boundary_probe.py'))
original=subprocess.run
def run(args,*a,**kw):
    if isinstance(args,(tuple,list)) and len(args)==4 and args[:2]==[sys.executable,'-B']:
        script=Path(args[2]);workspace=Path(args[3])
        if script.parent==root and script.name in names and workspace.is_dir():
            kw['env']={**kw.get('env',os.environ),'PYTHONPATH':str(workspace)}
    return original(args,*a,**kw)
subprocess.run=run
if __name__=='__main__':
    runpy.run_path(str(root/'continue-after-timeout.py'),run_name='__main__')
