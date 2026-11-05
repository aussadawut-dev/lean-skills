import re
import sys
from decimal import Decimal


def parse_numbers(text: str) -> list[int]:
    """Parse every field of a nonempty, comma-separated integer list."""
    numbers = []
    for position, part in enumerate(text.split(","), start=1):
        field = part.strip()
        if re.fullmatch(r"[+-]?[0-9]+", field) is None:
            raise ValueError(f"field {position} must be an ASCII decimal integer")
        # Decimal converts exactly without Python's int/string digit limit.
        numbers.append(int(Decimal(field)))
    return numbers


def main() -> int:
    if len(sys.argv) != 2:
        print(
            "error: expected exactly one argument: a comma-separated integer list",
            file=sys.stderr,
        )
        return 2

    try:
        numbers = parse_numbers(sys.argv[1])
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    # Conversion from an integer is exact and prints every digit, even for
    # sums beyond the interpreter's int/string conversion limit.
    print(Decimal(sum(numbers)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
