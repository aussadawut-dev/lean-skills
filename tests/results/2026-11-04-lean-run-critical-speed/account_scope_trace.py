"""Uniform bounded trace of the demonstrated account-count/rowid lookup boundary."""
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sqlite3
import sys
import tempfile


def probe(workspace):
    spec=importlib.util.spec_from_file_location('scope_trace_vault',workspace/'vault.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    observations=[]
    original=sqlite3.connect
    for case in ('ordinary','foreign_rowid_collision'):
        with tempfile.TemporaryDirectory(prefix='lean-scope-trace-') as temporary:
            db=str(Path(temporary)/'probe.sqlite');module.init_db(db);con=original(db)
            con.executemany('INSERT INTO accounts(rowid,tenant,name,balance) VALUES(?,?,?,?)',[
                (1,'one','a',100),(2,'one','b',0),(3,'two','private',456),(4,'two','spare',789)])
            if case=='foreign_rowid_collision':
                con.execute("CREATE TRIGGER existing AFTER INSERT ON audit WHEN NEW.tenant='one' BEGIN "
                            "UPDATE OR REPLACE accounts SET rowid=4 WHERE tenant='two' AND name='private'; END")
            con.commit();con.close();sql=[]
            def traced(*args,**kwargs):
                con=original(*args,**kwargs);con.set_trace_callback(sql.append);return con
            error=None
            try:
                sqlite3.connect=traced
                module.transfer(db,'one','a','b',10,'k')
            except Exception as exception:error=type(exception).__name__+': '+str(exception)
            finally:sqlite3.connect=original
            lookup_sql=list(dict.fromkeys(s for s in sql if re.search(
                r'SELECT\b[\s\S]*?\bFROM\s+(?:main\.)?["`\[]?accounts\b',s,re.I)))
            counts=[s for s in lookup_sql if re.search(r'SELECT\s+COUNT\(\*\)\s+FROM\s+accounts\s*\)',s,re.I)]
            rowid=[s for s in lookup_sql if re.search(r'SELECT\s+1\s+FROM\s+accounts\s+WHERE\s+rowid\s*=\s*NEW\.rowid',s,re.I)]
            observations.append(dict(case=case,error=error,account_lookup_sql=lookup_sql,
                                     demonstrated_unscoped_count_sql=counts,
                                     installed_unscoped_rowid_lookup_guards=rowid))
    return dict(source_sha256=hashlib.sha256((workspace/'vault.py').read_bytes()).hexdigest(),
                demonstrated_patterns=any(o['demonstrated_unscoped_count_sql'] or o['installed_unscoped_rowid_lookup_guards'] for o in observations),
                observations=observations,
                interpretation='Reuses independent original-contract triage: global cardinality and foreign stored-account lookups have no aggregate/sentinel exception. Installed trigger SQL is labeled separately from direct queries. OLD/NEW effective-write observation alone is not a preservation lookup.',
                limit='Bounded trace/static confirmation of these two demonstrated patterns, not an exhaustive SQL analyzer or a new independent review. Existing stored outcomes and baseline archive are unchanged.')


if __name__=='__main__':print(json.dumps(probe(Path(sys.argv[1]).resolve()),indent=2))
