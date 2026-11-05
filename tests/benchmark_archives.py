"""Pack, verify, restore and prune the raw benchmark cohorts kept outside the tree.

Each cohort under tests/results/ keeps its reports (README.md or
coordinator-notes.md, summary.json, manifest.json, comparison.csv) and its hash
manifest archive-sha256.json in the repository. Everything else is published as
one tarball per cohort, built from the git revision that last held the raw
files. The hash manifest lets anyone verify a restored cohort file by file.

  python3 tests/benchmark_archives.py pack --revision REV --out DIR [NAME ...]
  python3 tests/benchmark_archives.py verify [--kept] [NAME ...]
  python3 tests/benchmark_archives.py restore NAME --source FILE|URL|DIR
  python3 tests/benchmark_archives.py prune [NAME ...]
  python3 tests/benchmark_archives.py manifest NAME

Standard library only; no model calls.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / 'tests/results'
MANIFEST = 'archive-sha256.json'
KEPT = ('README.md', 'coordinator-notes.md', 'summary.json', 'manifest.json', 'comparison.csv', MANIFEST)
RELEASE = 'https://github.com/aussadawut-dev/lean-skills/releases/download/benchmark-archives-2026-11-05/'


def digest(root):
    """sha256 of every file under root, keyed by relative path; bytecode caches excluded."""
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob('*')) if path.is_file() and '__pycache__' not in path.parts}


def cohorts(names=()):
    found = sorted(path.name for path in RESULTS.iterdir() if path.is_dir() and (path / MANIFEST).is_file())
    unknown = sorted(set(names) - set(found))
    if unknown:
        raise SystemExit(f'No hash manifest for: {", ".join(unknown)}')
    return list(names) or found


def verify(name, root=None, kept=False):
    """Compare a cohort directory with its hash manifest.

    A full verification requires every recorded file with its recorded hash and
    nothing else. With kept=True only the committed subset is checked: each
    present file must match, and the missing raw files are counted.
    """
    root = Path(root or RESULTS / name)
    expected = json.loads((root / MANIFEST).read_text())
    actual = digest(root)
    actual.pop(MANIFEST, None)
    changed = sorted(path for path in expected if path in actual and actual[path] != expected[path])
    extra = sorted(set(actual) - set(expected))
    missing = sorted(set(expected) - set(actual))
    if kept:
        problems = changed + extra
        status = 'PASS' if not problems else 'FAIL'
        print(f'{status} {name}: {len(actual)} kept files match; {len(missing)} archived files not present'
              + (f'; changed {changed}; unexpected {extra}' if problems else ''))
        return not problems
    problems = changed or extra or missing
    status = 'PASS' if not problems else 'FAIL'
    print(f'{status} {name}: {len(expected)} files' + ('' if not problems else
          f'; changed {changed[:5]}; unexpected {extra[:5]}; missing {missing[:5]}'))
    return not problems


def pack(revision, out, names):
    """One reproducible tarball per cohort from a git revision, verified against the manifest."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    sums = []
    for name in names:
        target = out / f'{name}.tar.gz'
        with target.open('wb') as stream:
            subprocess.run(['git', 'archive', '--format=tar.gz', f'--prefix={name}/', f'{revision}:tests/results/{name}'],
                           cwd=ROOT, stdout=stream, check=True)
        with tempfile.TemporaryDirectory(prefix='lean-archive-check-') as temporary:
            extract(target, Path(temporary), name)
            restored = Path(temporary) / name
            if not (restored / MANIFEST).is_file():
                shutil.copyfile(RESULTS / name / MANIFEST, restored / MANIFEST)
            if not verify(name, restored):
                raise SystemExit(f'{name}: the packed tree does not match {MANIFEST}')
            files = len(digest(restored))
            raw = sum(path.stat().st_size for path in restored.rglob('*') if path.is_file())
        checksum = hashlib.sha256(target.read_bytes()).hexdigest()
        sums.append((checksum, target.name, files, raw, target.stat().st_size))
        print(f'{name}: {files} files, {raw / 1048576:.1f} MB raw, {target.stat().st_size / 1048576:.2f} MB packed, sha256 {checksum}')
    (out / 'SHA256SUMS').write_text(''.join(f'{checksum}  {filename}\n' for checksum, filename, *_ in sums))
    return sums


def extract(archive, destination, name):
    """Extract NAME/... members only, with the data filter when the interpreter has it."""
    with tarfile.open(archive) as tar:
        members = [member for member in tar.getmembers() if member.name.startswith(name + '/')]
        if not members:
            raise SystemExit(f'{archive} holds no {name}/ entries')
        if hasattr(tarfile, 'data_filter'):
            tar.extractall(destination, members, filter='data')
        else:
            tar.extractall(destination, members)


def restore(name, source):
    """Restore a cohort into tests/results/NAME from a tarball, URL or directory, then verify it."""
    destination = RESULTS / name
    manifest = (destination / MANIFEST).read_bytes()
    with tempfile.TemporaryDirectory(prefix='lean-archive-restore-') as temporary:
        staged = Path(temporary) / name
        if '://' in str(source):
            with urllib.request.urlopen(str(source)) as response:
                data = response.read()
            extract(io.BytesIO(data), Path(temporary), name)
        elif Path(source).is_dir():
            shutil.copytree(source, staged, ignore=shutil.ignore_patterns('__pycache__'))
        else:
            extract(Path(source), Path(temporary), name)
        (staged / MANIFEST).write_bytes(manifest)
        if not verify(name, staged):
            raise SystemExit(f'{name}: restored files do not match the committed {MANIFEST}; nothing changed')
        shutil.rmtree(destination)
        shutil.move(str(staged), str(destination))
    print(f'restored {destination}')


def manifest(name):
    """Write archive-sha256.json for a cohort that was archived without one."""
    root = RESULTS / name
    if (root / MANIFEST).is_file():
        raise SystemExit(f'{name} already has {MANIFEST}')
    hashes = digest(root)
    (root / MANIFEST).write_text(json.dumps(hashes, indent=2) + '\n')
    print(f'{name}: recorded {len(hashes)} files in {MANIFEST}')


def prune(name):
    """Keep only the committed report files of a cohort."""
    root = RESULTS / name
    removed = 0
    for path in sorted(root.rglob('*'), reverse=True):
        if path.is_file() and (path.parent != root or path.name not in KEPT):
            path.unlink()
            removed += 1
        elif path.is_dir() and not any(path.iterdir()):
            path.rmdir()
    print(f'{name}: removed {removed} files; kept {sorted(p.name for p in root.iterdir())}')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='command', required=True)
    command = commands.add_parser('pack', help='build one tarball per cohort from a git revision')
    command.add_argument('--revision', required=True, help='git revision that holds the raw cohort files')
    command.add_argument('--out', required=True, type=Path)
    command.add_argument('names', nargs='*')
    command = commands.add_parser('verify', help='check cohorts against their hash manifests')
    command.add_argument('--kept', action='store_true', help='check only the committed subset')
    command.add_argument('names', nargs='*')
    command = commands.add_parser('restore', help='put the raw files of one cohort back under tests/results')
    command.add_argument('name')
    command.add_argument('--source', help=f'tarball path, directory or URL; default {RELEASE}NAME.tar.gz')
    command = commands.add_parser('prune', help='remove everything but the committed report files')
    command.add_argument('names', nargs='*')
    command = commands.add_parser('manifest', help='write a hash manifest for a cohort archived without one')
    command.add_argument('name')
    args = parser.parse_args(argv)
    if args.command == 'pack':
        pack(args.revision, args.out, cohorts(args.names))
    elif args.command == 'verify':
        results = [verify(name, kept=args.kept) for name in cohorts(args.names)]
        return 0 if all(results) else 1
    elif args.command == 'restore':
        restore(args.name, args.source or f'{RELEASE}{args.name}.tar.gz')
    elif args.command == 'manifest':
        manifest(args.name)
    else:
        for name in cohorts(args.names):
            prune(name)
    return 0


if __name__ == '__main__':
    sys.exit(main())
