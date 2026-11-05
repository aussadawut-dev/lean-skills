"""Resolve concrete name-resolution anomalies printed before repair-1 timeout."""
import hashlib
import importlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import critical_final_findings_probe as helper
workspace=Path(sys.argv[1]).resolve()
sys.path.insert(0,str(workspace));vault=importlib.import_module('vault')
results=[]
with tempfile.TemporaryDirectory(prefix='lean-native-resolution-') as temp:
    for name,view,native_value in (
        ('cte','WITH pragma_recursive_triggers(recursive_triggers) AS (VALUES(7)) SELECT * FROM pragma_recursive_triggers',7),
        ('qualified','SELECT main.pragma_recursive_triggers.recursive_triggers FROM main.pragma_recursive_triggers()',0)):
        for operator,valid in (('<>',True),('=',False)):
            sql=f"CREATE VIEW saved_mode AS {view}; CREATE TRIGGER guard BEFORE INSERT ON audit WHEN (SELECT recursive_triggers FROM saved_mode){operator}{native_value} BEGIN SELECT RAISE(ABORT,'native guard'); END;"
            results.append(helper.run_case(vault,workspace,Path(temp),name+('-valid' if valid else '-abort'),'name-resolution',sql,77,valid,valid))
failed=[case['case'] for case in results if case['failures']]
print(json.dumps({'source_sha256':hashlib.sha256((workspace/'vault.py').read_bytes()).hexdigest(),'cases':results,'failed_cases':len(failed),'failed_case_names':failed,'finding_groups':{'name_resolution':bool(failed)}},indent=2))
raise SystemExit(bool(failed))
