"""Small JSON CLI; all failures have the same public error representation."""

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


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    try:
        if len(args) != 2:
            raise ValueError('arguments')
        request = json.loads(args[1], object_pairs_hook=_object)
        if not isinstance(request, dict):
            raise ValueError('request')
        operation = request.get('op')
        operations = {
            'balance': (vault.balance, {'tenant', 'account'}),
            'transfer': (vault.transfer,
                         {'tenant', 'source', 'target', 'amount', 'key'}),
        }
        function, fields = operations[operation]
        if request.keys() != fields | {'op'}:
            raise ValueError('fields')
        result = function(args[0], **{name: request[name] for name in fields})
        output = json.dumps(result)
    except Exception:
        print(json.dumps({'error': 'invalid request'}), file=sys.stderr)
        return 2
    print(output)
    return 0


if __name__ == '__main__':
    sys.exit(main())
