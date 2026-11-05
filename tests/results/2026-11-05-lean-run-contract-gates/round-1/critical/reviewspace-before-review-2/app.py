import json
import sys

import vault


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    try:
        if len(args) != 2:
            raise ValueError('invalid arguments')
        path, payload = args
        request = json.loads(payload)
        if not isinstance(request, dict):
            raise ValueError('invalid request')
        operation = request.pop('op')
        operations = {'balance': vault.balance, 'transfer': vault.transfer}
        result = operations[operation](path, **request)
        output = json.dumps(result)
    except Exception:
        print(json.dumps({'error': 'invalid request'}), file=sys.stderr)
        return 2
    print(output)
    return 0


if __name__ == '__main__':
    sys.exit(main())
