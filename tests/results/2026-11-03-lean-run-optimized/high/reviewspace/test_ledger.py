import copy
import unittest

from ledger import Ledger


def operation(source, target, amount, key):
    return dict(source=source, target=target, amount=amount, key=key)


class LedgerTestCase(unittest.TestCase):
    def assert_rejected_unchanged(self, ledger, action):
        balances = ledger.balances
        history = ledger.history
        before = copy.deepcopy((balances, history))
        with self.assertRaises(ValueError):
            action()
        self.assertIs(ledger.balances, balances)
        self.assertIs(ledger.history, history)
        self.assertEqual((ledger.balances, ledger.history), before)


class ConstructorTests(LedgerTestCase):
    def test_input_is_copied_in_both_directions(self):
        initial = {"a": 100, "b": 0}
        ledger = Ledger(initial)
        ledger.transfer("a", "b", 20, "first")
        self.assertEqual(initial, {"a": 100, "b": 0})
        initial["a"] = 1
        initial["c"] = 5
        self.assertEqual(ledger.balances, {"a": 80, "b": 20})

    def test_invalid_initial_balances_are_rejected(self):
        for invalid in (-1, True, False, 1.5, "10", None, []):
            with self.subTest(balance=invalid):
                initial = {"a": 10, "b": invalid}
                before = copy.deepcopy(initial)
                with self.assertRaises(ValueError):
                    Ledger(initial)
                self.assertEqual(initial, before)

    def test_constructor_requires_a_dictionary_of_string_accounts(self):
        for invalid in (None, [], [("a", 1)], {1: 10}, {None: 10}):
            with self.subTest(balances=invalid):
                with self.assertRaises(ValueError):
                    Ledger(invalid)

    def test_empty_ledger_and_unbounded_integer_balances(self):
        ledger = Ledger({})
        self.assertEqual(ledger.balances, {})
        self.assertEqual(ledger.history, {})
        amount = 10**100
        ledger = Ledger({"": amount, "b": 0})
        self.assertEqual(
            ledger.transfer("", "b", amount, " "),
            operation("", "b", amount, " "),
        )
        self.assertEqual(ledger.balances, {"": 0, "b": amount})


class TransferTests(LedgerTestCase):
    def test_success_returns_receipt_and_preserves_public_dictionaries(self):
        ledger = Ledger({"a": 100, "b": 0})
        balances, history = ledger.balances, ledger.history
        expected = operation("a", "b", 100, "all")
        self.assertEqual(ledger.transfer(**expected), expected)
        self.assertEqual(balances, {"a": 0, "b": 100})
        self.assertEqual(history, {"all": expected})
        self.assertIs(ledger.balances, balances)
        self.assertIs(ledger.history, history)

    def test_invalid_transfers_leave_all_state_unchanged(self):
        cases = [
            ("source", "missing"), ("target", "missing"),
            ("source", "b"), ("target", "a"),
            ("source", []), ("target", {}),
            ("source", None), ("target", 1),
        ]
        cases.extend(("amount", value) for value in
                     (0, -1, True, False, 1.0, "1", None, [], 1000))
        cases.extend(("key", value) for value in
                     ("", None, 1, True, [], {}))
        for field, value in cases:
            with self.subTest(field=field, value=value):
                ledger = Ledger({"a": 100, "b": 0})
                ledger.transfer("a", "b", 5, "seed")
                invalid = operation("a", "b", 10, "next")
                invalid[field] = value
                self.assert_rejected_unchanged(
                    ledger, lambda: ledger.transfer(**invalid)
                )

    def test_replay_succeeds_even_when_balance_is_now_insufficient(self):
        ledger = Ledger({"a": 100, "b": 0, "c": 0})
        original = ledger.transfer("a", "b", 100, "first")
        ledger.transfer("b", "c", 70, "second")
        before = copy.deepcopy((ledger.balances, ledger.history))
        self.assertEqual(ledger.transfer("a", "b", 100, "first"), original)
        self.assertEqual((ledger.balances, ledger.history), before)

    def test_changed_replay_payload_is_rejected(self):
        for field, value in (("source", "c"), ("target", "c"), ("amount", 11)):
            with self.subTest(field=field):
                ledger = Ledger({"a": 100, "b": 0, "c": 100})
                original = operation("a", "b", 10, "first")
                ledger.transfer(**original)
                changed = dict(original, **{field: value})
                self.assert_rejected_unchanged(
                    ledger, lambda: ledger.transfer(**changed)
                )

    def test_replay_does_not_accept_bool_or_float_amounts_equal_to_integer(self):
        ledger = Ledger({"a": 10, "b": 0})
        ledger.transfer("a", "b", 1, "first")
        for amount in (True, 1.0):
            with self.subTest(amount=amount):
                self.assert_rejected_unchanged(
                    ledger, lambda: ledger.transfer("a", "b", amount, "first")
                )

    def test_fresh_and_replayed_receipts_cannot_modify_history(self):
        ledger = Ledger({"a": 10, "b": 0})
        expected = operation("a", "b", 5, "first")
        first = ledger.transfer(**expected)
        first.update(source="other", amount=999, extra=[])
        replay = ledger.transfer(**expected)
        self.assertEqual(replay, expected)
        replay.clear()
        self.assertEqual(ledger.history, {"first": expected})
        self.assertEqual(ledger.transfer(**expected), expected)
        self.assertEqual(ledger.balances, {"a": 5, "b": 5})

    def test_failed_transfer_does_not_consume_key(self):
        ledger = Ledger({"a": 10, "b": 0})
        self.assert_rejected_unchanged(
            ledger, lambda: ledger.transfer("a", "b", 11, "retry")
        )
        expected = operation("a", "b", 10, "retry")
        self.assertEqual(ledger.transfer(**expected), expected)
        self.assertEqual(ledger.balances, {"a": 0, "b": 10})


class BatchTests(LedgerTestCase):
    def test_success_is_ordered_and_uses_intermediate_balances(self):
        ledger = Ledger({"a": 100, "b": 0, "c": 0})
        balances, history = ledger.balances, ledger.history
        operations = [
            operation("a", "b", 70, "first"),
            operation("b", "c", 50, "second"),
            operation("c", "a", 10, "third"),
            operation("a", "b", 70, "first"),
        ]
        before = copy.deepcopy(operations)
        receipts = ledger.batch(operations)
        self.assertEqual(receipts, before)
        self.assertEqual(operations, before)
        self.assertEqual(balances, {"a": 40, "b": 20, "c": 40})
        self.assertEqual(history, {op["key"]: op for op in before})
        self.assertIs(ledger.balances, balances)
        self.assertIs(ledger.history, history)
        operations[0]["amount"] = 999
        receipts[0].clear()
        self.assertEqual(receipts[3], before[3])
        receipts[3]["target"] = "other"
        self.assertEqual(ledger.history["first"], before[0])
        self.assertEqual(ledger.transfer(**before[0]), before[0])

    def test_empty_batch_leaves_state_and_dictionary_identity_unchanged(self):
        ledger = Ledger({"a": 10, "b": 0})
        ledger.transfer("a", "b", 1, "seed")
        balances, history = ledger.balances, ledger.history
        before = copy.deepcopy((balances, history))
        self.assertEqual(ledger.batch([]), [])
        self.assertEqual((ledger.balances, ledger.history), before)
        self.assertIs(ledger.balances, balances)
        self.assertIs(ledger.history, history)

    def test_invalid_batch_containers_raise_value_error(self):
        for operations in (None, (), {}, "", 1, iter([])):
            with self.subTest(operations=operations):
                ledger = Ledger({"a": 10, "b": 0})
                self.assert_rejected_unchanged(
                    ledger, lambda: ledger.batch(operations)
                )

    def test_late_failure_restores_balances_and_existing_history(self):
        invalid_operations = [
            operation("a", "b", 1000, "bad"),
            operation("a", "missing", 1, "bad"),
            operation("missing", "b", 1, "bad"),
            operation("a", "a", 1, "bad"),
            operation("a", "b", True, "bad"),
            operation("a", "b", 0, "bad"),
            operation("a", "b", 1, ""),
            operation("a", "b", 1, []),
            operation([], "b", 1, "bad"),
            None, [], {}, {"source": "a"},
            dict(operation("a", "b", 1, "bad"), extra=True),
            {1: "a", "target": "b", "amount": 1, "key": "bad"},
        ]
        for invalid in invalid_operations:
            with self.subTest(operation=invalid):
                ledger = Ledger({"a": 100, "b": 0, "c": 0})
                seed = operation("a", "b", 5, "seed")
                ledger.transfer(**seed)
                operations = [
                    seed,
                    operation("a", "b", 10, "first"),
                    operation("b", "c", 10, "second"),
                    invalid,
                ]
                before = copy.deepcopy(operations)
                self.assert_rejected_unchanged(
                    ledger, lambda: ledger.batch(operations)
                )
                self.assertEqual(operations, before)

    def test_conflicts_with_new_or_existing_keys_roll_back_batch(self):
        for conflict_key in ("seed", "new"):
            with self.subTest(key=conflict_key):
                ledger = Ledger({"a": 100, "b": 0, "c": 0})
                ledger.transfer("a", "b", 5, "seed")
                operations = [
                    operation("a", "b", 10, "new"),
                    operation("a", "c", 10, conflict_key),
                ]
                self.assert_rejected_unchanged(
                    ledger, lambda: ledger.batch(operations)
                )

    def test_failed_batch_can_retry_and_successful_batch_can_replay(self):
        ledger = Ledger({"a": 100, "b": 0, "c": 0})
        failed = [
            operation("a", "b", 80, "fund"),
            operation("b", "c", 90, "spend"),
        ]
        self.assert_rejected_unchanged(ledger, lambda: ledger.batch(failed))
        corrected = [failed[0], operation("b", "c", 50, "spend")]
        self.assertEqual(ledger.batch(corrected), corrected)
        self.assertEqual(ledger.balances, {"a": 20, "b": 30, "c": 50})
        before = copy.deepcopy((ledger.balances, ledger.history))
        self.assertEqual(ledger.batch(corrected), corrected)
        self.assertEqual((ledger.balances, ledger.history), before)


class IntegratedJourneyTests(LedgerTestCase):
    def test_funding_payments_failed_refund_recovery_and_replay(self):
        initial = {"treasury": 1000, "alice": 0, "bob": 0, "merchant": 0}
        ledger = Ledger(initial)
        funding = operation("treasury", "alice", 300, "fund-alice")
        first_receipt = ledger.transfer(**funding)
        payments = [
            operation("treasury", "bob", 200, "fund-bob"),
            operation("alice", "merchant", 80, "buy"),
            operation("bob", "alice", 50, "repay"),
            funding,
        ]
        self.assertEqual(ledger.batch(payments), payments)
        self.assertEqual(ledger.balances,
                         {"treasury": 500, "alice": 270, "bob": 150, "merchant": 80})
        refund = operation("merchant", "bob", 30, "refund")
        self.assert_rejected_unchanged(ledger, lambda: ledger.batch([
            refund, operation("bob", "alice", 999, "repay-2")
        ]))
        recovered = [refund, operation("bob", "alice", 20, "repay-2"), payments[1]]
        self.assertEqual(ledger.batch(recovered), recovered)
        expected_balances = {"treasury": 500, "alice": 290, "bob": 160, "merchant": 50}
        self.assertEqual(ledger.balances, expected_balances)
        first_receipt.clear()
        replay = ledger.batch([funding] + payments + recovered)
        self.assertEqual(replay, [funding] + payments + recovered)
        replay[0].clear()
        self.assertEqual(ledger.balances, expected_balances)
        self.assertEqual(sum(ledger.balances.values()), 1000)
        self.assertEqual(ledger.history, {op["key"]: op for op in
                                        [funding] + payments + recovered})
        self.assertEqual(initial,
                         {"treasury": 1000, "alice": 0, "bob": 0, "merchant": 0})


if __name__ == "__main__":
    unittest.main()
