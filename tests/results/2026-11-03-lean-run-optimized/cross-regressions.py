"""Run both retained regression suites against the other final implementation.
Coordinator-only supplemental evidence; no model tokens or trial modifications.
"""
import json, shutil, subprocess, sys, tempfile, time
from pathlib import Path
BASE=Path(__file__).resolve().parent
old=Path(json.loads((BASE/'metadata.json').read_text())['baseline_archive'])
for level in sys.argv[1:]:
    new_work=BASE/level/'workspace'
    old_work=old/level/('final-workspace' if level=='critical' else 'workspace')
    results=[]
    for name,application,tests in [('old_tests_on_new_code',new_work,old_work),('new_tests_on_old_code',old_work,new_work)]:
        with tempfile.TemporaryDirectory(prefix='lean-cross-regressions-') as temp:
            target=Path(temp)
            for source in application.glob('*.py'):
                if not source.name.startswith('test_'): shutil.copyfile(source,target/source.name)
            for source in tests.glob('test_*.py'): shutil.copyfile(source,target/source.name)
            started=time.perf_counter()
            p=subprocess.run([sys.executable,'-B','-m','unittest','discover','-v'],cwd=target,capture_output=True,text=True,timeout=120)
            (BASE/level/(name+'.log')).write_text(p.stdout+p.stderr)
            results.append({'direction':name,'exit_code':p.returncode,'elapsed_seconds':round(time.perf_counter()-started,3),'application_source':str(application),'tests_source':str(tests),'log':name+'.log'})
    (BASE/level/'cross-regressions.json').write_text(json.dumps(results,indent=2)+'\n')
    print(level,json.dumps(results),flush=True)
