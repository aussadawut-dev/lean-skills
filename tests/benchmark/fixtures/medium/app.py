"""Strict comma-separated ASCII integer list; synthetic benchmark candidate."""
import re
import sys

FIELD = re.compile(r'[+-]?[0-9]+')


def parse_numbers(text):
    if not isinstance(text, str) or not text.strip():
        raise ValueError('empty input')
    values = []
    for part in text.split(','):
        field = part.strip()
        if not FIELD.fullmatch(field):
            raise ValueError('invalid field: ' + repr(part))
        values.append(int(field))
    return values


def main(argv):
    if len(argv) != 1:
        print('usage: app.py LIST', file=sys.stderr)
        return 2
    try:
        values = parse_numbers(argv[0])
    except ValueError as error:
        print('error: ' + str(error), file=sys.stderr)
        return 2
    print(sum(values))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
