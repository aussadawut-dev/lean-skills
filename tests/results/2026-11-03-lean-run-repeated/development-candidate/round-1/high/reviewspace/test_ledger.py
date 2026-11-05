import copy
import unittest

from ledger import Ledger


def operation(source="a", target="b", amount=10, key="one"):
    return dict(source=source, target=target, amount=amount, key=key)


class LedgerTests(unittest.TestCase):
    def assert_rejected_without_change(self, ledger, action):
        balances, history = ledger.balances, ledger.history
        before = copy.deepcopy((balances, history))
        with self.assertRaises(ValueError):
            action()
        self.assertEqual((ledger.balances, ledger.history), before)
        self.assertIs(ledger.balances, balances)
        self.assertIs(ledger.history, history)

    def test_constructor_copies_input(self):
        balances = {"a": 100, "b": 0}
        ledger = Ledger(balances)
        self.assertIsNot(ledger.balances, balances)
        balances["a"] = 1
        self.assertEqual(ledger.balances, {"a": 100, "b": 0})
        ledger.transfer("a", "b", 20, "one")
        self.assertEqual(balances, {"a": 1, "b": 0})

    def test_constructor_accepts_empty_and_nonnegative_balances(self):
        for balances in ({}, {"a": 0}, {"": 0, "b": 10**30}):
            with self.subTest(balances=balances):
                ledger = Ledger(balances)
                self.assertEqual(ledger.balances, balances)
                self.assertEqual(ledger.history, {})

    def test_constructor_rejects_invalid_balances(self):
        invalid = [None, [], [("a", 1)], "a", {1: 1}, {None: 1}]
        invalid.extend({"a": value} for value in (-1, True, False, 1.0, "1", None, [], {}))
        for balances in invalid:
            with self.subTest(balances=balances):
                before = copy.deepcopy(balances)
                with self.assertRaises(ValueError):
                    Ledger(balances)
                self.assertEqual(balances, before)

    def test_transfer_records_all_effects_and_can_spend_exact_balance(self):
        for amount in (1, 100, 10**30):
            with self.subTest(amount=amount):
                ledger = Ledger({"a": amount, "b": 7})
                balances, history = ledger.balances, ledger.history
                expected = operation(amount=amount)
                self.assertEqual(ledger.transfer(**expected), expected)
                self.assertEqual(ledger.balances, {"a": 0, "b": amount + 7})
                self.assertEqual(ledger.history, {"one": expected})
                self.assertIs(ledger.balances, balances)
                self.assertIs(ledger.history, history)

    def test_empty_account_name_and_whitespace_key_are_valid(self):
        ledger = Ledger({"": 10, "b": 0})
        expected = operation(source="", key=" ")
        self.assertEqual(ledger.transfer(**expected), expected)
        self.assertEqual(ledger.balances, {"": 0, "b": 10})
        self.assertEqual(ledger.history, {" ": expected})

    def test_invalid_transfers_have_no_effect(self):
        changes = [
            {"source": "missing"}, {"target": "missing"},
            {"source": "b"}, {"source": None}, {"target": None},
            {"source": []}, {"target": {}}, {"source": 1}, {"target": True},
        ]
        changes.extend({"amount": value} for value in (0, -1, True, False, 1.0, "1", None, [], {}))
        changes.extend({"key": value} for value in ("", None, 1, True, [], {}))
        for change in changes:
            with self.subTest(change=change):
                ledger = Ledger({"a": 100, "b": 10, "c": 0})
                ledger.transfer("b", "c", 1, "seed")
                op = operation(**change)
                self.assert_rejected_without_change(ledger, lambda: ledger.transfer(**op))

    def test_insufficient_funds_has_no_effect_and_does_not_reserve_key(self):
        for source, target, amount in (("a", "b", 11), ("b", "a", 1)):
            with self.subTest(source=source):
                ledger = Ledger({"a": 10, "b": 0})
                self.assert_rejected_without_change(
                    ledger, lambda: ledger.transfer(source, target, amount, "retry")
                )
                expected = operation(amount=10, key="retry")
                self.assertEqual(ledger.transfer(**expected), expected)
                self.assertEqual(ledger.balances, {"a": 0, "b": 10})
                self.assertEqual(ledger.history, {"retry": expected})

    def test_replay_succeeds_even_after_balance_is_exhausted(self):
        ledger = Ledger({"a": 10, "b": 0})
        expected = operation()
        first = ledger.transfer(**expected)
        before = copy.deepcopy((ledger.balances, ledger.history))
        replay = ledger.transfer(**expected)
        self.assertEqual(replay, expected)
        self.assertIsNot(replay, first)
        self.assertEqual((ledger.balances, ledger.history), before)

    def test_changed_replay_payload_is_rejected(self):
        for change in ({"source": "c"}, {"target": "c"}, {"amount": 2}):
            with self.subTest(change=change):
                ledger = Ledger({"a": 100, "b": 10, "c": 10})
                ledger.transfer("a", "b", 1, "one")
                op = operation(amount=1)
                op.update(change)
                self.assert_rejected_without_change(ledger, lambda: ledger.transfer(**op))

    def test_replay_still_validates_types(self):
        ledger = Ledger({"a": 10, "b": 0})
        ledger.transfer("a", "b", 1, "one")
        for amount in (True, 1.0):
            with self.subTest(amount=amount):
                self.assert_rejected_without_change(
                    ledger, lambda: ledger.transfer("a", "b", amount, "one")
                )

    def test_new_and_replayed_receipts_cannot_modify_history(self):
        ledger = Ledger({"a": 100, "b": 0})
        expected = operation()
        for _ in range(2):
            receipt = ledger.transfer(**expected)
            receipt.clear()
            receipt["amount"] = 999
            self.assertEqual(ledger.history, {"one": expected})
            self.assertEqual(ledger.transfer(**expected), expected)
            self.assertEqual(ledger.balances, {"a": 90, "b": 10})

    def test_empty_batch_is_a_no_op(self):
        ledger = Ledger({"a": 100, "b": 0})
        ledger.transfer(**operation())
        balances, history = ledger.balances, ledger.history
        before = copy.deepcopy((balances, history))
        self.assertEqual(ledger.batch([]), [])
        self.assertEqual((ledger.balances, ledger.history), before)
        self.assertIs(ledger.balances, balances)
        self.assertIs(ledger.history, history)
        self.assertEqual(Ledger({}).batch([]), [])

    def test_batch_requires_a_list(self):
        invalid = [None, (), (operation(),), operation(), "", iter([operation()])]
        for operations in invalid:
            with self.subTest(operations=operations):
                ledger = Ledger({"a": 100, "b": 0})
                self.assert_rejected_without_change(ledger, lambda: ledger.batch(operations))

    def test_malformed_batch_operations_have_no_effect(self):
        invalid = [None, [], list(operation().items()), "one", {}, {1: 2}]
        invalid.append(dict(operation(), extra=True))
        for field in operation():
            malformed = operation()
            del malformed[field]
            invalid.append(malformed)
        for malformed in invalid:
            with self.subTest(operation=malformed):
                ledger = Ledger({"a": 100, "b": 0})
                ledger.transfer("a", "b", 1, "seed")
                operations = [operation(), malformed]
                before = copy.deepcopy(operations)
                self.assert_rejected_without_change(ledger, lambda: ledger.batch(operations))
                self.assertEqual(operations, before)

    def test_batch_rolls_back_when_any_transfer_is_invalid(self):
        invalid = [
            operation(source="missing", key="bad"),
            operation(target="missing", key="bad"),
            operation(target="a", key="bad"),
            operation(amount=0, key="bad"),
            operation(amount=True, key="bad"),
            operation(key=""),
            operation(source="b", target="c", amount=100, key="bad"),
            operation(amount=11),  # Conflicts with the first operation's new key.
            operation(amount=2, key="seed"),  # Conflicts with pre-batch history.
        ]
        for bad in invalid:
            with self.subTest(operation=bad):
                ledger = Ledger({"a": 100, "b": 0, "c": 0})
                ledger.transfer("a", "b", 1, "seed")
                self.assert_rejected_without_change(
                    ledger, lambda: ledger.batch([operation(), bad])
                )

    def test_batch_failure_at_first_middle_or_last_position(self):
        for position in range(3):
            with self.subTest(position=position):
                ledger = Ledger({"a": 100, "b": 0, "c": 0})
                operations = [operation(), operation("b", "c", 5, "two")]
                operations.insert(position, operation(amount=1000, key="bad"))
                self.assert_rejected_without_change(ledger, lambda: ledger.batch(operations))
                self.assertEqual(ledger.batch([operation()]), [operation()])

    def test_successful_batch_replays_in_order_and_detaches_receipts(self):
        ledger = Ledger({"a": 10, "b": 0, "c": 0})
        balances, history = ledger.balances, ledger.history
        operations = [operation(), operation(), operation("b", "c", 10, "two")]
        before = copy.deepcopy(operations)
        receipts = ledger.batch(operations)
        self.assertEqual(receipts, before)
        self.assertEqual(operations, before)
        self.assertEqual(ledger.balances, {"a": 0, "b": 0, "c": 10})
        self.assertEqual(ledger.history, {"one": before[0], "two": before[2]})
        self.assertIs(ledger.balances, balances)
        self.assertIs(ledger.history, history)
        receipts[0].clear()
        self.assertEqual(receipts[1], before[1])
        self.assertEqual(ledger.history["one"], before[0])
        self.assertEqual(ledger.batch(before), before)
        operations[2]["amount"] = 999
        self.assertEqual(ledger.history["two"], before[2])

    def test_integrated_funding_purchase_retry_and_recovery(self):
        initial = {"reserve": 100, "alice": 0, "bob": 0, "merchant": 0}
        ledger = Ledger(initial)
        funding = operation("reserve", "alice", 60, "fund")
        self.assertEqual(ledger.transfer(**funding), funding)
        gift = operation("alice", "bob", 25, "gift")
        purchase = operation("bob", "merchant", 20, "purchase")
        fee = operation("alice", "merchant", 5, "fee")
        checkout = [funding, gift, purchase, gift, fee]
        expected_balances = {"reserve": 40, "alice": 30, "bob": 5, "merchant": 25}
        expected_history = {op["key"]: op for op in (funding, gift, purchase, fee)}
        for _ in range(2):
            self.assertEqual(ledger.batch(checkout), checkout)
            self.assertEqual(ledger.balances, expected_balances)
            self.assertEqual(ledger.history, expected_history)

        refund = operation("merchant", "alice", 10, "refund")
        overspend = operation("alice", "reserve", 50, "settle")
        self.assert_rejected_without_change(ledger, lambda: ledger.batch([refund, overspend]))
        settlement = operation("alice", "reserve", 10, "settle")
        self.assertEqual(ledger.batch([refund, settlement]), [refund, settlement])
        self.assertEqual(ledger.balances, {"reserve": 50, "alice": 30, "bob": 5, "merchant": 15})
        expected_history.update(refund=refund, settle=settlement)
        self.assertEqual(ledger.history, expected_history)
        self.assertEqual(sum(ledger.balances.values()), 100)
        self.assertEqual(initial, {"reserve": 100, "alice": 0, "bob": 0, "merchant": 0})


if __name__ == "__main__":
    unittest.main()
