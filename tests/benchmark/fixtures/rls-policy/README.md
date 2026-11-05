# Synthetic policy record: Critical row-level security

This is the test fixture counterpart of the real decision record,
[2026-11-04-rls-policy-development](../../../results/2026-11-04-rls-policy-development/README.md).
It exists so the unit tests can prepare a cohort that declares the Critical
contract change without the measured archives.

Decision: during one tenant's transfer, other tenants' `accounts`, `transfers`
and `audit` rows behave as if absent. Expectations that depended on seeing those
rows are superseded and listed exactly in
[`superseded-expectations.json`](superseded-expectations.json): one historical
test per earlier synthetic Critical round, and the probe cases the row-hiding
reference solution fails. A suite or probe whose failures are all listed is
reported as policy-superseded, never as passed.
