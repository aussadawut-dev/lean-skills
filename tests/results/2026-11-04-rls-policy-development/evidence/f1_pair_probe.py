#!/usr/bin/env python3
"""Is the archived F1 expectation itself foreign-value dependent?

python3 -B f1_pair_probe.py ARCHIVE WORKSPACE
Replays the three critical_final_findings F1 trigger sets with the foreign
blue/private balance seeded as 77 (archived oracle) and as 78. If the API
outcome differs between the pair, the result reveals the foreign value.
"""
from contextlib import closing
import importlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile

archive, workspace = (Path(a).resolve() for a in sys.argv[1:3])
sys.path[:0] = [str(archive), str(workspace)]
sys.dont_write_bytecode = True
probe = importlib.import_module('critical_final_findings_probe')
vault = importlib.import_module('vault')

extra = "UPDATE accounts SET balance=78 WHERE tenant='blue' AND name='private';"
CASES = {
    'f1_foreign_corruption': probe.EARLY_RESTORE + probe.TOUCH_FOREIGN.format(extra=extra),
    'f1_nested_restore': probe.EARLY_RESTORE + probe.TOUCH_FOREIGN.format(extra=''),
    'f1_plain_restore_control': probe.TOUCH_FOREIGN.format(extra=''),
}

report, leaks = {}, []
with tempfile.TemporaryDirectory(prefix='f1-pair-') as directory:
    for name, sql in CASES.items():
        row = report[name] = {}
        for foreign in (77, 78):
            for entry in ('native', 'api'):
                path = Path(directory) / f'{name}-{foreign}-{entry}.db'
                vault.init_db(path)
                with closing(sqlite3.connect(path)) as con, con:
                    con.executemany('INSERT INTO accounts VALUES (?,?,?)',
                                    [('red', 'a', 100), ('red', 'b', 20), ('blue', 'private', foreign)])
                    con.executescript(sql)
                result = probe.native(path) if entry == 'native' else probe.api(vault, path)
                after = probe.snapshot(path)['accounts']
                row[f'{entry}_{foreign}'] = [result['status'], dict(after)['blue'] if False else
                                             [r for r in after if r[0] == 'blue'][0][2]]
        if row['api_77'][0] != row['api_78'][0]:
            leaks.append(name)
print(json.dumps(dict(foreign_value_observable=leaks, cases=report), indent=1))
