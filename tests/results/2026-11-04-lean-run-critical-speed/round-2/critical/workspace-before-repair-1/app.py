import json
import sqlite3
import sys

import vault


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    try:
        if len(args) != 2:
            raise ValueError('invalid arguments')
        path, raw_request = args
        request = json.loads(raw_request)
        if not isinstance(request, dict):
            raise ValueError('invalid request')

        operation = request.get('op')
        if operation == 'balance' and request.keys() == {'op', 'tenant', 'account'}:
            result = vault.balance(path, request['tenant'], request['account'])
        elif operation == 'transfer' and request.keys() == {
            'op', 'tenant', 'source', 'target', 'amount', 'key'
        }:
            result = vault.transfer(path, request['tenant'], request['source'],
                                    request['target'], request['amount'], request['key'])
        else:
            raise ValueError('invalid request')
    except (ValueError, TypeError, sqlite3.Error, OSError, OverflowError, RecursionError):
        print(json.dumps({'error': 'invalid request'}), file=sys.stderr)
        return 2

    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    sys.exit(main())
