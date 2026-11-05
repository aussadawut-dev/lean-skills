"""Parse and sum a strict comma-separated list of decimal integers."""

import re
import sys
from decimal import Decimal


def parse_numbers(text: str) -> list[int]:
    numbers = []
    for position, part in enumerate(text.split(","), start=1):
        field = part.strip()
        if re.fullmatch(r"[+-]?[0-9]+", field) is None:
            raise ValueError(
                f"field {position} must contain an ASCII decimal integer"
            )
        # Decimal preserves all digits without Python's int/string digit limit.
        numbers.append(int(Decimal(field)))
    return numbers


def main(argv=None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if len(argv) != 1:
        print("error: expected exactly one comma-separated integer list", file=sys.stderr)
        return 2
    try:
        total = sum(parse_numbers(argv[0]))
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    # Decimal formatting also supports results beyond the int/string digit limit.
    print(format(Decimal(total), "f"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
