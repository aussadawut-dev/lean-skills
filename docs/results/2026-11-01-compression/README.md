# Compressed instruction trials

Six bounded trials used Codex agents against the compressed candidate recorded
in [metadata.json](metadata.json). Existing agents were reused through follow-up
messages rather than fresh contexts; these are real agent trials, but not clean
independent comparisons with the previous wording. Agents used disposable local
fixtures and no network. Fixture boundaries were instructional, not OS sandboxing.

| Skill | Result | Evidence |
| --- | --- | --- |
| lean-init | PASS | Identified CLI, ran one test and valid input, reported incorrect help example; initial application files matched. |
| lean-task | PASS | Reproduced invalid input crash, added failing tests, fixed it, ran four passing tests and valid/invalid real CLI probes; unrelated file preserved. |
| lean-review | PASS | Reviewed the final task fixture, reran four tests and CLI probes, and reported focused review coverage and limits. |
| lean-grill | PASS | Asked whether deletion was permanent or reversible and deferred implementation; initial application files matched. |
| lean-effort | PASS | Set global high, set lean-review ultra, inspected, reset only lean-review and observed global high still effective. Conversation-level behavior was reported by the executing agent. |
| lean-update | PASS, bounded | Offline CLI 1.7.4 updated lean-init and added lean-instructions, retained unrelated files and Claude links, backed up, and recorded a source snapshot and revision. Coordinator verified lock sources exist. |

Coordinator independently compared application files, unrelated files and
installation metadata; agent messages supplied other observations. No changed
behavior or actionable instruction defect was observed in these cases, so no
additional instruction repair was made. This does not prove equivalence for all
inputs, levels, hosts, or the other six compressed skills. Long-term survival of
the update snapshot and live upstream behavior were not tested. Temporary fixture
artifacts under `/tmp` are not durable archival evidence. Five repository unit
and fixture tests passed separately.
