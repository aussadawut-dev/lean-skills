---
name: lean-security
description: Assess a requested security concern or changed trust boundary with evidence-backed abuse cases, and verify authorized repairs within a bounded scope.
license: MIT
---

# lean-security

## Ground rules

- **Standalone.** Standalone skill: use the current request, project instructions and available tools.
- **No installation.** No companion, runtime or scanner installation is required.
- **When to apply.** Apply for a requested security review/hardening task or a consequential changed security boundary, not a blanket audit of unrelated work.
- **Depth.** Use standard procedure depth unless requested otherwise; deeper investigation does not change model settings or permission.

## Input and result

- **Input.** Establish the target repository/revision or service, protected assets, relevant change, intended security properties and requested endpoint: assessment, repair, or verification. Reuse the existing agreement.
- **Authorization.** A clear repair request authorizes matching local work; an assessment alone does not authorize application edits. Resolve missing material ownership/permission rules before dependent work.
- **Assessment result.** For an assessment, return PASS when the required bounded assessment is complete with no mandatory findings, REWORK for demonstrated mandatory violations, or BLOCKED/unverified for missing required coverage. Findings already established remain actionable even if another area is blocked.
- **PASS.** PASS is a statement about the assessed scope and evidence, not a guarantee that the whole application is secure.
- **Repair result.** For a requested repair, DONE requires the agreed security and valid-use behavior, current checks, required review and delivery destination. Missing prerequisites are BLOCKED; demonstrated unresolved mandatory failures are FAILED.
- **Report.** Give assessed state, findings/dispositions, probes and results, coverage limits and the exact next action. When used inside a larger workflow, return this result to its owner without starting a second scope or repair loop. Do not publish findings or deploy repairs without matching authorization.

## Steps

1. **Map the boundary.** Map the affected data, actors, entry points and trust transitions. Identify where authentication, authorization, validation and sensitive-data handling are enforced, including server-side checks. Use a compact map only as detailed as the task needs.
2. **Choose abuse cases.** Choose plausible abuse cases from that map: cross-account access, privilege escalation, untrusted input reaching an interpreter, credential/data exposure, or relevant lifecycle/recovery failures. Inspect relevant dependency/configuration risks when in scope; verify time-sensitive vulnerability claims against authoritative sources and affected versions. Do not infer exploitability from a keyword or scanner result alone.
3. **Trace and probe.** For each material concern, trace an input to its security consequence and use a bounded local probe or test when possible. Record prerequisites, expected versus observed behavior, affected location/revision and limitations. Test both an allowed case and a denied case where relevant. Label an unverified concern as such; absence of a reproduction is not proof of safety.
4. **Prioritize findings.** Prioritize findings by demonstrated impact and reachability. Distinguish introduced defects, pre-existing issues and explicitly accepted risks. Each actionable finding needs severity, location, violated property, evidence, conditions and a scoped repair or next probe. Redact credentials and unnecessary personal data from evidence.
5. **Repair and recheck.** For authorized remediation, make the bounded repair, add meaningful regression coverage and recheck the affected abuse and valid-use cases. Run required project checks on final content and review the final diff. Apply existing risk/quality rules: consequential security changes need fresh independent review; a fresh review-only invocation may supply that review, but the repair author cannot self-certify independence. Missing required independence is BLOCKED. Preserve the controller's repair count; after the second REWORK allow one final fix-only pass with renewed checks/review, then stop with unresolved failures.

## Limits

- **Local first.** Use local source, configuration and controlled test data first.
- **Active probes.** Active probes must stay within the authorized target and environment; do not test other tenants, expose secrets, contact external systems or use real user data merely to prove a finding.
- **Tools.** Inspect tools before execution; missing scanners are not a reason to install dependencies or skip reasoning.
- **Missing access.** Report unavailable required access/checks explicitly.
