# Scoped and transactional writes

Use this procedure for persistent, concurrent or access-scoped application data. Derive invariants from the actual contract; do not add a storage architecture or stronger permissions than requested.

Before editing, identify these together:

- **Required effects:** the exact state transition, receipt/history and multiplicity, replay/conflict behavior and durable result.
- **Frame conditions:** which existing records and other scopes must remain unchanged. Checking only new records, affected accounts, row counts or global counts cannot establish preservation of unrelated history. A deleted historical receipt can permit duplicate execution; test preservation followed by replay after reopening.
- **Valid counterexamples:** ignored conflicts, no-op updates and internal identifier movement that preserve all contracted values. Hardening must retain these successes as well as reject destructive changes.

Choose a mechanism enforcing all three while preserving read authorization. Do not materialize other tenants' account/receipt contents into application snapshots to check preservation. Use scoped reads and appropriate transaction-local/storage controls for effective row changes. Keep data-dependent errors within the disclosure contract. Test that malformed data in another scope cannot affect an otherwise valid request.

Validate the complete logical result before commit, with rollback covering every required effect. Distinguish attempted statements from actual changes: storage can report success after skipping a write, triggers can undo/duplicate effects, and conflict policies can legitimately ignore an attempted change. Test invalid effects and valid no-ops as paired cases at the same boundary.

With SQLite or similar trigger-capable storage, verify relevant engine semantics. BEFORE guards can run before an ignored insert/update is discarded. UPDATE/INSERT OR REPLACE can delete a different record through a uniqueness or rowid collision; ordinary update checks or aggregate counts can miss that loss. Catch effective destructive replacement without rejecting ignored collisions. Changing recursive-trigger settings or connection behavior needs compatibility checks against existing benign triggers. Internal rowids are not application identities unless the contract makes them so; compare contracted values and duplicate multiplicity accordingly.

Keep proof bounded: required effects; unexpected changes outside the allowed write set; valid no-op/ignore/relocation controls; storage failure rollback; concurrency where required; and preserved history followed by durable replay. Include the real public interface and failure disclosure. Do not add unsupported assertions about exact error wording, exception classes or storage internals.

A fresh reviewer checks the write set and frame conditions together, then independently challenges enforcement with a valid/invalid pair. A repair that passes its reproducer still needs regression checks for newly constrained valid behavior and the original read boundary. Renew review of that delta; preserve the task-wide REWORK count.
