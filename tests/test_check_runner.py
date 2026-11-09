"""Check-runner safety and evidence retention, with real child processes."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

RUNNER = Path(__file__).resolve().parents[1] / 'skills/lean-run/scripts/check.py'


class CheckRunnerTests(unittest.TestCase):
    def run_check(self, directory, code, *options):
        return subprocess.run([sys.executable, '-B', str(RUNNER), '--log',
                               str(Path(directory) / 'check.log'), *options, '--',
                               sys.executable, '-u', '-c', code],
                              capture_output=True, text=True, timeout=10)

    def test_failure_preserves_exit_and_complete_log_but_bounds_excerpt(self):
        with tempfile.TemporaryDirectory() as temp:
            result = self.run_check(temp,
                "import sys; print('START'); print('x'*100000); "
                "print('MIDDLE',file=sys.stderr); print('END'); sys.exit(7)",
                '--max-chars', '640')
            data = json.loads(result.stdout)
            self.assertEqual((result.returncode, data['exit_code']), (7, 7))
            self.assertLessEqual(len(data['output_excerpt']), 640)
            self.assertTrue(data['excerpt_truncated'])
            self.assertIn('START', data['output_excerpt'])
            self.assertIn('END', data['output_excerpt'])
            log = Path(data['log']).read_text()
            self.assertIn('x'*100000, log)
            self.assertIn('MIDDLE', log)
            self.assertFalse(data['timed_out'])

    def test_success_reports_exit_without_interpreting_test_text(self):
        with tempfile.TemporaryDirectory() as temp:
            result = self.run_check(temp, "print('FAILED is a literal in this successful check')")
            self.assertEqual(result.returncode, 0)
            data = json.loads(result.stdout)
            self.assertEqual(data['exit_code'], 0)
            self.assertIn('FAILED', data['output_excerpt'])
            self.assertNotIn('status', data)

    def test_complete_success_excerpt_preserves_newlines_without_false_truncation(self):
        with tempfile.TemporaryDirectory() as temp:
            result = self.run_check(temp, "print('first'); print('second')")
            data = json.loads(result.stdout)
            self.assertEqual(data['output_excerpt'], 'first\nsecond\n')
            self.assertFalse(data['excerpt_truncated'])

    def test_existing_log_prevents_command_execution(self):
        with tempfile.TemporaryDirectory() as temp:
            log = Path(temp) / 'check.log'
            marker = Path(temp) / 'executed'
            log.write_text('existing evidence')
            result = self.run_check(temp, f'from pathlib import Path; Path({str(marker)!r}).touch()')
            self.assertEqual(result.returncode, 2)
            self.assertEqual(log.read_text(), 'existing evidence')
            self.assertFalse(marker.exists())

    def test_timeout_retains_partial_output_and_stops_check(self):
        with tempfile.TemporaryDirectory() as temp:
            marker = Path(temp) / 'late-write'
            result = self.run_check(temp,
                f"import time; from pathlib import Path; print('started'); "
                f"time.sleep(0.8); Path({str(marker)!r}).touch()",
                '--timeout', '0.15')
            data = json.loads(result.stdout)
            self.assertEqual((result.returncode, data['exit_code']), (124, 124))
            self.assertTrue(data['timed_out'])
            self.assertIn('started', Path(data['log']).read_text())
            time.sleep(0.8)
            self.assertFalse(marker.exists())

    def test_missing_executable_is_not_a_success(self):
        with tempfile.TemporaryDirectory() as temp:
            result = subprocess.run([sys.executable, '-B', str(RUNNER), '--log',
                str(Path(temp)/'check.log'), '--', str(Path(temp)/'absent')],
                capture_output=True, text=True, timeout=10)
            data = json.loads(result.stdout)
            self.assertEqual((result.returncode, data['exit_code']), (127, 127))
            self.assertIn('launch_error', data)

    @unittest.skipUnless(os.name == 'posix', 'POSIX process-group cleanup')
    def test_timeout_stops_descendant_that_ignores_term(self):
        with tempfile.TemporaryDirectory() as temp:
            marker = Path(temp) / 'descendant-write'
            child = ("import signal,time; from pathlib import Path; "
                     "signal.signal(signal.SIGTERM, signal.SIG_IGN); print('child ready'); "
                     f"time.sleep(0.9); Path({str(marker)!r}).touch()")
            result = self.run_check(temp,
                f"import subprocess,sys,time; subprocess.Popen([sys.executable,'-u','-c',{child!r}]); time.sleep(5)",
                '--timeout', '0.3')
            self.assertEqual(result.returncode, 124)
            self.assertIn('child ready', Path(temp, 'check.log').read_text())
            time.sleep(0.9)
            self.assertFalse(marker.exists())

    @unittest.skipUnless(os.name == 'posix', 'POSIX wrapper termination')
    def test_terminating_wrapper_stops_check_and_returns_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            log = Path(temp) / 'check.log'
            marker = Path(temp) / 'late-write'
            child = ("import time; from pathlib import Path; print('ready'); "
                     f"time.sleep(0.8); Path({str(marker)!r}).touch()")
            process = subprocess.Popen([sys.executable, '-B', str(RUNNER), '--log', str(log),
                '--', sys.executable, '-u', '-c', child], stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True)
            try:
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    if log.exists() and 'ready' in log.read_text():
                        break
                    time.sleep(0.01)
                self.assertIn('ready', log.read_text())
                process.terminate()
                stdout, stderr = process.communicate(timeout=5)
                self.assertEqual(process.returncode, 143, stderr)
                self.assertEqual(json.loads(stdout)['interrupted_signal'], 15)
                time.sleep(0.8)
                self.assertFalse(marker.exists())
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()


if __name__ == '__main__':
    unittest.main()
