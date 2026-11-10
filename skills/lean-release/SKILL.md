---
name: lean-release
description: Plan or execute an authorized application release or rollback with verified artifacts, migration safety, health checks and evidence-backed recovery.
license: MIT
---

# lean-release

## Ground rules

- **Standalone.** Standalone skill: follow the request, project instructions and actual deployment tools.
- **No installation.** No provider, runtime or companion is required.
- **Reuse.** Reuse existing acceptance, validation and authorization.
- **Depth.** Procedure depth defaults to standard and does not alter model settings or permissions.

## Input and result

- **Input.** Input is the application, requested version/artifact, target environment and endpoint: plan, release or recovery. Identify the exact source revision plus pending changes or immutable artifact, destination/account/environment, current deployed state and requested outcome. Resolve ambiguous targets before mutation.
- **Authorization.** A plan-only request ends with a plan. An explicit release request authorizes matching work; ask again only for a genuinely missing material decision or approval required by the user, project or tool.
- **READY.** A complete, actionable plan is READY with exact target/artifact, steps, checks, recovery strategy and outstanding prerequisites.
- **BLOCKED plan.** A plan with an indispensable unresolved decision is BLOCKED with completed planning and the needed answer; unavailable execution credentials do not block a plan that does not require them.
- **DONE.** A release or requested rollback is DONE only when that endpoint's mandatory artifact, target, health, data and delivery conditions have current evidence.
- **BLOCKED and FAILED.** Missing prerequisites are BLOCKED; an executed endpoint with unresolved demonstrated failure is FAILED.
- **Failed release.** A failed release followed by successful rollback is FAILED for the release, with recovery separately DONE; it does not satisfy shipping the requested version.
- **Report.** Report requested and resulting versions/environment, commands/operation IDs, checks and outcomes, migration/recovery state, observation limits and next action. When a controller owns the larger task, return this evidence and preserve its repair budget. Keep release notes or a continuation record in an existing agreed location; do not create workflow files, commit, tag, push or publish documentation as incidental steps.

## Steps

1. **Verify the artifact.** Verify the candidate artifact is the one tested and reviewed, and required checks cover its current content. Preflight the target's configuration, dependencies, permissions and capacity only as relevant to this release. Distinguish local simulation, staging evidence and live target evidence.
2. **Define success and recovery.** Define observable success/failure criteria, a bounded observation window and who/what can initiate recovery. Establish the last known good version and a usable recovery path before a risky mutation. Respect existing release mechanisms such as staged rollout or feature flags without imposing new infrastructure.
3. **Check data changes.** For schema/data changes, identify compatibility with both old and new application versions, sequencing, expected data invariants and whether the migration can safely be rerun. Verify required backup/recovery capability and a representative migration check when relevant. State irreversible effects. Permission to roll back code does not authorize destructive data restoration; obtain any missing material decision before dependent work. Use a forward repair when reversing data would violate the agreed recovery constraints.
4. **Execute authorized steps.** Execute only the authorized release steps, recording operation identifiers and actual state. If a command times out, disconnects or returns an uncertain result, inspect deployment state before retrying; do not issue a duplicate mutation based on missing output. Retry only for a new, supported cause within project/controller limits. Preserve denied actions and report the exact unmet permission.
5. **Verify the target.** Verify the actual target serves the requested version and exercise the relevant user/API journey, important failure checks and agreed health signals through the observation window. A successful deploy command alone is not release success. Report unavailable monitoring, simulated boundaries and remaining acceptance. Do not start ongoing monitoring or a new schedule unless requested.
6. **Recover on failure.** If release criteria fail, preserve evidence and use the already authorized recovery path when safe. If recovery is not authorized or its data effects differ from the plan, stop the dependent mutation and give the concrete decision needed. Verify restored service and data invariants after recovery; report the actual resulting version. Do not treat a rollback command's exit code as proof of restored service.

## Limits

- **Commands.** Use project deployment instructions and inspect unfamiliar commands.
- **Preserve.** Preserve unrelated work, existing releases and secrets.
- **Nothing implicit.** Never substitute production for an unavailable staging environment, publish an unverified build, change provider settings or spend money implicitly.
- **Missing access.** Missing credentials/access should produce a concrete prerequisite, not a credential search outside the authorized context.
