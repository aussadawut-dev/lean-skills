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
        operation = request.get("op")
        if operation == "balance":
            function = vault.balance
            fields = {"tenant", "account"}
        elif operation == "transfer":
            function = vault.transfer
            fields = {"tenant", "source", "target", "amount", "key"}
        else:
            raise ValueError("invalid operation")
        if set(request) != fields | {"op"}:
            raise ValueError("invalid fields")
        result = function(args[0], **{field: request[field] for field in fields})
        output = json.dumps(result)
    except (ValueError, TypeError, OverflowError, OSError, sqlite3.Error):
        print(json.dumps({"error": "invalid request"}), file=sys.stderr)
        return 2
    print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
