"""Atomic, idempotent batch ledger; synthetic benchmark candidate."""
import copy

FIELDS = frozenset(('source', 'target', 'amount', 'key'))


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


class Ledger:
    def __init__(self, balances):
        if not isinstance(balances, dict):
            raise ValueError('balances must be a mapping')
        for name, value in balances.items():
            if not isinstance(name, str) or not _is_int(value) or value < 0:
                raise ValueError('invalid balance')
        self.balances = {str(name): int(value) for name, value in balances.items()}
        self.history = {}

    def transfer(self, source, target, amount, key):
        if not isinstance(key, str) or not key:
            raise ValueError('invalid key')
        if not _is_int(amount) or amount <= 0:
            raise ValueError('invalid amount')
        if not isinstance(source, str) or not isinstance(target, str) or source == target:
            raise ValueError('invalid accounts')
        receipt = {'source': source, 'target': target, 'amount': amount, 'key': key}
        if key in self.history:
            if self.history[key] != receipt:
                raise ValueError('key conflict')
            return dict(receipt)
        if source not in self.balances or target not in self.balances:
            raise ValueError('unknown account')
        if self.balances[source] < amount:
            raise ValueError('insufficient funds')
        self.balances[source] -= amount
        self.balances[target] += amount
        self.history[key] = dict(receipt)
        return dict(receipt)

    def batch(self, operations):
        if not isinstance(operations, list):
            raise ValueError('operations must be a list')
        saved = (dict(self.balances), copy.deepcopy(self.history))
        receipts = []
        try:
            for operation in operations:
                if not isinstance(operation, dict) or set(operation) != FIELDS:
                    raise ValueError('invalid operation')
                receipts.append(self.transfer(**operation))
        except Exception:
            self.balances, self.history = saved
            raise
        return receipts
