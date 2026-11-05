"""The file viewer numbers lines, bounds output and says what remains."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

VIEW = Path(__file__).resolve().parents[1] / 'skills/lean-run/scripts/view.py'


def view(*args):
    return subprocess.run([sys.executable, '-B', str(VIEW), *args], capture_output=True, text=True, timeout=10)


class ViewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'module.py'
        self.path.write_text(''.join(f'line {n:03d} ' + 'x' * 30 + '\n' for n in range(1, 301)))

    def tearDown(self):
        self.temp.cleanup()

    def test_default_view_is_bounded_and_names_the_next_region(self):
        result = view(str(self.path))
        self.assertEqual(result.returncode, 0, result.stderr)
        header, *body, footer = result.stdout.splitlines()
        self.assertTrue(header.startswith(f'{self.path}: 300 lines, sha256 '), header)
        self.assertLessEqual(sum(len(line) + 1 for line in body), 6000)
        self.assertLess(len(body), 300)
        self.assertEqual(body[0], f'{1:>3}| line 001 ' + 'x' * 30)
        self.assertEqual(footer, f'[lines 1-{len(body)} of 300; next: --lines {len(body) + 1}-]')

    def test_region_and_end_of_file(self):
        result = view(str(self.path), '--lines', '50-52')
        self.assertEqual(result.stdout.splitlines()[1:], ['50| line 050 ' + 'x' * 30, '51| line 051 ' + 'x' * 30,
                                                          '52| line 052 ' + 'x' * 30, '[lines 50-52 of 300; continues at line 53]'])
        tail = view(str(self.path), '--lines', '298-')
        self.assertEqual(tail.stdout.splitlines()[-1], '[lines 298-300 of 300; end of file]')
        beyond = view(str(self.path), '--lines', '400-')
        self.assertEqual((beyond.returncode, beyond.stdout.splitlines()[-1]), (0, '[no lines at 400-; the file ends at line 300]'))

    def test_budget_applies_within_a_requested_region(self):
        result = view(str(self.path), '--lines', '1-100', '--max-chars', '500')
        body = result.stdout.splitlines()[1:-1]
        self.assertLessEqual(sum(len(line) + 1 for line in body), 500)
        self.assertGreater(len(body), 0)
        self.assertEqual(result.stdout.splitlines()[-1], f'[lines 1-{len(body)} of 300; next: --lines {len(body) + 1}-100]')

    def test_digest_changes_with_content_and_errors_are_explicit(self):
        first = view(str(self.path)).stdout.splitlines()[0]
        self.path.write_text('changed\n')
        self.assertNotEqual(first, view(str(self.path)).stdout.splitlines()[0])
        missing = view(str(self.path.with_name('absent.py')))
        self.assertEqual(missing.returncode, 2)
        self.assertIn('absent.py', missing.stderr)
        self.assertEqual(view(str(self.path), '--lines', '5-3').returncode, 2)
        self.assertEqual(view(str(self.path), '--max-chars', '10').returncode, 2)


if __name__ == '__main__':
    unittest.main()
