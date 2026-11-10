# Parser integrity

Use for untrusted structured input whose framing, repeated metadata or alternative
encodings determine what gets validated or published. Scope probes to formats the
contract supports. A library that tolerates malformed input can supply valid
fixtures, but acceptance by that library does not prove strict rejection.

## Select structure before validating values

Identify the format rules that establish the authoritative record, its enclosing
byte ranges and its representation. Preserve this provenance through decoding.
Do not choose whichever candidate or layout first yields acceptable values.
Once selected, malformed metadata or a policy failure must reject the operation
without promoting a marker inside payload/comment data or trying a shorter layout.

Challenge selection itself. Keep a self-consistent embedded marker and independently
corrupt the outer length, offset and count used to establish ownership, including
zero and contradictory bounds. A failed outer-structure check must not make its
contents eligible as a different archive. Keep valid embedded-marker controls at
and beyond policy limits so the fix preserves legitimate contents and rejection.

## Preserve representation and consume the complete record

Determine widths, optional fields and versions from the format's discriminants,
including local flags, sentinels or extension records. Carry those decisions into
later validation even when decoded values are zero or fit a smaller integer.
Validate every required field, repeated value and the complete selected span.
Do not accept a matching prefix while leaving mandatory trailing fields unchecked.
For example, a streamed ZIP64 member can be empty or small and still require
64-bit descriptor sizes; matching a 32-bit prefix cannot validate that descriptor.

## Evidence before independent review

Build a small representation table from the decoder's supported branches, not
only from previously failing examples. For each relevant branch, execute a valid
empty and nonempty control and a mutation in a discriminating field or suffix
that another layout would ignore. Pair embedded-marker controls with damaged
outer metadata as above. Use the public API and assert returned contents, published
bytes, expected errors and unchanged filesystem/state on failure.

Record which cases ran and their results in the existing tests or completion
evidence. Missing execution is outstanding acceptance. If a new spelling breaks
the same selection rule, replace that selection mechanism and rerun these pairs
before review; adding another signature exception does not establish the rule.
