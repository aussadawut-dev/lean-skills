class Ledger:
    def __init__(self, balances):
        if not isinstance(balances, dict):
            raise ValueError('balances must be a dictionary')
        for account, balance in balances.items():
            if not isinstance(account, str):
                raise ValueError('accounts must be strings')
            if isinstance(balance, bool) or not isinstance(balance, int) or balance < 0:
                raise ValueError('balances must be nonnegative integers')
        self.balances = dict(balances)
        self.history = {}

    def transfer(self, source, target, amount, key):
        if not isinstance(source, str) or not isinstance(target, str):
            raise ValueError('accounts must be strings')
        if source == target:
            raise ValueError('source and target must be distinct')
        if source not in self.balances or target not in self.balances:
            raise ValueError('account does not exist')
        if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
            raise ValueError('amount must be a positive integer')
        if not isinstance(key, str) or not key:
            raise ValueError('key must be a nonempty string')

        receipt = dict(source=source, target=target, amount=amount, key=key)
        if key in self.history:
            if self.history[key] != receipt:
                raise ValueError('key was already used with a different payload')
            return receipt
        if self.balances[source] < amount:
            raise ValueError('insufficient funds')

        self.balances[source] -= amount
        self.balances[target] += amount
        self.history[key] = receipt.copy()
        return receipt

    def batch(self, operations):
        if not isinstance(operations, list):
            raise ValueError('operations must be a list')

        # Stage all effects so any failed operation leaves public state untouched.
        staged = Ledger(self.balances)
        staged.history = self.history.copy()
        receipts = []
        fields = {'source', 'target', 'amount', 'key'}
        for op in operations:
            if not isinstance(op, dict) or op.keys() != fields:
                raise ValueError('each operation must contain source, target, amount and key')
            receipts.append(staged.transfer(**op))

        # Preserve dictionary identities for callers holding public references.
        self.balances.update(staged.balances)
        self.history.update(staged.history)
        return receipts
