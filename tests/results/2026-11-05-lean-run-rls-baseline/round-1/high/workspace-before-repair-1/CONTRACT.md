Repair ledger.py. Public API: Ledger(balances: dict[str,int]),
transfer(source,target,amount,key), batch(operations). Preserve the
public balances and history dictionaries and existing valid behavior.
Constructor copies input; nonnegative integer balances, excluding
bool, are required. Transfers require distinct existing accounts,
amount a positive int excluding bool, and a nonempty string key.
Reject invalid values, unavailable accounts and insufficient funds
with ValueError and absolutely no state change. Return a receipt
{'source':source,'target':target,'amount':amount,'key':key}.
A replay of a successful key with the same payload returns an equal
receipt with no second mutation; a changed payload is a ValueError.
Returned receipts must not let callers mutate internal history.
batch accepts a list of operation dictionaries using these names,
returning receipts in order. A batch is atomic: on any failure both
balances/history equal their pre-batch state, including earlier valid
operations; successful batches preserve ordinary replay semantics.
No persistence, concurrency or external service is requested here.
Add meaningful tests and exercise an integrated multi-transfer flow.
