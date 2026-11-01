"""Real npx installs in both scopes: all skills, then each skill alone.

Requires Node/npm and registry access (or a cached skills@1.7.4).
Never uses the real agent home/configuration. No LLM calls are made.
"""
from pathlib import Path
import os
import subprocess
import tempfile

from test_skills import NAMES, ROOT

CLI = 'skills@1.7.4'


def main():
    with tempfile.TemporaryDirectory(prefix='lean-skills-smoke-') as tmp:
        scratch = Path(tmp)
        cases = [('all', sorted(NAMES))] + [(n, [n]) for n in sorted(NAMES)]
        for scope, label, names in [(scope, label, names)
                                    for scope in ('global', 'project') for label, names in cases]:
            home = scratch / f'{scope}-{label}'
            home.mkdir()
            project = home / 'empty-project'
            project.mkdir()
            global_sentinel = home / '.agents' / 'skills' / 'lean-review' / 'SKILL.md'
            if scope == 'project':
                global_sentinel.parent.mkdir(parents=True)
                global_sentinel.write_text('Existing global skill: preserve me.\n')
            # Isolate every agent config path, retaining only executable/network basics.
            env = {k: v for k, v in os.environ.items() if k in (
                'PATH', 'TMPDIR', 'SYSTEMROOT', 'HTTPS_PROXY', 'HTTP_PROXY',
                'ALL_PROXY', 'NO_PROXY', 'SSL_CERT_FILE', 'NODE_EXTRA_CA_CERTS')}
            env.update(HOME=str(home), USERPROFILE=str(home),
                       XDG_CONFIG_HOME=str(home / '.config'),
                       CODEX_HOME=str(home / '.codex'),
                       CLAUDE_CONFIG_DIR=str(home / '.claude'),
                       npm_config_cache=str(scratch / 'npm-cache'),
                       DISABLE_TELEMETRY='1', DO_NOT_TRACK='1', CI='1')
            source = ROOT if label == 'all' else ROOT / 'skills' / label
            command = ['npx', '--yes', CLI, 'add', str(source),
                       '--agent', 'codex', 'claude-code', 'antigravity',
                       '--skill', '*' if label == 'all' else label, '--yes']
            if scope == 'global':
                command.append('--global')
            result = subprocess.run(command, cwd=project, env=env, text=True,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120)
            if result.returncode:
                raise RuntimeError(f'{label}: installation failed\n{result.stdout}')
            destination = home if scope == 'global' else project
            canonical = destination / '.agents' / 'skills'
            installed = {p.name for p in canonical.iterdir() if (p / 'SKILL.md').is_file()}
            assert installed == set(names), (label, installed)
            # skills@1.7.4 uses the universal directory for Codex/Antigravity;
            # Claude Code gets discovery links to the same canonical files.
            for agent in ('Codex', 'Claude Code', 'Antigravity'):
                assert agent in result.stdout, (label, agent, result.stdout)
            for name in names:
                for filename in ('SKILL.md', 'LICENSE'):
                    expected = (ROOT / 'skills' / name / filename).read_bytes()
                    for base in (canonical, destination / '.claude' / 'skills'):
                        assert (base / name / filename).read_bytes() == expected, (label, base, name)
            if scope == 'global':
                assert not list(project.iterdir()), f'{label}: modified empty project'
            else:
                assert global_sentinel.read_text() == 'Existing global skill: preserve me.\n'
                assert {p.name for p in global_sentinel.parents[1].iterdir()} == {'lean-review'}
                assert not (home / '.claude' / 'skills').exists()
                assert not (home / '.codex' / 'skills').exists()
            assert not list(home.rglob('.lean')), f'{label}: created workflow directory'
            print(f'PASS {scope}/{label}: {len(names)} skill(s), content and scope isolation verified',
                  flush=True)


if __name__ == '__main__':
    main()
