# Boundary cases

Use this table while mapping a public signature to evidence. Before review, the
acceptance evidence holds one parameterized case per row that applies to a
parameter, result or stored value; a row set aside needs a stated reason. Cases
assert outcomes through the public interface, not through private structure.

| Value kind | Cases |
| --- | --- |
| Any caller-supplied value | A subclass of the expected type that overrides equality, hashing, comparison, arithmetic, string conversion, copying, merging or missing-key behavior (for example a counter or default-valued mapping where a plain mapping is accepted); a proxy or view instead of a plain value; the same object passed twice or kept by the caller and mutated after the call |
| Integers and amounts | A boolean where a number is accepted; zero; negative; the largest value the storage holds and one past it; a float with an integral value; an integer subclass |
| Text and identifiers | Empty; only whitespace; leading or trailing whitespace; a NUL byte; non-ASCII text and characters outside the basic plane; a very long value; a name that differs only in case or quoting from an existing one; a text subclass |
| Floating point | NaN; infinities; negative zero; values near the precision limit |
| Containers and sequences | Empty; one element; duplicate keys or elements; keys of an unexpected type; nested values; mutation of the input during the call; a result that aliases the input |
| Repeated and partial operations | The same request replayed with identical values; replayed with different values; a failure after a partial write leaves nothing persisted; interleaved requests on the same key |
| Absence | Missing optional values; a key or row that does not exist; empty storage |

Derive each case from acceptance; a row with no path into the signature needs
no case. Keep the cases in one parameterized table with shared setup and a
reusable state assertion.
