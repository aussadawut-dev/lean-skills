class Ledger:
    def __init__(self, balances):
        if not isinstance(balances, dict):
            raise ValueError('balances must be a dictionary')
        if any(not isinstance(account, str) for account in balances):
            raise ValueError('accounts must be strings')
        if any(
            not isinstance(balance, int) or isinstance(balance, bool) or balance < 0
            for balance in balances.values()
        ):
            raise ValueError('balances must be nonnegative integers')
        self.balances = balances.copy()
        self.history = {}

    def transfer(self, source, target, amount, key):
        if not isinstance(source, str) or not isinstance(target, str):
            raise ValueError('accounts must be strings')
        if source == target:
            raise ValueError('source and target must be distinct')
        if source not in self.balances or target not in self.balances:
            raise ValueError('accounts must exist')
        if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
            raise ValueError('amount must be a positive integer')
        if not isinstance(key, str) or not key:
            raise ValueError('key must be a nonempty string')

        receipt = dict(source=source, target=target, amount=amount, key=key)
        if key in self.history:
            if self.history[key] != receipt:
                raise ValueError('key already used for a different transfer')
            return self.history[key].copy()
        if self.balances[source] < amount:
            raise ValueError('insufficient funds')

        self.balances[source] -= amount
        self.balances[target] += amount
        self.history[key] = receipt
        return receipt.copy()

    def batch(self, operations):
        if not isinstance(operations, list):
            raise ValueError('operations must be a list')

        staged = Ledger(self.balances)
        staged.history = self.history.copy()
        receipts = []
        for operation in operations:
            if not isinstance(operation, dict) or set(operation) != {
                'source', 'target', 'amount', 'key'
            }:
                raise ValueError('operations must contain source, target, amount and key')
            receipts.append(staged.transfer(**operation))

        # Commit only after every operation succeeds, retaining the public dicts.
        self.balances.clear()
        self.balances.update(staged.balances)
        self.history.clear()
        self.history.update(staged.history)
        return receipts
