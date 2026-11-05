#!/usr/bin/env python3
"""Focused A/B/R3 replay: python3 -B abr3_probe.py ARCHIVE_DIR WORKSPACE.

A  = REPLACE UPSERT arm (final review F2-A; not covered by final_guard_probe.py)
B  = schema-qualified trigger target (F2-B) plus unqualified control
R3 = NATURAL JOIN tenant-local guard, harmless and aborting, direct and view-backed
Each foreign case runs on paired databases differing only in beta/private balance.
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
helper = importlib.import_module('foreign_guard_probe')
vault = importlib.import_module('vault')

A = """CREATE TRIGGER guard BEFORE INSERT ON audit BEGIN
  {verb} INTO accounts VALUES('beta','private',0)
  ON CONFLICT(tenant,name) DO UPDATE
    SET balance=accounts.balance WHERE accounts.balance=777;
  SELECT CASE WHEN changes()=1 THEN RAISE(ABORT,'audit rule') END;
END;"""
B = """CREATE TRIGGER observe BEFORE UPDATE ON {target}
WHEN OLD.tenant='beta' AND OLD.balance=777
BEGIN SELECT RAISE(ABORT,'foreign balance'); END;
CREATE TRIGGER invoke AFTER INSERT ON audit BEGIN
  UPDATE accounts SET balance=balance WHERE tenant='beta' AND name='private';
END;"""
NATURAL_DIRECT = """CREATE TRIGGER natural_guard BEFORE INSERT ON audit
WHEN (SELECT balance FROM accounts NATURAL JOIN
      (SELECT 'alpha' AS tenant,'cash' AS name))={t}
BEGIN SELECT RAISE(ABORT,'local guard'); END;"""
NATURAL_VIEW = """CREATE VIEW cash_view AS SELECT balance FROM accounts NATURAL JOIN
      (SELECT 'alpha' AS tenant,'cash' AS name);
CREATE TRIGGER natural_guard BEFORE INSERT ON audit
WHEN (SELECT balance FROM cash_view)={t}
BEGIN SELECT RAISE(ABORT,'local guard'); END;"""

# name -> (sql, foreign_pair?, expected local outcome)
CASES = {
    'A_replace_upsert': (A.format(verb='REPLACE'), True, None),
    'A_control_insert_or_replace': (A.format(verb='INSERT OR REPLACE'), True, None),
    'B_main_qualified': (B.format(target='main.accounts'), True, None),
    'B_control_unqualified': (B.format(target='accounts'), True, None),
    'R3_direct_harmless': (NATURAL_DIRECT.format(t=999), False, 'success'),
    'R3_direct_abort': (NATURAL_DIRECT.format(t=90), False, 'rejected'),
    'R3_view_harmless': (NATURAL_VIEW.format(t=999), False, 'success'),
    'R3_view_abort': (NATURAL_VIEW.format(t=90), False, 'rejected'),
}


def run(sql, balance, entry, directory, name):
    path = Path(directory) / f'{name}-{balance}-{entry}.db'
    vault.init_db(path)
    with closing(sqlite3.connect(path)) as con, con:
        con.executemany('INSERT INTO accounts VALUES (?,?,?)', [
            ('alpha', 'cash', 100), ('alpha', 'savings', 0), ('beta', 'private', balance)])
        con.executescript(sql)
    call = {'native': helper.native, 'api': lambda p: helper.api(p, vault),
            'cli': lambda p: helper.cli(p, workspace)}[entry]
    return helper.check(path, call, helper.snapshot(path), entry, balance)


def main():
    report, failed = {}, []
    with tempfile.TemporaryDirectory(prefix='abr3-') as directory:
        for name, (sql, pair, expected) in CASES.items():
            row = report[name] = {}
            for balance in ((777, 778) if pair else (777,)):
                for entry in ('native', 'api', 'cli'):
                    r = run(sql, balance, entry, directory, name)
                    row[f'{entry}_{balance}'] = (r['status'], r.get('error'), r['state_pass'])
                    if not r['state_pass']:
                        failed.append(f'{name}:{entry}_{balance}:state')
            if pair:
                for entry in ('api', 'cli'):
                    if row[f'{entry}_777'][:2] != row[f'{entry}_778'][:2]:
                        failed.append(f'{name}:{entry}:foreign_value_observable')
            else:
                for entry in ('native', 'api', 'cli'):
                    if row[f'{entry}_777'][0] != expected:
                        failed.append(f'{name}:{entry}:local_outcome')
    print(json.dumps(dict(sqlite=sqlite3.sqlite_version, failed=failed, cases=report), indent=1))
    return bool(failed)


if __name__ == '__main__':
    raise SystemExit(main())
