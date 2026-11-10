"""Create offline, disposable lean-update agent-evaluation fixtures; no agent calls."""
from pathlib import Path
import argparse
import hashlib
import json
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('destination', type=Path, help='New output directory outside the repository')
parser.add_argument('--node-modules', type=Path, help='Optional local node_modules containing the Skills CLI and its dependencies; copied into the fixture')
args = parser.parse_args()
out = args.destination.resolve()
if out == ROOT or ROOT in out.parents or out.exists():
    parser.error('Destination must be new and outside the repository')
out.mkdir(parents=True)
if args.node_modules:
    modules = args.node_modules.resolve()
    if not (modules / 'skills/bin/cli.mjs').is_file():
        parser.error('node_modules must contain skills/bin/cli.mjs')
    shutil.copytree(modules, out / 'tools/node_modules', symlinks=True)


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args], text=True).strip()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


source = out / 'upstream'
source.mkdir()
subprocess.run(['git', 'init', '-q', str(source)], check=True)
git(source, 'config', 'user.name', 'Fixture')
git(source, 'config', 'user.email', 'fixture@example.invalid')
(source / 'skills').mkdir()
for name in ('lean-update', 'lean-init', 'lean-instructions'):
    shutil.copytree(ROOT / 'skills' / name, source / 'skills' / name)
# A deterministic older candidate, without altering the real source.
with (source / 'skills/lean-init/SKILL.md').open('a') as f:
    f.write('\nFixture old revision.\n')
shutil.rmtree(source / 'skills/lean-instructions')
git(source, 'add', '.')
git(source, 'commit', '-qm', 'old fixture')
old = git(source, 'rev-parse', 'HEAD')
shutil.copytree(ROOT / 'skills/lean-instructions', source / 'skills/lean-instructions')
shutil.copyfile(ROOT / 'skills/lean-init/SKILL.md', source / 'skills/lean-init/SKILL.md')
git(source, 'add', '.')
git(source, 'commit', '-qm', 'new fixture')
new = git(source, 'rev-parse', 'HEAD')

for case in ('collection', 'named', 'conflict', 'preview', 'scope'):
    base = out / case
    project = base / 'project'
    installed = project / '.agents/skills'
    installed.mkdir(parents=True)
    for name in ('lean-update', 'lean-init'):
        shutil.copytree(source / 'skills' / name, installed / name)
    # Existing lean-init is at the old revision, with an optional local edit.
    (installed / 'lean-init/SKILL.md').write_text(git(source, 'show', f'{old}:skills/lean-init/SKILL.md') + '\n')
    if case == 'conflict':
        with (installed / 'lean-init/SKILL.md').open('a') as f:
            f.write('\nFixture local customization: preserve this line.\n')
    links = project / '.claude/skills'
    links.mkdir(parents=True)
    for name in ('lean-update', 'lean-init'):
        (links / name).symlink_to(Path('../../.agents/skills') / name)
    # A deliberately separate unrelated directory must remain untouched.
    (installed / 'unrelated').mkdir()
    (installed / 'unrelated/SKILL.md').write_text('Unrelated skill: preserve exactly.\n')
    if case == 'scope':
        global_skills = base / 'home/.agents/skills'
        global_skills.mkdir(parents=True)
        shutil.copytree(installed / 'lean-update', global_skills / 'lean-update')
        (base / 'global-initial.json').write_text(json.dumps({
            str(p.relative_to(base / 'home')): digest(p)
            for p in (base / 'home').rglob('*') if p.is_file()
        }, indent=2, sort_keys=True) + '\n')
    (base / 'fixture.json').write_text(json.dumps({
        'source': str(source), 'old_revision': old, 'candidate_revision': new,
        'scope': 'project', 'agents': ['codex', 'claude-code'],
        'local_cli': str(out / 'tools/node_modules/skills/bin/cli.mjs') if args.node_modules else None,
        'note': 'Fixture metadata for evaluator; not installer provenance.'
    }, indent=2) + '\n')
    initial = {str(p.relative_to(project)): digest(p) for p in project.rglob('*') if p.is_file()}
    (base / 'initial.json').write_text(json.dumps(initial, indent=2, sort_keys=True) + '\n')

(out / 'candidate.json').write_text(json.dumps({
    'repository_head': git(ROOT, 'rev-parse', 'HEAD'),
    'skill_sha256': digest(ROOT / 'skills/lean-update/SKILL.md'),
    'old_fixture_revision': old, 'new_fixture_revision': new,
    'note': 'Use skill hash to identify uncommitted candidate content.'
}, indent=2) + '\n')
print(out)
