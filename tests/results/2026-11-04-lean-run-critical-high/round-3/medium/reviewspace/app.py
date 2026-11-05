import re
import sys


_INTEGER_FIELD = re.compile(r"[+-]?[0-9]+")
_CHUNK_DIGITS = 9
_CHUNK_BASE = 10 ** _CHUNK_DIGITS


def parse_numbers(text: str) -> list[int]:
    """Parse every field of a nonempty list of ASCII decimal integers."""
    numbers = []
    for position, field in enumerate(text.split(","), start=1):
        token = field.strip()
        if _INTEGER_FIELD.fullmatch(token) is None:
            raise ValueError(f"field {position} must be an ASCII decimal integer")

        digits = token[1:] if token[0] in "+-" else token
        value = 0
        # Small conversions avoid Python's limit on decimal string length.
        for start in range(0, len(digits), _CHUNK_DIGITS):
            chunk = digits[start:start + _CHUNK_DIGITS]
            value = value * (10 ** len(chunk)) + int(chunk)
        numbers.append(-value if token[0] == "-" else value)
    return numbers


def _format_integer(value: int) -> str:
    """Format an arbitrary-size integer without a single large conversion."""
    if value == 0:
        return "0"

    sign = "-" if value < 0 else ""
    remaining = abs(value)
    chunks = []
    while remaining:
        remaining, chunk = divmod(remaining, _CHUNK_BASE)
        chunks.append(chunk)
    return sign + str(chunks[-1]) + "".join(
        f"{chunk:0{_CHUNK_DIGITS}d}" for chunk in reversed(chunks[:-1])
    )


def main(argv=None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if len(arguments) != 1:
        print("error: expected exactly one argument: a comma-separated list "
              "of integers", file=sys.stderr)
        return 2

    try:
        numbers = parse_numbers(arguments[0])
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    print(_format_integer(sum(numbers)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
