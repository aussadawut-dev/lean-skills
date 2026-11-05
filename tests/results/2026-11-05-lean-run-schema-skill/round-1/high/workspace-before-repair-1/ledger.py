class Ledger:
    def __init__(self, balances):
        if not isinstance(balances, dict):
            raise ValueError('balances must be a dictionary')
        balances = dict(balances)
        for account, balance in balances.items():
            if not isinstance(account, str):
                raise ValueError('account names must be strings')
            if (not isinstance(balance, int) or isinstance(balance, bool)
                    or balance < 0):
                raise ValueError('balances must be nonnegative integers')
        self.balances = balances
        self.history = {}

    def transfer(self, source, target, amount, key):
        if (not isinstance(source, str) or not isinstance(target, str)
                or source == target
                or source not in self.balances or target not in self.balances):
            raise ValueError('source and target must be distinct existing accounts')
        if (not isinstance(amount, int) or isinstance(amount, bool)
                or amount <= 0):
            raise ValueError('amount must be a positive integer')
        if not isinstance(key, str) or not key:
            raise ValueError('key must be a nonempty string')

        receipt = dict(source=source, target=target, amount=amount, key=key)
        if key in self.history:
            if self.history[key] != receipt:
                raise ValueError('key already used for a different transfer')
            return dict(self.history[key])
        if self.balances[source] < amount:
            raise ValueError('insufficient funds')

        source_balance = self.balances[source] - amount
        target_balance = self.balances[target] + amount
        self.balances[source] = source_balance
        self.balances[target] = target_balance
        self.history[key] = receipt
        return dict(receipt)

    def batch(self, operations):
        if not isinstance(operations, list):
            raise ValueError('operations must be a list')
        operations = list(operations)
        for index, operation in enumerate(operations):
            if not isinstance(operation, dict):
                raise ValueError('each operation must be a dictionary')
            operation = dict(operation)
            if operation.keys() != {'source', 'target', 'amount', 'key'}:
                raise ValueError('operation must contain source, target, amount and key')
            operations[index] = operation

        # Existing receipts are shared only for reading; transfer returns copies.
        staged = Ledger(self.balances)
        staged.history.update(self.history)
        receipts = [staged.transfer(**operation) for operation in operations]

        # Commit only after every operation succeeds, preserving public dicts.
        self.balances.update(staged.balances)
        self.history.update(staged.history)
        return receipts
