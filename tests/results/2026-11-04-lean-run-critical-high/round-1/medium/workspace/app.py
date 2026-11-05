import re
import sys


_INTEGER = re.compile(r"[+-]?[0-9]+")
_CHUNK_DIGITS = 9
_CHUNK_BASE = 10 ** _CHUNK_DIGITS


def parse_numbers(text: str) -> list[int]:
    """Parse every field of a nonempty, comma-separated ASCII integer list."""
    numbers = []
    for index, part in enumerate(text.split(","), start=1):
        field = part.strip()
        if _INTEGER.fullmatch(field) is None:
            raise ValueError(f"field {index} must be a nonempty ASCII decimal integer")

        digits = field.lstrip("+-")
        value = 0
        # Small conversions preserve arbitrary precision without changing
        # Python's process-wide limit on decimal string conversions.
        for offset in range(0, len(digits), _CHUNK_DIGITS):
            chunk = digits[offset:offset + _CHUNK_DIGITS]
            value = value * (10 ** len(chunk)) + int(chunk)
        numbers.append(-value if field.startswith("-") else value)
    return numbers


def _format_integer(value: int) -> str:
    """Render an integer even when it exceeds Python's decimal digit limit."""
    if value == 0:
        return "0"
    sign = "-" if value < 0 else ""
    value = abs(value)
    chunks = []
    while value:
        value, chunk = divmod(value, _CHUNK_BASE)
        chunks.append(chunk)
    return sign + str(chunks[-1]) + "".join(
        f"{chunk:0{_CHUNK_DIGITS}d}" for chunk in reversed(chunks[:-1])
    )


def main(argv=None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if len(argv) != 1:
        print("error: expected exactly one argument containing a comma-separated integer list",
              file=sys.stderr)
        return 2
    try:
        numbers = parse_numbers(argv[0])
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(_format_integer(sum(numbers)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
