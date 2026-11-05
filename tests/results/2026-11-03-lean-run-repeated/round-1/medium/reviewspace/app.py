import re
import sys
from decimal import Decimal


def parse_numbers(text: str) -> list[int]:
    """Parse every field as a signed ASCII decimal integer."""
    numbers = []
    for index, part in enumerate(text.split(","), start=1):
        field = part.strip()
        if re.fullmatch(r"[+-]?[0-9]+", field) is None:
            raise ValueError(f"field {index}: expected an ASCII decimal integer")
        # Decimal converts exactly, without Python's int/string digit limit.
        numbers.append(int(Decimal(field)))
    return numbers


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    if len(argv) != 1:
        print("error: expected exactly one comma-separated integer list argument", file=sys.stderr)
        return 2
    try:
        numbers = parse_numbers(argv[0])
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    # Format the exact integer sum without the int/string digit limit, too.
    print(format(Decimal(sum(numbers)), "f"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
