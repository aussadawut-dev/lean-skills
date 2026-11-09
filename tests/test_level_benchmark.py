"""Validate benchmark fixture faults without invoking an agent or network."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import sys

import level_benchmark as benchmark


class LevelBenchmarkTests(unittest.TestCase):
    def test_deadline_is_transported_to_real_child_without_changing_prompt_or_cap(self):
        with tempfile.TemporaryDirectory(prefix='lean-deadline-transport-') as scratch:
            base=Path(scratch);trial=base/'high';(trial/'workspace').mkdir(parents=True)
            prompt='unchanged fixture prompt';(trial/'prompt.txt').write_text(prompt)
            child=base/'child.py'
            child.write_text('import json,os,subprocess,sys\n'
                'payload=sys.stdin.read()\n'
                'value=subprocess.check_output([sys.executable,"-c",'
                '\'import os;print(os.environ["LEAN_RUN_DEADLINE_UNIX"])\'],text=True).strip()\n'
                'print(json.dumps({"type":"transport","deadline":value,"prompt":payload}))\n'
                'print(json.dumps({"type":"turn.completed","usage":{"input_tokens":0,"cached_input_tokens":0,"output_tokens":0}}))\n')
            with patch.object(benchmark,'cli_command',return_value=[sys.executable,'-B',str(child)]),contextlib.redirect_stdout(io.StringIO()):
                benchmark.run(base,'high','implementation',900,'gpt-6-astra','max')
            folder=trial/'implementation'
            running=json.loads((folder/'running.json').read_text())
            events=[json.loads(line) for line in (folder/'events.jsonl').read_text().splitlines()]
            self.assertEqual(events[0]['prompt'],prompt)
            self.assertEqual(events[0]['deadline'],running['budget_environment']['LEAN_RUN_DEADLINE_UNIX'])
            self.assertAlmostEqual(float(events[0]['deadline'])-running['started_unix'],900)
            self.assertFalse(json.loads((folder/'metrics.json').read_text())['timed_out'])
    def test_baseline_defects_and_protected_resources(self):
        expected = {
            'medium': {'test_M2_empty_fields', 'test_M3_ascii_integer_grammar', 'test_M4_cli_error_contract'},
            'high': {'test_H1_input_and_receipt_ownership', 'test_H2_value_validation',
                     'test_H3_failed_transfer_atomicity', 'test_H4_replay_and_conflict', 'test_H5_batch_atomicity'},
            'critical': {'test_C1_read_isolation', 'test_C2_transfer_isolation', 'test_C3_tenant_scoped_receipts',
                         'test_C4_invalid_request_preserves_state', 'test_C5_storage_failure_rolls_back',
                         'test_C6_concurrent_duplicate', 'test_C7_concurrent_no_overspend', 'test_C9_cli_errors_are_generic'},
        }
        with tempfile.TemporaryDirectory(prefix='lean-level-fixture-check-') as scratch:
            base=benchmark.prepare(Path(scratch)/'cases')
            for level, failures in expected.items():
                with self.subTest(level=level), contextlib.redirect_stdout(io.StringIO()):
                    grade=benchmark.grade(base,level,'baseline')
                    self.assertEqual({c['id'] for c in grade['cases'] if c['status']!='PASS'},failures)
                    self.assertEqual(grade['protected_files_changed'],[])
            contract=base/'medium/workspace/CONTRACT.md'
            contract.write_text('Tampered contract\n')
            with contextlib.redirect_stdout(io.StringIO()):
                grade=benchmark.grade(base,'medium','tampered')
            self.assertEqual(grade['protected_files_changed'],['CONTRACT.md'])

    def test_prepare_preserves_existing_destinations_and_reviewer_input(self):
        with tempfile.TemporaryDirectory(prefix='lean-level-review-check-') as scratch:
            base=benchmark.prepare(Path(scratch)/'cases')
            before=benchmark.digest_tree(base)
            with self.assertRaises(ValueError): benchmark.prepare(base)
            self.assertEqual(before,benchmark.digest_tree(base))
            (base/'medium/implementation').mkdir()
            (base/'medium/implementation/final.txt').write_text('Author claims PASS')
            with contextlib.redirect_stdout(io.StringIO()): benchmark.prepare_review(base,'medium')
            review=base/'medium/reviewspace'
            self.assertFalse((review/'implementation').exists())
            self.assertEqual((review/'.baseline/app.py').read_bytes(),(base/'medium/initial/app.py').read_bytes())
            self.assertEqual(benchmark.digest_tree(review),json.loads((base/'medium/review-initial-hashes.json').read_text()))
            with self.assertRaises(ValueError): benchmark.prepare_review(base,'medium')


if __name__=='__main__': unittest.main()
