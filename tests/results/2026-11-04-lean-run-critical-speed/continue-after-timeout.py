"""Retain a timed-out implementation, grade/review its artifacts, continue the cohort.

No model controls, prompts, deadlines, task files or raw metrics are changed.
Unknown usage remains unknown; no timed-out implementation is relaunched.
"""
import importlib.util
import json
from pathlib import Path
import sys

root=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('frozen_runner',root/'runner-frozen.py')
c=importlib.util.module_from_spec(spec);spec.loader.exec_module(c)
original=c.run_phase


def annotate():
    for path in root.glob('round-*/*/result.json'):
        result=c.read(path);bad=[]
        for metric in path.parent.glob('*/metrics.json'):
            value=c.read(metric)
            if value['timed_out'] or value['usage'] is None:bad.append(metric.parent.name)
        if bad:
            result.setdefault('quality_status','PASS' if result['status'] in ('DONE','TIMEOUT') else 'FAILED')
            if result['status']=='DONE':result['status']='TIMEOUT'
            result['measurement_status']='INCOMPLETE_USAGE'
            result['incomplete_phases']=bad
            c.write(path,result)


def run_phase(base,b,number,level,phase):
    annotate()
    try:
        return original(base,b,number,level,phase)
    except RuntimeError:
        path=base/f'round-{number}'/level/phase/'metrics.json'
        if not path.exists():raise
        metric=c.read(path)
        if not metric['timed_out'] or phase.startswith('review'):raise
        notes_path=root/'timeout-acknowledgements.json'
        notes=c.read(notes_path) if notes_path.exists() else {}
        key=f'round-{number}/{level}/{phase}'
        notes[key]={'timed_out':True,'raw_exit_code':metric['exit_code'],
                    'elapsed_seconds':metric['elapsed_seconds'],'usage_known':metric['usage'] is not None,
                    'action':'Retain attempt; grade and independently review current artifacts. No implementation rerun.'}
        c.write(notes_path,notes)
        c.capture_logs(base/f'round-{number}'/level,phase,base/f'round-{number}'/level/'workspace')
        print(json.dumps({'acknowledged_timeout':key,'usage':'UNKNOWN','implementation_relaunched':False}),flush=True)


c.run_phase=run_phase
code=c.run(root)
annotate()
if code in (0,3):
    results=[c.read(p) for p in root.glob('round-*/*/result.json')]
    if any(value.get('measurement_status')=='INCOMPLETE_USAGE' for value in results):
        c.progress(root,3,'all','cohort','COMPLETE_WITH_INCOMPLETE_USAGE')
        code=4
sys.exit(code)
