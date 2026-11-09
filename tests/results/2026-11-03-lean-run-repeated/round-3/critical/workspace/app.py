import json
import sqlite3
import sys

import vault


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    try:
        if len(args) != 2:
            raise ValueError("invalid arguments")
        request = json.loads(args[1])
        if not isinstance(request, dict):
            raise ValueError("invalid request")
        fields = {
            "balance": {"op", "tenant", "account"},
            "transfer": {"op", "tenant", "source", "target", "amount", "key"},
        }
        operation = request.get("op")
        if (not isinstance(operation, str) or operation not in fields
                or set(request) != fields[operation]):
            raise ValueError("invalid request")
        request.pop("op")
        if operation == "balance":
            result = vault.balance(args[0], **request)
        else:
            result = vault.transfer(args[0], **request)
        output = json.dumps(result)
    except (ValueError, TypeError, OverflowError, sqlite3.Error, OSError, RecursionError):
        print(json.dumps({"error": "request failed"}), file=sys.stderr)
        return 2
    print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
