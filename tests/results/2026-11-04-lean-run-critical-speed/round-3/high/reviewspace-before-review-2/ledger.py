class Ledger:
    def __init__(self, balances):
        if not isinstance(balances, dict):
            raise ValueError('balances must be a dictionary')
        if any(
            not isinstance(balance, int) or isinstance(balance, bool) or balance < 0
            for balance in balances.values()
        ):
            raise ValueError('balances must be nonnegative integers')
        self.balances = balances.copy()
        self.history = {}

    def transfer(self, source, target, amount, key):
        if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
            raise ValueError('amount must be a positive integer')
        if not isinstance(key, str) or not key:
            raise ValueError('key must be a nonempty string')
        try:
            accounts_exist = source in self.balances and target in self.balances
        except TypeError:
            raise ValueError('accounts must exist') from None
        if not accounts_exist or source == target:
            raise ValueError('accounts must exist and be distinct')

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

        # Stage all transfers so failures never touch the public dictionaries.
        staged = Ledger(self.balances)
        staged.history.update(self.history)
        receipts = []
        for operation in operations:
            if not isinstance(operation, dict) or operation.keys() != {
                'source', 'target', 'amount', 'key'
            }:
                raise ValueError('operations must contain source, target, amount and key')
            receipts.append(staged.transfer(**operation))

        self.balances.update(staged.balances)
        self.history.update(staged.history)
        return receipts
