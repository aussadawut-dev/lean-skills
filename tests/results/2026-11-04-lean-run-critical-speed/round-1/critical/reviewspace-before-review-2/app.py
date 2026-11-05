import json
import sqlite3
import sys

import vault


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        if len(argv) != 2:
            raise ValueError('invalid request')
        path, raw_request = argv
        request = json.loads(raw_request)
        if not isinstance(request, dict):
            raise ValueError('invalid request')
        operation = request.get('op')
        if operation == 'balance' and set(request) == {'op', 'tenant', 'account'}:
            result = vault.balance(path, request['tenant'], request['account'])
        elif operation == 'transfer' and set(request) == {
                'op', 'tenant', 'source', 'target', 'amount', 'key'}:
            result = vault.transfer(
                path, request['tenant'], request['source'], request['target'],
                request['amount'], request['key'],
            )
        else:
            raise ValueError('invalid request')
    except (ValueError, TypeError, OverflowError, RecursionError, sqlite3.Error):
        print(json.dumps({'error': 'invalid request'}), file=sys.stderr)
        return 2
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    sys.exit(main())
