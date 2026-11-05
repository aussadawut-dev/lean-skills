"""Check the actual overflow/CLI contract behind over-specific historical assertions."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile


def probe(workspace):
    sys.path.insert(0, str(workspace))
    spec=importlib.util.spec_from_file_location('error_boundary_vault',workspace/'vault.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    cases=[]
    for case in ('stored_integer_overflow','audit_storage_failure'):
        with tempfile.TemporaryDirectory(prefix='lean-error-boundary-') as temporary:
            db=str(Path(temporary)/'probe.sqlite');module.init_db(db);con=sqlite3.connect(db)
            try:
                con.executemany('INSERT INTO accounts VALUES(?,?,?)',[
                    ('alpha','a',100),('alpha','b',2**63-1 if case=='stored_integer_overflow' else 0),
                    ('beta','private',777)])
                if case=='audit_storage_failure':
                    con.execute("CREATE TRIGGER fault BEFORE INSERT ON audit BEGIN SELECT RAISE(ABORT,'SQL private details'); END")
                con.commit()
                def snapshot():
                    return {table:con.execute(f'SELECT * FROM {table} ORDER BY rowid').fetchall()
                            for table in ('accounts','transfers','audit')}
                before=snapshot();exception=None
                try:module.transfer(db,'alpha','a','b',1,'k')
                except Exception as error:exception=type(error).__name__+': '+str(error)
                api_pass=exception is not None and snapshot()==before
                request=dict(op='transfer',tenant='alpha',source='a',target='b',amount=1,key='k')
                p=subprocess.run([sys.executable,'-B',str(workspace/'app.py'),db,json.dumps(request)],
                                 capture_output=True,text=True,timeout=30)
                try:message=json.loads(p.stderr)
                except ValueError:message=None
                cli_pass=(p.returncode==2 and p.stdout=='' and isinstance(message,dict)
                          and isinstance(message.get('error'),str)
                          and not any(s in p.stderr.lower() for s in ('traceback','private','sql ','beta'))
                          and snapshot()==before)
                cases.append(dict(case=case,passed=api_pass and cli_pass,api_exception=exception,
                                  exit_code=p.returncode,stdout=p.stdout,stderr=p.stderr,
                                  data_unchanged=snapshot()==before))
            finally:con.close()
    return dict(source_sha256=hashlib.sha256((workspace/'vault.py').read_bytes()).hexdigest(),
                cases=cases,failed_cases=sum(not c['passed'] for c in cases),
                contract='Storage overflow exception class and literal generic CLI message are unspecified. Reject atomically; CLI exit 2, no stdout, generic JSON without SQL/foreign details.')


if __name__=='__main__':print(json.dumps(probe(Path(sys.argv[1]).resolve()),indent=2))
