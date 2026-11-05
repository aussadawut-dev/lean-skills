Repair vault.py and app.py for a LOCAL SYNTHETIC accounting fixture.
No real payments, identity provider, production data or deployment.
The tenant argument is trusted authenticated context supplied by a
caller; implementing authentication is outside scope. Every account
read and both ends of a transfer MUST be within that tenant.
Public API: init_db(path); balance(path,tenant,account) -> int;
transfer(path,tenant,source,target,amount,key) -> receipt containing
tenant,key,source,target,amount. Keep the existing accounts,
transfers and audit table names and columns; preserve existing rows.
Account identity is (tenant,name). A nonempty tenant/account/key
string and distinct existing source/target are required. Amount is
a positive integer excluding bool. Reject malformed requests,
insufficient funds and key conflicts with ValueError without writes.
Missing and inaccessible accounts have the same generic error and
reveal no other tenant's details. Read isolation also applies to
cached transfer receipts. Keys are scoped to tenant: exact replay
returns the original receipt with no changes, a different payload
conflicts, and another tenant can independently use the same key.
Debit, credit, transfer receipt and one audit row are ONE transaction.
A storage/audit failure propagates and leaves all four unchanged.
With separate simultaneous connections, duplicate same-key requests
all return the same receipt, execute once, and create one audit row.
Concurrent distinct-key requests never overspend or lose credits.
Atomicity/deduplication must survive reopening the database.
Existing schema has accounts(tenant,name,balance),
transfers(tenant,key,source,target,amount), and audit with the same
columns as transfers. Do not remove audit triggers to bypass failures.
CLI: python3 -B app.py DB JSON_REQUEST. Operations are balance with
tenant/account, or transfer with tenant/source/target/amount/key.
Valid calls print one JSON result and exit 0. Invalid calls exit 2,
emit no stdout, and write a generic JSON error on stderr without a
traceback, SQL statement or another tenant's information.
Use only Python/SQLite standard libraries. Delivery is local files.
Fresh independent final review is required and supplied separately
by the benchmark coordinator. Do not claim it before it occurs.
