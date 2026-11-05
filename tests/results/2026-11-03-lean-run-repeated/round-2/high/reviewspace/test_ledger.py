from copy import deepcopy
import unittest

from ledger import Ledger


def operation(source="a", target="b", amount=10, key="new"):
    return dict(source=source, target=target, amount=amount, key=key)


class LedgerTests(unittest.TestCase):
    def seeded_ledger(self):
        ledger = Ledger({"a": 100, "b": 0, "c": 0})
        ledger.transfer("a", "b", 10, "existing")
        return ledger

    def assert_state(self, ledger, before, balances, history):
        self.assertEqual((ledger.balances, ledger.history), before)
        self.assertIs(ledger.balances, balances)
        self.assertIs(ledger.history, history)

    def assert_rejected_without_change(self, ledger, action):
        before = deepcopy((ledger.balances, ledger.history))
        balances, history = ledger.balances, ledger.history
        with self.assertRaises(ValueError):
            action()
        self.assert_state(ledger, before, balances, history)

    def test_constructor_copies_input(self):
        original = {"a": 100, "b": 0}
        ledger = Ledger(original)
        original["a"] = 1
        original["outside"] = 5
        self.assertEqual(ledger.balances, {"a": 100, "b": 0})
        ledger.transfer("a", "b", 20, "one")
        self.assertEqual(original, {"a": 1, "b": 0, "outside": 5})

    def test_constructor_accepts_nonnegative_integer_balances(self):
        for balances in ({}, {"": 0}, {"a": 10**100, "b": 0}):
            with self.subTest(balances=balances):
                ledger = Ledger(balances)
                self.assertEqual(ledger.balances, balances)
                self.assertIsNot(ledger.balances, balances)
                self.assertEqual(ledger.history, {})

    def test_constructor_rejects_invalid_balances(self):
        for value in (-1, True, False, 1.0, "1", None, [], {}):
            with self.subTest(value=value):
                original = {"a": 1, "bad": value}
                before = deepcopy(original)
                with self.assertRaises(ValueError):
                    Ledger(original)
                self.assertEqual(original, before)

    def test_constructor_requires_a_dictionary_with_string_accounts(self):
        for balances in (None, [], [("a", 1)], ("a", 1), {1: 1}, {None: 0}):
            with self.subTest(balances=balances):
                with self.assertRaises(ValueError):
                    Ledger(balances)

    def test_transfer_receipt_and_exact_available_balance(self):
        ledger = Ledger({"a": 10, "b": 0})
        balances, history = ledger.balances, ledger.history
        receipt = ledger.transfer("a", "b", 10, "one")
        self.assertEqual(receipt, operation(amount=10, key="one"))
        self.assertEqual(ledger.balances, {"a": 0, "b": 10})
        self.assertEqual(ledger.history, {"one": receipt})
        self.assertIs(ledger.balances, balances)
        self.assertIs(ledger.history, history)

    def test_transfer_preserves_large_integers(self):
        ledger = Ledger({"a": 10**100, "b": 1})
        receipt = ledger.transfer("a", "b", 10**100, "large")
        self.assertEqual(ledger.balances, {"a": 0, "b": 10**100 + 1})
        self.assertEqual(receipt, operation(amount=10**100, key="large"))

    def test_invalid_amounts_leave_state_unchanged(self):
        for amount in (0, -1, True, False, 1.0, "1", None, [], {}):
            with self.subTest(amount=amount):
                ledger = self.seeded_ledger()
                self.assert_rejected_without_change(
                    ledger, lambda: ledger.transfer("a", "b", amount, "invalid")
                )

    def test_invalid_keys_leave_state_unchanged(self):
        for key in ("", None, 0, True, [], {}):
            with self.subTest(key=key):
                ledger = self.seeded_ledger()
                self.assert_rejected_without_change(
                    ledger, lambda: ledger.transfer("a", "b", 1, key)
                )

    def test_unavailable_invalid_and_identical_accounts_are_atomic(self):
        for source, target in (
            ("missing", "b"), ("a", "missing"), ("a", "a"),
            ([], "b"), ("a", {}), (1, "b"), ("a", None),
        ):
            with self.subTest(source=source, target=target):
                ledger = self.seeded_ledger()
                self.assert_rejected_without_change(
                    ledger, lambda: ledger.transfer(source, target, 1, "invalid")
                )

    def test_insufficient_funds_are_atomic_and_do_not_reserve_key(self):
        ledger = self.seeded_ledger()
        self.assert_rejected_without_change(
            ledger, lambda: ledger.transfer("a", "b", 91, "retry")
        )
        receipt = ledger.transfer("a", "b", 90, "retry")
        self.assertEqual(receipt, operation(amount=90, key="retry"))
        self.assertEqual(ledger.balances, {"a": 0, "b": 100, "c": 0})

    def test_replay_succeeds_after_source_is_empty(self):
        ledger = Ledger({"a": 10, "b": 0})
        receipt = ledger.transfer("a", "b", 10, "one")
        before = deepcopy((ledger.balances, ledger.history))
        replay = ledger.transfer("a", "b", 10, "one")
        self.assertEqual(replay, receipt)
        self.assertEqual((ledger.balances, ledger.history), before)
        self.assertIsNot(replay, receipt)

    def test_replay_rejects_each_changed_payload_field(self):
        for changed in (
            operation(source="c", key="existing"),
            operation(target="c", key="existing"),
            operation(amount=11, key="existing"),
        ):
            with self.subTest(changed=changed):
                ledger = self.seeded_ledger()
                self.assert_rejected_without_change(
                    ledger, lambda: ledger.transfer(**changed)
                )

    def test_replay_still_validates_amount_type(self):
        for amount in (True, 1.0):
            with self.subTest(amount=amount):
                ledger = Ledger({"a": 1, "b": 0})
                ledger.transfer("a", "b", 1, "one")
                self.assert_rejected_without_change(
                    ledger, lambda: ledger.transfer("a", "b", amount, "one")
                )

    def test_new_and_replayed_receipts_cannot_change_history(self):
        for replay in (False, True):
            with self.subTest(replay=replay):
                ledger = Ledger({"a": 10, "b": 0})
                receipt = ledger.transfer("a", "b", 10, "one")
                if replay:
                    receipt = ledger.transfer("a", "b", 10, "one")
                before = deepcopy((ledger.balances, ledger.history))
                receipt.clear()
                receipt["amount"] = -100
                self.assertEqual((ledger.balances, ledger.history), before)
                self.assertEqual(
                    ledger.transfer("a", "b", 10, "one"),
                    operation(amount=10, key="one"),
                )

    def test_successful_batch_preserves_order_and_replay_semantics(self):
        ledger = self.seeded_ledger()
        balances, history = ledger.balances, ledger.history
        operations = [
            operation(key="existing"),
            operation(amount=90, key="fund"),
            operation("b", "c", 100, "spend"),
            operation("b", "c", 100, "spend"),
            operation(amount=90, key="fund"),
        ]
        before = deepcopy(operations)
        receipts = ledger.batch(operations)
        self.assertEqual(receipts, before)
        self.assertEqual(operations, before)
        self.assertEqual(ledger.balances, {"a": 0, "b": 0, "c": 100})
        self.assertEqual(
            ledger.history, {op["key"]: op for op in before}
        )
        self.assertIs(ledger.balances, balances)
        self.assertIs(ledger.history, history)

    def test_failed_batch_restores_earlier_balances_and_history(self):
        ledger = self.seeded_ledger()
        existing_receipt = ledger.history["existing"]
        operations = [
            operation(key="existing"),
            operation("b", "c", 5, "early"),
            operation(amount=91, key="fail"),
        ]
        before = deepcopy(operations)
        self.assert_rejected_without_change(ledger, lambda: ledger.batch(operations))
        self.assertEqual(operations, before)
        self.assertIs(ledger.history["existing"], existing_receipt)

    def test_invalid_batch_operations_roll_back_prior_success(self):
        invalid_operations = [
            operation(source="missing"), operation(target="missing"),
            operation(target="a"), operation(source=[]),
            operation(amount=0), operation(amount=True), operation(amount="1"),
            operation(key=""), operation(key=[]),
            operation(target="c", key="existing"),
            {"source": "a", "target": "b", "amount": 1},
            dict(operation(), extra=1), {**operation(), 1: "extra"},
            None, [], "not an operation",
        ]
        for invalid in invalid_operations:
            with self.subTest(invalid=invalid):
                ledger = self.seeded_ledger()
                operations = [operation("b", "c", 5, "early"), invalid]
                before = deepcopy(operations)
                self.assert_rejected_without_change(
                    ledger, lambda: ledger.batch(operations)
                )
                self.assertEqual(operations, before)

    def test_conflicting_key_within_batch_is_atomic(self):
        ledger = self.seeded_ledger()
        self.assert_rejected_without_change(
            ledger,
            lambda: ledger.batch([
                operation(key="repeated"),
                operation(target="c", key="repeated"),
            ]),
        )

    def test_batch_requires_a_list(self):
        for operations in (
            None, (), (operation(),), iter([operation()]), {}, "invalid",
        ):
            with self.subTest(operations=operations):
                ledger = self.seeded_ledger()
                self.assert_rejected_without_change(
                    ledger, lambda: ledger.batch(operations)
                )

    def test_empty_batch_preserves_state(self):
        ledger = self.seeded_ledger()
        before = deepcopy((ledger.balances, ledger.history))
        balances, history = ledger.balances, ledger.history
        self.assertEqual(ledger.batch([]), [])
        self.assert_state(ledger, before, balances, history)

    def test_batch_receipts_are_independent_of_inputs_history_and_each_other(self):
        ledger = self.seeded_ledger()
        op = operation(amount=90, key="batch")
        receipts = ledger.batch([op, op, operation(key="existing")])
        expected = deepcopy(receipts)
        before = deepcopy((ledger.balances, ledger.history))
        op.clear()
        receipts[0].clear()
        self.assertEqual(receipts[1:], expected[1:])
        receipts[1]["amount"] = 1
        receipts[2].clear()
        self.assertEqual((ledger.balances, ledger.history), before)

    def test_integrated_funding_saving_refund_failure_retry_and_replay(self):
        original = {"payroll": 100, "wallet": 0, "savings": 0}
        ledger = Ledger(original)
        funding = operation("payroll", "wallet", 60, "fund")
        self.assertEqual(ledger.transfer(**funding), funding)
        saving = operation("wallet", "savings", 20, "save")
        refund = operation("wallet", "payroll", 10, "refund")
        self.assertEqual(
            ledger.batch([saving, refund, saving, funding]),
            [saving, refund, saving, funding],
        )
        self.assertEqual(ledger.balances, {"payroll": 50, "wallet": 30, "savings": 20})
        expected_history = {op["key"]: op for op in (funding, saving, refund)}
        self.assertEqual(ledger.history, expected_history)

        next_saving = operation("wallet", "savings", 15, "next")
        failed_payout = operation("savings", "payroll", 36, "payout")
        self.assert_rejected_without_change(
            ledger, lambda: ledger.batch([next_saving, failed_payout])
        )

        payout = operation("savings", "payroll", 35, "payout")
        retry = [next_saving, payout]
        self.assertEqual(ledger.batch(retry), retry)
        self.assertEqual(ledger.balances, {"payroll": 85, "wallet": 15, "savings": 0})
        expected_history.update({op["key"]: op for op in retry})
        self.assertEqual(ledger.history, expected_history)
        before = deepcopy((ledger.balances, ledger.history))
        self.assertEqual(ledger.batch(retry), retry)
        self.assertEqual((ledger.balances, ledger.history), before)
        self.assertEqual(original, {"payroll": 100, "wallet": 0, "savings": 0})
        self.assertEqual(sum(ledger.balances.values()), 100)


if __name__ == "__main__":
    unittest.main()
