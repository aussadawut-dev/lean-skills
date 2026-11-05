"""Verify trial fixtures expose real, distinguishable behavior without providers."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('coverage_fixtures', ROOT / 'tests/behavioral/prepare_coverage.py')
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)


class CoverageFixturesTest(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory(prefix='lean-coverage-test-')
        self.addCleanup(self.scratch.cleanup)
        self.output = fixtures.prepare(Path(self.scratch.name) / 'cases')

    def run_app(self, case, *args):
        return subprocess.run([sys.executable, '-B', *args], cwd=self.output / case / 'app',
                              capture_output=True, text=True, timeout=10)

    def test_standalone_inventories_and_no_clobber(self):
        for name, case in fixtures.CASES.items():
            base = self.output / name
            self.assertEqual({p.name for p in (base / 'skills').iterdir()}, {case['skill']})
            self.assertEqual(json.loads((base / 'initial.json').read_text()), fixtures.snapshot(base / 'app'))
        before = fixtures.snapshot(self.output)
        with self.assertRaises(ValueError):
            fixtures.prepare(self.output)
        with self.assertRaises(ValueError):
            fixtures.prepare(ROOT / 'forbidden-fixture')
        self.assertEqual(fixtures.snapshot(self.output), before)

    def test_security_and_diagnosis_are_demonstrable_without_edits(self):
        security = self.output / 'security/app'
        initial = fixtures.snapshot(security)
        probe = self.run_app('security', '-c',
                             "from service import read_invoice; print(read_invoice('alice', 2)['owner'])")
        self.assertEqual(probe.returncode, 0)
        self.assertEqual(probe.stdout.strip(), 'bob')
        self.assertEqual(fixtures.snapshot(security), initial)
        failure = self.run_app('diagnosis', 'app.py', '2')
        self.assertNotEqual(failure.returncode, 0)
        self.assertIn('TypeError', failure.stderr)
        counterexample = self.run_app('diagnosis', '-c',
            "from pricing import total; print(total(2, {'unit_price': 10, 'tax_percent': 7}))")
        self.assertEqual(counterexample.returncode, 0)
        self.assertAlmostEqual(float(counterexample.stdout), 21.4)
        stale = self.run_app('handoff', '-m', 'unittest', 'discover', '-v')
        self.assertNotEqual(stale.returncode, 0)
        self.assertIn('21 != 20', stale.stderr)

    def test_release_uncertainty_and_recovery_preserve_records(self):
        state_path = self.output / 'release/app/state.json'
        initial = json.loads(state_path.read_text())
        self.assertEqual(self.run_app('release', 'deploy.py', 'verify').returncode, 0)
        self.assertNotEqual(self.run_app('release', 'deploy.py', 'deploy', 'unknown').returncode, 0)
        self.assertEqual(json.loads(state_path.read_text()), initial)
        release = self.run_app('release', 'deploy.py', 'deploy', 'v2')
        self.assertEqual(release.returncode, 124)
        observed = json.loads(self.run_app('release', 'deploy.py', 'status').stdout)
        self.assertEqual(observed['version'], 'v2')
        self.assertFalse(observed['healthy'])
        self.assertNotEqual(self.run_app('release', 'deploy.py', 'health').returncode, 0)
        self.assertEqual(self.run_app('release', 'deploy.py', 'rollback', 'v1').returncode, 0)
        self.assertEqual(self.run_app('release', 'deploy.py', 'health').returncode, 0)
        final = json.loads(state_path.read_text())
        self.assertEqual(final['version'], 'v1')
        self.assertEqual(final['records'], initial['records'])
        self.assertEqual([op['action'] for op in final['operations']], ['deploy-v2', 'rollback-v1'])


if __name__ == '__main__':
    unittest.main()
