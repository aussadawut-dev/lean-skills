class Ledger:
    """An in-memory ledger with idempotent transfers and atomic batches."""

    def __init__(self, balances):
        if not isinstance(balances, dict):
            raise ValueError("balances must be a dictionary")
        for account, balance in balances.items():
            if not isinstance(account, str):
                raise ValueError("accounts must be strings")
            if (not isinstance(balance, int) or isinstance(balance, bool)
                    or balance < 0):
                raise ValueError("balances must be nonnegative integers")
        self.balances = balances.copy()
        self.history = {}

    def transfer(self, source, target, amount, key):
        if not isinstance(source, str) or not isinstance(target, str):
            raise ValueError("accounts must be strings")
        if source == target:
            raise ValueError("source and target must be distinct")
        if source not in self.balances or target not in self.balances:
            raise ValueError("account does not exist")
        if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
            raise ValueError("amount must be a positive integer")
        if not isinstance(key, str) or not key:
            raise ValueError("key must be a nonempty string")

        receipt = dict(source=source, target=target, amount=amount, key=key)
        if key in self.history:
            if self.history[key] != receipt:
                raise ValueError("key already used for a different transfer")
            return self.history[key].copy()
        if self.balances[source] < amount:
            raise ValueError("insufficient funds")

        source_balance = self.balances[source] - amount
        target_balance = self.balances[target] + amount
        self.balances[source] = source_balance
        self.balances[target] = target_balance
        self.history[key] = receipt
        return receipt.copy()

    def batch(self, operations):
        if not isinstance(operations, list):
            raise ValueError("operations must be a list")

        # Stage all changes so a later failure cannot affect either public dict.
        staged = Ledger(self.balances)
        staged.history.update(self.history)
        receipts = []
        for op in operations:
            if (not isinstance(op, dict)
                    or op.keys() != {"source", "target", "amount", "key"}):
                raise ValueError("each operation must contain source, target, amount and key")
            receipts.append(staged.transfer(**op))

        # Keep existing references to the public dictionaries valid on success.
        self.balances.update(staged.balances)
        self.history.update(staged.history)
        return receipts
