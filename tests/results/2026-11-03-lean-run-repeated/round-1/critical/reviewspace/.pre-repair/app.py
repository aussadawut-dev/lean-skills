import json
import sqlite3
import sys

import vault


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate field")
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError("invalid JSON constant")


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    try:
        if len(args) != 2:
            raise ValueError("invalid arguments")
        path, raw = args
        request = json.loads(raw, object_pairs_hook=_unique_object,
                             parse_constant=_invalid_constant)
        if not isinstance(request, dict):
            raise ValueError("invalid request")

        operation = request.get("op")
        if operation == "balance":
            fields = {"tenant", "account"}
            action = vault.balance
        elif operation == "transfer":
            fields = {"tenant", "source", "target", "amount", "key"}
            action = vault.transfer
        else:
            raise ValueError("invalid operation")
        if set(request) != fields | {"op"}:
            raise ValueError("invalid fields")
        result = action(path, **{field: request[field] for field in fields})
        output = json.dumps(result)
    except (ValueError, TypeError, sqlite3.Error, OSError, OverflowError, RecursionError):
        print(json.dumps({"error": "invalid request"}), file=sys.stderr)
        return 2

    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
