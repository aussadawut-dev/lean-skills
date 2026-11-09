---
name: lean-grill
description: Stress-test requirements or a plan and resolve consequential design decisions before dependent implementation.
license: MIT
---

# lean-grill

Standalone skill: use the current request or explicit arguments. Read applicable project instructions and only task-relevant context. No Lean installation, CLI, configuration or companion skill is required; do not install a workflow or create workflow files as prerequisites. Existing project rules apply.

Use requested procedure depth, or standard by default. High adds relevant boundary cases and stronger evidence; ultra adds cross-part consistency and contradictory evidence where relevant. Depth does not change model reasoning settings. Keep decisions in conversation unless a suitable project record exists or the user requests persistence.

Input is an existing requirement, scope or plan and its intended outcome. Conclude with the decisions/assumptions, concrete scenarios and evidence supporting readiness, unresolved material points and their next owner/action. No questions is a valid outcome when the plan is already actionable. A missing required plan or decision is BLOCKED; do not invent approval, implement a solution or repeat settled questions to fill a checklist.

1. Accept the existing scope and decision record; reopen settled choices only when new requirements or contradictory evidence affect them. Read the plan and its closest project evidence. Reuse settled choices rather than asking again. A clear plan can finish READY without questions.
2. Probe only relevant boundaries: goal and acceptance, actors, data ownership/lifecycle, permissions, integration contracts, failure recovery and operations. Use concrete scenarios to expose omissions or contradictions.
3. Classify each open point as NEED DECISION or SAFE ASSUMPTION. Safe assumptions are reversible, low risk and consistent with known choices. Do not assume authorization, tenant isolation, destructive behavior, retention or breaking contract semantics.
4. Resolve material choices near the beginning rather than asking one routine implementation question per phase. New material evidence may still require a targeted question later; do not restart the whole intake. Ask a small batch of questions that materially affect the result. State consequences and recommend an option when evidence supports it. Wait for answers before dependent follow-ups; independent work may continue.
5. When called within an implementation workflow, send results to its controller to continue authorized work; readiness is a stage result, not completion of implementation. Return READY, READY_WITH_ASSUMPTIONS or BLOCKED, with decisions, assumptions, open questions and affected acceptance criteria. Preserve the result in an existing project record when appropriate. This skill does not grant implementation or publication authority.

High depth walks normal flows, exceptions and recovery per relevant actor. Ultra checks cross-flow consistency in successive focused rounds. Stop when the plan is actionable; do not turn routine work into a questionnaire.
