"""Small JSON-only command line interface to the accounting fixture."""
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
    argv = sys.argv[1:] if argv is None else argv
    try:
        if len(argv) != 2:
            raise ValueError('invalid arguments')
        request = json.loads(argv[1], object_pairs_hook=_object,
                             parse_constant=_invalid_constant)
        if not isinstance(request, dict):
            raise ValueError('invalid request')
        operation = request.pop('op')
        functions = {'balance': vault.balance, 'transfer': vault.transfer}
        result = functions[operation](argv[0], **request)
    except Exception:
        # The CLI is a trust boundary: never expose SQL, paths, trigger errors
        # or details of accounts through the error response.
        print(json.dumps({'error': 'invalid request'}), file=sys.stderr)
        return 2
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    sys.exit(main())
