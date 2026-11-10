---
name: lean-scope
description: Turn a non-trivial request into bounded scope and observable acceptance, without requiring a separate workflow.
license: MIT
---

# lean-scope

## Ground rules

- **Standalone.** Standalone skill: use the current request or explicit arguments. Read applicable project instructions and only task-relevant context.
- **No prerequisites.** No Lean installation, CLI, configuration or companion skill is required; do not install a workflow or create workflow files as prerequisites. Existing project rules apply.
- **Depth.** Use requested procedure depth, or standard by default. High adds relevant boundary cases and stronger evidence; ultra adds cross-part consistency and contradictory evidence where relevant. Depth does not change model reasoning settings.
- **Records.** Keep decisions in conversation unless a suitable project record exists or the user requests persistence.

## Input and result

- **Input.** Input is the request, known users/constraints and any existing agreement.
- **READY.** Return READY when the bounded scope has observable acceptance, a verification method and delivery destination; READY_WITH_ASSUMPTIONS when only explicit reversible assumptions remain.
- **BLOCKED.** Return BLOCKED for a material unanswered decision, naming its effect and the next question.
- **Evidence.** Cite the request, decisions and project evidence that support the scope.
- **Product and UX.** Read [product and UX acceptance](references/product-ux.md) for product discovery or user-facing behavior where usability or accessibility affects acceptance.
- **Scope only.** A scope-only request ends with this deliverable; it does not start implementation.

## Steps

1. **Read context.** Read the request, closest source files and existing decisions. Reuse settled choices. Skip a formal specification for trivial mechanical work unless requested.
2. **Explore when unclear.** When the request is broad, unclear or has materially different directions, explore before settling scope: reflect the goal, draft a few representative use cases or before/after scenarios as unconfirmed examples, and ask whether they match. Offer appropriately sized approaches and their trade-offs where useful. Ask small related batches, adapting subsequent questions to the answers. Research current external facts with sources when needed to choose scope. Skip unnecessary discovery for small or clear requests or when the user says to proceed; still ask for indispensable material decisions.
3. **Ask clearly.** Number questions or use-case confirmations and label their choices a, b, c, etc. Offer a recommended choice with a brief reason only when supported; show a suggested reply such as `1a 2b` for recommended or otherwise established answers. Accept codes, natural language and mixed replies, including edits or uncertainty. If a question is unanswered, do not treat the suggestion as consent; follow up on unanswered material choices.
   - **Question dialog.** Prefer the host's structured question dialog whenever a suitable tool is available in the current mode; follow its schema and limits, splitting batches when needed. Keep use-case context in chat and make each dialog question self-contained, retaining numbered questions and lettered choices where supported. Include brief recommendation reasons and allow free-text corrections. A preselected recommendation is not a submitted answer. Fall back to numbered, lettered chat questions and copyable replies when no suitable dialog is available; do not claim unsupported input prefilling.
4. **Recap before scope.** Keep a compact distinction between agreed items, open decisions and proposals. Before converting an exploratory discussion to scope, recap and ask whether anything is missing. If the user adds something, explore its goal and relevant use case, update the recap and ask again. Once they say it is complete, produce scope; do not impose this confirmation loop on clear or proceed-now requests. Continue independent authorized work while awaiting material answers.
5. **Write the scope.** Reuse an existing delivery agreement rather than generating a second specification. Include the verification method and delivery destination (workspace by default, or the requested PR/deployment). State the goal, included behavior, exclusions, acceptance criteria, constraints, assumptions and likely affected components. For multi-part work, list bounded tasks and dependencies; do not silently expand into adjacent improvements.
6. **Separate decisions.** Distinguish reversible implementation choices from unresolved material decisions about security, ownership, business rules, data lifecycle or external contracts. Ask only for decisions that change the result, explaining the options and their consequences.
7. **Approve or stop.** A clear implementation request already approves matching scope: present it and continue. A specification-only request stops at the specification. Wait for missing material decisions or approval explicitly required by project instructions; elapsed time is not approval.
8. **Return and maintain.** When called within an implementation workflow, return the agreed scope and unresolved decisions to its controller; a scope result does not complete that implementation request. Keep scope current as requirements arrive. Record replacements instead of quietly dropping acceptance items. Material expansions need a user decision before dependent work. At completion, map each acceptance item to evidence and disclose deferred work.

## Depth

- **High.** At high depth, cover actors, normal flows, boundaries and recovery.
- **Ultra.** At ultra depth, check states, cross-feature interactions and rollout/rollback constraints where relevant.
- **Stop.** Stop when acceptance is observable and remaining uncertainty is explicit.
