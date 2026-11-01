---
name: lean-grill
description: Stress-test requirements or a plan and resolve consequential design decisions before dependent implementation.
license: MIT
---

# lean-grill

This is a standalone skill. Use the current request or explicit invocation arguments as input. Read existing project instructions and only the context needed for this task. No Lean installation, CLI, configuration, or other skill is required. Do not install a workflow or create workflow files as a prerequisite. Existing project rules still apply.

Use the user's requested procedure depth; otherwise use standard depth. High adds boundary cases and stronger evidence; ultra adds cross-part consistency and contradictory evidence where relevant. Depth does not change model reasoning settings. Keep decisions in the conversation unless the project already has a suitable record or the user requests persistence.

1. Read the plan and its closest project evidence. Reuse settled choices rather than asking again. A clear plan can finish READY without questions.
2. Probe only relevant boundaries: goal and acceptance, actors, data ownership/lifecycle, permissions, integration contracts, failure recovery and operations. Use concrete scenarios to expose omissions or contradictions.
3. Classify each open point as NEED DECISION or SAFE ASSUMPTION. Safe assumptions are reversible, low risk and consistent with known choices. Do not assume authorization, tenant isolation, destructive behavior, retention or breaking contract semantics.
4. Ask a small batch of questions that materially affect the result. State consequences and recommend an option when evidence supports it. Wait for answers before dependent follow-ups; independent work may continue.
5. Return READY, READY_WITH_ASSUMPTIONS or BLOCKED, with decisions, assumptions, open questions and affected acceptance criteria. Preserve the result in an existing project record when appropriate. This skill does not grant implementation or publication authority.

High depth walks normal flows, exceptions and recovery per relevant actor. Ultra checks cross-flow consistency in successive focused rounds. Stop when the plan is actionable; do not turn routine work into a questionnaire.
