import re
import sys
from decimal import Decimal


def parse_numbers(text: str) -> list[int]:
    """Parse a nonempty comma-separated list of signed ASCII integers."""
    numbers = []
    for index, part in enumerate(text.split(","), start=1):
        field = part.strip()
        if not field:
            raise ValueError(f"field {index} is empty")
        if re.fullmatch(r"[+-]?[0-9]+", field) is None:
            raise ValueError(f"field {index} must be an ASCII decimal integer")
        # Decimal construction is exact and avoids Python's int/string digit limit.
        numbers.append(int(Decimal(field)))
    return numbers


def main():
    if len(sys.argv) != 2:
        print(
            "usage: python3 -B app.py 'INTEGER[,INTEGER...]'\n"
            "error: exactly one comma-separated integer-list argument is required",
            file=sys.stderr,
        )
        return 2
    try:
        numbers = parse_numbers(sys.argv[1])
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    # Decimal also formats arbitrary-size integer sums without the digit limit.
    print(Decimal(sum(numbers)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
