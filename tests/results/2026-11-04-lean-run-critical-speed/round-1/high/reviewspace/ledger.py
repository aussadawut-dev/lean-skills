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
        self.balances = dict(balances)
        self.history = {}

    def transfer(self, source, target, amount, key):
        if not isinstance(source, str) or not isinstance(target, str):
            raise ValueError('accounts must be strings')
        if source == target:
            raise ValueError('source and target must be distinct')
        if source not in self.balances or target not in self.balances:
            raise ValueError('accounts must exist')
        if (not isinstance(amount, int) or isinstance(amount, bool)
                or amount <= 0):
            raise ValueError('amount must be a positive integer')
        if not isinstance(key, str) or not key:
            raise ValueError('key must be a nonempty string')

        receipt = dict(source=source, target=target, amount=amount, key=key)
        if key in self.history:
            if self.history[key] != receipt:
                raise ValueError('key was already used for a different transfer')
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

        # All work stays private until every operation succeeds. Transfers only
        # add history entries, so sharing existing receipts with the stage is safe.
        staged = Ledger(self.balances)
        staged.history.update(self.history)
        receipts = []
        fields = {'source', 'target', 'amount', 'key'}
        for operation in operations:
            if not isinstance(operation, dict) or operation.keys() != fields:
                raise ValueError('each operation must contain source, target, amount and key')
            receipts.append(staged.transfer(**operation))

        # Keep the public dictionaries themselves stable for existing callers.
        self.balances.update(staged.balances)
        self.history.update(staged.history)
        return receipts
