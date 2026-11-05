class Ledger:
    def __init__(self, balances):
        self.balances = balances
        self.history = {}
    def transfer(self, source, target, amount, key):
        if key in self.history:
            return self.history[key]
        self.balances[source] -= amount
        if self.balances[source] < 0:
            raise ValueError('insufficient funds')
        self.balances[target] += amount
        receipt = dict(source=source, target=target, amount=amount, key=key)
        self.history[key] = receipt
        return receipt
    def batch(self, operations):
        return [self.transfer(**op) for op in operations]
