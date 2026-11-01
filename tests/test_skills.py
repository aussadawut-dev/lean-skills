"""Offline checks for independently distributable skills (stdlib only)."""
from pathlib import Path
import re
import shutil
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
NAMES = {
    'lean-init', 'lean-task', 'lean-scope', 'lean-research', 'lean-grill',
    'lean-agents', 'lean-review', 'lean-gate', 'lean-effort', 'lean-update',
    'lean-model-update', 'lean-target', 'lean-run', 'lean-instructions',
}


class SkillTests(unittest.TestCase):
    def test_complete_collection(self):
        self.assertEqual({p.name for p in (ROOT / 'skills').iterdir()}, NAMES)

    def test_companion_routes_resolve(self):
        text = (ROOT / 'skills/lean-run/SKILL.md').read_text()
        routes = set(re.findall(r'`(lean-[a-z-]+)`', text))
        self.assertEqual(routes, NAMES - {'lean-run'})

    def test_readme_skill_catalogs_and_local_links(self):
        for filename in ('README.md', 'README.th.md'):
            with self.subTest(readme=filename):
                text = (ROOT / filename).read_text()
                catalog = set(re.findall(r'\]\(skills/(lean-[a-z-]+)/SKILL\.md\)', text))
                self.assertEqual(catalog, NAMES)
                for link in re.findall(r'\]\(([^)]+)\)', text):
                    if '://' not in link and not link.startswith('#'):
                        self.assertTrue((ROOT / link.split('#')[0]).is_file(), link)

    def test_each_skill_can_be_distributed_alone(self):
        for name in sorted(NAMES):
            with self.subTest(skill=name), tempfile.TemporaryDirectory() as tmp:
                # Only this skill is present: no sibling skills or original repository.
                dest = Path(tmp) / name
                shutil.copytree(ROOT / 'skills' / name, dest, symlinks=True)
                self.assertFalse(any(p.is_symlink() for p in dest.rglob('*')))
                self.assertEqual((dest / 'LICENSE').read_bytes(), (ROOT / 'LICENSE').read_bytes())
                text = (dest / 'SKILL.md').read_text()
                parts = text.split('---\n', 2)
                self.assertEqual(parts[0], '')
                self.assertEqual(len(parts), 3)
                metadata = dict(line.split(': ', 1) for line in parts[1].splitlines())
                self.assertEqual(set(metadata), {'name', 'description', 'license'})
                self.assertEqual(metadata['name'], name)
                self.assertTrue(20 < len(metadata['description']) < 1024)
                self.assertEqual(metadata['license'], 'MIT')
                self.assertNotIn('TODO', text)
                self.assertNotRegex(text, r'\.lean/|\.lean\b|python3 .*bin/lean')
                # Named optional companions are allowed; packaged resources must
                # still resolve with this skill installed completely alone.
                for link in re.findall(r'\]\(([^)]+)\)', parts[2]):
                    if '://' in link or link.startswith('#'):
                        continue
                    target = (dest / link.split('#')[0]).resolve()
                    self.assertIn(dest.resolve(), target.parents)
                    self.assertTrue(target.is_file(), link)


if __name__ == '__main__':
    unittest.main()
