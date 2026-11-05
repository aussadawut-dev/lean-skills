class Ledger:
    def __init__(self, balances):
        if not isinstance(balances, dict):
            raise ValueError('balances must be a dictionary')
        for account, balance in balances.items():
            if not isinstance(account, str):
                raise ValueError('account names must be strings')
            if (not isinstance(balance, int) or isinstance(balance, bool)
                    or balance < 0):
                raise ValueError('balances must be nonnegative integers')
        self.balances = balances.copy()
        self.history = {}

    def transfer(self, source, target, amount, key):
        return self._transfer(self.balances, self.history,
                              source, target, amount, key)

    @staticmethod
    def _transfer(balances, history, source, target, amount, key):
        if not isinstance(source, str) or not isinstance(target, str):
            raise ValueError('account names must be strings')
        if source == target:
            raise ValueError('source and target must be distinct')
        if source not in balances or target not in balances:
            raise ValueError('account unavailable')
        if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
            raise ValueError('amount must be a positive integer')
        if not isinstance(key, str) or not key:
            raise ValueError('key must be a nonempty string')

        receipt = dict(source=source, target=target, amount=amount, key=key)
        if key in history:
            if history[key] != receipt:
                raise ValueError('key already used for a different transfer')
            return receipt
        if balances[source] < amount:
            raise ValueError('insufficient funds')

        balances[source] -= amount
        balances[target] += amount
        history[key] = receipt.copy()
        return receipt

    def batch(self, operations):
        if not isinstance(operations, list):
            raise ValueError('operations must be a list')

        # Existing history entries are only read; each new receipt is copied.
        # Staging both dictionaries therefore isolates every batch failure.
        balances = self.balances.copy()
        history = self.history.copy()
        receipts = []
        fields = {'source', 'target', 'amount', 'key'}
        for operation in operations:
            if not isinstance(operation, dict) or operation.keys() != fields:
                raise ValueError('each operation must contain source, target, amount and key')
            receipts.append(self._transfer(
                balances, history, operation['source'], operation['target'],
                operation['amount'], operation['key']))

        # Keep the public dictionary objects, including references held by callers.
        self.balances.update(balances)
        self.history.update(history)
        return receipts
