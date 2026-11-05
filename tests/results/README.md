# Benchmark and evaluation archives

The dated folders here are the measured cohorts and evaluation reports that
[README.md](../../README.md) and [tests/benchmark/README.md](../benchmark/README.md)
cite. Each folder keeps only its report (`README.md` or `coordinator-notes.md`),
`summary.json`, `manifest.json`, `comparison.csv` and `archive-sha256.json` in the
repository: 70 files, 1.4 MB. The raw files (initial fixtures, prompts, event
logs, workspaces, review outputs, probe scripts and reports: 8,174 files,
78 MB) are packed as one tarball per cohort, 11.7 MB in all. Their home is the
GitHub release `benchmark-archives-2026-11-05` of this repository; a maintainer
uploads the tarballs there with the command under *Verify, restore, pack*, and
`restore` downloads from it by default. The tarballs were built from commit
`8bf16f59ad610ac7ff5f19b595deb706cbde3ed3`, the last revision that held every
raw file in the tree. Keep that commit reachable (merge rather than squash) or
upload the release assets first, because the tarballs are rebuilt from it.

`npx skills add aussadawut-dev/lean-skills` clones this repository with
`--depth 1`; the archives no longer travel with that clone.

## Verify, restore, pack

`archive-sha256.json` lists the sha256 of every raw file of its cohort, itself
excluded. It is the verification source for a downloaded archive; the tarball
hashes below only identify the files uploaded to the release.

```bash
python3 tests/benchmark_archives.py verify --kept
```

checks that the committed files still match their recorded hashes.

```bash
python3 tests/benchmark_archives.py restore 2026-11-04-lean-run-critical-high
```

downloads that cohort's tarball from the release (or takes `--source` with a
local tarball, a directory or another URL), verifies every file against the
committed manifest and only then replaces the folder. `verify` without `--kept`
then requires the complete tree. `prune NAME` returns a restored folder to the
committed subset. A restored cohort is also what
`tests/repeated_benchmark.py prepare --baseline` needs; a pruned folder is
refused with a message that points here.

```bash
python3 tests/benchmark_archives.py pack --revision 8bf16f59ad610ac7ff5f19b595deb706cbde3ed3 --out dist
```

rebuilds the tarballs from git history and verifies each against its manifest
before writing `dist/SHA256SUMS`. Seven early folders were archived without a
manifest; theirs were generated from that same commit with
`python3 tests/benchmark_archives.py manifest NAME`, so every cohort verifies.

Publishing or refreshing the release is a maintainer step:

```bash
gh release create benchmark-archives-2026-11-05 dist/*.tar.gz dist/SHA256SUMS \
  --title "Benchmark archives (2026-11-05)" --notes "Raw cohort files; see tests/results/README.md"
```

Links inside a cohort report that point beyond its kept files resolve only
after that cohort is restored. The probe scripts that the cohorts froze are
also kept as current code in [`tests/probes/`](../probes/). The unit tests do
not read these folders: they build a synthetic lineage with
[`tests/synthetic_cohorts.py`](../synthetic_cohorts.py).

## Cohorts

| Cohort | Raw files | Raw MB | Tarball MB | Tarball sha256 |
| --- | ---: | ---: | ---: | --- |
| [2026-11-01](2026-11-01/README.md) | 23 | 0.3 | 0.07 | `bcb1f1d7c86a490f…` |
| [2026-11-01-compression](2026-11-01-compression/README.md) | 2 | 0.0 | 0.00 | `82c7ce5ae1333307…` |
| [2026-11-01-naming](2026-11-01-naming/README.md) | 10 | 0.1 | 0.01 | `903c1d9797cec4e0…` |
| [2026-11-01-update-behavior](2026-11-01-update-behavior/README.md) | 1 | 0.0 | 0.00 | `19f5c60ef18fa57c…` |
| [2026-11-02-scope-completion](2026-11-02-scope-completion/README.md) | 3 | 0.1 | 0.04 | `6ea37f49fc00ee90…` |
| [2026-11-03-lean-run-critical-medium](2026-11-03-lean-run-critical-medium/README.md) | 1228 | 8.9 | 1.69 | `04b6f75f523e3d82…` |
| [2026-11-03-lean-run-optimized](2026-11-03-lean-run-optimized/README.md) | 247 | 1.5 | 0.32 | `aff10eb545dc18be…` |
| [2026-11-03-lean-run-repeated](2026-11-03-lean-run-repeated/README.md) | 1376 | 8.7 | 1.85 | `e60998eab6dad5e1…` |
| [2026-11-03-level-benchmark](2026-11-03-level-benchmark/README.md) | 196 | 1.5 | 0.33 | `a6d2048a0f3f1f4e…` |
| [2026-11-03-v57-log-analysis](2026-11-03-v57-log-analysis/README.md) | 13 | 0.5 | 0.07 | `b95bb582520b9c40…` |
| [2026-11-04-lean-run-critical-high](2026-11-04-lean-run-critical-high/README.md) | 1383 | 14.8 | 1.95 | `ade1ccd59da74b8c…` |
| [2026-11-04-lean-run-critical-high-pilot](2026-11-04-lean-run-critical-high-pilot/README.md) | 415 | 5.1 | 0.63 | `d73842c4097ed152…` |
| [2026-11-04-lean-run-critical-speed](2026-11-04-lean-run-critical-speed/README.md) | 1269 | 10.3 | 1.65 | `74298ac7fc0bfcf2…` |
| [2026-11-04-lean-run-in-source-budget](2026-11-04-lean-run-in-source-budget/README.md) | 463 | 5.5 | 0.71 | `4e7dfde53c81f0e8…` |
| [2026-11-04-rls-policy-development](2026-11-04-rls-policy-development/README.md) | 13 | 0.1 | 0.02 | `fd30db352e73c4fc…` |
| [2026-11-05-lean-run-contract-gates](2026-11-05-lean-run-contract-gates/README.md) | 494 | 7.4 | 0.82 | `6a098badd0b946d3…` |
| [2026-11-05-lean-run-rls-baseline](2026-11-05-lean-run-rls-baseline/README.md) | 388 | 4.6 | 0.56 | `8b09a4fa3f16d7b0…` |
| [2026-11-05-lean-run-rls-critical-rerun](2026-11-05-lean-run-rls-critical-rerun/README.md) | 145 | 2.0 | 0.22 | `a67b74337994d9da…` |
| [2026-11-05-lean-run-schema-skill](2026-11-05-lean-run-schema-skill/coordinator-notes.md) | 505 | 6.9 | 0.77 | `23948ec1166ade40…` |

Full tarball hashes (git 2.43.0 on Linux; another git or zlib may compress
the same verified tree to different bytes):

```
bcb1f1d7c86a490f593dd5eeac32b7c4fedf4133a076cc51051dffe13e366a71  2026-11-01.tar.gz
82c7ce5ae13333074b46121136732d9a6d83ed79a025acf207d9b65a269669c6  2026-11-01-compression.tar.gz
903c1d9797cec4e09b0e86ad3fdb3b3bab03c7a29ed4e98ad690b4f7449c3e5d  2026-11-01-naming.tar.gz
19f5c60ef18fa57c88750e7f040f6645b9073f09053e16028072bf073d19a928  2026-11-01-update-behavior.tar.gz
6ea37f49fc00ee902be8a383aa67acbb7e67b2dcda5931399803a9ea98819039  2026-11-02-scope-completion.tar.gz
04b6f75f523e3d827ccd66df97110b9aa116e63102e93c7de047332614cfc8e2  2026-11-03-lean-run-critical-medium.tar.gz
aff10eb545dc18be2dcec3d33cdfa2a7354381c8e05b002ac11e4cd210a872d6  2026-11-03-lean-run-optimized.tar.gz
e60998eab6dad5e10561c814f259d1073a25f70a21da553a7fa88fb8bd477b73  2026-11-03-lean-run-repeated.tar.gz
a6d2048a0f3f1f4e0f9b190b67537b14a264ac4038ba8d14c8d208d6583af59d  2026-11-03-level-benchmark.tar.gz
b95bb582520b9c40417699cd3700f2a7960ffa7fcb98455e4f52a361cf8cc5af  2026-11-03-v57-log-analysis.tar.gz
ade1ccd59da74b8c6d1f38571b1d2eb8ab5c14074a0e302c3e93ac864de73ce6  2026-11-04-lean-run-critical-high.tar.gz
d73842c4097ed1528dca0c6e32648773d82dd3c9a4b0ce7409a918f0074ef5fa  2026-11-04-lean-run-critical-high-pilot.tar.gz
74298ac7fc0bfcf2af0e16169221a634e85dc9c7a4bd7d58f4b022622aba3194  2026-11-04-lean-run-critical-speed.tar.gz
4e7dfde53c81f0e8d105355e883ba70f0db9de96fb671e414e46cd8c9d42d612  2026-11-04-lean-run-in-source-budget.tar.gz
fd30db352e73c4fc804c454e79bb218875a65835cb575a2494a3cde05120f7c6  2026-11-04-rls-policy-development.tar.gz
6a098badd0b946d313ba985c4c6b5d75ab3afbc137fa61228608a4ff9721be2b  2026-11-05-lean-run-contract-gates.tar.gz
8b09a4fa3f16d7b0c99c3ab6f3d5f2c22724977ae11eba65d41e98a8f5144cfa  2026-11-05-lean-run-rls-baseline.tar.gz
a67b74337994d9da8f0c686b048d4685e9b21837ad87c9d31b33264e45077c8a  2026-11-05-lean-run-rls-critical-rerun.tar.gz
23948ec1166ade4039faa356baa3060c4d16592af52128f4c68eed068e561bd9  2026-11-05-lean-run-schema-skill.tar.gz
```
