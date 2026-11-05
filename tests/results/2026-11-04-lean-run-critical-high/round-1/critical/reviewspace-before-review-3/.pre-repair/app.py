import json
import sqlite3
import sys

import vault


def main(argv=None):
    arguments = sys.argv[1:] if argv is None else argv
    try:
        if len(arguments) != 2:
            raise ValueError('invalid request')
        path, payload = arguments
        request = json.loads(payload)
        if not isinstance(request, dict):
            raise ValueError('invalid request')
        operation = request.pop('op', None)
        if operation == 'balance':
            result = vault.balance(path, **request)
        elif operation == 'transfer':
            result = vault.transfer(path, **request)
        else:
            raise ValueError('invalid request')
    except (ValueError, TypeError, sqlite3.Error, OSError, OverflowError, RecursionError):
        print(json.dumps({'error': 'invalid request'}), file=sys.stderr)
        return 2
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    sys.exit(main())
