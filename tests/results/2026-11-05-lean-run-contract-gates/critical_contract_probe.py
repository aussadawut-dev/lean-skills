#!/usr/bin/env python3
"""Oracle-judged contract probe for the Critical tenant-transfer fixture.

python3 -B critical_contract_probe.py WORKSPACE   (exit 0 = PASS)

Each scenario installs schema changes and triggers, then runs one transfer
through the API and CLI. The expected outcome is not hand-written: an oracle
copies the database, removes other tenants' accounts/transfers/audit rows
(triggers suspended), restores the original trigger order and runs the four
transfer writes natively. The contract policy is then applied: the transfer is
rejected when the final ledger rows differ from the existing rows plus the
debit, credit, receipt and one audit row. Scenarios marked foreign run with the
other tenant's balance at 777, 778 and absent; observations must be identical.

Checked per run: status matches the oracle; a native SQLite error propagates
with its message; receipt and final own ledger rows match; side tables written
by triggers equal the oracle's; other tenants' rows keep their values and
storage types; schema is unchanged; a rejected run writes nothing; a successful
run replays exactly. Each failure names the contract clause.

Only contract-traceable properties fail the probe. The contract fixes ValueError
for malformed requests, funds and key conflicts and requires native SQLite errors
to propagate, but does not fix the exception type of a policy rejection, so
either ValueError or sqlite3.Error passes there. It does not mention physical
rowids, so moved foreign rowids are reported as an advisory observation.
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
LEDGER = ('accounts', 'transfers', 'audit')
COUNTERS = "'c='||changes()||',t='||total_changes()||',l='||last_insert_rowid()"
CLAUSES = {
    'status': 'final-effect rule / storage failure propagates',
    'native_error': 'storage/audit failure propagates',
    'receipt': 'receipt and exact replay',
    'own_rows': 'debit, credit, receipt and one audit row',
    'side_tables': 'trigger writes to other tables keep native behavior',
    'foreign_rows_changed': 'other tenants\' rows stay byte-identical',
    'schema': 'do not remove triggers; preserve schema',
    'partial_write': 'rejection without writes',
    'replay': 'exact replay returns the original receipt with no changes',
    'foreign_data_observable': 'no outcome may depend on other tenants\' rows',
    'interface': 'public API / CLI contract',
}


def body(sql, timing='AFTER INSERT ON audit'):
    return f'CREATE TRIGGER b {timing} BEGIN {sql} END;'


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
LEAK = ("CREATE TRIGGER leak BEFORE INSERT ON audit BEGIN SELECT CASE WHEN EXISTS(SELECT 1 FROM accounts "
        "WHERE tenant='beta') THEN RAISE(ABORT,(SELECT name||':'||balance FROM accounts WHERE tenant='beta')) END; END;")

# name -> (setup before seeding rows, trigger/view SQL, run with foreign triple, database encoding)
SCENARIOS = {
    # Read isolation through equivalent SQL forms (A/B/R3, F2).
    'replace_upsert': ('', UPSERT.format(verb='REPLACE'), True, None),
    'insert_or_replace_upsert': ('', UPSERT.format(verb='INSERT OR REPLACE'), True, None),
    'qualified_update_trigger': ('', OBSERVE.format(target='main.accounts'), True, None),
    'unqualified_update_trigger': ('', OBSERVE.format(target='accounts'), True, None),
    'renamed_tenant_column': ('ALTER TABLE accounts RENAME COLUMN tenant TO Tenant;', LEAK, True, None),
    'renamed_table_case': ('ALTER TABLE accounts RENAME TO staging; ALTER TABLE staging RENAME TO ACCOUNTS;',
                           LEAK, True, None),
    'foreign_count_read': ('', "CREATE TRIGGER r BEFORE INSERT ON audit WHEN (SELECT count(*) FROM accounts)>2 "
                               "BEGIN SELECT RAISE(ABORT,'count'); END;", True, None),
    'counters_after_foreign_noop': ('', body("UPDATE accounts SET balance=balance WHERE tenant='beta'; "
                                             f"SELECT RAISE(ABORT,{COUNTERS});"), True, None),
    'counters_first_update': ('', f"CREATE TRIGGER c BEFORE UPDATE ON accounts BEGIN SELECT RAISE(ABORT,{COUNTERS}); END;",
                              True, None),
    # Foreign writes: invisible rows are untouched; remaining foreign rows reject.
    'f1_net_change': ('', EARLY + TOUCH.format(
        extra="UPDATE accounts SET balance=778 WHERE tenant='beta' AND name='private';"), True, None),
    'f1_nested_restore': ('', EARLY + TOUCH.format(extra=''), True, None),
    'foreign_balance_write': ('', body("UPDATE accounts SET balance=0 WHERE tenant='beta';"), True, None),
    'foreign_receipt_write': ('', body("UPDATE transfers SET amount=0 WHERE tenant='beta';"), True, None),
    'foreign_history_delete': ('', body("DELETE FROM audit WHERE tenant='beta';"), True, None),
    'foreign_rowid_move': ('', body("UPDATE accounts SET rowid=rowid+100 WHERE tenant='beta';"), True, None),
    'foreign_insert_or_ignore': ('', body("INSERT OR IGNORE INTO accounts VALUES('beta','private',0);"), True, None),
    'foreign_delete_reinsert': ('', body("DELETE FROM accounts WHERE tenant='beta' AND name='private'; "
                                         "INSERT INTO accounts VALUES('beta','private',777);"), True, None),
    'transient_foreign_audit': ('CREATE UNIQUE INDEX ua ON audit(tenant,key);', body(
        "INSERT OR IGNORE INTO audit VALUES('beta','old','temporary','x',1); "
        "DELETE FROM audit WHERE tenant='beta' AND source='temporary';"), True, None),
    'transient_foreign_observed': ('CREATE TABLE observed(tenant,name,balance);', body(
        "INSERT INTO accounts VALUES('beta','transient',123); "
        "INSERT INTO observed SELECT tenant,name,balance FROM accounts WHERE tenant='beta'; "
        "DELETE FROM accounts WHERE tenant='beta';"), True, None),
    'cross_tenant_unique_replace':('CREATE UNIQUE INDEX ub ON accounts(balance) WHERE balance>500;', body(
        "INSERT OR REPLACE INTO accounts VALUES('alpha','tmp',777); DELETE FROM accounts WHERE name='tmp';"),
        True, None),
    'own_row_into_hidden_slot': ('', body(f"UPDATE accounts SET rowid=3 WHERE tenant='alpha' AND name='{TARGET}';"),
                                 True, None),
    # Required effects and storage failures.
    'own_extra_row': ('', body("INSERT INTO accounts VALUES('alpha','extra',1);"), True, None),
    'ignored_audit_insert': ('', "CREATE TRIGGER s BEFORE INSERT ON audit BEGIN SELECT RAISE(IGNORE); END;", False, None),
    'ignored_credit': ('', f"CREATE TRIGGER s BEFORE UPDATE ON accounts WHEN NEW.name='{TARGET}' "
                           "BEGIN SELECT RAISE(IGNORE); END;", False, None),
    'audit_abort': ('', "CREATE TRIGGER v AFTER INSERT ON audit BEGIN SELECT RAISE(ABORT,'audit veto'); END;", False, None),
    'erased_audit': ('', body("DELETE FROM audit WHERE key=NEW.key;"), False, None),
    'duplicate_audit': ('', body("INSERT INTO audit VALUES(NEW.tenant,NEW.key,NEW.source,NEW.target,NEW.amount);"),
                        False, None),
    'reversed_credit': ('', body(f"UPDATE accounts SET balance=balance-NEW.amount WHERE tenant=NEW.tenant AND "
                                 f"name=NEW.target;"), False, None),
    'trigger_performs_update': ('', "CREATE TRIGGER h BEFORE UPDATE ON accounts BEGIN UPDATE accounts SET "
                                    "balance=NEW.balance WHERE tenant=OLD.tenant AND name=OLD.name; "
                                    "SELECT RAISE(IGNORE); END;", False, None),
    'restored_noop': ('', body(f"UPDATE accounts SET balance=1 WHERE tenant='alpha' AND name='{TARGET}'; "
                               f"UPDATE accounts SET balance=10 WHERE tenant='alpha' AND name='{TARGET}';"), False, None),
    # Native trigger semantics over this tenant's rows.
    'trigger_order': ('', "CREATE TRIGGER z_skip AFTER INSERT ON audit BEGIN SELECT RAISE(IGNORE); END; "
                          "CREATE TRIGGER a_veto AFTER INSERT ON audit BEGIN SELECT RAISE(ABORT,'audit veto'); END;",
                      False, None),
    'trigger_order_reverse': ('', "CREATE TRIGGER a_veto AFTER INSERT ON audit BEGIN SELECT RAISE(ABORT,'audit veto'); "
                                  "END; CREATE TRIGGER z_skip AFTER INSERT ON audit BEGIN SELECT RAISE(IGNORE); END;",
                              False, None),
    'natural_join_harmless': ('', NATURAL.format(t=999), False, None),
    'natural_join_abort': ('', NATURAL.format(t=90), False, None),
    'side_table_rowid_shape': ('CREATE TABLE shape(tenant,name,balance,r); CREATE VIEW v AS SELECT *,rowid AS r FROM accounts;',
                               body("INSERT INTO shape SELECT * FROM v;"), True, None),
    'side_table_counters': ('CREATE TABLE seen(c,t,l); CREATE TABLE scratch(x);', body(
        "INSERT INTO seen VALUES(changes(),total_changes(),last_insert_rowid()); INSERT INTO scratch VALUES(1); "
        "INSERT INTO seen VALUES(changes(),total_changes(),last_insert_rowid());"), True, None),
    'multirow_ignore': ('CREATE TABLE obs(n,c,t); CREATE TABLE scratch(n INTEGER PRIMARY KEY); '
                        'INSERT INTO scratch VALUES (1),(2),(3);',
                        "CREATE TRIGGER skip BEFORE UPDATE ON scratch WHEN OLD.n<3 BEGIN SELECT RAISE(IGNORE); END; "
                        + body("UPDATE scratch SET n=n+10; INSERT INTO obs VALUES((SELECT group_concat(n) FROM scratch),"
                               "changes(),total_changes());"), False, None),
    'instead_of_view': ('CREATE TABLE log(x); CREATE VIEW mine AS SELECT name,balance FROM accounts;',
                        "CREATE TRIGGER io INSTEAD OF INSERT ON mine BEGIN INSERT INTO log VALUES(NEW.name); END; "
                        + body("INSERT INTO mine VALUES('x',1);"), False, None),
    'utf16_side_table': ('CREATE TABLE marks(t);', body("INSERT INTO marks SELECT name FROM accounts ORDER BY name;"),
                         True, 'UTF-16le'),
    'recursive_triggers_on': ('CREATE TABLE log(x);', "CREATE TRIGGER rec AFTER INSERT ON log WHEN NEW.x<3 BEGIN "
                              "INSERT INTO log VALUES(NEW.x+1); END; " + body("INSERT INTO log VALUES(1);"), False, None),
    'no_triggers': ('', '', True, None),
}
VARIANTS = (777, 778, None)


def seed(path, vault, setup, sql, foreign, encoding):
    if encoding:
        with closing(sqlite3.connect(path)) as con:
            con.execute(f"PRAGMA encoding='{encoding}'")
            con.execute('CREATE TABLE encoding_seed(x)')
    vault.init_db(path)
    with closing(sqlite3.connect(path)) as con, con:
        # Own rows are inserted first so their rowids are identical in every
        # variant; only the other tenant's rows differ between variants.
        con.executemany('INSERT INTO accounts VALUES (?,?,?)', [(TENANT, SOURCE, 100), (TENANT, TARGET, 0)])
        con.execute("INSERT INTO audit VALUES ('alpha','history','cash','savings',1)")
        if foreign is not None:
            con.execute("INSERT INTO accounts(rowid,tenant,name,balance) VALUES (3,'beta','private',?)", (foreign,))
            con.execute("INSERT INTO transfers VALUES ('beta','old','private','x',5)")
            con.execute("INSERT INTO audit VALUES ('beta','old','private','x',5)")
        con.executescript(setup)
        con.executescript(sql)


def ledger_names(con):
    names = {row[0].lower(): row[0] for row in con.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
    return {table: names[table] for table in LEDGER}


def state(path):
    with closing(sqlite3.connect(path)) as con:
        names = ledger_names(con)
        tables = [row[0] for row in con.execute(
            "SELECT name FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        rows = {}
        for table in tables:
            key = table.lower() if table.lower() in LEDGER else 'side:' + table
            columns = [row[1] for row in con.execute(f'PRAGMA table_info("{table}")')]
            typed = ','.join(f'typeof("{c}"),"{c}"' for c in columns)
            rid = 'rowid,' if key in LEDGER else ''
            rows[key] = sorted(con.execute(f'SELECT {rid}{typed} FROM "{table}"').fetchall(), key=repr)
        schema = con.execute('SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY type,name').fetchall()
    return rows, schema


def own(rows, mine=True, rowids=False):
    """Ledger rows split by tenant as typed value multisets (rowids only on request)."""
    out = {}
    for table in LEDGER:
        keep = [r for r in rows.get(table, []) if (r[1] == 'text' and r[2] == TENANT) == mine]
        out[table] = sorted((r if rowids else r[1:]) for r in keep)
    return out


def side(rows):
    return {k: v for k, v in rows.items() if k.startswith('side:')}


def oracle(path, directory):
    copy = Path(directory) / ('oracle-' + path.name)
    shutil.copyfile(path, copy)
    with closing(sqlite3.connect(copy)) as con, con:
        names = ledger_names(con)
        triggers = con.execute("SELECT name,sql FROM sqlite_schema WHERE type='trigger' ORDER BY rowid").fetchall()
        for name, _ in triggers:
            con.execute(f'DROP TRIGGER "{name}"')
        for table in LEDGER:
            con.execute(f'DELETE FROM "{names[table]}" WHERE (tenant=?) IS NOT 1', (TENANT,))
        for _, sql in triggers:
            con.execute(sql)
    before = own(state(copy)[0])
    try:
        with closing(sqlite3.connect(copy)) as con, con:
            con.execute('BEGIN IMMEDIATE')
            con.execute('UPDATE accounts SET balance=90 WHERE tenant=? AND name=?', (TENANT, SOURCE))
            con.execute('UPDATE accounts SET balance=10 WHERE tenant=? AND name=?', (TENANT, TARGET))
            for table in ('transfers', 'audit'):
                con.execute(f'INSERT INTO {table} VALUES (?,?,?,?,?)', tuple(RECEIPT.values()))
    except sqlite3.Error as error:
        return 'rejected', str(error), None
    rows = state(copy)[0]
    expected = {t: list(v) for t, v in before.items()}
    for name, old, new in ((SOURCE, 100, 90), (TARGET, 0, 10)):
        expected['accounts'].remove(('text', TENANT, 'text', name, 'integer', old))
        expected['accounts'].append(('text', TENANT, 'text', name, 'integer', new))
    receipt = ('text', TENANT, 'text', KEY, 'text', SOURCE, 'text', TARGET, 'integer', AMOUNT)
    for table in ('transfers', 'audit'):
        expected[table].append(receipt)
    expected = {t: sorted(v) for t, v in expected.items()}
    if own(rows) != expected or any(own(rows, False).values()):
        return 'rejected', 'policy', None
    return 'success', None, rows


def api(path, vault):
    try:
        return 'success', vault.transfer(path, TENANT, SOURCE, TARGET, AMOUNT, KEY)
    except sqlite3.Error as error:
        return 'rejected', str(error)
    except ValueError as error:
        return 'rejected', f'ValueError: {error}'
    except Exception as error:  # noqa: BLE001 - recorded as an interface failure
        return 'invalid', f'{type(error).__name__}: {error}'


def cli(path, workspace):
    run = subprocess.run([sys.executable, '-B', str(workspace / 'app.py'), str(path),
                          json.dumps(dict(op='transfer', **RECEIPT))],
                         cwd=workspace, capture_output=True, text=True, timeout=60)
    if run.returncode == 0 and not run.stderr:
        try:
            return 'success', json.loads(run.stdout)
        except ValueError:
            pass
    if run.returncode == 2 and not run.stdout:
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
    report, failures, advisories = {}, [], []
    with tempfile.TemporaryDirectory(prefix='critical-contract-') as directory:
        for name, (setup, sql, triple, encoding) in SCENARIOS.items():
            case = report[name] = {}
            seen = {'api': set(), 'cli': set()}
            for foreign in (VARIANTS if triple else (777,)):
                label = 'absent' if foreign is None else str(foreign)
                for entry in ('api', 'cli'):
                    path = Path(directory) / f'{name}-{label}-{entry}.db'
                    seed(path, vault, setup, sql, foreign, encoding)
                    expected_status, expected_error, oracle_rows = oracle(path, directory)
                    rows_before, schema_before = state(path)
                    status, detail = api(path, vault) if entry == 'api' else cli(path, workspace)
                    rows_after, schema_after = state(path)
                    problems = []
                    if status == 'invalid':
                        problems.append('interface')
                    elif status != expected_status:
                        problems.append('status')
                    if entry == 'api' and status == 'rejected' == expected_status and expected_error != 'policy' \
                            and detail != expected_error:
                        problems.append('native_error')
                    if status == 'success' and detail != RECEIPT:
                        problems.append('receipt')
                    if status == expected_status == 'success':
                        if own(rows_after) != own(oracle_rows):
                            problems.append('own_rows')
                        if side(rows_after) != side(oracle_rows):
                            problems.append('side_tables')
                    if own(rows_after, False) != own(rows_before, False):
                        problems.append('foreign_rows_changed')
                    elif own(rows_after, False, True) != own(rows_before, False, True):
                        advisories.append(f'{name}:{entry}_{label}:foreign_rowids_moved')
                    if schema_after != schema_before:
                        problems.append('schema')
                    if status != 'success' and rows_after != rows_before:
                        problems.append('partial_write')
                    if status == 'success' and entry == 'api':
                        if api(path, vault) != (status, detail) or state(path) != (rows_after, schema_after):
                            problems.append('replay')
                    seen[entry].add(json.dumps([status, detail if entry == 'api' else None], sort_keys=True))
                    case[f'{entry}_{label}'] = [status, detail if status != 'success' else 'receipt',
                                                expected_status, expected_error, problems]
                    failures += [f'{name}:{entry}_{label}:{p}' for p in problems]
            for entry, observed in seen.items():
                if len(observed) != 1:
                    failures.append(f'{name}:{entry}:foreign_data_observable')
    clauses = sorted({CLAUSES[f.rsplit(':', 1)[1]] for f in failures})
    print(json.dumps(dict(workspace=str(workspace), sqlite_version=sqlite3.sqlite_version,
                          source_sha256=hashlib.sha256((workspace / 'vault.py').read_bytes()).hexdigest(),
                          scenarios=len(SCENARIOS), failed_cases=len(failures), failed_clauses=clauses,
                          failures=failures, advisory_observations=advisories, cases=report), indent=1))
    return bool(failures)


if __name__ == '__main__':
    raise SystemExit(main())
