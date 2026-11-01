---
name: lean-research
description: Compare meaningful technical approaches using traceable evidence and recommend by the user’s actual constraints.
license: MIT
---

# lean-research

This is a standalone skill. Use the current request or explicit invocation arguments as input. Read existing project instructions and only the context needed for this task. No Lean installation, CLI, configuration, or other skill is required. Do not install a workflow or create workflow files as a prerequisite. Existing project rules still apply.

Use the user's requested procedure depth; otherwise use standard depth. High adds boundary cases and stronger evidence; ultra adds cross-part consistency and contradictory evidence where relevant. Depth does not change model reasoning settings. Keep decisions in the conversation unless the project already has a suitable record or the user requests persistence.

1. State the decision question, constraints and stopping condition: what evidence would be sufficient to choose or expose a concrete blocker. Read relevant local code and documentation before widening the search. Include the current approach or no change when it is a real option.
2. Build a bounded shortlist of meaningfully different approaches, usually two to five. Compare each against the same decision-relevant criteria rather than arbitrary numerical scores.
3. Use repository evidence for local behavior and primary documentation, specifications, release notes or source for external claims. Verify time-sensitive facts. Link decisive claims and record versions or dates where relevant; label facts, inferences and unknowns separately.
4. Explain trade-offs and when each leading option wins. Recommend a conditional choice, with the evidence gaps that could reverse it. Propose a targeted probe when documentation cannot settle the decision; run it only within the task's authorization.
5. Stop when the question is answered sufficiently for the task; widen the search only for a new relevant evidence gap. When called within an authorized implementation workflow, return the decision evidence to its controller to continue that work. Return a concise comparison, recommendation and unresolved questions. Research does not itself authorize implementation, dependencies, paid services or external writes.

High depth broadens relevant candidates and corroborates decisive claims. Ultra investigates the strongest options in depth and seeks contradictory evidence. Repeated vendor pages are not independent corroboration; disclose sparse evidence instead of manufacturing certainty.
