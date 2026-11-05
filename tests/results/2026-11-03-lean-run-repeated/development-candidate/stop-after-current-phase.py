import json,os,signal,subprocess,time
from pathlib import Path
base=Path('/private/var/folders/1j/hzh7y3gn7yl8648zpkw4rvbw0000gn/T/lean-run-cohort-20261103-c1ze4zc_/cohort')
target=Path('/private/var/folders/1j/hzh7y3gn7yl8648zpkw4rvbw0000gn/T/lean-run-cohort-20261103-c1ze4zc_/cohort/round-1/critical/implementation/metrics.json')
parent=11800
while not target.exists(): time.sleep(0.05)
while True:
 try:
  metrics=json.loads(target.read_text());break
 except (ValueError,OSError):time.sleep(0.01)
command=subprocess.check_output(['ps','-o','command=','-p',str(parent)],text=True)
if 'runner-frozen.py run' in command and str(base) in command:
 os.kill(parent,signal.SIGINT)
 (base/'development-stop.json').write_text(json.dumps({'reason':'Known log truncation metadata defect and duplicate successful-log reads; revise before final nine-trial validation','stopped_after_metrics':str(target.relative_to(base)),'measured_phase_preserved':True,'phase_usage_known':metrics.get('usage') is not None,'unix':time.time()},indent=2)+'\n')
 print('Stopped coordinator after completed measured phase; no model phase interrupted.',flush=True)
