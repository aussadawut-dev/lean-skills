import re
import sys


_INTEGER = re.compile(r"[+-]?[0-9]+")
_CHUNK_DIGITS = 9
_CHUNK_BASE = 10 ** _CHUNK_DIGITS


def parse_numbers(text: str) -> list[int]:
    """Parse every field of a nonempty, comma-separated ASCII integer list."""
    numbers = []
    for position, field in enumerate(text.split(","), start=1):
        token = field.strip()
        if _INTEGER.fullmatch(token) is None:
            raise ValueError(f"field {position} must contain an ASCII decimal integer")

        negative = token.startswith("-")
        digits = token[1:] if token[0] in "+-" else token
        value = 0
        # Bounded conversions avoid Python's limit on decimal integer digits.
        for start in range(0, len(digits), _CHUNK_DIGITS):
            chunk = digits[start:start + _CHUNK_DIGITS]
            value = value * 10 ** len(chunk) + int(chunk)
        numbers.append(-value if negative else value)
    return numbers


def _format_integer(value: int) -> str:
    """Render an integer without relying on Python's decimal digit limit."""
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
        print("error: expected exactly one comma-separated integer list", file=sys.stderr)
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
