"""JSON command-line boundary for the local accounting fixture."""

import json
import sys

import vault


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate field')
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError('invalid JSON constant')


def main(argv=None):
    argv = sys.argv if argv is None else argv
    try:
        if len(argv) != 3:
            raise ValueError('invalid arguments')
        request = json.loads(
            argv[2], object_pairs_hook=_object, parse_constant=_invalid_constant,
        )
        if not isinstance(request, dict):
            raise ValueError('invalid request')
        operation = request.pop('op')
        if operation == 'balance' and set(request) == {'tenant', 'account'}:
            result = vault.balance(argv[1], **request)
        elif operation == 'transfer' and set(request) == {
            'tenant', 'source', 'target', 'amount', 'key'
        }:
            result = vault.transfer(argv[1], **request)
        else:
            raise ValueError('invalid operation')
        output = json.dumps(result)
    except Exception:
        # Never expose exception messages, SQL, paths, or another tenant's data.
        print(json.dumps({'error': 'invalid request'}), file=sys.stderr)
        return 2
    print(output)
    return 0


if __name__ == '__main__':
    sys.exit(main())
