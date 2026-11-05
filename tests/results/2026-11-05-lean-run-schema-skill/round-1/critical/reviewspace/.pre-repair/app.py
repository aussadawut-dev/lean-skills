"""Small JSON command-line interface for the local vault."""

import json
import sys
import vault


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        if len(argv) != 2:
            raise ValueError('invalid arguments')
        request = json.loads(argv[1])
        if type(request) is not dict:
            raise ValueError('invalid request')
        operation = request.get('op')
        fields = {
            'balance': {'tenant', 'account'},
            'transfer': {'tenant', 'source', 'target', 'amount', 'key'},
        }
        if not isinstance(operation, str) or operation not in fields:
            raise ValueError('invalid operation')
        if request.keys() != fields[operation] | {'op'}:
            raise ValueError('invalid request')
        args = {name: request[name] for name in fields[operation]}
        result = {'balance': vault.balance, 'transfer': vault.transfer}[operation](
            argv[0], **args
        )
        output = json.dumps(result)
    except Exception:
        print(json.dumps({'error': 'invalid request'}), file=sys.stderr)
        return 2
    print(output)
    return 0


if __name__ == '__main__':
    sys.exit(main())
