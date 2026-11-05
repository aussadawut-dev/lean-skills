def _plain_string(value, message):
    if not issubclass(type(value), str):
        raise ValueError(message)
    # Call the built-in implementation, bypassing subclass conversion hooks.
    return str.__str__(value)


def _plain_integer(value, minimum, message):
    if not issubclass(type(value), int) or type(value) is bool:
        raise ValueError(message)
    value = int.__int__(value)
    if value < minimum:
        raise ValueError(message)
    return value


class Ledger:
    def __init__(self, balances):
        if not isinstance(balances, dict):
            raise ValueError('balances must be a dictionary')
        owned_balances = {}
        for account, balance in dict(balances).items():
            account = _plain_string(account, 'account names must be strings')
            balance = _plain_integer(balance, 0, 'balances must be nonnegative integers')
            if account in owned_balances:
                raise ValueError('account names must be unique')
            owned_balances[account] = balance
        self.balances = owned_balances
        self.history = {}

    def transfer(self, source, target, amount, key):
        account_error = 'source and target must be distinct existing accounts'
        source = _plain_string(source, account_error)
        target = _plain_string(target, account_error)
        if (source == target
                or source not in self.balances or target not in self.balances):
            raise ValueError(account_error)
        amount = _plain_integer(amount, 1, 'amount must be a positive integer')
        key = _plain_string(key, 'key must be a nonempty string')
        if not key:
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
            normalized = {
                _plain_string(field, 'operation field names must be strings'): value
                for field, value in operation.items()
            }
            if (len(operation) != 4
                    or normalized.keys() != {'source', 'target', 'amount', 'key'}):
                raise ValueError('operation must contain source, target, amount and key')
            operations[index] = normalized

        # Existing receipts are shared only for reading; transfer returns copies.
        staged = Ledger(self.balances)
        staged.history.update(self.history)
        receipts = [staged.transfer(**operation) for operation in operations]

        # Commit only after every operation succeeds, preserving public dicts.
        self.balances.update(staged.balances)
        self.history.update(staged.history)
        return receipts
