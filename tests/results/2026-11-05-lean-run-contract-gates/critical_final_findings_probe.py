#!/usr/bin/env python3
"""Replay the two round-3 Critical final review findings.

Derived from tests/results/2026-11-04-lean-run-critical-high/round-3/critical/
review-3/final.txt. Native comparison is an engine-specific oracle for fixture
setup and observable outcomes. Database files live in temporary directories.
"""
import argparse
from contextlib import closing
import hashlib
import importlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile


RECEIPT = dict(tenant='red', key='new', source='a', target='b', amount=10)
REQUEST = dict(op='transfer', **RECEIPT)
ARGS = ('red', 'a', 'b', 10, 'new')

EARLY_RESTORE = """
CREATE TRIGGER early_restore BEFORE UPDATE ON accounts
WHEN OLD.tenant='blue' AND OLD.name='private' AND OLD.balance=78 AND NEW.balance=77
BEGIN UPDATE accounts SET balance=77 WHERE tenant=OLD.tenant AND name=OLD.name; END;
"""
TOUCH_FOREIGN = """
CREATE TRIGGER touch_foreign AFTER INSERT ON audit BEGIN
  UPDATE accounts SET balance=78 WHERE tenant='blue' AND name='private';
  UPDATE accounts SET balance=77 WHERE tenant='blue' AND name='private';
  {extra}
END;
"""
MODE_GUARD = """
CREATE VIEW saved_mode AS
SELECT recursive_triggers, 'pragma_recursive_triggers' AS marker FROM {reference};
CREATE TRIGGER guard BEFORE INSERT ON audit WHEN
  (SELECT recursive_triggers FROM saved_mode)={abort_mode}
  OR (SELECT marker FROM saved_mode) IS NOT 'pragma_recursive_triggers'
BEGIN SELECT RAISE(ABORT,'native guard'); END;
"""


def snapshot(path):
    with closing(sqlite3.connect(path)) as con:
        return {
            'accounts': con.execute('SELECT * FROM accounts ORDER BY tenant,name').fetchall(),
            'transfers': con.execute('SELECT * FROM transfers ORDER BY tenant,key').fetchall(),
            'audit': con.execute('SELECT * FROM audit ORDER BY tenant,key').fetchall(),
            'schema': con.execute(
                'SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY type,name'
            ).fetchall(),
        }


def setup(vault, path, trigger_sql):
    vault.init_db(path)
    with closing(sqlite3.connect(path)) as con, con:
        con.executemany('INSERT INTO accounts (tenant,name,balance) VALUES (?,?,?)',
                        [('red', 'a', 100), ('red', 'b', 20), ('blue', 'private', 77)])
        con.executescript(trigger_sql)
    return snapshot(path)


def native(path):
    with closing(sqlite3.connect(path)) as con:
        mode = con.execute('PRAGMA recursive_triggers').fetchone()[0]
        try:
            with con:
                con.execute('BEGIN IMMEDIATE')
                con.execute("UPDATE accounts SET balance=90 WHERE tenant='red' AND name='a'")
                con.execute("UPDATE accounts SET balance=30 WHERE tenant='red' AND name='b'")
                for table in ('transfers', 'audit'):
                    con.execute(f'INSERT INTO {table} (tenant,key,source,target,amount) '
                                'VALUES (:tenant,:key,:source,:target,:amount)', RECEIPT)
        except sqlite3.Error as error:
            return {'status': 'storage_error', 'error': str(error), 'recursive_triggers': mode}
    return {'status': 'success', 'recursive_triggers': mode}


def api(vault, path):
    try:
        return {'status': 'success', 'receipt': vault.transfer(path, *ARGS)}
    except Exception as error:
        return {
            'status': 'storage_error' if isinstance(error, sqlite3.Error) else 'other_error',
            'type': type(error).__name__, 'error': str(error),
        }


def cli(workspace, path):
    run = subprocess.run(
        [sys.executable, '-B', str(workspace / 'app.py'), str(path), json.dumps(REQUEST)],
        cwd=workspace, capture_output=True, text=True, timeout=15,
    )
    if run.returncode == 0 and not run.stderr:
        try:
            return {'status': 'success', 'receipt': json.loads(run.stdout)}
        except ValueError:
            pass
    if run.returncode == 2 and not run.stdout:
        try:
            message = json.loads(run.stderr)
        except ValueError:
            message = None
        if (isinstance(message, dict) and isinstance(message.get('error'), str)
                and not any(marker in run.stderr.lower()
                            for marker in ('blue', 'private', 'traceback', 'native guard',
                                           'pragma_recursive_triggers', 'update accounts'))):
            return {'status': 'storage_error', 'returncode': run.returncode}
    return {'status': 'invalid_cli', 'returncode': run.returncode,
            'stdout': run.stdout, 'stderr': run.stderr}


def expected_snapshot(before, foreign, success):
    if not success:
        return before
    row = tuple(RECEIPT[key] for key in ('tenant', 'key', 'source', 'target', 'amount'))
    return dict(before, accounts=[('blue', 'private', foreign), ('red', 'a', 90), ('red', 'b', 30)],
                transfers=[row], audit=[row])


def run_case(vault, workspace, directory, name, finding, sql, native_foreign, native_success,
             valid_transfer):
    native_path = directory / (name + '-native.db')
    native_before = setup(vault, native_path, sql)
    native_result = native(native_path)
    native_after = snapshot(native_path)
    expected_native = expected_snapshot(native_before, native_foreign, native_success)
    native_pass = (
        native_result['status'] == ('success' if native_success else 'storage_error')
        and native_after == expected_native
    )
    result = {'case': name, 'finding': finding, 'native_pass': native_pass, 'native': native_result,
              'expected': 'success' if valid_transfer else 'storage_error', 'failures': []}
    if not native_pass:
        result['failures'].append('native_oracle_changed')
        result['native_accounts'] = native_after['accounts']
        return result

    for entry, call in (('api', lambda path: api(vault, path)),
                        ('cli', lambda path: cli(workspace, path))):
        path = directory / (name + '-' + entry + '.db')
        before = setup(vault, path, sql)
        observed = call(path)
        after = snapshot(path)
        expected = expected_snapshot(before, 77, valid_transfer)
        mismatches = [field for field in expected if expected[field] != after[field]]
        if observed['status'] != result['expected']:
            mismatches.append('status')
        if valid_transfer and observed.get('receipt') != RECEIPT:
            mismatches.append('receipt')
        if observed['status'] == 'success':
            replay = call(path)
            observed['replay'] = replay
            if replay.get('receipt') != RECEIPT or snapshot(path) != after:
                mismatches.append('replay')
        result['failures'].extend(entry + ':' + field for field in mismatches)
        result[entry] = dict(observed, reopened_accounts=after['accounts'],
                             reopened_transfers=after['transfers'], reopened_audit=after['audit'],
                             schema_preserved=after['schema'] == before['schema'])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('workspace', type=Path)
    args = parser.parse_args()
    workspace = args.workspace.resolve()
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(workspace))
    vault = importlib.import_module('vault')

    with closing(sqlite3.connect(':memory:')) as con:
        mode = con.execute('PRAGMA recursive_triggers').fetchone()[0]
    extra = "UPDATE accounts SET balance=78 WHERE tenant='blue' AND name='private';"
    cases = [
        ('f1_foreign_corruption', 'F1', EARLY_RESTORE + TOUCH_FOREIGN.format(extra=extra),
         78, True, False),
        ('f1_nested_restore', 'F1', EARLY_RESTORE + TOUCH_FOREIGN.format(extra=''),
         77, True, True),
        ('f1_plain_restore_control', 'F1', TOUCH_FOREIGN.format(extra=''), 77, True, True),
        ('f2_single_quoted_view', 'F2',
         MODE_GUARD.format(reference="'pragma_recursive_triggers'()", abort_mode=1 - mode),
         77, True, True),
        ('f2_unquoted_view_control', 'F2',
         MODE_GUARD.format(reference='pragma_recursive_triggers()', abort_mode=1 - mode),
         77, True, True),
        ('f2_guard_still_blocks_control', 'F2',
         MODE_GUARD.format(reference='pragma_recursive_triggers()', abort_mode=mode),
         77, False, False),
    ]
    with tempfile.TemporaryDirectory(prefix='lean-run-critical-final-') as directory:
        results = [run_case(vault, workspace, Path(directory), *case) for case in cases]
    failed = [result['case'] for result in results if result['failures']]
    print(json.dumps({'workspace': str(workspace), 'sqlite_version': sqlite3.sqlite_version,
                      'source_sha256': hashlib.sha256((workspace / 'vault.py').read_bytes()).hexdigest(),
                      'issue_count': len(failed), 'failed_cases': len(failed),
                      'failed_case_names': failed, 'cases': results},
                     indent=2))
    return bool(failed)


if __name__ == '__main__':
    raise SystemExit(main())
