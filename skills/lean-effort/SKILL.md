---
name: lean-effort
description: Inspect or set conversation-level procedure depth for these skills, independently of model reasoning effort.
license: MIT
---

# lean-effort

This is a standalone skill. Use the current request or explicit invocation arguments as input. Read existing project instructions and only the context needed for this task. No Lean installation, CLI, configuration, or other skill is required. Do not install a workflow or create workflow files as a prerequisite. Existing project rules still apply.

Use the user's requested procedure depth; otherwise use standard depth. High adds boundary cases and stronger evidence; ultra adds cross-part consistency and contradictory evidence where relevant. Depth does not change model reasoning settings. Keep decisions in the conversation unless the project already has a suitable record or the user requests persistence.

Accept no arguments to inspect; otherwise accept standard, high, ultra or reset, optionally scoped to a named procedure. Interpret input as text, never shell code.

1. Read preferences already established in the conversation and applicable project instructions. No saved preference means standard. If no arguments were given, report effective global and procedure-specific levels without writing anything.
2. An explicit procedure level overrides the conversation-wide level. Reset with a procedure removes its override; reset without one removes the conversation-wide preference, leaving named overrides intact. Unsupported levels need clarification rather than silent coercion.
3. Standard uses the smallest sufficient procedure and evidence. High adds relevant boundary/failure cases and stronger corroboration. Ultra adds cross-part consistency, contradictory evidence and deeper investigation where it could change the result. None lowers acceptance, validation or review requirements.
4. Record the new preference in the conversation and report its scope and effective level. Other installed skills are not required; apply the preference when carrying out the named procedure directly.
5. This does not change the model, model reasoning effort, tool permissions or agent count. Conversation preferences do not promise persistence into another chat. Persist only when explicitly requested, in an agreed existing settings/documentation location; do not create a workflow installation.
