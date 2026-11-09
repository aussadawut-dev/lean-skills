import copy
import unittest

from ledger import Ledger


def operation(source="a", target="b", amount=20, key="payment"):
    return dict(source=source, target=target, amount=amount, key=key)


class LedgerTests(unittest.TestCase):
    def seeded_ledger(self):
        ledger = Ledger({"a": 100, "b": 20, "c": 0})
        ledger.transfer("b", "c", 5, "seed")
        return ledger

    def snapshot(self, ledger):
        return copy.deepcopy((ledger.balances, ledger.history))

    def assert_rejected_without_change(self, ledger, action):
        balances, history = ledger.balances, ledger.history
        before = self.snapshot(ledger)
        with self.assertRaises(ValueError):
            action()
        self.assertEqual((ledger.balances, ledger.history), before)
        self.assertIs(ledger.balances, balances)
        self.assertIs(ledger.history, history)

    def test_constructor_copies_input(self):
        original = {"a": 100, "b": 0}
        ledger = Ledger(original)
        original["a"] = 200
        original["outside"] = 10
        self.assertEqual(ledger.balances, {"a": 100, "b": 0})
        ledger.transfer("a", "b", 20, "payment")
        self.assertEqual(original, {"a": 200, "b": 0, "outside": 10})

    def test_constructor_rejects_invalid_balances(self):
        invalid = [None, [], (), 1, "accounts", {1: 10}, {None: 10}]
        invalid.extend({"a": value} for value in
                       [-1, True, False, 1.0, "1", None, [], {}])
        for balances in invalid:
            with self.subTest(balances=balances):
                before = copy.deepcopy(balances)
                with self.assertRaises(ValueError):
                    Ledger(balances)
                self.assertEqual(balances, before)

    def test_empty_ledger_and_empty_batch(self):
        ledger = Ledger({})
        self.assertEqual(ledger.batch([]), [])
        self.assertEqual((ledger.balances, ledger.history), ({}, {}))
        self.assert_rejected_without_change(
            ledger, lambda: ledger.transfer("a", "b", 1, "missing"))
        seeded = self.seeded_ledger()
        before = self.snapshot(seeded)
        self.assertEqual(seeded.batch([]), [])
        self.assertEqual((seeded.balances, seeded.history), before)

    def test_transfer_returns_receipt_and_preserves_public_dictionaries(self):
        ledger = self.seeded_ledger()
        balances, history = ledger.balances, ledger.history
        receipt = ledger.transfer("a", "b", 20, "payment")
        self.assertEqual(receipt, operation())
        self.assertEqual(ledger.balances, {"a": 80, "b": 35, "c": 5})
        self.assertEqual(ledger.history, {
            "seed": operation("b", "c", 5, "seed"), "payment": operation()})
        self.assertIs(ledger.balances, balances)
        self.assertIs(ledger.history, history)

    def test_insufficient_funds_do_not_change_state(self):
        ledger = self.seeded_ledger()
        self.assert_rejected_without_change(
            ledger, lambda: ledger.transfer("a", "b", 101, "too-much"))

    def test_invalid_transfers_do_not_change_state(self):
        invalid = []
        for field in ("source", "target"):
            invalid.extend({field: value} for value in
                           ["missing", None, 1, True, [], {}])
        invalid.append({"target": "a"})
        invalid.extend({"amount": value} for value in
                       [0, -1, True, False, 1.0, "1", None, [], {}])
        invalid.extend({"key": value} for value in
                       ["", None, 1, True, [], {}])
        for change in invalid:
            with self.subTest(change=change):
                ledger = self.seeded_ledger()
                payload = dict(operation(), **change)
                self.assert_rejected_without_change(
                    ledger, lambda: ledger.transfer(**payload))

    def test_valid_boundaries_and_replay_with_empty_source(self):
        amount = 10 ** 100
        ledger = Ledger({"": amount, "b": 0})
        expected = operation("", "b", amount, " ")
        first = ledger.transfer(**expected)
        self.assertEqual(ledger.balances, {"": 0, "b": amount})
        before = self.snapshot(ledger)
        replay = ledger.transfer(**expected)
        self.assertEqual(first, expected)
        self.assertEqual(replay, expected)
        self.assertIsNot(first, replay)
        self.assertEqual((ledger.balances, ledger.history), before)

    def test_changed_replay_payload_is_rejected(self):
        changes = [dict(source="c"), dict(target="c"), dict(amount=21),
                   dict(source="b", target="a")]
        for change in changes:
            with self.subTest(change=change):
                ledger = Ledger({"a": 100, "b": 100, "c": 100})
                ledger.transfer(**operation())
                payload = dict(operation(), **change)
                self.assert_rejected_without_change(
                    ledger, lambda: ledger.transfer(**payload))

    def test_replay_validates_types_before_comparing_payload(self):
        ledger = Ledger({"a": 3, "b": 0})
        ledger.transfer("a", "b", 1, "payment")
        for change in [dict(amount=True), dict(amount=1.0),
                       dict(source=[]), dict(target=None)]:
            with self.subTest(change=change):
                payload = dict(operation(amount=1), **change)
                self.assert_rejected_without_change(
                    ledger, lambda: ledger.transfer(**payload))

    def test_returned_transfer_receipts_are_isolated(self):
        ledger = Ledger({"a": 100, "b": 0})
        receipt = ledger.transfer(**operation())
        receipt.clear()
        self.assertEqual(ledger.history, {"payment": operation()})
        replay = ledger.transfer(**operation())
        self.assertEqual(replay, operation())
        replay["amount"] = 999
        self.assertEqual(ledger.history, {"payment": operation()})
        self.assertEqual(ledger.balances, {"a": 80, "b": 20})

    def test_batch_matches_ordered_transfers_with_replays(self):
        ledger, sequential = self.seeded_ledger(), self.seeded_ledger()
        balances, history = ledger.balances, ledger.history
        operations = [operation("a", "b", 70, "one"),
                      operation("b", "c", 80, "two"),
                      operation("a", "b", 70, "one"),
                      operation("b", "c", 5, "seed"),
                      operation("c", "a", 50, "three")]
        original = copy.deepcopy(operations)
        expected = [sequential.transfer(**item) for item in operations]
        self.assertEqual(ledger.batch(operations), expected)
        self.assertEqual(ledger.balances, {"a": 80, "b": 5, "c": 35})
        self.assertEqual(self.snapshot(ledger), self.snapshot(sequential))
        self.assertEqual(operations, original)
        self.assertIs(ledger.balances, balances)
        self.assertIs(ledger.history, history)

    def test_batch_receipts_are_isolated_from_history_and_each_other(self):
        ledger = self.seeded_ledger()
        seed = operation("b", "c", 5, "seed")
        receipts = ledger.batch([operation(), operation(), seed])
        receipts[0].clear()
        self.assertEqual(receipts[1], operation())
        receipts[1]["amount"] = 999
        receipts[2].clear()
        self.assertEqual(ledger.history, {"seed": seed, "payment": operation()})
        self.assertEqual(ledger.transfer(**operation()), operation())
        self.assertEqual(ledger.transfer(**seed), seed)

    def test_batch_failure_rolls_back_at_every_position(self):
        valid = [operation(), operation("b", "c", 10, "second")]
        failure = operation("c", "a", 1000, "failed")
        for position in range(3):
            with self.subTest(position=position):
                ledger = self.seeded_ledger()
                operations = valid[:position] + [failure] + valid[position:]
                original = copy.deepcopy(operations)
                self.assert_rejected_without_change(
                    ledger, lambda: ledger.batch(operations))
                self.assertEqual(operations, original)

    def test_batch_rejects_conflicting_new_and_existing_keys_atomically(self):
        for conflict in [operation(amount=21), operation("b", "c", 6, "seed")]:
            with self.subTest(conflict=conflict):
                ledger = self.seeded_ledger()
                self.assert_rejected_without_change(
                    ledger, lambda: ledger.batch([operation(), conflict]))

    def test_batch_rejects_non_list_input(self):
        for operations in [None, {}, (), "operations", 1, iter([])]:
            with self.subTest(operations=operations):
                ledger = self.seeded_ledger()
                self.assert_rejected_without_change(
                    ledger, lambda: ledger.batch(operations))

    def test_batch_rejects_malformed_operations_atomically(self):
        invalid = [None, [], (), "operation", 1, {},
                   dict(operation(), extra=1), {1: "a"}]
        invalid.extend({key: value for key, value in operation().items()
                        if key != missing} for missing in operation())
        invalid.extend([operation(source=[]), operation(target="missing"),
                        operation(target="a"), operation(amount=-1),
                        operation(amount=True), operation(key="")])
        for bad_operation in invalid:
            with self.subTest(operation=bad_operation):
                ledger = self.seeded_ledger()
                self.assert_rejected_without_change(
                    ledger, lambda: ledger.batch([operation(), bad_operation]))

    def test_integrated_multi_transfer_flow(self):
        initial = {"cash": 1000, "savings": 0, "bills": 0}
        ledger = Ledger(initial)
        save = operation("cash", "savings", 200, "save")
        self.assertEqual(ledger.transfer(**save), save)
        payments = [operation("cash", "bills", 300, "rent"),
                    operation("savings", "cash", 50, "refill"),
                    operation("cash", "bills", 300, "rent"),
                    operation("savings", "bills", 100, "pay")]
        self.assertEqual(ledger.batch(payments), payments)
        self.assertEqual(ledger.balances, {"cash": 550, "savings": 50, "bills": 400})
        before = self.snapshot(ledger)
        self.assertEqual(ledger.transfer(**save), save)
        self.assertEqual((ledger.balances, ledger.history), before)

        retry = operation("cash", "savings", 400, "retry")
        failed = operation("bills", "cash", 401, "refund")
        self.assert_rejected_without_change(
            ledger, lambda: ledger.batch([retry, failed]))
        corrected = [retry, operation("bills", "cash", 400, "refund")]
        self.assertEqual(ledger.batch(corrected), corrected)
        self.assertEqual(ledger.balances, {"cash": 550, "savings": 450, "bills": 0})
        self.assertEqual(ledger.history, {
            item["key"]: item for item in [save] + payments + corrected})
        before = self.snapshot(ledger)
        self.assertEqual(ledger.batch(corrected), corrected)
        self.assertEqual((ledger.balances, ledger.history), before)
        self.assert_rejected_without_change(
            ledger, lambda: ledger.transfer("cash", "savings", 201, "save"))
        self.assertEqual(sum(ledger.balances.values()), 1000)
        self.assertEqual(initial, {"cash": 1000, "savings": 0, "bills": 0})


if __name__ == "__main__":
    unittest.main()
