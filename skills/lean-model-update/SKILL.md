---
name: lean-model-update
description: Research and evaluate model choices for task sizes, then propose updates to an existing model configuration with explicit approval.
license: MIT
---

# lean-model-update

Standalone skill: use the current request or explicit arguments. Read applicable project instructions and only task-relevant context. No Lean installation, CLI, configuration or companion skill is required; do not install a workflow or create workflow files as prerequisites. Existing project rules apply.

Use requested procedure depth, or standard by default. High adds relevant boundary cases and stronger evidence; ultra adds cross-part consistency and contradictory evidence where relevant. Depth does not change model reasoning settings. Keep decisions in conversation unless a suitable project record exists or the user requests persistence.

Establish the requested endpoint: research/proposal, evaluation, or application of an exact approved mapping. A proposal concludes READY with sources, candidate changes, destination, budget and untested assumptions; no evaluation or edit is implied. Evaluation concludes DONE only for the approved trials, reporting actual outcomes and limits. Application concludes DONE only after the approved diff and configuration validation. Missing access, budget, required review or exact-change approval is BLOCKED for the affected endpoint; an unresolved executed validation failure is FAILED. Preserve completed evidence and give the next action rather than restarting the whole workflow.

1. Discover the user's providers and existing model configuration, if any. Verify current model/effort availability from runtime listings and official sources. Report dates, unavailable capabilities and untested candidates; do not hard-code a supposedly current model list.
2. Propose candidates, representative tasks, scoring criteria and a user-approved resource budget before evaluations. Task sizes may use 3S, 2S, S, M, L, XL, 2XL and 3XL, but do not invent benchmark results or require a bundled task bank. If suitable tasks or usage accounting are missing, report that gap and provide a research-only proposal.
3. Run approved evaluations with available tools in disposable copies, preserving permissions and private data. Use authorized subscriptions or credentials only; do not silently switch to paid APIs or alter provider settings. Track actual usage when observable and disclose estimates. Do not claim a hard cap is enforced when the runner cannot enforce it; obtain agreement to supported limits before running.
4. Compare correctness first, then observed time and usage. Preserve existing mappings where evidence is inadequate. Report skipped/failed runs, sample-size limits and sources. Have a fresh independent reviewer inspect the supporting results and candidate solutions before applying an evaluation-based mapping; unavailable required review leaves application blocked.
5. Show the exact old-to-new proposal and configuration destination. Apply only after approval of that proposal; a changed proposal needs renewed approval. If no config exists, keep the proposal in chat unless the user asks to create one. Validate syntax and supported model identifiers after editing.

No Lean runtime, benchmark bank or other skill is supplied or required. This procedure uses the host's real capabilities and honestly stops where they are insufficient.
