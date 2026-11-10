# Recorded results

An index of every recorded evaluation and benchmark, and where its evidence lives.

## What it does

Results come in two kinds, so they live in two places:

- **Evaluation reports** are small and kept here, complete.
- **`lean-run` benchmark cohorts** are large: about 8,000 files and 78 MB in full. The Skills
  CLI shallow-clones the default branch on every install, so they live only on the
  [`benchmark-archives`](https://github.com/aussadawut-dev/lean-skills/tree/benchmark-archives)
  branch, under `tests/results/`. Narratives, logs, review transcripts and
  `archive-sha256.json` are there.

## Evaluation reports

| Folder | Record | Outcome |
| --- | --- | --- |
| 2026-11-01 | Behavioral evaluation: ten core Codex scenarios plus targeted trials | see [report](2026-11-01/README.md) |
| 2026-11-01-naming | Live subagent naming checks on Claude Code and Antigravity | see [report](2026-11-01-naming/README.md) |
| 2026-11-01-compression, 2026-11-01-update-behavior | Instruction compression and update-behavior notes | see [compression](2026-11-01-compression/README.md) and [update behavior](2026-11-01-update-behavior/README.md) |
| 2026-11-02-scope-completion | Five fresh Codex runs for security, release, diagnosis, UX scope and handoff | see [report](2026-11-02-scope-completion/README.md) |

These reports kept their original wording, so paths inside them (`tests/behavioral.md`,
`tests/results/...`) refer to the layout at the time. Today those are
[docs/evaluation.md](../evaluation.md) and this folder.

## Benchmark cohorts

Oldest first. Each outcome is the cohort's own first line. **None met its requested
optimization target.**

| Folder | Record | Outcome |
| --- | --- | --- |
| [2026-11-03-level-benchmark](https://github.com/aussadawut-dev/lean-skills/blob/benchmark-archives/tests/results/2026-11-03-level-benchmark/README.md) | One measured attempt per level | medium and high passed first review; critical needed one repair |
| [2026-11-03-lean-run-optimized](https://github.com/aussadawut-dev/lean-skills/blob/benchmark-archives/tests/results/2026-11-03-lean-run-optimized/README.md) | Shortened entrypoint before/after | time -3.02%, tokens -9.21%, same outcomes |
| [2026-11-03-v57-log-analysis](https://github.com/aussadawut-dev/lean-skills/blob/benchmark-archives/tests/results/2026-11-03-v57-log-analysis/README.md) | Log analysis against native v5.7 (Thai) | analysis only |
| [2026-11-03-lean-run-repeated](https://github.com/aussadawut-dev/lean-skills/blob/benchmark-archives/tests/results/2026-11-03-lean-run-repeated/README.md) | Three repeats per level | target NOT MET; 7/9 passed |
| [2026-11-03-lean-run-critical-medium](https://github.com/aussadawut-dev/lean-skills/blob/benchmark-archives/tests/results/2026-11-03-lean-run-critical-medium/README.md) | Critical integrity and Medium implementation | target NOT MET; 7/9 passed |
| [2026-11-04-lean-run-critical-high-pilot](https://github.com/aussadawut-dev/lean-skills/blob/benchmark-archives/tests/results/2026-11-04-lean-run-critical-high-pilot/README.md) | High and Critical pilot | target not met; 1/2 passed |
| [2026-11-04-lean-run-critical-high](https://github.com/aussadawut-dev/lean-skills/blob/benchmark-archives/tests/results/2026-11-04-lean-run-critical-high/README.md) | Critical completion and High workflow time | target NOT MET; 6/9 passed |
| [2026-11-04-lean-run-critical-speed](https://github.com/aussadawut-dev/lean-skills/blob/benchmark-archives/tests/results/2026-11-04-lean-run-critical-speed/README.md) | Critical speed and integrity | target NOT MET; 8/9 passed |
| [2026-11-04-lean-run-in-source-budget](https://github.com/aussadawut-dev/lean-skills/blob/benchmark-archives/tests/results/2026-11-04-lean-run-in-source-budget/README.md) | SQL-source and phase-budget pilot | target not met; 1/2 passed |
| [2026-11-04-rls-policy-development](https://github.com/aussadawut-dev/lean-skills/blob/benchmark-archives/tests/results/2026-11-04-rls-policy-development/README.md) | Row-level-security policy record, prototype and superseded expectations | policy record, not a measured trial |
| [2026-11-05-lean-run-rls-baseline](https://github.com/aussadawut-dev/lean-skills/blob/benchmark-archives/tests/results/2026-11-05-lean-run-rls-baseline/README.md) | First RLS contract | High DONE; Critical protocol-invalid |
| [2026-11-05-lean-run-rls-critical-rerun](https://github.com/aussadawut-dev/lean-skills/blob/benchmark-archives/tests/results/2026-11-05-lean-run-rls-critical-rerun/README.md) | Critical rerun with corrected RLS wording | stopped after the first assessment |
| [2026-11-05-lean-run-contract-gates](https://github.com/aussadawut-dev/lean-skills/blob/benchmark-archives/tests/results/2026-11-05-lean-run-contract-gates/README.md) | First cohort under the contract gate policy | High DONE; Critical FAILED |
| [2026-11-05-lean-run-schema-skill](https://github.com/aussadawut-dev/lean-skills/blob/benchmark-archives/tests/results/2026-11-05-lean-run-schema-skill/README.md) | Second cohort under that policy | High DONE; Critical FAILED |

### Restore a cohort

```sh
git fetch origin benchmark-archives
git checkout origin/benchmark-archives -- tests/results/<cohort>
```

Auditing or extending a cohort also needs the benchmark harness; see
[Benchmarks](../evaluation.md#benchmarks) for how to restore it.
