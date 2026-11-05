class Ledger:
    def __init__(self, balances):
        if not isinstance(balances, dict):
            raise ValueError('balances must be a dictionary')
        for account, balance in balances.items():
            if not isinstance(account, str):
                raise ValueError('account names must be strings')
            if isinstance(balance, bool) or not isinstance(balance, int) or balance < 0:
                raise ValueError('balances must be nonnegative integers')
        self.balances = balances.copy()
        self.history = {}

    def transfer(self, source, target, amount, key):
        if (not isinstance(source, str) or not isinstance(target, str)
                or source == target
                or source not in self.balances or target not in self.balances):
            raise ValueError('source and target must be distinct existing accounts')
        if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
            raise ValueError('amount must be a positive integer')
        if not isinstance(key, str) or not key:
            raise ValueError('key must be a nonempty string')

        receipt = dict(source=source, target=target, amount=amount, key=key)
        if key in self.history:
            if self.history[key] != receipt:
                raise ValueError('key was already used for a different transfer')
            return receipt
        if self.balances[source] < amount:
            raise ValueError('insufficient funds')

        self.balances[source] -= amount
        self.balances[target] += amount
        self.history[key] = receipt
        return receipt.copy()

    def batch(self, operations):
        if not isinstance(operations, list):
            raise ValueError('operations must be a list')

        # Stage both dictionaries so failures never touch the live ledger.
        pending = Ledger(self.balances)
        pending.history.update(self.history)
        receipts = []
        fields = {'source', 'target', 'amount', 'key'}
        for operation in operations:
            if not isinstance(operation, dict) or set(operation) != fields:
                raise ValueError('each operation must contain source, target, amount and key')
            receipts.append(pending.transfer(**operation))

        # Keep the public dictionary objects intact for callers holding references.
        self.balances.update(pending.balances)
        self.history.update(pending.history)
        return receipts
