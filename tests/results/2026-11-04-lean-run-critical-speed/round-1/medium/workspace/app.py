import re
import sys


_CHUNK_DIGITS = 9
_CHUNK_BASE = 10 ** _CHUNK_DIGITS


def parse_numbers(text: str) -> list[int]:
    """Parse every field as a signed ASCII decimal integer."""
    numbers = []
    for index, part in enumerate(text.split(','), start=1):
        field = part.strip()
        if re.fullmatch(r'[+-]?[0-9]+', field) is None:
            raise ValueError(f'field {index} must be an ASCII decimal integer')

        digits = field.lstrip('+-')
        value = 0
        # Small conversions avoid Python's decimal string length limit.
        for start in range(0, len(digits), _CHUNK_DIGITS):
            chunk = digits[start:start + _CHUNK_DIGITS]
            value = value * (10 ** len(chunk)) + int(chunk)
        numbers.append(-value if field.startswith('-') else value)
    return numbers


def _format_integer(value: int) -> str:
    """Format an integer without the decimal string length limit."""
    if value == 0:
        return '0'
    sign = '-' if value < 0 else ''
    value = abs(value)
    chunks = []
    while value:
        value, remainder = divmod(value, _CHUNK_BASE)
        chunks.append(remainder)
    return sign + str(chunks[-1]) + ''.join(
        f'{chunk:0{_CHUNK_DIGITS}d}' for chunk in reversed(chunks[:-1])
    )


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print('error: expected exactly one comma-separated integer list', file=sys.stderr)
        return 2
    try:
        numbers = parse_numbers(args[0])
    except ValueError as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 2
    print(_format_integer(sum(numbers)))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
