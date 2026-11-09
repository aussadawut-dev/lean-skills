class Ledger:
    def __init__(self, balances):
        if not isinstance(balances, dict):
            raise ValueError('balances must be a dictionary')
        for account, balance in balances.items():
            if not isinstance(account, str):
                raise ValueError('accounts must be strings')
            if (not isinstance(balance, int) or isinstance(balance, bool)
                    or balance < 0):
                raise ValueError('balances must be nonnegative integers')
        self.balances = balances.copy()
        self.history = {}

    def transfer(self, source, target, amount, key):
        if (not isinstance(source, str) or not isinstance(target, str)
                or source == target or source not in self.balances
                or target not in self.balances):
            raise ValueError('source and target must be distinct existing accounts')
        if (not isinstance(amount, int) or isinstance(amount, bool)
                or amount <= 0):
            raise ValueError('amount must be a positive integer')
        if not isinstance(key, str) or not key:
            raise ValueError('key must be a nonempty string')

        receipt = dict(source=source, target=target, amount=amount, key=key)
        if key in self.history:
            if self.history[key] != receipt:
                raise ValueError('key already used with a different payload')
            return self.history[key].copy()
        if self.balances[source] < amount:
            raise ValueError('insufficient funds')

        source_balance = self.balances[source] - amount
        target_balance = self.balances[target] + amount
        self.balances[source] = source_balance
        self.balances[target] = target_balance
        self.history[key] = receipt
        return receipt.copy()

    def batch(self, operations):
        if not isinstance(operations, list):
            raise ValueError('operations must be a list')

        # All validation and transfers happen on staged state. Existing receipts
        # may be shared here because transfer never changes stored receipts.
        staged = Ledger(self.balances)
        staged.history.update(self.history)
        receipts = []
        for operation in operations:
            if (not isinstance(operation, dict)
                    or set(operation) != {'source', 'target', 'amount', 'key'}):
                raise ValueError('each operation must contain source, target, amount and key')
            receipts.append(staged.transfer(**operation))

        # Preserve references callers hold to the two public dictionaries.
        self.balances.update(staged.balances)
        self.history.update(staged.history)
        return receipts
