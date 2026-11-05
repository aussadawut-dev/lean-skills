import re
import sys


_INTEGER = re.compile(r"[+-]?[0-9]+")
_CHUNK_DIGITS = 9
_CHUNK_BASE = 10 ** _CHUNK_DIGITS


def _parse_integer(field: str) -> int:
    """Convert a validated field without Python's decimal digit limit."""
    digits = field[1:] if field[0] in "+-" else field
    value = 0
    for offset in range(0, len(digits), _CHUNK_DIGITS):
        chunk = digits[offset:offset + _CHUNK_DIGITS]
        value = value * 10 ** len(chunk) + int(chunk)
    return -value if field[0] == "-" else value


def parse_numbers(text: str) -> list[int]:
    """Parse a nonempty comma-separated list of signed ASCII integers."""
    numbers = []
    for index, part in enumerate(text.split(","), start=1):
        field = part.strip()
        if not _INTEGER.fullmatch(field):
            raise ValueError(f"field {index} must contain an ASCII decimal integer")
        numbers.append(_parse_integer(field))
    return numbers


def _format_integer(value: int) -> str:
    """Format any integer using decimal chunks below Python's digit limit."""
    if value == 0:
        return "0"
    sign = "-" if value < 0 else ""
    value = abs(value)
    chunks = []
    while value:
        value, remainder = divmod(value, _CHUNK_BASE)
        chunks.append(remainder)
    return sign + str(chunks[-1]) + "".join(
        f"{chunk:0{_CHUNK_DIGITS}d}" for chunk in reversed(chunks[:-1])
    )


def main() -> int:
    if len(sys.argv) != 2:
        print(
            "error: expected exactly one integer-list argument; "
            "usage: app.py '1,-2,+3'",
            file=sys.stderr,
        )
        return 2
    try:
        numbers = parse_numbers(sys.argv[1])
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(_format_integer(sum(numbers)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
