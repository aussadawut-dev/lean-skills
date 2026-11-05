import json
import sys

import vault


def main(argv=None):
    arguments = sys.argv[1:] if argv is None else argv
    try:
        if len(arguments) != 2:
            raise ValueError("Invalid arguments")
        path, raw_request = arguments
        request = json.loads(raw_request)
        if not isinstance(request, dict):
            raise ValueError("Invalid request")

        operation = request.get("op")
        if operation == "balance":
            if set(request) != {"op", "tenant", "account"}:
                raise ValueError("Invalid request")
            result = vault.balance(path, request["tenant"], request["account"])
        elif operation == "transfer":
            if set(request) != {"op", "tenant", "source", "target", "amount", "key"}:
                raise ValueError("Invalid request")
            result = vault.transfer(
                path, request["tenant"], request["source"], request["target"],
                request["amount"], request["key"],
            )
        else:
            raise ValueError("Invalid operation")
        output = json.dumps(result)
    except Exception:
        # The CLI must not expose account details or underlying storage errors.
        print(json.dumps({"error": "Invalid request"}), file=sys.stderr)
        return 2

    print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
