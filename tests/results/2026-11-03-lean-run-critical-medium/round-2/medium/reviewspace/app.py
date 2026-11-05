from decimal import Decimal
import re
import sys


_INTEGER = re.compile(r"[+-]?[0-9]+")


def parse_numbers(text: str) -> list[int]:
    numbers = []
    for index, part in enumerate(text.split(","), start=1):
        field = part.strip()
        if _INTEGER.fullmatch(field) is None:
            raise ValueError(f"field {index}: expected an ASCII decimal integer")
        # Decimal conversion is exact and avoids the int(string) digit limit.
        numbers.append(int(Decimal(field)))
    return numbers


def main() -> int:
    if len(sys.argv) != 2:
        print("error: expected exactly one comma-separated integer list", file=sys.stderr)
        return 2
    try:
        total = sum(parse_numbers(sys.argv[1]))
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    # Decimal also formats arbitrarily large integers without a digit limit.
    print(Decimal(total))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
