#!/usr/bin/env python3
"""New equivalent forms not in any archived probe: variant_probe.py ARCHIVE WORKSPACE..."""
from contextlib import closing
import importlib
from pathlib import Path
import sqlite3
import sys
import tempfile

archive = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(archive))
sys.dont_write_bytecode = True
helper = importlib.import_module('foreign_guard_probe')

TAIL = "SELECT CASE WHEN changes()=1 THEN RAISE(ABORT,'audit rule') END;"
VARIANTS = {
    'upsert_target_alias': "INSERT INTO accounts AS a VALUES('beta','private',0) ON CONFLICT(tenant,name) "
                           "DO UPDATE SET balance=a.balance WHERE a.balance=777; " + TAIL,
    'update_target_alias': "UPDATE accounts AS a SET balance=a.balance WHERE a.tenant='beta' "
                           "AND a.name='private' AND a.balance=777; " + TAIL,
    'update_target_qualified_col': "UPDATE accounts SET balance=accounts.balance WHERE accounts.tenant='beta' "
                                   "AND accounts.name='private' AND accounts.balance=777; " + TAIL,
}

for ws in map(Path, sys.argv[2:]):
    ws = ws.resolve()
    for name in [m for m in sys.modules if m in ('vault', 'vault_guard')]:
        del sys.modules[name]
    sys.path.insert(0, str(ws))
    vault = importlib.import_module('vault')
    sys.path.remove(str(ws))
    print('==', ws.name)
    with tempfile.TemporaryDirectory() as tmp:
        for label, body in VARIANTS.items():
            outcomes = []
            for foreign in (777, 778):
                path = Path(tmp) / f'{ws.name}-{label}-{foreign}.db'
                vault.init_db(path)
                with closing(sqlite3.connect(path)) as con, con:
                    con.executemany('INSERT INTO accounts VALUES (?,?,?)',
                                    [('alpha', 'cash', 100), ('alpha', 'savings', 0), ('beta', 'private', foreign)])
                    try:
                        con.executescript(f'CREATE TRIGGER v BEFORE INSERT ON audit BEGIN {body} END;')
                    except sqlite3.Error as error:
                        outcomes.append(('not_valid_sqlite', str(error)))
                        break
                r = helper.api(path, vault)
                outcomes.append((r['status'], r.get('error')))
            leak = len(outcomes) == 2 and outcomes[0] != outcomes[1]
            print(f'  {label}: 777={outcomes[0]} 778={outcomes[-1]} {"LEAK" if leak else "ok"}')
