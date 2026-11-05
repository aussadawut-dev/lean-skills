# lean-run High and Critical, first RLS contract (protocol-invalid Critical)

Recorded 2026-11-05. Prepared from the
[SQL-source and phase-budget pilot](../2026-11-04-lean-run-in-source-budget/README.md)
with the Critical contract changed to row-level security
([policy record](policy-record.md)), the superseded-expectation list and the
accumulated probe set as blocking gates.

- **High: DONE.** One repair. Implementation 298.7 s, review 393.2 s, repair 227.0 s,
  re-review 141.7 s; 1,060.7 s and 83,236 uncached input in total. The first
  launch failed after 4 s with "Selected model is at capacity" before any model
  turn; it is retained under `infrastructure-failures/` and in
  [infrastructure-failures.json](infrastructure-failures.json), and the phase
  was relaunched unchanged.
- **Critical: PROTOCOL_INVALID** ([record](round-1/critical/protocol-invalid.json)).
  The new contract sentence rejected "any effect beyond" the ledger writes
  without limiting it to the ledger tables, so it also forbade trigger writes to
  other tables that the frozen historical suites expect. The trial stopped after
  its second assessment by user decision and is excluded from quality and cost
  comparisons. Its F3 (rowcount) and F4 (table-name case) findings were genuine
  candidate defects. Four measured phases: 812.8 s, 692.5 s, 613.4 s and 306.2 s.

No summary or comparison is rendered because the Critical trial has no terminal
result. All raw phase events, metrics, assessments and requests are retained.
