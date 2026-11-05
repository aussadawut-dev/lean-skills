import json
import sys

import vault


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate field")
        result[key] = value
    return result


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        if len(argv) != 2:
            raise ValueError("invalid arguments")
        request = json.loads(argv[1], object_pairs_hook=_unique_object)
        if not isinstance(request, dict):
            raise ValueError("invalid request")
        operation = request.pop("op", None)
        if operation == "balance" and set(request) == {"tenant", "account"}:
            result = vault.balance(argv[0], **request)
        elif operation == "transfer" and set(request) == {"tenant", "source", "target", "amount", "key"}:
            result = vault.transfer(argv[0], **request)
        else:
            raise ValueError("invalid operation")
        output = json.dumps(result)
    except Exception:
        # The command boundary must never disclose SQL, storage errors or data.
        print(json.dumps({"error": "request failed"}), file=sys.stderr)
        return 2
    print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
