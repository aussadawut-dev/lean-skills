from decimal import Decimal
import re
import sys


def parse_numbers(text):
    """Parse a nonempty comma-separated list of signed ASCII integers."""
    numbers = []
    for index, part in enumerate(text.split(","), start=1):
        field = part.strip()
        if re.fullmatch(r"[+-]?[0-9]+", field) is None:
            raise ValueError(
                f"field {index}: expected a nonempty ASCII decimal integer"
            )
        # Decimal construction is exact and bypasses int's string digit limit.
        numbers.append(int(Decimal(field)))
    return numbers


def main():
    if len(sys.argv) != 2:
        print("error: expected exactly one comma-separated integer list",
              file=sys.stderr)
        return 2

    try:
        numbers = parse_numbers(sys.argv[1])
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    # The exact integer sum also needs rendering beyond int's string digit limit.
    print(Decimal(sum(numbers)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
