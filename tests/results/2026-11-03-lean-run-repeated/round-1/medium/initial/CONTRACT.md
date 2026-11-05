Repair app.py while preserving parse_numbers(text) -> list[int].
Accept one nonempty comma-separated list of ASCII decimal integers,
with optional + or - and surrounding whitespace on each field.
Empty fields/input, underscores, decimal/exponent notation, Unicode
numerals and non-numbers must raise ValueError. Never drop a field.
CLI: python3 -B app.py '1,-2,+3' prints 2 and exits 0. A leading
negative list such as '-2,-3' is also valid. Exactly one positional
argument is required. Invalid input/arity exits 2 with a useful error
on stderr, no stdout and no traceback. Preserve valid signed values,
zeros and arbitrary-size integers. Standard library only.
