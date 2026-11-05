import re
import sys
from decimal import Decimal


_INTEGER = re.compile(r"[+-]?[0-9]+")


def parse_numbers(text) -> list[int]:
    numbers = []
    for index, part in enumerate(text.split(","), start=1):
        field = part.strip()
        if _INTEGER.fullmatch(field) is None:
            raise ValueError(
                f"field {index} must be a nonempty ASCII decimal integer"
            )
        # Decimal converts exactly without the int(string) decimal digit limit.
        numbers.append(int(Decimal(field)))
    return numbers


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    if len(argv) != 1:
        print(
            "error: expected exactly one argument containing a comma-separated "
            "integer list",
            file=sys.stderr,
        )
        return 2
    try:
        total = sum(parse_numbers(argv[0]))
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    # Decimal also avoids the digit limit when rendering an arbitrary-size sum.
    print(format(Decimal(total), "f"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
