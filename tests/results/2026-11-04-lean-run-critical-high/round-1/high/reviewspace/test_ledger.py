from copy import deepcopy
import unittest

from ledger import Ledger


def operation(source="a", target="b", amount=10, key="one"):
    return dict(source=source, target=target, amount=amount, key=key)


class LedgerTests(unittest.TestCase):
    def assert_rejected_without_change(self, ledger, action):
        balances = ledger.balances
        history = ledger.history
        before = deepcopy((balances, history))
        with self.assertRaises(ValueError):
            action()
        self.assertIs(ledger.balances, balances)
        self.assertIs(ledger.history, history)
        self.assertEqual((ledger.balances, ledger.history), before)

    def test_constructor_copies_input(self):
        opening = {"a": 30, "b": 0}
        ledger = Ledger(opening)
        self.assertIsNot(ledger.balances, opening)
        opening["a"] = 999
        opening["c"] = 5
        self.assertEqual(ledger.balances, {"a": 30, "b": 0})
        ledger.transfer("a", "b", 7, "payment")
        self.assertEqual(opening, {"a": 999, "b": 0, "c": 5})

    def test_constructor_rejects_invalid_containers_keys_and_balances(self):
        invalid = [
            None, [], [("a", 1)], "a",
            {1: 1}, {False: 0}, {None: 1}, {("a",): 1},
            {"a": -1}, {"a": True}, {"a": False}, {"a": 1.0},
            {"a": "1"}, {"a": None}, {"a": []},
        ]
        for balances in invalid:
            with self.subTest(balances=balances):
                before = deepcopy(balances)
                with self.assertRaises(ValueError):
                    Ledger(balances)
                self.assertEqual(balances, before)

    def test_valid_empty_accounts_zero_balances_and_large_integers(self):
        empty = Ledger({})
        self.assertEqual(empty.balances, {})
        self.assertEqual(empty.history, {})
        self.assertEqual(empty.batch([]), [])
        large = 10 ** 80
        ledger = Ledger({"": 0, "payer": large})
        receipt = ledger.transfer("payer", "", large, " ")
        self.assertEqual(receipt, operation("payer", "", large, " "))
        self.assertEqual(ledger.balances, {"": large, "payer": 0})

    def test_transfer_returns_receipt_and_preserves_public_dictionaries(self):
        ledger = Ledger({"a": 50, "b": 10, "untouched": 7})
        balances, history = ledger.balances, ledger.history
        expected = operation(amount=50)
        self.assertEqual(ledger.transfer(**expected), expected)
        self.assertEqual(ledger.balances, {"a": 0, "b": 60, "untouched": 7})
        self.assertEqual(ledger.history, {"one": expected})
        self.assertIs(ledger.balances, balances)
        self.assertIs(ledger.history, history)

    def test_invalid_transfers_are_value_errors_without_state_changes(self):
        changes = [
            {"source": "missing"}, {"target": "missing"},
            {"source": None}, {"source": []}, {"source": 1},
            {"target": None}, {"target": {}}, {"target": True},
            {"target": "a"},
            {"amount": 0}, {"amount": -1}, {"amount": True},
            {"amount": False}, {"amount": 1.0}, {"amount": "1"},
            {"amount": None}, {"amount": []}, {"amount": 46},
            {"key": ""}, {"key": 1}, {"key": True},
            {"key": None}, {"key": []}, {"key": {}},
        ]
        for change in changes:
            with self.subTest(change=change):
                ledger = Ledger({"a": 50, "b": 10, "c": 0})
                ledger.transfer("a", "c", 5, "seed")
                request = operation()
                request.update(change)
                self.assert_rejected_without_change(
                    ledger, lambda: ledger.transfer(**request)
                )

    def test_replay_needs_no_remaining_funds_and_returns_a_fresh_receipt(self):
        ledger = Ledger({"a": 10, "b": 0})
        request = operation()
        original = ledger.transfer(**request)
        before = deepcopy((ledger.balances, ledger.history))
        replay = ledger.transfer(**request)
        self.assertEqual(replay, original)
        self.assertIsNot(replay, original)
        self.assertEqual((ledger.balances, ledger.history), before)

    def test_replay_rejects_changed_payload_and_bool_integer_alias(self):
        ledger = Ledger({"a": 10, "b": 10, "c": 5})
        request = operation(amount=1)
        ledger.transfer(**request)
        for change in ({"source": "b"}, {"target": "c"},
                       {"amount": 2}, {"amount": True}):
            with self.subTest(change=change):
                changed = dict(request, **change)
                self.assert_rejected_without_change(
                    ledger, lambda: ledger.transfer(**changed)
                )

    def test_transfer_and_replay_receipts_do_not_expose_history(self):
        ledger = Ledger({"a": 30, "b": 0})
        request = operation()
        original = ledger.transfer(**request)
        original.clear()
        self.assertEqual(ledger.history, {"one": request})
        replay = ledger.transfer(**request)
        replay["amount"] = 999
        replay["extra"] = []
        self.assertEqual(ledger.history, {"one": request})
        self.assertEqual(ledger.transfer(**request), request)
        self.assertEqual(ledger.balances, {"a": 20, "b": 10})

    def test_batch_orders_receipts_and_replays_existing_and_new_keys(self):
        ledger = Ledger({"a": 100, "b": 0, "c": 0, "untouched": 7})
        seed = operation(amount=20, key="seed")
        ledger.transfer(**seed)
        balances, history = ledger.balances, ledger.history
        move = operation("b", "c", 15, "move")
        second = operation(amount=10, key="second")
        requests = [move, seed, second, move]
        before_requests = deepcopy(requests)
        receipts = ledger.batch(requests)
        self.assertEqual(receipts, requests)
        self.assertEqual(requests, before_requests)
        self.assertEqual(ledger.balances,
                         {"a": 70, "b": 15, "c": 15, "untouched": 7})
        self.assertEqual(ledger.history,
                         {"seed": seed, "move": move, "second": second})
        self.assertIs(ledger.balances, balances)
        self.assertIs(ledger.history, history)
        before = deepcopy((ledger.balances, ledger.history))
        self.assertEqual(ledger.batch(requests), requests)
        self.assertEqual(ledger.transfer(**move), move)
        self.assertEqual((ledger.balances, ledger.history), before)

    def test_batch_uses_prior_credits_but_cannot_spend_future_credits(self):
        ledger = Ledger({"a": 10, "b": 0, "c": 0})
        credit = operation("a", "b", 10, "credit")
        spend = operation("b", "c", 10, "spend")
        self.assert_rejected_without_change(
            ledger, lambda: ledger.batch([spend, credit])
        )
        self.assertEqual(ledger.batch([credit, spend]), [credit, spend])
        self.assertEqual(ledger.balances, {"a": 0, "b": 0, "c": 10})
        self.assertEqual(ledger.history, {"credit": credit, "spend": spend})

    def test_batch_receipts_are_independent_of_history_inputs_and_each_other(self):
        ledger = Ledger({"a": 30, "b": 0})
        request = operation()
        expected = request.copy()
        receipts = ledger.batch([request, request])
        self.assertIsNot(receipts[0], receipts[1])
        self.assertIsNot(receipts[0], request)
        receipts[0].clear()
        self.assertEqual(receipts[1], expected)
        receipts[1]["amount"] = 99
        request["source"] = "changed"
        self.assertEqual(ledger.history, {"one": expected})
        self.assertEqual(ledger.transfer(**expected), expected)

    def test_batch_failure_discards_prior_effects_and_allows_retry(self):
        failures = [
            operation("b", "c", 31, "overdraft"),
            operation("a", "missing", 1, "missing-account"),
            operation("a", "a", 1, "same-account"),
            operation(amount=True, key="bool"),
            operation(key=""),
            operation(amount=9, key="seed"),
            operation(amount=21, key="new"),
            {"source": "a", "target": "b", "amount": 1},
            dict(operation(key="extra"), unexpected=True),
            {1: "a", "target": "b", "amount": 1, "key": "bad-field"},
            None, [], ("a", "b", 1, "tuple"),
        ]
        for failure in failures:
            with self.subTest(failure=failure):
                ledger = Ledger({"a": 60, "b": 0, "c": 10})
                ledger.transfer("a", "b", 10, "seed")
                first = operation(amount=20, key="new")
                requests = [first, failure]
                before_requests = deepcopy(requests)
                self.assert_rejected_without_change(
                    ledger, lambda: ledger.batch(requests)
                )
                self.assertEqual(requests, before_requests)
                self.assertEqual(ledger.transfer(**first), first)
                self.assertEqual(ledger.balances, {"a": 30, "b": 30, "c": 10})
                self.assertEqual(set(ledger.history), {"seed", "new"})

    def test_batch_rejects_non_list_containers_without_state_changes(self):
        invalid = [None, {}, (), (operation(),), iter([operation()]), "", 1, True]
        for requests in invalid:
            with self.subTest(container_type=type(requests).__name__):
                ledger = Ledger({"a": 30, "b": 0})
                ledger.transfer("a", "b", 5, "seed")
                self.assert_rejected_without_change(
                    ledger, lambda: ledger.batch(requests)
                )

    def test_empty_batch_preserves_existing_state_and_dictionary_identity(self):
        ledger = Ledger({"a": 30, "b": 0})
        ledger.transfer("a", "b", 5, "seed")
        balances, history = ledger.balances, ledger.history
        before = deepcopy((balances, history))
        self.assertEqual(ledger.batch([]), [])
        self.assertEqual((ledger.balances, ledger.history), before)
        self.assertIs(ledger.balances, balances)
        self.assertIs(ledger.history, history)

    def test_integrated_payments_rollback_retry_and_replay(self):
        opening = {"alice": 100, "bob": 40, "shop": 0}
        ledger = Ledger(opening)
        purchase = operation("alice", "shop", 25, "purchase")
        repay = operation("bob", "alice", 15, "repay")
        groceries = operation("alice", "shop", 20, "groceries")
        refund = operation("shop", "alice", 5, "refund")
        finish = operation("bob", "shop", 25, "finish")

        self.assertEqual(ledger.transfer(**purchase), purchase)
        self.assertEqual(ledger.batch([repay, groceries, repay]),
                         [repay, groceries, repay])
        self.assertEqual(ledger.balances, {"alice": 70, "bob": 25, "shop": 45})
        self.assert_rejected_without_change(
            ledger,
            lambda: ledger.batch([refund, operation("bob", "shop", 26, "finish")]),
        )
        self.assertEqual(ledger.batch([refund, finish]), [refund, finish])
        self.assertEqual(ledger.balances, {"alice": 75, "bob": 0, "shop": 65})

        completed = [purchase, repay, groceries, refund, finish]
        before = deepcopy((ledger.balances, ledger.history))
        receipts = ledger.batch(completed)
        self.assertEqual(receipts, completed)
        receipts[-1].clear()
        self.assertEqual((ledger.balances, ledger.history), before)
        self.assert_rejected_without_change(
            ledger, lambda: ledger.transfer("alice", "shop", 26, "purchase")
        )
        self.assertEqual(ledger.history, {item["key"]: item for item in completed})
        self.assertEqual(opening, {"alice": 100, "bob": 40, "shop": 0})
        self.assertEqual(sum(ledger.balances.values()), 140)


if __name__ == "__main__":
    unittest.main()
