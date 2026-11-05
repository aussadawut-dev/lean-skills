import json
import sys

import vault


def _unique_object(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError('invalid request')
        result[name] = value
    return result


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    try:
        if len(args) != 2:
            raise ValueError('invalid request')
        path, payload = args
        request = json.loads(payload, object_pairs_hook=_unique_object)
        if not isinstance(request, dict):
            raise ValueError('invalid request')

        operation = request.get('op')
        if operation == 'balance' and set(request) == {'op', 'tenant', 'account'}:
            result = vault.balance(path, request['tenant'], request['account'])
        elif operation == 'transfer' and set(request) == {
            'op', 'tenant', 'source', 'target', 'amount', 'key'
        }:
            result = vault.transfer(
                path, request['tenant'], request['source'], request['target'],
                request['amount'], request['key'],
            )
        else:
            raise ValueError('invalid request')
        output = json.dumps(result)
    except Exception:
        # This is the process boundary: parser, validation and storage errors
        # all have the same public response, with no private exception details.
        print(json.dumps({'error': 'invalid request'}), file=sys.stderr)
        return 2

    print(output)
    return 0


if __name__ == '__main__':
    sys.exit(main())
