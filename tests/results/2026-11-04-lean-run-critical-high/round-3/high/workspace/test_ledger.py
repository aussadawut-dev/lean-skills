import copy
import unittest

from ledger import Ledger


def operation(source="a", target="b", amount=5, key="new"):
    return dict(source=source, target=target, amount=amount, key=key)


class LedgerChecks(unittest.TestCase):
    def populated_ledger(self):
        ledger = Ledger({"a": 100, "b": 0, "c": 0})
        ledger.transfer("a", "b", 10, "seed")
        return ledger

    def assert_rejected_unchanged(self, ledger, action, *args):
        balances, history = ledger.balances, ledger.history
        before = copy.deepcopy((balances, history))
        with self.assertRaises(ValueError):
            action(*args)
        self.assertEqual((ledger.balances, ledger.history), before)
        self.assertIs(ledger.balances, balances)
        self.assertIs(ledger.history, history)


class ConstructorTests(LedgerChecks):
    def test_copies_input_in_both_directions(self):
        initial = {"a": 10, "b": 0}
        ledger = Ledger(initial)
        self.assertIsNot(ledger.balances, initial)
        initial["a"] = 500
        initial["outside"] = 1
        self.assertEqual(ledger.balances, {"a": 10, "b": 0})
        ledger.transfer("a", "b", 3, "one")
        self.assertEqual(initial, {"a": 500, "b": 0, "outside": 1})
        self.assertEqual(ledger.history, {"one": operation(amount=3, key="one")})

    def test_valid_boundaries(self):
        self.assertEqual(Ledger({}).balances, {})
        self.assertEqual(Ledger({}).history, {})
        balances = {"": 0, "large": 10**50}
        self.assertEqual(Ledger(balances).balances, balances)

    def test_requires_a_dictionary(self):
        for balances in (None, [], [("a", 1)], (), "a", 1):
            with self.subTest(balances=balances):
                with self.assertRaises(ValueError):
                    Ledger(balances)

    def test_requires_string_account_names(self):
        for account in (1, True, None, ("a",), b"a"):
            with self.subTest(account=account):
                with self.assertRaises(ValueError):
                    Ledger({account: 10})

    def test_requires_nonnegative_integer_balances(self):
        for amount in (True, False, -1, 1.5, "2", None, [], {}):
            with self.subTest(amount=amount):
                balances = {"valid": 10, "invalid": amount}
                before = copy.deepcopy(balances)
                with self.assertRaises(ValueError):
                    Ledger(balances)
                self.assertEqual(balances, before)


class TransferTests(LedgerChecks):
    def test_receipt_full_balance_spend_and_public_dictionary_identity(self):
        ledger = Ledger({"a": 30, "b": 0})
        balances, history = ledger.balances, ledger.history
        receipt = ledger.transfer("a", "b", 30, "one")
        expected = operation(amount=30, key="one")
        self.assertEqual(receipt, expected)
        self.assertEqual(ledger.balances, {"a": 0, "b": 30})
        self.assertEqual(ledger.history, {"one": expected})
        self.assertIs(ledger.balances, balances)
        self.assertIs(ledger.history, history)

    def test_invalid_amounts_do_not_change_state(self):
        for amount in (True, False, 0, -1, 1.5, "5", None, [], {}):
            with self.subTest(amount=amount):
                ledger = self.populated_ledger()
                self.assert_rejected_unchanged(
                    ledger, ledger.transfer, "a", "b", amount, "invalid"
                )

    def test_invalid_keys_do_not_change_state(self):
        for key in ("", None, 1, True, b"key", [], {}):
            with self.subTest(key=key):
                ledger = self.populated_ledger()
                self.assert_rejected_unchanged(
                    ledger, ledger.transfer, "a", "b", 5, key
                )

    def test_invalid_or_unavailable_accounts_do_not_change_state(self):
        pairs = (
            ("missing", "b"), ("a", "missing"), ("a", "a"),
            (None, "b"), ("a", None), (1, "b"), ("a", False),
            ([], "b"), ("a", {}), (b"a", "b"),
        )
        for source, target in pairs:
            with self.subTest(source=source, target=target):
                ledger = self.populated_ledger()
                self.assert_rejected_unchanged(
                    ledger, ledger.transfer, source, target, 5, "invalid"
                )

    def test_insufficient_funds_do_not_change_state(self):
        ledger = self.populated_ledger()
        self.assert_rejected_unchanged(
            ledger, ledger.transfer, "a", "b", 91, "too-much"
        )

    def test_replay_after_source_is_depleted(self):
        ledger = Ledger({"a": 5, "b": 0})
        receipt = ledger.transfer("a", "b", 5, "one")
        before = copy.deepcopy((ledger.balances, ledger.history))
        self.assertEqual(ledger.transfer("a", "b", 5, "one"), receipt)
        self.assertEqual((ledger.balances, ledger.history), before)

    def test_replay_requires_the_same_valid_payload(self):
        payloads = (
            ("a", "b", 2), ("b", "a", 1), ("a", "c", 1),
            ("missing", "b", 1), ([], "b", 1), ("a", "a", 1),
            ("a", "b", True), ("a", "b", 1.0), ("a", "b", 0),
        )
        for payload in payloads:
            with self.subTest(payload=payload):
                ledger = Ledger({"a": 10, "b": 10, "c": 0})
                ledger.transfer("a", "b", 1, "one")
                self.assert_rejected_unchanged(
                    ledger, ledger.transfer, *payload, "one"
                )

    def test_returned_and_replayed_receipts_cannot_change_history(self):
        ledger = Ledger({"a": 10, "b": 0})
        expected = operation(amount=3, key="one")
        receipt = ledger.transfer("a", "b", 3, "one")
        receipt.clear()
        self.assertEqual(ledger.history, {"one": expected})
        replay = ledger.transfer("a", "b", 3, "one")
        self.assertEqual(replay, expected)
        replay["amount"] = 999
        self.assertEqual(ledger.history, {"one": expected})
        self.assertEqual(ledger.transfer("a", "b", 3, "one"), expected)
        self.assertEqual(ledger.balances, {"a": 7, "b": 3})

    def test_empty_account_name_whitespace_key_and_large_integer_are_valid(self):
        amount = 10**50
        ledger = Ledger({"": amount, "b": 0})
        self.assertEqual(
            ledger.transfer("", "b", amount, " "),
            operation(source="", amount=amount, key=" "),
        )
        self.assertEqual(ledger.balances, {"": 0, "b": amount})


class BatchTests(LedgerChecks):
    def test_empty_batch_preserves_state_and_public_dictionaries(self):
        ledger = self.populated_ledger()
        balances, history = ledger.balances, ledger.history
        before = copy.deepcopy((balances, history))
        self.assertEqual(ledger.batch([]), [])
        self.assertEqual((ledger.balances, ledger.history), before)
        self.assertIs(ledger.balances, balances)
        self.assertIs(ledger.history, history)

    def test_requires_a_list(self):
        containers = (None, {}, (), (operation(),), "", b"", iter([operation()]))
        for operations in containers:
            with self.subTest(operations=operations):
                ledger = self.populated_ledger()
                self.assert_rejected_unchanged(ledger, ledger.batch, operations)

    def test_requires_operation_dictionaries_with_exact_fields(self):
        malformed = [None, [], (), "operation", 1, {}, {**operation(), "extra": 1}]
        malformed.extend(
            {key: value for key, value in operation().items() if key != missing}
            for missing in ("source", "target", "amount", "key")
        )
        malformed.append({**operation(), 1: "unexpected"})
        for invalid in malformed:
            with self.subTest(invalid=invalid):
                ledger = self.populated_ledger()
                self.assert_rejected_unchanged(
                    ledger, ledger.batch, [operation(key="prefix"), invalid]
                )

    def test_failed_batch_rolls_back_balances_and_history(self):
        ledger = self.populated_ledger()
        self.assert_rejected_unchanged(ledger, ledger.batch, [
            operation(amount=10, key="seed"),
            operation(target="c", amount=20, key="fund-c"),
            operation(source="c", amount=21, key="overdraw-c"),
        ])

    def test_transfer_validation_failures_roll_back_valid_prefix(self):
        invalid_operations = (
            operation(amount=0), operation(amount=True), operation(key=""),
            operation(target="missing"), operation(source="missing"),
            operation(target="a"), operation(source=[]), operation(key=[]),
            operation(amount=11, key="seed"),
        )
        for invalid in invalid_operations:
            with self.subTest(invalid=invalid):
                ledger = self.populated_ledger()
                self.assert_rejected_unchanged(
                    ledger, ledger.batch, [operation(key="prefix"), invalid]
                )

    def test_conflicting_keys_within_batch_roll_back(self):
        ledger = self.populated_ledger()
        self.assert_rejected_unchanged(ledger, ledger.batch, [
            operation(amount=5, key="same"),
            operation(amount=6, key="same"),
        ])

    def test_ordered_success_and_replays_preserve_public_dictionaries(self):
        ledger = self.populated_ledger()
        balances, history = ledger.balances, ledger.history
        operations = [
            operation(amount=10, key="seed"),
            operation(target="c", amount=30, key="fund-c"),
            operation(source="c", amount=12, key="spend-c"),
            operation(target="c", amount=30, key="fund-c"),
            operation(source="b", target="a", amount=2, key="refund"),
        ]
        expected = copy.deepcopy(operations)
        receipts = ledger.batch(operations)
        self.assertEqual(receipts, expected)
        self.assertEqual(operations, expected)
        self.assertEqual(ledger.balances, {"a": 62, "b": 20, "c": 18})
        self.assertEqual(ledger.history, {op["key"]: op for op in expected})
        self.assertIs(ledger.balances, balances)
        self.assertIs(ledger.history, history)

        operations[1]["amount"] = 999
        receipts[1].clear()
        self.assertEqual(receipts[3], expected[3])
        for receipt in receipts:
            receipt.clear()
        self.assertEqual(ledger.history, {op["key"]: op for op in expected})
        self.assertEqual(ledger.transfer("a", "c", 30, "fund-c"), expected[1])

    def test_batch_replay_succeeds_with_depleted_source(self):
        ledger = Ledger({"a": 5, "b": 0})
        operations = [operation(key="drain"), operation(key="drain")]
        self.assertEqual(ledger.batch(operations), operations)
        before = copy.deepcopy((ledger.balances, ledger.history))
        self.assertEqual(ledger.batch(operations), operations)
        self.assertEqual((ledger.balances, ledger.history), before)


class IntegratedJourneyTests(LedgerChecks):
    def test_payments_retries_failed_batch_and_recovery(self):
        initial = {"checking": 120, "savings": 30, "merchant": 0}
        ledger = Ledger(initial)
        deposit = ledger.transfer("checking", "savings", 20, "deposit")
        self.assertEqual(ledger.transfer("checking", "savings", 20, "deposit"), deposit)
        payments = [
            operation("savings", "merchant", 40, "payment"),
            operation("checking", "savings", 25, "replenish"),
            operation("savings", "merchant", 40, "payment"),
            operation("merchant", "checking", 5, "rebate"),
        ]
        self.assertEqual(ledger.batch(payments), payments)
        self.assertEqual(ledger.balances, {"checking": 80, "savings": 35, "merchant": 35})
        completed = copy.deepcopy((ledger.balances, ledger.history))
        self.assertEqual(ledger.batch(payments), payments)
        self.assertEqual((ledger.balances, ledger.history), completed)

        self.assert_rejected_unchanged(ledger, ledger.batch, [
            operation("checking", "merchant", 15, "retry"),
            operation("savings", "checking", 36, "overdraft"),
        ])
        retry = ledger.transfer("checking", "merchant", 15, "retry")
        self.assertEqual(retry, operation("checking", "merchant", 15, "retry"))
        self.assertEqual(ledger.transfer("checking", "merchant", 15, "retry"), retry)
        self.assert_rejected_unchanged(
            ledger, ledger.transfer, "checking", "merchant", 1, "retry"
        )
        self.assertEqual(ledger.balances, {"checking": 65, "savings": 35, "merchant": 50})
        self.assertEqual(sum(ledger.balances.values()), 150)
        self.assertEqual(set(ledger.history), {"deposit", "payment", "replenish", "rebate", "retry"})
        self.assertEqual(initial, {"checking": 120, "savings": 30, "merchant": 0})


if __name__ == "__main__":
    unittest.main()
