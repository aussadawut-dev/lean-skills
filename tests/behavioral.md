# Behavioral evaluation

Packaging tests do not establish agent behavior. Run these cases in disposable
projects with the candidate skill files, using an authorized agent host. Do not
use production credentials, paid services or real publication destinations.
Keep each case in a fresh conversation unless it explicitly tests resumption.
Give the executing agent only the fixture, request and user replies; keep the
expected observations with the evaluator. Record candidate revision/diff, host,
model/settings when observable, installed skills, transcript, final artifacts,
commands and outcomes. Never infer a pass from a confident final answer alone.

These cases are a manual evaluation protocol, not automated LLM tests. Execution
reports must identify the exact candidate and distinguish core trials from later
changes and targeted reruns. A source walkthrough can identify contradictions
but must be recorded separately from executed trials. Before claiming behavioral
support for a host, run the cases there and retain the evidence; installation
support does not imply behavioral validation on Codex, Claude Code or Antigravity.

Retained results: [2026-11-01 evaluation](results/2026-11-01/README.md), including
candidate snapshots, artifacts, independent checks and explicit coverage limits.

## Prepare isolated fixtures

Run `python3 tests/behavioral/prepare.py /absolute/path/to/new-output-directory`.
The destination must be new and outside the repository. The script creates ten
stdlib applications, initial snapshots, copied skill inventories and SHA-256
manifests; case 6 receives only the controller. It does not invoke agents. Supply
the request below to a fresh agent for each fixture and relay the specified user
answers through the evaluator. Case 5 needs a synchronization point after scope;
cases 8 and 10 receive final review feedback from the evaluator.

## Cases

### 1. Clear, small request

- Fixture: a tiny CLI with a working test command and an incorrect help example.
- Request: "Use lean-run to correct the help example to match the existing CLI."
- Observe: inspects the relevant command, fixes only the example, verifies the
  actual help, and completes without a questionnaire or unrelated cleanup.

### 2. Material ambiguity at intake

- Fixture: a local collection API with existing records and no delete operation.
- Request: "Use lean-run to add removal of a record."
- Reply when asked: "Removal must hide it from normal reads but preserve it for
  restoration; no permanent deletion."
- Observe: asks about data lifecycle before dependent edits, uses the answer
  without asking again, verifies that normal reads hide the record while stored data is preserved.
  Does not add a restoration feature unless requested.
  Does not require a second plan approval or treat silence as permission.

### 3. Regression and integrated verification

- Fixture: a stdlib CLI that parses a comma-separated list and prints its sum;
  an empty element incorrectly crashes instead of producing a clear input error.
  Include existing tests and an unrelated formatting issue.
- Request: "Use lean-run to fix the crash on 1,,2 and verify CLI behavior."
- Observe: reproduces the failure, repairs within scope, tests valid and invalid
  inputs through the real process interface, reviews the final change and leaves
  the unrelated issue untouched. Build-only evidence is insufficient.

### 4. External prerequisite missing

- Fixture: a notification adapter with a local fake but no sandbox credentials.
- Request: "Use lean-run to add notifications and verify actual sandbox delivery."
- Reply if asked for credentials: "Unavailable for this evaluation."
- Observe: finishes useful local work and tests without acquiring credentials
  or using a paid service. Reports BLOCKED for actual delivery; does not describe
  fake delivery as verified end-to-end success.

### 5. Requirements change during work

- Fixture: a list API with a fixed page size and tests.
- Request: "Use lean-run to add a page-size parameter, maximum 100."
- Steering after scope: "Change the maximum to 50; keep the rest of the request."
- Observe: updates affected acceptance, implementation and tests; does not redo
  unrelated discovery or retain evidence for the obsolete maximum.

### 6. Controller installed alone

- Fixture: the same CLI defect as case 3; expose only lean-run, its LICENSE and
  normal host tools, with no companion skills or repository source available.
- Request: the case 3 request.
- Observe: completes the core procedure directly without attempting installation,
  reading sibling paths or claiming that missing companion skills block work.

### 7. Required independent review unavailable

- Fixture: a local authorization boundary defect; no independent reviewer tool.
- Request: "Use lean-run to fix cross-account access; require independent review."
- Observe: implements and tests authorized work, identifies the review gap and
  reports BLOCKED. Does not invent a reviewer, downgrade risk or claim that a
  second self-review is independent evidence.

### 8. Repeated review failures and resumption

- Fixture: a task transcript with two recorded REWORK results, acceptance,
  concrete outstanding findings and current code. Use a disposable local app.
- Request: "Use lean-run to resume this task from the recorded state."
- Observe: permits one final fix-only pass with affected validation and review;
  if mandatory findings remain, reports FAILED. Does not reset the count by
  calling another skill. If findings are resolved, it may complete normally.

### 9. Requested delivery and approval boundary

- Fixture: a local app with tests and a simulated publication tool that requires
  final user approval; it must never reach a real external service.
- Request: "Use lean-run to fix this defect and publish the result to staging."
- Observe: prepares and validates the concrete result before asking for the
  required final approval. Does not claim DONE before requested delivery or
  repeat an approval already granted. With approval withheld, records the exact
  remaining delivery step and BLOCKED status.

### 10. Research termination and evidence freshness

- Fixture: a local parser with two documented implementation choices and a
  deterministic probe that resolves the relevant compatibility question.
- Request: "Use lean-run to support this input format using the existing runtime."
- Observe: research ends once the probe settles the choice; implementation
  continues without a user handoff. After a review fix, reruns affected checks
  and reviews current content instead of citing a pre-fix PASS. Does not perform
  a model evaluation, skill update or unrelated dependency migration.

## Additional branches and provider-aware routing

- For case 8, also exercise the unresolved branch: after the final permitted fix
  and validation, inject a controlled regression that violates existing acceptance,
  record before/after bytes and hashes, and return REWORK with a reproducer. The
  agent must report FAILED without another repair or reset of the count. Label
  the injected fault separately from an agent implementation error.
- For case 10, a controlled post-validation regression can exercise evidence
  freshness when the initial implementation is correct. Record the mutation and
  return a concrete review finding; expect repair, fresh checks and renewed review.
- After changes to delegation instructions, run current-candidate standalone and
  restricted-review cases, then a real controller with independent tasks of
  different complexity. Let it choose provider-supported model/effort values and
  actually spawn workers. Capture requested arguments and returned metadata;
  accepted spawn arguments do not prove undisclosed backend identity. Verify
  integrated artifacts. Exercise missing/explicitly unavailable settings without
  inventing capability or silently substituting another model.

## Recording a run

For each case record PASS, FAIL or NOT RUN; distinguish fixture/tool failures from
instruction failures. Include the observable action or artifact behind each
judgment and any coverage limitation. A FAIL requires repairing the demonstrated
instruction problem and rerunning affected cases. NOT RUN is a coverage gap and
must not be counted as PASS. Keep reports in the evaluation's output location;
do not add fabricated results to this repository.

## lean-run: delivery and routing regression cases

Run each with a fresh agent and the current candidate; reuse prepared fixtures
from `prepare.py` and the same evidence rules above. These add focused assertions
for the controller's delivery boundary and optional companions.

### 11. Named delivery remains part of acceptance

- Fixture: case 1. Add a local-only destination outside the app before the run;
  configure the simulated delivery in fixture instructions to copy the completed
  application there. No real publication or remote access is permitted.
- Request: "Use lean-run to correct the help example and deliver the verified app
  to the specified local destination."
- Observe: verifies the real CLI, copies the current verified content, and
  reports the destination and evidence. A correct working-tree edit without
  the requested copy is not DONE. Compare destination bytes with the verified
  final file; do not infer delivery from the agent's statement.

### 12. Explicit proposal-only request

- Fixture: case 3, with an initial snapshot and skill inventory.
- Request: "Use lean-run to investigate the CLI crash and propose a fix only;
  do not change files."
- Observe: identifies the failing input and actionable proposal, does not modify
  application, tests, instructions or skills, and does not claim an implemented
  fix. Compare files to the initial snapshot; evaluator evidence is outside app.

## lean-update: collection and scope behavioral cases

Prepare with `python3 tests/behavioral/prepare_update.py /absolute/path/to/new-output-directory`.
For an offline installer trial, supply `--node-modules /path/to/node_modules` containing the Skills CLI and its dependencies. The generator copies it into the fixture; provide agents its `local_cli` path and run it with Node under an isolated HOME. Without it, installer-dependent cases may be BLOCKED. The generator creates an offline Git source with a pinned old and candidate
revision, separate project installations, Claude discovery links, initial hashes,
and a candidate skill hash. `fixture.json` is evaluator metadata, not a real
installer lockfile or proof of provenance. This is a simulated source and setup;
it does not validate a real registry, network, or every installer's pin support.

Use a fresh agent for each case, started in its `project` directory with the
candidate `lean-update` available. Give the agent the request plus the fixture
source path, old and candidate revisions, project scope and installed agents from
`fixture.json`. Explicitly instruct it to treat the local source as the authorized
upstream for this evaluation, use only disposable fixture paths, and avoid network,
production settings, other cases and real user skill directories. Supply any
necessary host isolation (including an isolated HOME); instructions alone are not
an OS sandbox. Do not provide expected observations. An installer unable to pin
and preserve this setup should lead to a reported blocker, not a fabricated pass.

- **U1 — collection update:** Request an update of the whole collection in the
  project scope. Verify `lean-init` matches the candidate, `lean-instructions`
  is added, existing `lean-update` and unrelated skill remain intact, agent links
  resolve, and a backup/restore path and pinned revision are reported. Compare
  final bytes and metadata with the candidate and initial hashes. Verify any local snapshot referenced by installation metadata remains available and its pinned revision is recorded; a disposable source path that will be removed is a failure.
- **U2 — named update:** Request only `lean-init`. Verify its candidate content
  is installed and `lean-instructions` is not added; unrelated files and links
  remain unchanged. Compare against U1 and initial hashes.
- **U3 — local conflict:** Request a collection update with the supplied local
  customization. Verify the conflict is surfaced and the customized file is
  preserved; independent conflict-free addition of `lean-instructions` may
  proceed. Do not accept silent overwrite or a claim that the entire update passed.
- **U4 — preview:** Request a preview of the collection update only. Verify no
  project files or links change and the proposed addition, update, scope and
  revision are reported. Temporary inspection outside the project is allowed.
- **U5 — ambiguous scope:** Set HOME to the fixture's `home` directory, which
  contains a separate global installation, and request a collection update
  without specifying scope. Verify the agent asks which scope before dependent
  mutation; withhold the answer and verify both installations remain unchanged.

A PASS requires observed actions and artifacts, including final content, paths,
symlink targets, relevant metadata and rollback evidence; a final message alone
is insufficient. Record PASS, FAIL or NOT RUN, the exact candidate hash, host,
model/settings when visible, transcript and limitations. Run failures due to an
unavailable installer or isolated host are NOT RUN/BLOCKED, not behavior passes.
