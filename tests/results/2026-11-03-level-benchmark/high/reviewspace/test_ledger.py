import copy
import unittest

from ledger import Ledger


def operation(source="a", target="b", amount=10, key="payment"):
    return dict(source=source, target=target, amount=amount, key=key)


class LedgerAssertions(unittest.TestCase):
    def assert_rejected_unchanged(self, ledger, action):
        balances = ledger.balances
        history = ledger.history
        before = copy.deepcopy((balances, history))
        with self.assertRaises(ValueError):
            action()
        self.assertEqual((ledger.balances, ledger.history), before)
        self.assertIs(ledger.balances, balances)
        self.assertIs(ledger.history, history)


class ConstructorTests(unittest.TestCase):
    def test_constructor_copies_input_in_both_directions(self):
        original = {"a": 100, "b": 0}
        ledger = Ledger(original)
        self.assertIsNot(ledger.balances, original)
        original["a"] = 999
        original["outside"] = 1
        self.assertEqual(ledger.balances, {"a": 100, "b": 0})
        ledger.transfer("a", "b", 10, "payment")
        self.assertEqual(original, {"a": 999, "b": 0, "outside": 1})

    def test_empty_and_zero_balances_are_valid(self):
        for opening in ({}, {"a": 0, "b": 0}, {"": 2, "b": 0}):
            with self.subTest(opening=opening):
                ledger = Ledger(opening)
                self.assertEqual(ledger.balances, opening)
                self.assertEqual(ledger.history, {})

    def test_constructor_rejects_invalid_balances_without_changing_input(self):
        for value in (-1, True, False, 1.0, "1", None, [], {}):
            with self.subTest(value=value):
                opening = {"a": 100, "b": value}
                before = copy.deepcopy(opening)
                with self.assertRaises(ValueError):
                    Ledger(opening)
                self.assertEqual(opening, before)

    def test_constructor_requires_a_dictionary_of_string_accounts(self):
        for opening in (None, [], [("a", 1)], ("a", 1), "a", 1, True,
                        {1: 10}, {None: 10}, {("a",): 10}):
            with self.subTest(opening=opening):
                with self.assertRaises(ValueError):
                    Ledger(opening)


class TransferTests(LedgerAssertions):
    def test_transfer_returns_receipt_and_preserves_public_dictionaries(self):
        ledger = Ledger({"a": 100, "b": 0})
        balances, history = ledger.balances, ledger.history
        receipt = ledger.transfer("a", "b", 30, "payment")
        self.assertEqual(receipt, operation(amount=30))
        self.assertEqual(balances, {"a": 70, "b": 30})
        self.assertEqual(history, {"payment": receipt})
        self.assertIs(ledger.balances, balances)
        self.assertIs(ledger.history, history)

    def test_entire_balance_and_large_integers_transfer_exactly(self):
        amount = 10 ** 100
        ledger = Ledger({"": amount, "b": 1})
        self.assertEqual(ledger.transfer("", "b", amount, "large"),
                         operation(source="", amount=amount, key="large"))
        self.assertEqual(ledger.balances, {"": 0, "b": amount + 1})

    def test_invalid_amounts_leave_state_unchanged(self):
        for amount in (0, -1, True, False, 1.0, 1.5, "1", None, [], {}):
            with self.subTest(amount=amount):
                ledger = Ledger({"a": 100, "b": 0})
                self.assert_rejected_unchanged(
                    ledger, lambda: ledger.transfer("a", "b", amount, "bad"))

    def test_invalid_keys_leave_state_unchanged(self):
        for key in ("", None, True, 1, 1.0, [], {}, ()):
            with self.subTest(key=key):
                ledger = Ledger({"a": 100, "b": 0})
                self.assert_rejected_unchanged(
                    ledger, lambda: ledger.transfer("a", "b", 10, key))

    def test_missing_and_invalid_accounts_leave_state_unchanged(self):
        for account in ("missing", None, True, 1, [], {}, ("a",)):
            for field in ("source", "target"):
                with self.subTest(account=account, field=field):
                    ledger = Ledger({"a": 100, "b": 0})
                    payload = operation()
                    payload[field] = account
                    self.assert_rejected_unchanged(
                        ledger, lambda: ledger.transfer(**payload))

    def test_same_account_is_rejected(self):
        ledger = Ledger({"a": 100})
        self.assert_rejected_unchanged(
            ledger, lambda: ledger.transfer("a", "a", 10, "same"))

    def test_insufficient_funds_preserve_existing_state(self):
        ledger = Ledger({"a": 100, "b": 0})
        ledger.transfer("a", "b", 10, "existing")
        self.assert_rejected_unchanged(
            ledger, lambda: ledger.transfer("a", "b", 91, "too-much"))
        ledger.transfer("a", "b", 90, "too-much")
        self.assertEqual(ledger.balances, {"a": 0, "b": 100})

    def test_replay_succeeds_even_after_source_is_empty(self):
        ledger = Ledger({"a": 10, "b": 0})
        first = ledger.transfer("a", "b", 10, "payment")
        before = copy.deepcopy((ledger.balances, ledger.history))
        replay = ledger.transfer("a", "b", 10, "payment")
        self.assertEqual(replay, first)
        self.assertIsNot(replay, first)
        self.assertEqual((ledger.balances, ledger.history), before)

    def test_replay_rejects_every_changed_payload_field(self):
        for payload in (operation(source="c"), operation(target="c"),
                        operation(amount=11), operation(source="b", target="a")):
            with self.subTest(payload=payload):
                ledger = Ledger({"a": 100, "b": 20, "c": 30})
                ledger.transfer(**operation())
                self.assert_rejected_unchanged(
                    ledger, lambda: ledger.transfer(**payload))

    def test_replay_does_not_bypass_amount_validation(self):
        for amount in (True, 1.0, False, None):
            with self.subTest(amount=amount):
                ledger = Ledger({"a": 100, "b": 0})
                ledger.transfer("a", "b", 1, "payment")
                self.assert_rejected_unchanged(
                    ledger, lambda: ledger.transfer("a", "b", amount, "payment"))

    def test_original_and_replayed_receipts_cannot_change_history(self):
        ledger = Ledger({"a": 100, "b": 0})
        first = ledger.transfer(**operation())
        first.clear()
        self.assertEqual(ledger.history, {"payment": operation()})
        replay = ledger.transfer(**operation())
        self.assertEqual(replay, operation())
        replay.update(source="b", target="a", amount=100, key="forged")
        self.assertEqual(ledger.history, {"payment": operation()})
        self.assertEqual(ledger.transfer(**operation()), operation())
        self.assertEqual(ledger.balances, {"a": 90, "b": 10})


class BatchTests(LedgerAssertions):
    def test_batch_uses_prior_operations_and_returns_receipts_in_order(self):
        ledger = Ledger({"a": 100, "b": 0, "c": 0})
        balances, history = ledger.balances, ledger.history
        operations = [operation(amount=60, key="fund"),
                      operation(source="b", target="c", amount=40, key="spend")]
        original = copy.deepcopy(operations)
        receipts = ledger.batch(operations)
        self.assertEqual(receipts, original)
        self.assertEqual(operations, original)
        self.assertEqual(balances, {"a": 40, "b": 20, "c": 40})
        self.assertEqual(history, {op["key"]: op for op in original})
        self.assertIs(ledger.balances, balances)
        self.assertIs(ledger.history, history)

    def test_batch_replays_existing_and_new_keys_without_double_spending(self):
        ledger = Ledger({"a": 100, "b": 0, "c": 0})
        existing = operation(amount=100, key="fund")
        spend = operation(source="b", target="c", amount=100, key="spend")
        ledger.transfer(**existing)
        operations = [existing, spend, spend.copy(), existing.copy()]
        self.assertEqual(ledger.batch(operations), operations)
        self.assertEqual(ledger.balances, {"a": 0, "b": 0, "c": 100})
        self.assertEqual(ledger.history, {"fund": existing, "spend": spend})
        before = copy.deepcopy((ledger.balances, ledger.history))
        self.assertEqual(ledger.batch(operations), operations)
        self.assertEqual((ledger.balances, ledger.history), before)

    def test_later_failure_rolls_back_balances_and_history(self):
        failures = [operation(amount=1000, key="bad"),
                    operation(amount=True, key="bad"),
                    operation(source="missing", key="bad"),
                    operation(target="missing", key="bad"),
                    operation(target="a", key="bad"),
                    operation(key=""), operation(key=[]),
                    operation(amount=11, key="existing"),
                    operation(amount=21, key="new")]
        for failure in failures:
            with self.subTest(failure=failure):
                ledger = Ledger({"a": 100, "b": 0})
                ledger.transfer(**operation(key="existing"))
                operations = [operation(key="existing"),
                              operation(amount=20, key="new"), failure]
                self.assert_rejected_unchanged(
                    ledger, lambda: ledger.batch(operations))

    def test_batch_requires_a_list(self):
        for operations in (None, {}, operation(), (), (operation(),),
                           iter([operation()]), "operations", 1, False):
            with self.subTest(operations=operations):
                ledger = Ledger({"a": 100, "b": 0})
                self.assert_rejected_unchanged(
                    ledger, lambda: ledger.batch(operations))

    def test_malformed_later_operations_are_atomic_value_errors(self):
        malformed = [None, 1, "payment", [], (), {},
                     dict(operation(), unexpected=True), {1: "a"}]
        for field in ("source", "target", "amount", "key"):
            incomplete = operation()
            del incomplete[field]
            malformed.append(incomplete)
        for invalid in malformed:
            with self.subTest(invalid=invalid):
                ledger = Ledger({"a": 100, "b": 0})
                self.assert_rejected_unchanged(
                    ledger, lambda: ledger.batch([operation(), invalid]))

    def test_failed_batch_keys_are_available_on_retry(self):
        ledger = Ledger({"a": 100, "b": 0, "c": 0})
        fund = operation(amount=60, key="fund")
        spend = operation(source="b", target="c", amount=61, key="spend")
        self.assert_rejected_unchanged(ledger, lambda: ledger.batch([fund, spend]))
        spend["amount"] = 40
        self.assertEqual(ledger.batch([fund, spend]), [fund, spend])
        self.assertEqual(ledger.balances, {"a": 40, "b": 20, "c": 40})
        self.assertEqual(ledger.history, {"fund": fund, "spend": spend})

    def test_batch_receipts_are_detached_including_duplicate_replays(self):
        ledger = Ledger({"a": 100, "b": 0})
        receipts = ledger.batch([operation(), operation()])
        self.assertIsNot(receipts[0], receipts[1])
        receipts[0].clear()
        self.assertEqual(receipts[1], operation())
        receipts[1]["amount"] = 999
        self.assertEqual(ledger.history, {"payment": operation()})
        replay = ledger.batch([operation()])[0]
        replay.clear()
        self.assertEqual(ledger.transfer(**operation()), operation())

    def test_empty_batch_preserves_state_and_dictionary_identity(self):
        ledger = Ledger({"a": 100, "b": 0})
        ledger.transfer(**operation())
        balances, history = ledger.balances, ledger.history
        before = copy.deepcopy((balances, history))
        self.assertEqual(ledger.batch([]), [])
        self.assertEqual((ledger.balances, ledger.history), before)
        self.assertIs(ledger.balances, balances)
        self.assertIs(ledger.history, history)


class IntegratedJourneyTests(LedgerAssertions):
    def test_payments_retries_failure_and_recovery(self):
        opening = {"treasury": 150, "alice": 0, "bob": 0, "vendor": 0}
        ledger = Ledger(opening)
        salary = operation("treasury", "alice", 60, "salary")
        self.assertEqual(ledger.transfer(**salary), salary)
        gift = operation("alice", "bob", 25, "gift")
        purchase = operation("bob", "vendor", 10, "purchase")
        rebate = operation("treasury", "bob", 15, "rebate")
        payments = [gift, purchase, rebate, purchase.copy()]
        receipts = ledger.batch(payments)
        self.assertEqual(receipts, payments)
        self.assertEqual(ledger.balances,
                         {"treasury": 75, "alice": 35, "bob": 30, "vendor": 10})
        before = copy.deepcopy((ledger.balances, ledger.history))
        self.assertEqual(ledger.batch(payments), payments)
        self.assertEqual((ledger.balances, ledger.history), before)
        receipts[0].clear()
        self.assertEqual(ledger.history["gift"], gift)
        refund = operation("vendor", "alice", 5, "refund")
        adjustment = operation("alice", "treasury", 1000, "adjustment")
        self.assert_rejected_unchanged(
            ledger, lambda: ledger.batch([refund, adjustment]))
        adjustment["amount"] = 20
        self.assertEqual(ledger.batch([refund, adjustment]), [refund, adjustment])
        self.assert_rejected_unchanged(
            ledger, lambda: ledger.transfer("bob", "vendor", 11, "purchase"))
        self.assertEqual(ledger.balances,
                         {"treasury": 95, "alice": 20, "bob": 30, "vendor": 5})
        self.assertEqual(ledger.history, {op["key"]: op for op in
                                         (salary, gift, purchase, rebate,
                                          refund, adjustment)})
        self.assertEqual(sum(ledger.balances.values()), 150)
        self.assertEqual(opening,
                         {"treasury": 150, "alice": 0, "bob": 0, "vendor": 0})


if __name__ == "__main__":
    unittest.main()
