"""The budget helper reports a caller's cap without creating one or hiding failure."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

SCRIPT=Path(__file__).resolve().parents[1]/'skills/lean-run/scripts/budget.py'
spec=importlib.util.spec_from_file_location('lean_budget',SCRIPT)
budget=importlib.util.module_from_spec(spec);spec.loader.exec_module(budget)


class BudgetTests(unittest.TestCase):
    def test_no_deadline_stays_unbounded(self):
        self.assertEqual(budget.status({},100),{'mode':'UNBOUNDED'})

    def test_fixed_deadline_transitions_without_resetting(self):
        environment={'LEAN_RUN_DEADLINE_UNIX':'1000','LEAN_RUN_PHASE_SECONDS':'900'}
        self.assertEqual(budget.status(environment,100)['remaining_seconds'],900)
        self.assertEqual(budget.status(environment,819)['mode'],'WORK')
        self.assertEqual(budget.status(environment,820)['mode'],'VERIFY')
        self.assertEqual(budget.status(environment,999)['remaining_seconds'],1)
        self.assertEqual(budget.status(environment,1001)['mode'],'DEADLINE')
        self.assertEqual(environment['LEAN_RUN_DEADLINE_UNIX'],'1000')

    def test_explicit_reserve_and_invalid_values(self):
        environment={'LEAN_RUN_DEADLINE_UNIX':'1000','LEAN_RUN_PHASE_SECONDS':'900'}
        self.assertEqual(budget.status(environment,700,300)['mode'],'VERIFY')
        for value in ('nan','inf','broken'):
            with self.subTest(value=value),self.assertRaises(ValueError):
                budget.status(dict(environment,LEAN_RUN_DEADLINE_UNIX=value),100)
        with self.assertRaises(ValueError):budget.status(environment,100,-1)

    def test_cli_reads_caller_environment(self):
        result=subprocess.run([sys.executable,'-B',str(SCRIPT)],capture_output=True,text=True,
                              env={**os.environ,'LEAN_RUN_DEADLINE_UNIX':'1','LEAN_RUN_PHASE_SECONDS':'900'})
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout)['mode'],'DEADLINE')
