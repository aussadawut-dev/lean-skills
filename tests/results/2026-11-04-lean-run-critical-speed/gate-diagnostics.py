"""Read-only diagnostics for the Critical coordinator gate."""
from pathlib import Path
import json, subprocess, sys

root=Path(__file__).resolve().parent
number,index=map(int,sys.argv[1:]);trial=root/f'round-{number}/critical'
for probe in ('account_scope_trace','dollar_identifier_probe','error_boundary_probe','trigger_counter_probe','unicode_space_probe','trigger_separator_probe','malformed_effect_probe'):
    report=subprocess.run([sys.executable,'-B',str(root/(probe+'.py')),str(trial/'workspace')],capture_output=True,text=True,check=True,timeout=60)
    (trial/f'assessment-{index}-{probe}.json').write_text(report.stdout)
    result=json.loads(report.stdout)
    if probe=='account_scope_trace':
        print(probe, 'known patterns',result['demonstrated_patterns'])
        print('account lookups',list(dict.fromkeys(s for o in result['observations'] for s in o['account_lookup_sql'])))
    else:
        print(probe,'failed cases',result['failed_cases'])
