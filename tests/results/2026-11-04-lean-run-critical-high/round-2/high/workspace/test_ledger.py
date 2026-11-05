import copy
import unittest

from ledger import Ledger


def operation(source="a", target="b", amount=10, key="new"):
    return {"source": source, "target": target, "amount": amount, "key": key}


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.ledger = Ledger({"a": 100, "b": 30, "c": 0})

    def assert_rejected_without_change(self, action):
        balances = self.ledger.balances
        history = self.ledger.history
        before = copy.deepcopy((balances, history))
        with self.assertRaises(ValueError):
            action()
        self.assertIs(self.ledger.balances, balances)
        self.assertIs(self.ledger.history, history)
        self.assertEqual((balances, history), before)

    def test_constructor_copies_input(self):
        balances = {"a": 100, "b": 0}
        ledger = Ledger(balances)
        balances["a"] = 5
        balances["outside"] = 10
        self.assertEqual(ledger.balances, {"a": 100, "b": 0})
        ledger.transfer("a", "b", 20, "one")
        self.assertEqual(balances, {"a": 5, "b": 0, "outside": 10})

    def test_constructor_rejects_boolean_balance(self):
        with self.assertRaises(ValueError):
            Ledger({"a": True})

    def test_constructor_rejects_invalid_containers_keys_and_balances(self):
        invalid = [None, [], (), [("a", 10)]]
        invalid.extend({"a": 10, "b": value}
                       for value in [-1, False, 1.0, "1", None, [], {}])
        invalid.extend({key: 10} for key in [1, True, None, ("a",), b"a"])
        for balances in invalid:
            with self.subTest(balances=balances):
                before = copy.deepcopy(balances)
                with self.assertRaises(ValueError):
                    Ledger(balances)
                self.assertEqual(balances, before)

    def test_empty_ledger_and_valid_balance_boundaries(self):
        empty = Ledger({})
        self.assertEqual(empty.balances, {})
        self.assertEqual(empty.history, {})
        self.assertEqual(empty.batch([]), [])

        # Account names may be any strings; a key need only be nonempty.
        large = 10 ** 100
        ledger = Ledger({"": 0, "\u0394": large})
        expected = operation("\u0394", "", large, " ")
        self.assertEqual(ledger.transfer(**expected), expected)
        self.assertEqual(ledger.balances, {"": large, "\u0394": 0})

    def test_transfer_preserves_public_dictionaries_and_unrelated_accounts(self):
        balances = self.ledger.balances
        history = self.ledger.history
        expected = operation(amount=100, key="full-balance")
        self.assertEqual(self.ledger.transfer(**expected), expected)
        self.assertIs(self.ledger.balances, balances)
        self.assertIs(self.ledger.history, history)
        self.assertEqual(balances, {"a": 0, "b": 130, "c": 0})
        self.assertEqual(history, {"full-balance": expected})

    def test_transfer_rejects_insufficient_funds_atomically(self):
        self.ledger.transfer("a", "c", 5, "existing")
        self.assert_rejected_without_change(
            lambda: self.ledger.transfer("a", "b", 96, "too-much")
        )

    def test_transfer_rejects_boolean_amount(self):
        self.assert_rejected_without_change(
            lambda: self.ledger.transfer("a", "b", True, "boolean")
        )

    def test_transfer_rejects_invalid_amounts(self):
        for amount in [False, 0, -1, 1.0, 2.5, "1", None, [], {}]:
            with self.subTest(amount=amount):
                self.assert_rejected_without_change(
                    lambda: self.ledger.transfer("a", "b", amount, "invalid")
                )

    def test_transfer_rejects_invalid_keys(self):
        for key in ["", None, 1, True, b"key", [], {}, ("key",)]:
            with self.subTest(key=key):
                self.assert_rejected_without_change(
                    lambda: self.ledger.transfer("a", "b", 10, key)
                )

    def test_transfer_rejects_invalid_or_unavailable_accounts(self):
        for field in ["source", "target"]:
            for account in ["missing", None, 1, True, [], {}, b"a", ("a",)]:
                with self.subTest(field=field, account=account):
                    payload = operation()
                    payload[field] = account
                    self.assert_rejected_without_change(
                        lambda: self.ledger.transfer(**payload)
                    )
        self.assert_rejected_without_change(
            lambda: self.ledger.transfer("a", "a", 10, "same-account")
        )

    def test_failed_transfer_does_not_reserve_key(self):
        self.assert_rejected_without_change(
            lambda: self.ledger.transfer("a", "b", 101, "retry")
        )
        expected = operation(amount=100, key="retry")
        self.assertEqual(self.ledger.transfer(**expected), expected)
        self.assertEqual(self.ledger.balances, {"a": 0, "b": 130, "c": 0})
        self.assertEqual(self.ledger.history, {"retry": expected})

    def test_replay_after_source_is_empty(self):
        receipt = self.ledger.transfer("a", "b", 100, "all")
        before = copy.deepcopy((self.ledger.balances, self.ledger.history))
        self.assertEqual(self.ledger.transfer("a", "b", 100, "all"), receipt)
        self.assertEqual((self.ledger.balances, self.ledger.history), before)

    def test_replay_rejects_changed_payload(self):
        self.ledger.transfer("a", "c", 20, "seed")
        self.ledger.transfer("a", "b", 10, "used")
        for change in [{"source": "c"}, {"target": "c"}, {"amount": 11}]:
            with self.subTest(change=change):
                payload = operation(key="used")
                payload.update(change)
                self.assert_rejected_without_change(
                    lambda: self.ledger.transfer(**payload)
                )

    def test_replay_does_not_bypass_amount_type_validation(self):
        self.ledger.transfer("a", "b", 1, "one")
        for amount in [True, 1.0]:
            with self.subTest(amount=amount):
                self.assert_rejected_without_change(
                    lambda: self.ledger.transfer("a", "b", amount, "one")
                )

    def test_same_payload_with_new_key_transfers_again(self):
        first = operation(key="first")
        second = operation(key="second")
        self.assertEqual(self.ledger.transfer(**first), first)
        self.assertEqual(self.ledger.transfer(**second), second)
        self.assertEqual(self.ledger.balances, {"a": 80, "b": 50, "c": 0})
        self.assertEqual(self.ledger.history, {"first": first, "second": second})

    def test_transfer_receipt_cannot_change_history(self):
        expected = operation(key="receipt")
        receipt = self.ledger.transfer(**expected)
        receipt["amount"] = 999
        receipt["extra"] = "caller data"
        self.assertEqual(self.ledger.history, {"receipt": expected})
        replay = self.ledger.transfer(**expected)
        self.assertEqual(replay, expected)
        replay.clear()
        self.assertEqual(self.ledger.history, {"receipt": expected})

    def test_batch_rolls_back_late_failure(self):
        self.ledger.transfer("a", "c", 5, "existing")
        self.assert_rejected_without_change(
            lambda: self.ledger.batch([
                operation(amount=20, key="first"),
                operation("b", "c", 1000, "second"),
            ])
        )

    def test_batch_rejects_malformed_operation_atomically(self):
        self.ledger.transfer("a", "c", 5, "existing")
        malformed = [None, [], (), "operation", {},
                     {**operation(), "unexpected": 0},
                     {**operation(), 0: "extra"}]
        for missing_field in ["source", "target", "amount", "key"]:
            payload = operation()
            del payload[missing_field]
            malformed.append(payload)
        for payload in malformed:
            with self.subTest(payload=payload):
                self.assert_rejected_without_change(
                    lambda: self.ledger.batch([operation(), payload])
                )

    def test_batch_rejects_invalid_containers(self):
        for operations in [None, {}, (), (operation(),), "operations",
                           iter([operation()])]:
            with self.subTest(operations=operations):
                self.assert_rejected_without_change(
                    lambda: self.ledger.batch(operations)
                )

    def test_batch_rejects_invalid_payloads_atomically(self):
        for change in [{"amount": True}, {"target": "missing"},
                       {"source": []}, {"key": []}, {"source": "b"}]:
            with self.subTest(change=change):
                payload = operation(key="second")
                payload.update(change)
                self.assert_rejected_without_change(
                    lambda: self.ledger.batch([operation(key="first"), payload])
                )

    def test_empty_batch_is_noop(self):
        self.ledger.transfer("a", "b", 10, "existing")
        balances = self.ledger.balances
        history = self.ledger.history
        before = copy.deepcopy((balances, history))
        self.assertEqual(self.ledger.batch([]), [])
        self.assertIs(self.ledger.balances, balances)
        self.assertIs(self.ledger.history, history)
        self.assertEqual((balances, history), before)

    def test_batch_success_obeys_order_and_preserves_input(self):
        balances = self.ledger.balances
        history = self.ledger.history
        operations = [operation("a", "c", 40, "first"),
                      operation("c", "b", 30, "second"),
                      operation("b", "a", 20, "third")]
        before = copy.deepcopy(operations)
        self.assertEqual(self.ledger.batch(operations), before)
        self.assertEqual(operations, before)
        self.assertIs(self.ledger.balances, balances)
        self.assertIs(self.ledger.history, history)
        self.assertEqual(balances, {"a": 80, "b": 40, "c": 10})
        self.assertEqual(history, {op["key"]: op for op in before})

    def test_batch_replays_within_and_across_batches(self):
        existing = operation(amount=20, key="existing")
        self.ledger.transfer(**existing)
        onward = operation("b", "c", 50, "onward")
        returned = operation("c", "a", 10, "returned")
        operations = [existing, onward, onward, returned]
        self.assertEqual(self.ledger.batch(operations), operations)
        self.assertEqual(self.ledger.balances, {"a": 90, "b": 0, "c": 40})
        self.assertEqual(self.ledger.history,
                         {op["key"]: op for op in [existing, onward, returned]})
        before = copy.deepcopy((self.ledger.balances, self.ledger.history))
        self.assertEqual(self.ledger.batch(operations), operations)
        self.assertEqual((self.ledger.balances, self.ledger.history), before)

    def test_batch_receipts_are_detached_from_inputs_and_each_other(self):
        payload = operation()
        expected = payload.copy()
        receipts = self.ledger.batch([payload, payload])
        self.assertEqual(receipts, [expected, expected])
        payload["amount"] = 999
        receipts[0].clear()
        self.assertEqual(receipts[1], expected)
        receipts[1]["target"] = "c"
        receipts.clear()
        self.assertEqual(self.ledger.history, {"new": expected})
        self.assertEqual(self.ledger.transfer(**expected), expected)
        self.assertEqual(self.ledger.balances, {"a": 90, "b": 40, "c": 0})

    def test_batch_conflicts_with_new_or_existing_key_abort_all_changes(self):
        self.ledger.transfer("a", "b", 10, "existing")
        for conflicting in [operation(target="c", key="existing"),
                            operation(amount=11, key="fresh")]:
            with self.subTest(conflicting=conflicting):
                self.assert_rejected_without_change(
                    lambda: self.ledger.batch([operation(key="fresh"), conflicting])
                )

    def test_batch_cannot_spend_future_funds(self):
        self.assert_rejected_without_change(
            lambda: self.ledger.batch([
                operation("c", "b", 1, "too-early"),
                operation("a", "c", 1, "later"),
            ])
        )

    def test_integrated_payments_rollback_retry_and_replay(self):
        initial = {"pool": 250, "alice": 0, "bob": 0, "reserve": 50}
        self.ledger = Ledger(initial)
        balances = self.ledger.balances
        history = self.ledger.history
        opening = operation("pool", "alice", 100, "opening")
        payment = operation("alice", "bob", 40, "payment")
        fee = operation("bob", "reserve", 15, "fee")
        top_up = operation("pool", "bob", 50, "top-up")
        self.assertEqual(self.ledger.transfer(**opening), opening)
        payments = [opening, payment, fee, payment, top_up]
        self.assertEqual(self.ledger.batch(payments), payments)
        self.assertEqual(balances,
                         {"pool": 100, "alice": 60, "bob": 75, "reserve": 65})

        rebate = operation("reserve", "alice", 20, "rebate")
        too_large = operation("alice", "pool", 100, "refund")
        self.assert_rejected_without_change(
            lambda: self.ledger.batch([rebate, too_large])
        )
        refund = operation("alice", "pool", 80, "refund")
        recovered = [rebate, refund]
        self.assertEqual(self.ledger.batch(recovered), recovered)
        self.assertEqual(balances,
                         {"pool": 180, "alice": 0, "bob": 75, "reserve": 45})
        before = copy.deepcopy((balances, history))
        self.assertEqual(self.ledger.batch(recovered), recovered)
        self.assertEqual((balances, history), before)

        final_payment = operation("bob", "alice", 5, "final")
        conflict = operation("pool", "alice", 101, "opening")
        self.assert_rejected_without_change(
            lambda: self.ledger.batch([final_payment, conflict])
        )
        self.assertEqual(self.ledger.transfer(**final_payment), final_payment)
        self.assertEqual(balances,
                         {"pool": 180, "alice": 5, "bob": 70, "reserve": 45})
        self.assertEqual(sum(balances.values()), 300)
        self.assertEqual(initial,
                         {"pool": 250, "alice": 0, "bob": 0, "reserve": 50})
        committed = [opening, payment, fee, top_up, rebate, refund, final_payment]
        self.assertEqual(history, {op["key"]: op for op in committed})
        self.assertIs(self.ledger.balances, balances)
        self.assertIs(self.ledger.history, history)


if __name__ == "__main__":
    unittest.main()
