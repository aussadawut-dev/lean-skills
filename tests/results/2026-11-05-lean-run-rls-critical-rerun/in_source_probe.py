#!/usr/bin/env python3
"""Check native SQLite source resolution through the transfer API and CLI.

Requires the pilot critical_final_findings_probe.py helper beside this script.
"""
import argparse
import hashlib
import importlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
from contextlib import closing

import critical_final_findings_probe as helper


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('workspace', type=Path)
    workspace = parser.parse_args().workspace.resolve()
    sys.path.insert(0, str(workspace))
    sys.dont_write_bytecode = True
    vault = importlib.import_module('vault')

    with closing(sqlite3.connect(':memory:')) as con:
        mode = con.execute('PRAGMA recursive_triggers').fetchone()[0]
    sources = (
        ('in_plain', 'SELECT 0 IN pragma_recursive_triggers', int(mode == 0)),
        ('in_main', 'SELECT 0 IN main.pragma_recursive_triggers', int(mode == 0)),
        ('not_indexed', 'SELECT pragma_recursive_triggers.recursive_triggers '
         'FROM pragma_recursive_triggers NOT INDEXED', mode),
    )
    results = []
    with tempfile.TemporaryDirectory(prefix='lean-run-in-source-') as directory:
        for name, select, expected_value in sources:
            for suffix, comparison, success in (('abort', '=', False),
                                                ('harmless', '<>', True)):
                sql = f"""
                    CREATE VIEW saved_mode(observed) AS {select};
                    CREATE TRIGGER native_guard BEFORE INSERT ON audit
                    WHEN (SELECT observed FROM saved_mode) {comparison} {expected_value}
                    BEGIN SELECT RAISE(ABORT,'native guard'); END;
                """
                result = helper.run_case(vault, workspace, Path(directory),
                                         f'{name}_{suffix}', 'R3-F1', sql, 77,
                                         success, success)
                if not success and result['native'].get('error') != 'native guard':
                    result['native_pass'] = False
                    result['failures'].append('native_guard_did_not_execute')
                if not success and result.get('api', {}).get('status') == 'storage_error':
                    if result['api'].get('error') != 'native guard':
                        result['failures'].append('api:native_guard_did_not_execute')
                results.append(result)
    failed = [result['case'] for result in results if result['failures']]
    print(json.dumps({
        'workspace': str(workspace), 'sqlite_version': sqlite3.sqlite_version,
        'source_sha256': hashlib.sha256((workspace / 'vault.py').read_bytes()).hexdigest(),
        'failed_cases': len(failed), 'failed_case_names': failed, 'cases': results,
    }, indent=2))
    return bool(failed)


if __name__ == '__main__':
    raise SystemExit(main())
