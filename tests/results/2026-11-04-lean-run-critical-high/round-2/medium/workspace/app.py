import re
import sys


_INTEGER = re.compile(r"[+-]?[0-9]+")
_CHUNK_DIGITS = 9
_CHUNK_BASE = 10 ** _CHUNK_DIGITS


def parse_numbers(text: str) -> list[int]:
    """Parse every field of a nonempty list of ASCII decimal integers."""
    numbers = []
    for index, part in enumerate(text.split(","), start=1):
        field = part.strip()
        if not field:
            raise ValueError(f"field {index} is empty; expected an ASCII decimal integer")
        if _INTEGER.fullmatch(field) is None:
            raise ValueError(f"field {index} must be an ASCII decimal integer")

        negative = field.startswith("-")
        digits = field[1:] if field[0] in "+-" else field
        # Small chunks avoid Python's limit on decimal string conversions.
        value = 0
        for start in range(0, len(digits), _CHUNK_DIGITS):
            chunk = digits[start:start + _CHUNK_DIGITS]
            value = value * (10 ** len(chunk)) + int(chunk)
        numbers.append(-value if negative else value)
    return numbers


def _format_integer(value: int) -> str:
    """Render an integer without the interpreter's decimal digit limit."""
    if value == 0:
        return "0"
    sign = "-" if value < 0 else ""
    value = abs(value)
    chunks = []
    while value:
        value, remainder = divmod(value, _CHUNK_BASE)
        chunks.append(remainder)
    leading = str(chunks.pop())
    return sign + leading + "".join(
        f"{chunk:0{_CHUNK_DIGITS}d}" for chunk in reversed(chunks)
    )


def main(argv=None):
    arguments = sys.argv[1:] if argv is None else argv
    if len(arguments) != 1:
        print("error: expected exactly one comma-separated integer list", file=sys.stderr)
        print("usage: python3 -B app.py 'INTEGER[,INTEGER...]'", file=sys.stderr)
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
