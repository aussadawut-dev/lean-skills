"""JSON command line interface for the local accounting fixture."""

import json
import sqlite3
import sys

import vault


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("invalid request")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError("invalid request")


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    try:
        if len(args) != 2:
            raise ValueError("invalid request")
        path, raw_request = args
        request = json.loads(
            raw_request, object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
        if not isinstance(request, dict):
            raise ValueError("invalid request")
        operation = request.get("op")
        if operation == "balance":
            if set(request) != {"op", "tenant", "account"}:
                raise ValueError("invalid request")
            result = vault.balance(path, request["tenant"], request["account"])
        elif operation == "transfer":
            if set(request) != {"op", "tenant", "source", "target", "amount", "key"}:
                raise ValueError("invalid request")
            result = vault.transfer(
                path, request["tenant"], request["source"], request["target"],
                request["amount"], request["key"],
            )
        else:
            raise ValueError("invalid request")
    except (ValueError, TypeError, sqlite3.Error, OSError, OverflowError):
        print(json.dumps({"error": "invalid request"}), file=sys.stderr)
        return 2
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
