import json
import sys

import vault


OPERATIONS = {
    "balance": (vault.balance, {"tenant", "account"}),
    "transfer": (vault.transfer, {"tenant", "source", "target", "amount", "key"}),
}


def main(argv=None):
    arguments = sys.argv[1:] if argv is None else argv
    try:
        if len(arguments) != 2:
            raise ValueError("invalid arguments")
        path, payload = arguments
        request = json.loads(payload)
        if not isinstance(request, dict):
            raise ValueError("invalid request")
        operation = request.get("op")
        if not isinstance(operation, str) or operation not in OPERATIONS:
            raise ValueError("invalid operation")
        function, fields = OPERATIONS[operation]
        if request.keys() != fields | {"op"}:
            raise ValueError("invalid fields")
        result = function(path, **{field: request[field] for field in fields})
        output = json.dumps(result)
    except Exception:
        # The CLI is a public boundary: storage and validation details stay private.
        print(json.dumps({"error": "invalid request"}), file=sys.stderr)
        return 2
    print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
