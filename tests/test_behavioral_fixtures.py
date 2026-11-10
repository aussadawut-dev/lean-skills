"""Check that offline update-evaluation fixtures have the intended boundaries."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from test_skills import NAMES

ROOT = Path(__file__).resolve().parents[1]


class CoreFixturesTest(unittest.TestCase):
    def test_collection_and_standalone_fixture_discovery(self):
        with tempfile.TemporaryDirectory(prefix='lean-core-fixtures-') as tmp:
            out = Path(tmp) / 'evaluation'
            subprocess.run([sys.executable, str(ROOT / 'tests/fixtures/prepare.py'),
                            str(out)], check=True, capture_output=True, text=True)
            cases = sorted(out.glob('case-*'))
            self.assertEqual(len(cases), 10)
            for case in cases:
                expected = {'lean-run'} if case.name == 'case-06' else NAMES
                self.assertEqual({p.name for p in (case / 'skills').iterdir()}, expected)
                self.assertEqual((case / 'skills/lean-run/references/handoff.md').read_bytes(),
                                 (ROOT / 'skills/lean-run/references/handoff.md').read_bytes())
                self.assertTrue((case / 'manifest.json').is_file())


class UpdateFixturesTest(unittest.TestCase):
    def test_update_scenarios_are_isolated_and_distinguishable(self):
        with tempfile.TemporaryDirectory(prefix='lean-update-fixtures-') as tmp:
            out = Path(tmp) / 'evaluation'
            subprocess.run([sys.executable, str(ROOT / 'tests/fixtures/prepare_update.py'),
                            str(out)], check=True, capture_output=True, text=True)
            meta = json.loads((out / 'candidate.json').read_text())
            self.assertNotEqual(meta['old_fixture_revision'], meta['new_fixture_revision'])
            source = out / 'upstream'
            old_inventory = subprocess.check_output(
                ['git', '-C', str(source), 'ls-tree', '--name-only',
                 meta['old_fixture_revision'], 'skills/lean-instructions'], text=True)
            new_inventory = subprocess.check_output(
                ['git', '-C', str(source), 'ls-tree', '--name-only',
                 meta['new_fixture_revision'], 'skills/lean-instructions'], text=True)
            self.assertFalse(old_inventory.strip())
            self.assertTrue(new_inventory.strip())
            for name in ('collection', 'named', 'conflict', 'preview', 'scope'):
                base = out / name
                project = base / 'project'
                skills = project / '.agents/skills'
                self.assertFalse((skills / 'lean-instructions').exists())
                self.assertEqual((project / '.claude/skills/lean-init').resolve(),
                                 (skills / 'lean-init').resolve())
                self.assertIn('Fixture old revision.', (skills / 'lean-init/SKILL.md').read_text())
                self.assertTrue((base / 'initial.json').is_file())
                customized = 'Fixture local customization' in (skills / 'lean-init/SKILL.md').read_text()
                self.assertEqual(customized, name == 'conflict')
            self.assertTrue((out / 'scope/home/.agents/skills/lean-update/SKILL.md').is_file())
            self.assertTrue((out / 'scope/global-initial.json').is_file())
            self.assertFalse((out / 'named/home').exists())


if __name__ == '__main__':
    unittest.main()
