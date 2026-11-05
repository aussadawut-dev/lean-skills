"""Offline fixtures and grading for three measured lean-run agent trials.

Preparing/grading uses only the standard library. `run` explicitly invokes the
already authenticated Codex CLI; it is never called by unittest discovery.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import textwrap
import time

ROOT = Path(__file__).resolve().parents[1]
LEVELS = ("medium", "high", "critical")

FIXTURES = {
    "medium": {
        "title": "Strict integer-list CLI",
        "contract": """
            Repair app.py while preserving parse_numbers(text) -> list[int].
            Accept one nonempty comma-separated list of ASCII decimal integers,
            with optional + or - and surrounding whitespace on each field.
            Empty fields/input, underscores, decimal/exponent notation, Unicode
            numerals and non-numbers must raise ValueError. Never drop a field.
            CLI: python3 -B app.py '1,-2,+3' prints 2 and exits 0. A leading
            negative list such as '-2,-3' is also valid. Exactly one positional
            argument is required. Invalid input/arity exits 2 with a useful error
            on stderr, no stdout and no traceback. Preserve valid signed values,
            zeros and arbitrary-size integers. Standard library only.
        """,
        "files": {
            "app.py": """
                import sys
                def parse_numbers(text):
                    return [int(part) for part in text.split(',') if part.strip()]
                if __name__ == '__main__':
                    print(sum(parse_numbers(sys.argv[1])))
            """,
            "test_public.py": """
                import unittest
                from app import parse_numbers
                class PublicTests(unittest.TestCase):
                    def test_valid(self):
                        self.assertEqual(parse_numbers('1,-2,+3'), [1,-2,3])
            """,
        },
    },
    "high": {
        "title": "Atomic, idempotent batch ledger",
        "contract": """
            Repair ledger.py. Public API: Ledger(balances: dict[str,int]),
            transfer(source,target,amount,key), batch(operations). Preserve the
            public balances and history dictionaries and existing valid behavior.
            Constructor copies input; nonnegative integer balances, excluding
            bool, are required. Transfers require distinct existing accounts,
            amount a positive int excluding bool, and a nonempty string key.
            Reject invalid values, unavailable accounts and insufficient funds
            with ValueError and absolutely no state change. Return a receipt
            {'source':source,'target':target,'amount':amount,'key':key}.
            A replay of a successful key with the same payload returns an equal
            receipt with no second mutation; a changed payload is a ValueError.
            Returned receipts must not let callers mutate internal history.
            batch accepts a list of operation dictionaries using these names,
            returning receipts in order. A batch is atomic: on any failure both
            balances/history equal their pre-batch state, including earlier valid
            operations; successful batches preserve ordinary replay semantics.
            No persistence, concurrency or external service is requested here.
            Add meaningful tests and exercise an integrated multi-transfer flow.
        """,
        "files": {
            "ledger.py": """
                class Ledger:
                    def __init__(self, balances):
                        self.balances = balances
                        self.history = {}
                    def transfer(self, source, target, amount, key):
                        if key in self.history:
                            return self.history[key]
                        self.balances[source] -= amount
                        if self.balances[source] < 0:
                            raise ValueError('insufficient funds')
                        self.balances[target] += amount
                        receipt = dict(source=source, target=target, amount=amount, key=key)
                        self.history[key] = receipt
                        return receipt
                    def batch(self, operations):
                        return [self.transfer(**op) for op in operations]
            """,
            "test_public.py": """
                import unittest
                from ledger import Ledger
                class PublicTests(unittest.TestCase):
                    def test_transfer(self):
                        ledger=Ledger({'a':100,'b':0})
                        ledger.transfer('a','b',20,'one')
                        self.assertEqual(ledger.balances, {'a':80,'b':20})
            """,
        },
    },
    "critical": {
        "title": "Tenant isolation and transactional SQLite transfers",
        "contract": """
            Repair vault.py and app.py for a LOCAL SYNTHETIC accounting fixture.
            No real payments, identity provider, production data or deployment.
            The tenant argument is trusted authenticated context supplied by a
            caller; implementing authentication is outside scope. Every account
            read and both ends of a transfer MUST be within that tenant.
            Public API: init_db(path); balance(path,tenant,account) -> int;
            transfer(path,tenant,source,target,amount,key) -> receipt containing
            tenant,key,source,target,amount. Keep the existing accounts,
            transfers and audit table names and columns; preserve existing rows.
            Account identity is (tenant,name). A nonempty tenant/account/key
            string and distinct existing source/target are required. Amount is
            a positive integer excluding bool. Reject malformed requests,
            insufficient funds and key conflicts with ValueError without writes.
            Missing and inaccessible accounts have the same generic error and
            reveal no other tenant's details. Read isolation also applies to
            cached transfer receipts. Keys are scoped to tenant: exact replay
            returns the original receipt with no changes, a different payload
            conflicts, and another tenant can independently use the same key.
            Debit, credit, transfer receipt and one audit row are ONE transaction.
            A storage/audit failure propagates and leaves all four unchanged.
            With separate simultaneous connections, duplicate same-key requests
            all return the same receipt, execute once, and create one audit row.
            Concurrent distinct-key requests never overspend or lose credits.
            Atomicity/deduplication must survive reopening the database.
            Existing schema has accounts(tenant,name,balance),
            transfers(tenant,key,source,target,amount), and audit with the same
            columns as transfers. Do not remove audit triggers to bypass failures.
            CLI: python3 -B app.py DB JSON_REQUEST. Operations are balance with
            tenant/account, or transfer with tenant/source/target/amount/key.
            Valid calls print one JSON result and exit 0. Invalid calls exit 2,
            emit no stdout, and write a generic JSON error on stderr without a
            traceback, SQL statement or another tenant's information.
            Use only Python/SQLite standard libraries. Delivery is local files.
            Fresh independent final review is required and supplied separately
            by the benchmark coordinator. Do not claim it before it occurs.
        """,
        "files": {
            "vault.py": """
                import sqlite3
                import time
                def init_db(path):
                    with sqlite3.connect(path) as con:
                        con.executescript('''
                        CREATE TABLE IF NOT EXISTS accounts (
                          tenant TEXT, name TEXT, balance INTEGER,
                          PRIMARY KEY(tenant,name));
                        CREATE TABLE IF NOT EXISTS transfers (
                          tenant TEXT, key TEXT, source TEXT, target TEXT, amount INTEGER,
                          PRIMARY KEY(tenant,key));
                        CREATE TABLE IF NOT EXISTS audit (
                          tenant TEXT, key TEXT, source TEXT, target TEXT, amount INTEGER);
                        ''')
                def balance(path, tenant, account):
                    with sqlite3.connect(path) as con:
                        return con.execute('SELECT balance FROM accounts WHERE name=?', (account,)).fetchone()[0]
                def transfer(path, tenant, source, target, amount, key):
                    with sqlite3.connect(path) as con:
                        con.row_factory = sqlite3.Row
                        old=con.execute('SELECT * FROM transfers WHERE key=?',(key,)).fetchone()
                        if old:
                            return dict(old)
                        funds=con.execute('SELECT balance FROM accounts WHERE name=?',(source,)).fetchone()[0]
                        if funds < amount:
                            raise ValueError('insufficient funds')
                        time.sleep(0.02)
                        con.execute('UPDATE accounts SET balance=balance-? WHERE name=?',(amount,source))
                        con.commit()
                        con.execute('UPDATE accounts SET balance=balance+? WHERE name=?',(amount,target))
                        con.commit()
                        con.execute('INSERT INTO transfers VALUES (?,?,?,?,?)',(tenant,key,source,target,amount))
                        con.execute('INSERT INTO audit VALUES (?,?,?,?,?)',(tenant,key,source,target,amount))
                        return dict(tenant=tenant,key=key,source=source,target=target,amount=amount)
            """,
            "app.py": """
                import json
                import sys
                import vault
                if __name__ == '__main__':
                    request=json.loads(sys.argv[2])
                    operation=request.pop('op')
                    result=getattr(vault,operation)(sys.argv[1],**request)
                    print(json.dumps(result))
            """,
            "test_public.py": """
                import sqlite3
                import tempfile
                import unittest
                from pathlib import Path
                import vault
                class PublicTests(unittest.TestCase):
                    def test_valid_transfer(self):
                        with tempfile.TemporaryDirectory() as tmp:
                            path=Path(tmp)/'db.sqlite'
                            vault.init_db(path)
                            with sqlite3.connect(path) as con:
                                con.executemany('INSERT INTO accounts VALUES (?,?,?)', [('one','a',100),('one','b',0)])
                            vault.transfer(path,'one','a','b',10,'k')
                            self.assertEqual(vault.balance(path,'one','a'),90)
            """,
        },
    },
}

# Evaluator tests are outside trial workspaces. Each method is one predefined
# issue category, not a count of assertions or raw failing test cases.
GRADER = r'''
import concurrent.futures
import copy
import importlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest

LEVEL, WORKSPACE = sys.argv[1:3]
sys.path.insert(0, WORKSPACE)

def cli(*args):
    return subprocess.run([sys.executable,'-B',str(Path(WORKSPACE)/'app.py'),*args],
                          cwd=WORKSPACE,capture_output=True,text=True,timeout=8)

class Medium(unittest.TestCase):
    def setUp(self): self.parse=importlib.import_module('app').parse_numbers
    def test_M1_valid_inputs(self):
        for text, expected in [('1,-2,+3',[1,-2,3]),(' 0 , -0, +0002 ',[0,0,2]),('9'*80,[int('9'*80)])]:
            self.assertEqual(self.parse(text),expected)
        p=cli('-2,-3'); self.assertEqual((p.returncode,p.stdout.strip(),p.stderr),(0,'-5',''))
    def test_M2_empty_fields(self):
        for text in ('',' ','1,,2',',1','1,','1, ,2'):
            with self.assertRaises(ValueError,msg=repr(text)): self.parse(text)
    def test_M3_ascii_integer_grammar(self):
        for text in ('1_000','١','１','1.0','1e2','NaN','+','--1','a'):
            with self.assertRaises(ValueError,msg=repr(text)): self.parse(text)
    def test_M4_cli_error_contract(self):
        for args in [(),('1','2'),('x',),('',),('1,,2',)]:
            p=cli(*args)
            self.assertEqual(p.returncode,2,args); self.assertEqual(p.stdout,'')
            self.assertTrue(p.stderr.strip()); self.assertNotIn('Traceback',p.stderr)

class High(unittest.TestCase):
    def setUp(self): self.Ledger=importlib.import_module('ledger').Ledger
    def test_H1_input_and_receipt_ownership(self):
        initial={'a':100,'b':0}; ledger=self.Ledger(initial)
        result=ledger.transfer('a','b',10,'k')
        self.assertEqual(initial,{'a':100,'b':0})
        result['amount']=999
        self.assertEqual(ledger.transfer('a','b',10,'k')['amount'],10)
    def test_H2_value_validation(self):
        for value in (True,-1,1.5,'5'):
            with self.assertRaises(ValueError): self.Ledger({'a':value})
        for amount in (0,-1,True,1.5,'5',None):
            ledger=self.Ledger({'a':100,'b':0})
            with self.assertRaises(ValueError): ledger.transfer('a','b',amount,'k')
            self.assertEqual(ledger.balances,{'a':100,'b':0}); self.assertEqual(ledger.history,{})
        for key in ('',None,3):
            with self.assertRaises(ValueError): self.Ledger({'a':100,'b':0}).transfer('a','b',1,key)
    def test_H3_failed_transfer_atomicity(self):
        for source,target,amount in [('a','b',101),('a','missing',10),('missing','b',10),('a','a',10)]:
            ledger=self.Ledger({'a':100,'b':0})
            with self.assertRaises(ValueError): ledger.transfer(source,target,amount,'k')
            self.assertEqual(ledger.balances,{'a':100,'b':0}); self.assertEqual(ledger.history,{})
    def test_H4_replay_and_conflict(self):
        ledger=self.Ledger({'a':100,'b':0,'c':0}); first=ledger.transfer('a','b',10,'k')
        self.assertEqual(ledger.transfer('a','b',10,'k'),first)
        before=copy.deepcopy((ledger.balances,ledger.history))
        for args in [('a','b',11,'k'),('a','c',10,'k')]:
            with self.assertRaises(ValueError): ledger.transfer(*args)
        self.assertEqual((ledger.balances,ledger.history),before)
    def test_H5_batch_atomicity(self):
        ledger=self.Ledger({'a':100,'b':0,'c':0}); ledger.transfer('a','b',5,'existing')
        before=copy.deepcopy((ledger.balances,ledger.history))
        with self.assertRaises(ValueError):
            ledger.batch([dict(source='a',target='b',amount=20,key='one'),dict(source='a',target='c',amount=100,key='two')])
        self.assertEqual((ledger.balances,ledger.history),before)
    def test_H6_integrated_success(self):
        ledger=self.Ledger({'a':100,'b':0,'c':0})
        operations=[dict(source='a',target='b',amount=20,key='one'),dict(source='b',target='c',amount=10,key='two')]
        receipts=ledger.batch(operations)
        self.assertEqual(ledger.balances,{'a':80,'b':10,'c':10})
        self.assertEqual(ledger.batch(operations),receipts)
        self.assertEqual(ledger.balances,{'a':80,'b':10,'c':10}); self.assertEqual(len(ledger.history),2)

class Critical(unittest.TestCase):
    def setUp(self):
        self.v=importlib.import_module('vault'); self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup); self.path=Path(self.tmp.name)/'vault.sqlite'
        self.v.init_db(self.path)
        with sqlite3.connect(self.path) as con:
            con.executemany('INSERT INTO accounts VALUES (?,?,?)', [('alpha','a',100),('alpha','b',0),('beta','a',700),('beta','b',0),('beta','secret',999)])
    def snapshot(self):
        with sqlite3.connect(self.path) as con:
            return {table:con.execute('SELECT * FROM '+table+' ORDER BY rowid').fetchall() for table in ('accounts','transfers','audit')}
    def test_C1_read_isolation(self):
        self.assertEqual(self.v.balance(self.path,'beta','a'),700)
        messages=[]
        for account in ('secret','missing'):
            with self.assertRaises(ValueError) as error: self.v.balance(self.path,'alpha',account)
            messages.append(str(error.exception))
        self.assertEqual(messages[0],messages[1]); self.assertNotIn('999',messages[0])
    def test_C2_transfer_isolation(self):
        self.v.transfer(self.path,'alpha','a','b',10,'k')
        accounts=self.snapshot()['accounts']
        self.assertIn(('alpha','a',90),accounts); self.assertIn(('alpha','b',10),accounts)
        self.assertIn(('beta','a',700),accounts); self.assertIn(('beta','b',0),accounts)
        before=self.snapshot()
        with self.assertRaises(ValueError): self.v.transfer(self.path,'alpha','a','secret',10,'other')
        self.assertEqual(self.snapshot(),before)
    def test_C3_tenant_scoped_receipts(self):
        self.v.transfer(self.path,'beta','a','b',10,'shared')
        result=self.v.transfer(self.path,'alpha','a','b',10,'shared')
        self.assertEqual(result['tenant'],'alpha')
        self.assertEqual(len(self.snapshot()['transfers']),2)
        before=self.snapshot()
        with self.assertRaises(ValueError): self.v.transfer(self.path,'alpha','a','b',11,'shared')
        self.assertEqual(self.snapshot(),before)
    def test_C4_invalid_request_preserves_state(self):
        for amount in (0,-5,True,1.5,'5',None,101):
            before=self.snapshot()
            with self.assertRaises(ValueError): self.v.transfer(self.path,'alpha','a','b',amount,'k')
            self.assertEqual(self.snapshot(),before)
        for tenant,source,target,key in [('alpha','a','a','k'),('','a','b','k'),('alpha','a','b',''),('alpha','a','b',None),('alpha','missing','b','k')]:
            before=self.snapshot()
            with self.assertRaises(ValueError): self.v.transfer(self.path,tenant,source,target,10,key)
            self.assertEqual(self.snapshot(),before)
    def test_C5_storage_failure_rolls_back(self):
        with sqlite3.connect(self.path) as con:
            con.execute("CREATE TRIGGER reject_audit BEFORE INSERT ON audit WHEN NEW.key='fault' BEGIN SELECT RAISE(ABORT,'audit unavailable'); END")
        before=self.snapshot()
        with self.assertRaises(Exception): self.v.transfer(self.path,'alpha','a','b',10,'fault')
        self.assertEqual(self.snapshot(),before)
        with sqlite3.connect(self.path) as con:
            self.assertEqual(con.execute("SELECT count(*) FROM sqlite_master WHERE name='reject_audit'").fetchone()[0],1)
    def test_C6_concurrent_duplicate(self):
        barrier=threading.Barrier(6)
        def action(_):
            barrier.wait(timeout=5)
            return self.v.transfer(self.path,'alpha','a','b',10,'same')
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool: results=list(pool.map(action,range(6)))
        self.assertTrue(all(r==results[0] for r in results))
        self.assertEqual(self.v.balance(self.path,'alpha','a'),90)
        self.assertEqual(self.v.balance(self.path,'alpha','b'),10)
        state=self.snapshot(); self.assertEqual(len(state['transfers']),1); self.assertEqual(len(state['audit']),1)
    def test_C7_concurrent_no_overspend(self):
        barrier=threading.Barrier(6)
        def action(i):
            barrier.wait(timeout=5)
            try: self.v.transfer(self.path,'alpha','a','b',25,'distinct-'+str(i)); return True
            except ValueError: return False
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool: results=list(pool.map(action,range(6)))
        self.assertEqual(sum(results),4)
        self.assertEqual(self.v.balance(self.path,'alpha','a'),0); self.assertEqual(self.v.balance(self.path,'alpha','b'),100)
        self.assertEqual(len(self.snapshot()['audit']),4)
    def test_C8_durable_exact_replay(self):
        first=self.v.transfer(self.path,'alpha','a','b',10,'persist')
        before=self.snapshot(); self.v.init_db(self.path)
        self.assertEqual(self.v.transfer(self.path,'alpha','a','b',10,'persist'),first)
        self.assertEqual(self.snapshot(),before)
        p=cli(str(self.path),json.dumps(dict(op='balance',tenant='alpha',account='a')))
        self.assertEqual(p.returncode,0); self.assertEqual(json.loads(p.stdout),90)
    def test_C9_cli_errors_are_generic(self):
        messages=[]
        for request in [dict(op='balance',tenant='alpha',account='secret'),dict(op='balance',tenant='alpha',account='missing'),dict(op='drop',tenant='alpha')]:
            before=self.snapshot(); p=cli(str(self.path),json.dumps(request))
            self.assertEqual(p.returncode,2); self.assertEqual(p.stdout,'')
            error=json.loads(p.stderr); self.assertIn('error',error)
            self.assertNotIn('Traceback',p.stderr); self.assertNotIn('999',p.stderr)
            self.assertEqual(self.snapshot(),before); messages.append(error)
        self.assertEqual(messages[0],messages[1])

class Result(unittest.TestResult):
    def __init__(self): super().__init__(); self.cases=[]
    def addSuccess(self,test): super().addSuccess(test); self.cases.append({'id':test._testMethodName,'status':'PASS'})
    def addFailure(self,test,err): super().addFailure(test,err); self.cases.append({'id':test._testMethodName,'status':'FAIL','detail':self._exc_info_to_string(err,test)})
    def addError(self,test,err): super().addError(test,err); self.cases.append({'id':test._testMethodName,'status':'ERROR','detail':self._exc_info_to_string(err,test)})
result=Result()
unittest.defaultTestLoader.loadTestsFromTestCase({'medium':Medium,'high':High,'critical':Critical}[LEVEL]).run(result)
print(json.dumps({'level':LEVEL,'cases':result.cases,'checks':result.testsRun,'issues':len(result.failures)+len(result.errors)},indent=2))
'''


def digest_tree(path):
    return {str(p.relative_to(path)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(path.rglob('*')) if p.is_file() and '__pycache__' not in p.parts}


def prepare(destination):
    destination = destination.resolve()
    if destination.exists() or destination == ROOT or ROOT in destination.parents:
        raise ValueError('Use a new destination outside the source repository')
    destination.mkdir(parents=True)
    (destination / 'grader.py').write_text(GRADER)
    for level, case in FIXTURES.items():
        base = destination / level
        workspace = base / 'workspace'
        workspace.mkdir(parents=True)
        for name, content in case['files'].items():
            (workspace / name).write_text(textwrap.dedent(content).lstrip('\n'))
        (workspace / 'CONTRACT.md').write_text(textwrap.dedent(case['contract']).strip()+'\n')
        (workspace / 'AGENTS.md').write_text(
            'This is an isolated LOCAL benchmark fixture. Use Python standard library only. '
            'Work exclusively in this workspace; do not inspect evaluator scripts, sibling trials, '
            'global skills, other repositories, credentials, network or external services. '
            'Read .agents/skills/lean-run/SKILL.md and apply it. Do not modify CONTRACT.md, '
            'AGENTS.md, supplied test_public.py or .agents. You may edit application Python '
            'and add meaningful tests. Use python3 -B -m unittest discover -v and real public '
            'interfaces. No installs, commits, pushes, publication or extra agents. '
            'The coordinator supplies fresh independent review after implementation. '
            'When that review is mandatory, explicitly report it pending; do not claim it occurred. '
            'Deliver local code and a concise evidence report in the final response. '
            'Do not create workflow files. These read boundaries are instructional, not OS sandboxing.\n')
        shutil.copytree(ROOT/'skills/lean-run',workspace/'.agents/skills/lean-run')
        shutil.copytree(workspace,base/'initial')
        (base/'initial-hashes.json').write_text(json.dumps(digest_tree(workspace),indent=2))
        prompt = (f'Use lean-run at .agents/skills/lean-run/SKILL.md to complete the {level} '
                  f'benchmark task: {case["title"]}. Read CONTRACT.md and implement all its '
                  'requirements, reproduce defects, add meaningful regression checks and exercise '
                  'the relevant integrated journey. Scope is fully specified: proceed without '
                  'routine clarification. Procedure depth is standard for every level. '
                  'The level describes workload/risk, not model reasoning effort. The coordinator '
                  'will supply fresh independent review after this implementation stage. Report '
                  'current checks, remaining requirements and any required pending review honestly.\n')
        (base/'prompt.txt').write_text(prompt)
    (destination/'manifest.json').write_text(json.dumps({
        'source_revision':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'skill_sha256':digest_tree(ROOT/'skills/lean-run'),
        'generator_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'grader_sha256':hashlib.sha256(GRADER.encode()).hexdigest(),
        'levels':{k:v['title'] for k,v in FIXTURES.items()},
        'issue_unit':'one failed predefined contract category; not individual assertions',
        'repetitions_per_level':1,
    },indent=2)+'\n')
    return destination


def grade(base, level, label):
    started = time.perf_counter()
    p = subprocess.run([sys.executable,'-B',str(base/'grader.py'),level,str(base/level/'workspace')],
                       capture_output=True,text=True,timeout=90)
    if p.returncode:
        raise RuntimeError('Evaluator infrastructure failed: '+p.stderr)
    result = json.loads(p.stdout)
    result['elapsed_seconds'] = round(time.perf_counter()-started,3)
    result['workspace_sha256'] = digest_tree(base/level/'workspace')
    result['protected_files_changed'] = [name for name,digest in json.loads((base/level/'initial-hashes.json').read_text()).items()
        if (name in ('CONTRACT.md','AGENTS.md','test_public.py') or name.startswith('.agents/'))
        and result['workspace_sha256'].get(name)!=digest]
    (base/level/(label+'-grade.json')).write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'level':level,'label':label,'issues':result['issues'],'checks':result['checks'],
                      'protected_files_changed':result['protected_files_changed']}),flush=True)
    return result


def cli_command(workspace, final_message):
    disabled=set()
    for root in (Path('/Users/x10/.agents/skills'),Path('/Users/x10/.codex/skills'),Path('/Users/x10/.codex/skills/.system')):
        disabled.update(p.parent.name for p in root.glob('*/SKILL.md') if p.parent.name!='lean-run')
    skill_config='skills.config=['+','.join('{name='+json.dumps(n)+',enabled=false}' for n in sorted(disabled))+']'
    return ['codex','-a','never','exec','--ignore-user-config','--ephemeral','--json',
            '--skip-git-repo-check','--sandbox','workspace-write','--model','gpt-6-astra',
            '-c','model_reasoning_effort="max"','-c','skills.bundled.enabled=false',
            '-c','web_search="disabled"','-c',skill_config,'--disable','plugins','--disable','apps',
            '--disable','multi_agent','--disable','memories','--disable','hooks',
            '--cd',str(workspace),'-o',str(final_message),'-']


def run(base, level, phase, timeout):
    trial=base/level
    workspace=trial/('reviewspace' if phase.startswith('review') else 'workspace')
    destination=trial/phase
    destination.mkdir()
    prompt=(trial/('review-prompt.txt' if phase.startswith('review') else 'prompt.txt')).read_text()
    (destination/'prompt.txt').write_text(prompt)
    command=cli_command(workspace,destination/'final.txt')
    started=time.perf_counter(); started_at=time.time()
    timed_out=False
    with (destination/'events.jsonl').open('w') as out,(destination/'stderr.log').open('w') as err:
        proc=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=out,stderr=err,text=True,start_new_session=True)
        (destination/'running.json').write_text(json.dumps({'pid':proc.pid,'started_unix':started_at,'command':command},indent=2))
        try:
            proc.communicate(prompt,timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out=True; os.killpg(proc.pid,signal.SIGTERM)
            try: proc.wait(timeout=10)
            except subprocess.TimeoutExpired: os.killpg(proc.pid,signal.SIGKILL); proc.wait()
    elapsed=time.perf_counter()-started
    events=[]
    for line in (destination/'events.jsonl').read_text().splitlines():
        try: events.append(json.loads(line))
        except json.JSONDecodeError: pass
    usages=[e['usage'] for e in events if e.get('type')=='turn.completed' and 'usage' in e]
    usage={k:sum(v.get(k,0) for v in usages) for k in set().union(*(v.keys() for v in usages))} if usages else None
    metrics={'level':level,'phase':phase,'started_unix':started_at,'elapsed_seconds':round(elapsed,3),
             'exit_code':proc.returncode,'timed_out':timed_out,'usage':usage,
             'requested_model':'gpt-6-astra','requested_effort':'max',
             'model_identity_evidence':'requested CLI controls; backend identity not independently attested',
             'completed_turns':len(usages),'command':command,
             'command_count':sum(e.get('type')=='item.completed' and e.get('item',{}).get('type')=='command_execution' for e in events),
             'event_types':sorted({e.get('type','unknown') for e in events})}
    if usage:
        metrics['total_tokens']=usage.get('input_tokens',0)+usage.get('output_tokens',0)
        metrics['uncached_input_tokens']=usage.get('input_tokens',0)-usage.get('cached_input_tokens',0)
    (destination/'metrics.json').write_text(json.dumps(metrics,indent=2)+'\n')
    print(json.dumps({k:v for k,v in metrics.items() if k not in ('command','event_types')}),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    p=commands.add_parser('prepare'); p.add_argument('destination',type=Path)
    p=commands.add_parser('grade'); p.add_argument('base',type=Path); p.add_argument('level',choices=LEVELS); p.add_argument('--label',default='final')
    p=commands.add_parser('run'); p.add_argument('base',type=Path); p.add_argument('level',choices=LEVELS); p.add_argument('--phase',default='implementation'); p.add_argument('--timeout',type=int,default=900)
    args=parser.parse_args()
    if args.command=='prepare': print(prepare(args.destination))
    elif args.command=='grade': grade(args.base.resolve(),args.level,args.label)
    else: run(args.base.resolve(),args.level,args.phase,args.timeout)
