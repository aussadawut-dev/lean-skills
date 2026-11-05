"""Continue after retained write-phase timeout; never relaunch the timed-out phase."""
import importlib.util
import json
from pathlib import Path
import sys
root=Path(sys.argv[1]).resolve()
spec=importlib.util.spec_from_file_location('frozen_runner',root/'runner-frozen.py')
runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
original=runner.run_phase

def retained_phase(root,b,number,level,phase):
    trial=root/f'round-{number}'/level
    path=trial/phase/'metrics.json'
    if path.exists():
        metric=runner.read(path)
        if metric['timed_out'] and not phase.startswith('review'):
            assert metric['exit_code']!=0 and metric['usage'] is None
            runner.capture_logs(trial,phase,trial/'workspace')
            runner.progress(root,number,level,phase,'TIMEOUT_RETAINED_FOR_INDEPENDENT_ASSESSMENT')
            return
    return original(root,b,number,level,phase)
runner.run_phase=retained_phase
raise SystemExit(runner.run(root))
