#!/usr/bin/env python3
"""Row-level-security policy probe for the Critical tenant-transfer fixture.

python3 -B rls_policy_probe.py WORKSPACE   (exit 0 = PASS)

Policy decided 2026-11-04 (user, after the final F2/F1 contradiction was shown):
during a tenant's transfer, other tenants' accounts/transfers/audit rows behave as
if absent. Reads and writes of user SQL (triggers, views) never see or change them;
new rows for another tenant, or any effect beyond the expected transfer, reject
the whole transaction. This supersedes the reject-on-foreign-write expectations
of critical_final_findings_probe.py F1 and the historical tests that encode it,
because those expectations require outcomes that depend on foreign values.

Independent oracle: copy the database, delete foreign rows (triggers dropped and
restored), run SQLite natively, then apply the policy check in Python. Each
scenario runs with the foreign balance 777, 778 and with the foreign row absent;
API and CLI observations must be identical across that triple, match the oracle,
leave foreign rows byte- and rowid-identical, and keep the schema unchanged.
Documented out-of-scope channels (cross-tenant UNIQUE on value columns, storage
size, timing) are not asserted here.
"""
from contextlib import closing
import hashlib
import importlib
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile

TENANT, SOURCE, TARGET, AMOUNT, KEY = 'alpha', 'cash', 'savings', 10, 'k'
RECEIPT = dict(tenant=TENANT, key=KEY, source=SOURCE, target=TARGET, amount=AMOUNT)
TABLES = ('accounts', 'transfers', 'audit')
COUNTERS = "'c='||changes()||',t='||total_changes()||',l='||last_insert_rowid()"
UPSERT = """CREATE TRIGGER g BEFORE INSERT ON audit BEGIN
  {verb} INTO accounts VALUES('beta','private',0) ON CONFLICT(tenant,name)
  DO UPDATE SET balance=accounts.balance WHERE accounts.balance=777;
  SELECT CASE WHEN changes()=1 THEN RAISE(ABORT,'audit rule') END; END;"""
OBSERVE = """CREATE TRIGGER o BEFORE UPDATE ON {target} WHEN OLD.tenant='beta' AND OLD.balance=777
BEGIN SELECT RAISE(ABORT,'foreign balance'); END;
CREATE TRIGGER i AFTER INSERT ON audit BEGIN
  UPDATE accounts SET balance=balance WHERE tenant='beta' AND name='private'; END;"""
EARLY = """CREATE TRIGGER early BEFORE UPDATE ON accounts
WHEN OLD.tenant='beta' AND OLD.balance=778 AND NEW.balance=777
BEGIN UPDATE accounts SET balance=777 WHERE tenant=OLD.tenant AND name=OLD.name; END;"""
TOUCH = """CREATE TRIGGER touch AFTER INSERT ON audit BEGIN
  UPDATE accounts SET balance=778 WHERE tenant='beta' AND name='private';
  UPDATE accounts SET balance=777 WHERE tenant='beta' AND name='private'; {extra} END;"""
NATURAL = """CREATE TRIGGER n BEFORE INSERT ON audit WHEN (SELECT balance FROM accounts NATURAL JOIN
  (SELECT 'alpha' AS tenant,'cash' AS name))={t} BEGIN SELECT RAISE(ABORT,'local guard'); END;"""


def body(sql):
    return f'CREATE TRIGGER b AFTER INSERT ON audit BEGIN {sql} END;'


SCENARIOS = {
    'replace_upsert': UPSERT.format(verb='REPLACE'),
    'insert_or_replace_upsert': UPSERT.format(verb='INSERT OR REPLACE'),
    'qualified_update_trigger': OBSERVE.format(target='main.accounts'),
    'unqualified_update_trigger': OBSERVE.format(target='accounts'),
    'f1_net_change': EARLY + TOUCH.format(
        extra="UPDATE accounts SET balance=778 WHERE tenant='beta' AND name='private';"),
    'f1_nested_restore': EARLY + TOUCH.format(extra=''),
    'f1_plain_restore': TOUCH.format(extra=''),
    'foreign_balance_write': body("UPDATE accounts SET balance=0 WHERE tenant='beta';"),
    'foreign_storage_class': body("UPDATE accounts SET name=CAST(name AS BLOB) WHERE tenant='beta';"),
    'foreign_receipt_write': body("UPDATE transfers SET amount=0 WHERE tenant='beta';"),
    'foreign_delete': body("DELETE FROM accounts WHERE tenant='beta';"),
    'foreign_rowid_move': body("UPDATE accounts SET rowid=rowid+100 WHERE tenant='beta';"),
    'foreign_insert_or_ignore': body("INSERT OR IGNORE INTO accounts VALUES('beta','private',0);"),
    'foreign_delete_reinsert': body("DELETE FROM accounts WHERE tenant='beta' AND name='private'; "
                                    "INSERT INTO accounts VALUES('beta','private',777);"),
    'foreign_count_read': "CREATE TRIGGER r BEFORE INSERT ON audit WHEN "
                          "(SELECT count(*) FROM accounts)>2 BEGIN SELECT RAISE(ABORT,'count'); END;",
    'counters_after_foreign_noop': body("UPDATE accounts SET balance=balance WHERE tenant='beta'; "
                                        f"SELECT RAISE(ABORT,{COUNTERS});"),
    'counters_first_update': f"CREATE TRIGGER c BEFORE UPDATE ON accounts BEGIN SELECT RAISE(ABORT,{COUNTERS}); END;",
    'cross_tenant_unique_replace': "CREATE UNIQUE INDEX ub ON accounts(balance) WHERE balance>500;" + body(
        "INSERT OR REPLACE INTO accounts VALUES('alpha','tmp',777); DELETE FROM accounts WHERE name='tmp';"),
    'own_row_into_hidden_slot': body(f"UPDATE accounts SET rowid=3 WHERE tenant='alpha' AND name='{TARGET}';"),
    'own_extra_row': body("INSERT INTO accounts VALUES('alpha','extra',1);"),
    'local_natural_harmless': NATURAL.format(t=999),
    'local_natural_abort': NATURAL.format(t=90),
    'local_restore_noop': body(f"UPDATE accounts SET balance=1 WHERE tenant='alpha' AND name='{TARGET}'; "
                               f"UPDATE accounts SET balance=10 WHERE tenant='alpha' AND name='{TARGET}';"),
    'no_triggers': '',
}
VARIANTS = (777, 778, None)


def seed(path, vault, sql, foreign):
    vault.init_db(path)
    with closing(sqlite3.connect(path)) as con, con:
        con.executemany('INSERT INTO accounts VALUES (?,?,?)', [(TENANT, SOURCE, 100), (TENANT, TARGET, 0)])
        if foreign is not None:
            con.execute("INSERT INTO accounts(rowid,tenant,name,balance) VALUES (3,'beta','private',?)", (foreign,))
            con.execute("INSERT INTO transfers VALUES ('beta','old','private','x',5)")
            con.execute("INSERT INTO audit VALUES ('beta','old','private','x',5)")
        con.executescript(sql)


def state(path):
    with closing(sqlite3.connect(path)) as con:
        rows = {t: sorted(con.execute(f'SELECT rowid,typeof(tenant),tenant,* FROM {t}').fetchall(), key=repr)
                for t in TABLES}
        schema = con.execute('SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY type,name').fetchall()
    return rows, schema


def logical(rows, mine):
    keep = (lambda r: r[1] == 'text' and r[2] == TENANT) if mine else (lambda r: not (r[1] == 'text' and r[2] == TENANT))
    return {t: sorted((r[3:] if mine else r) for r in rows[t] if keep(r)) for t in TABLES}


def oracle(path, directory):
    """Native SQLite on the database without foreign rows, then the policy check."""
    copy = Path(directory) / ('oracle-' + path.name)
    shutil.copyfile(path, copy)
    with closing(sqlite3.connect(copy)) as con, con:
        triggers = con.execute("SELECT name,sql FROM sqlite_schema WHERE type='trigger'").fetchall()
        for name, _ in triggers:
            con.execute(f'DROP TRIGGER "{name}"')
        for table in TABLES:
            con.execute(f'DELETE FROM {table} WHERE (tenant=?) IS NOT 1', (TENANT,))
        for _, sql in triggers:
            con.execute(sql)
    before = logical(state(copy)[0], True)
    try:
        with closing(sqlite3.connect(copy)) as con, con:
            con.execute('BEGIN IMMEDIATE')
            con.execute('UPDATE accounts SET balance=90 WHERE tenant=? AND name=?', (TENANT, SOURCE))
            con.execute('UPDATE accounts SET balance=10 WHERE tenant=? AND name=?', (TENANT, TARGET))
            for table in ('transfers', 'audit'):
                con.execute(f'INSERT INTO {table} VALUES (?,?,?,?,?)', tuple(RECEIPT.values()))
    except sqlite3.Error as error:
        return 'rejected', str(error)
    rows = state(copy)[0]
    expected = dict(before)
    expected['accounts'] = sorted([(TENANT, SOURCE, 90), (TENANT, TARGET, 10)] +
                                  [r for r in before['accounts'] if r[1] not in (SOURCE, TARGET)])
    for table in ('transfers', 'audit'):
        expected[table] = sorted(before[table] + [tuple(RECEIPT.values())])
    others = {t: [r for r in rows[t] if not (r[1] == 'text' and r[2] == TENANT)] for t in TABLES}
    if logical(rows, True) != expected or any(others.values()):
        return 'rejected', 'policy'
    return 'success', None


def api(path, vault):
    try:
        return 'success', vault.transfer(path, TENANT, SOURCE, TARGET, AMOUNT, KEY)
    except sqlite3.Error as error:
        return 'rejected', str(error)
    except Exception as error:  # noqa: BLE001 - recorded as an interface failure
        return 'invalid', f'{type(error).__name__}: {error}'


def cli(path, workspace):
    run = subprocess.run([sys.executable, '-B', str(workspace / 'app.py'), str(path),
                          json.dumps(dict(op='transfer', **RECEIPT))],
                         cwd=workspace, capture_output=True, text=True, timeout=30)
    if run.returncode == 0 and not run.stderr:
        return 'success', json.loads(run.stdout)
    if run.returncode == 2 and not run.stdout:
        # The contract requires a generic JSON error, not specific wording.
        try:
            message = json.loads(run.stderr)
        except ValueError:
            message = None
        if (isinstance(message, dict) and isinstance(message.get('error'), str)
                and not any(marker in run.stderr.lower() for marker in
                            ('beta', 'private', '777', '778', 'traceback', 'select', 'update ', 'trigger'))):
            return 'rejected', None
    return 'invalid', [run.returncode, run.stdout, run.stderr]


def main():
    workspace = Path(sys.argv[1]).resolve()
    sys.path.insert(0, str(workspace))
    sys.dont_write_bytecode = True
    vault = importlib.import_module('vault')
    report, failures = {}, []
    with tempfile.TemporaryDirectory(prefix='rls-probe-') as directory:
        for name, sql in SCENARIOS.items():
            case = report[name] = {}
            seen = {'api': set(), 'cli': set()}
            for foreign in VARIANTS:
                label = 'absent' if foreign is None else str(foreign)
                for entry in ('api', 'cli'):
                    path = Path(directory) / f'{name}-{label}-{entry}.db'
                    seed(path, vault, sql, foreign)
                    expected_status, expected_error = oracle(path, directory)
                    rows_before, schema_before = state(path)
                    status, detail = api(path, vault) if entry == 'api' else cli(path, workspace)
                    rows_after, schema_after = state(path)
                    problems = []
                    if status != expected_status:
                        problems.append('status')
                    if entry == 'api' and status == 'rejected' and expected_error != 'policy' \
                            and detail != expected_error:
                        problems.append('native_error')
                    if status == 'success' and detail != RECEIPT:
                        problems.append('receipt')
                    if logical(rows_after, False) != logical(rows_before, False):
                        problems.append('foreign_rows_changed')
                    if schema_after != schema_before:
                        problems.append('schema')
                    if status != 'success' and rows_after != rows_before:
                        problems.append('partial_write')
                    if status == 'success' and entry == 'api' and api(path, vault) != (status, detail):
                        problems.append('replay')
                    seen[entry].add(json.dumps([status, detail if entry == 'api' else None], sort_keys=True))
                    case[f'{entry}_{label}'] = [status, detail if status != 'success' else 'receipt',
                                                expected_status, problems]
                    failures += [f'{name}:{entry}_{label}:{p}' for p in problems]
            for entry, observed in seen.items():
                if len(observed) != 1:
                    failures.append(f'{name}:{entry}:foreign_data_observable')
    print(json.dumps(dict(workspace=str(workspace), sqlite_version=sqlite3.sqlite_version,
                          source_sha256=hashlib.sha256((workspace / 'vault.py').read_bytes()).hexdigest(),
                          failed_cases=len(failures), failures=failures, cases=report), indent=1))
    return bool(failures)


if __name__ == '__main__':
    raise SystemExit(main())
