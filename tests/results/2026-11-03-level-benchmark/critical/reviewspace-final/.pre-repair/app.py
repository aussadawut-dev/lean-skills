import json
import sqlite3
import sys

import vault


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    try:
        if len(argv) != 2:
            raise ValueError("invalid request")
        path, raw_request = argv
        request = json.loads(raw_request)
        if not isinstance(request, dict):
            raise ValueError("invalid request")
        operation = request.get("op")
        if operation == "balance":
            fields = {"op", "tenant", "account"}
            handler = vault.balance
        elif operation == "transfer":
            fields = {"op", "tenant", "source", "target", "amount", "key"}
            handler = vault.transfer
        else:
            raise ValueError("invalid request")
        if set(request) != fields:
            raise ValueError("invalid request")
        result = handler(path, **{key: value for key, value in request.items() if key != "op"})
    except (ValueError, TypeError, sqlite3.Error, OSError, OverflowError, RecursionError):
        # The CLI never exposes account identifiers, SQL or storage diagnostics.
        print(json.dumps({"error": "invalid request"}), file=sys.stderr)
        return 2
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
