import re
import sys


_INTEGER = re.compile(r"[+-]?[0-9]+")
_CHUNK_DIGITS = 9
_CHUNK_BASE = 10 ** _CHUNK_DIGITS


def parse_numbers(text: str) -> list[int]:
    """Parse every field of a nonempty list of signed ASCII decimal integers."""
    numbers = []
    for index, field in enumerate(text.split(","), start=1):
        field = field.strip()
        if not field:
            raise ValueError(f"field {index} is empty; expected an ASCII decimal integer")
        if _INTEGER.fullmatch(field) is None:
            raise ValueError(
                f"field {index} must be an ASCII decimal integer with an optional + or - sign"
            )

        digits = field[1:] if field[0] in "+-" else field
        value = 0
        # Small conversions preserve arbitrary-size inputs without changing
        # Python's process-wide decimal conversion limit.
        for offset in range(0, len(digits), _CHUNK_DIGITS):
            chunk = digits[offset:offset + _CHUNK_DIGITS]
            value = value * (10 ** len(chunk)) + int(chunk)
        numbers.append(-value if field[0] == "-" else value)
    return numbers


def _format_integer(value: int) -> str:
    """Format the sum without Python's decimal digit limit, including carries."""
    if value == 0:
        return "0"
    sign = "-" if value < 0 else ""
    value = abs(value)
    chunks = []
    while value:
        value, chunk = divmod(value, _CHUNK_BASE)
        chunks.append(chunk)
    return sign + str(chunks[-1]) + "".join(
        str(chunk).zfill(_CHUNK_DIGITS) for chunk in reversed(chunks[:-1])
    )


def main() -> int:
    if len(sys.argv) != 2:
        print(
            "error: expected exactly one argument: a nonempty comma-separated list of integers",
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
    sys.exit(main())
