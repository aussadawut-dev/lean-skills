"""Check that offline update-evaluation fixtures have the intended boundaries."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class UpdateFixturesTest(unittest.TestCase):
    def test_update_scenarios_are_isolated_and_distinguishable(self):
        with tempfile.TemporaryDirectory(prefix='lean-update-fixtures-') as tmp:
            out = Path(tmp) / 'evaluation'
            subprocess.run([sys.executable, str(ROOT / 'tests/behavioral/prepare_update.py'),
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
