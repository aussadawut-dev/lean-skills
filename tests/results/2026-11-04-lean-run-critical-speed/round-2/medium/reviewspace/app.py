import re
import sys


_CHUNK_DIGITS = 9
_CHUNK_BASE = 10 ** _CHUNK_DIGITS


def parse_numbers(text):
    """Parse every field as a signed ASCII decimal integer."""
    numbers = []
    for index, part in enumerate(text.split(","), start=1):
        field = part.strip()
        if re.fullmatch(r"[+-]?[0-9]+", field) is None:
            raise ValueError(f"field {index} must be an ASCII decimal integer")

        digits = field.lstrip("+-")
        number = 0
        # Bounded conversions avoid Python's decimal digit limit without
        # changing interpreter-wide settings for callers of this function.
        for start in range(0, len(digits), _CHUNK_DIGITS):
            chunk = digits[start:start + _CHUNK_DIGITS]
            number = number * (10 ** len(chunk)) + int(chunk)
        numbers.append(-number if field.startswith("-") else number)
    return numbers


def _format_integer(number):
    """Render arbitrary-size integers without a whole-number str conversion."""
    if number == 0:
        return "0"
    sign = "-" if number < 0 else ""
    number = abs(number)
    chunks = []
    while number:
        number, remainder = divmod(number, _CHUNK_BASE)
        chunks.append(remainder)
    return sign + str(chunks[-1]) + "".join(
        f"{chunk:0{_CHUNK_DIGITS}d}" for chunk in reversed(chunks[:-1])
    )


def main():
    if len(sys.argv) != 2:
        print("error: expected exactly one comma-separated integer list argument",
              file=sys.stderr)
        return 2
    try:
        numbers = parse_numbers(sys.argv[1])
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(_format_integer(sum(numbers)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
