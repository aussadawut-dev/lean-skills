# lean-skills benchmark archives

This branch holds the complete `tests/results` tree of
[lean-skills](https://github.com/aussadawut-dev/lean-skills): every recorded
benchmark cohort with its workspaces, prompts, review transcripts, event logs,
probe outputs and hash manifests. It is an orphan branch so that installing the
skills, which shallow-clones the default branch, never downloads it.

Paths are identical to the default branch. There, `tests/results/README.md`
indexes the cohorts and each cohort folder keeps only the files its unit tests
read.

Restore one complete cohort into a checkout of the default branch:

```sh
git fetch origin benchmark-archives
git checkout origin/benchmark-archives -- tests/results/<cohort>
```

Each cohort's `archive-sha256.json` lists every file with its digest, and
`python3 tests/audit_repeated_benchmark.py tests/results/<cohort>` audits a
completed cohort against it. Add new cohorts with new commits; never rewrite
this branch.

Snapshot of `tests/results` at commit 8bf16f5 on `claude/lean-run-contract-gates`
(recorded 2026-11-05).
