
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
