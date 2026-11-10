# Boundary cases

Use this table while mapping a public signature to evidence. Before review, the
acceptance evidence holds one parameterized case per row that applies to a
parameter, result or stored value; a row set aside needs a stated reason. Cases
assert outcomes through the public interface, not through private structure.

## Cases

| Value kind | Cases |
| --- | --- |
| Any caller-supplied value | A subclass of the expected type that overrides equality, hashing, comparison, arithmetic, string conversion, copying, merging or missing-key behavior (for example a counter or default-valued mapping where a plain mapping is accepted); a proxy or view instead of a plain value; the same object passed twice or kept by the caller and mutated after the call |
| Integers and amounts | A boolean where a number is accepted; zero; negative; the largest value the storage holds and one past it; a float with an integral value; an integer subclass |
| Text and identifiers | Empty; only whitespace; leading or trailing whitespace; a NUL byte; non-ASCII text and characters outside the basic plane; a very long value; a name that differs only in case or quoting from an existing one; a text subclass |
| Floating point | NaN; infinities; negative zero; values near the precision limit |
| Containers and sequences | Empty; one element; duplicate keys or elements; keys of an unexpected type; nested values; mutation of the input during the call; a result that aliases the input |
| Repeated and partial operations | The same request replayed with identical values; replayed with different values; a failure after a partial write leaves nothing persisted; interleaved requests on the same key |
| Absence | Missing optional values; a key or row that does not exist; empty storage |
| Structured input with overlapping or repeated metadata | Follow [parser integrity](parser-integrity.md). Keep an embedded structural marker while corrupting the outer lengths, offsets or counts that establish ownership; include zero and inconsistent bounds. Pair an accepted input at a limit with a rejected input just beyond it. Corrupt repeated metadata independently and retain valid controls. |
| Alternative encodings and record widths | Derive supported representations from their format discriminants. For each, pair empty and nonempty valid values with corruption confined to bytes an alternate or shorter decoder would ignore. Check exact consumption and forbid fallback after the selected representation fails. |
| Filesystem names and publication | On the target filesystem, verify a pair of names the contract requires to coexist and a pair that resolves to the same entry. A collision must not silently overwrite or merge data. Check both the returned result and what was published. |
| Rollback that requires cleanup | Fail publication after staging data. Also fail a cleanup preparation step while removal remains possible. Check that the original state is unchanged, owned staging data is gone, and the operation returns a contract-allowed error within the expected bound. |

## Applying the cases

Derive each case from acceptance; a row with no path into the signature needs
no case. Keep the cases in one parameterized table with shared setup and a
reusable state assertion.
