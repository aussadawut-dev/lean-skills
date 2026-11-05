import subprocess
import sys
import unittest
from decimal import localcontext
from pathlib import Path

from app import parse_numbers


APP = Path(__file__).resolve().with_name("app.py")
INVALID_INPUTS = (
    "",
    " \t\n",
    ",",
    ",1",
    "1,",
    "1,,2",
    "1, \t,2",
    "1_000",
    "1,2_3",
    "1.0",
    ".5",
    "1e3",
    "1E+3",
    "0x10",
    "0o10",
    "0b10",
    "+",
    "-",
    "--1",
    "+-1",
    "-+1",
    "++1",
    "1 2",
    "- 1",
    "1\t2",
    "1\n2",
    "one",
    "NaN",
    "Infinity",
    "\u0661",
    "\uff11",
    "1\u0662",
    "\u00b2",
    "\u22121",
    "1;2",
    "1\x00",
    "1\u200b",
    "bad,2,3",
    "1,bad,3",
    "1,2,bad",
)


class ParseNumbersTests(unittest.TestCase):
    def test_valid_values_preserve_every_field_and_order(self):
        cases = (
            ("7", [7]),
            ("+7", [7]),
            ("-7", [-7]),
            ("1,-2,+3", [1, -2, 3]),
            (" \t+001 ,\n -002 \r, 000 ", [1, -2, 0]),
            ("-0,+0,000", [0, 0, 0]),
            ("1,1,1", [1, 1, 1]),
            ("\u00a0-4\u2003,\t+5\n", [-4, 5]),
        )
        for text, expected in cases:
            with self.subTest(text=text):
                actual = parse_numbers(text)
                self.assertIsInstance(actual, list)
                self.assertEqual(actual, expected)
                self.assertTrue(all(type(value) is int for value in actual))

    def test_invalid_input_raises_value_error(self):
        for text in INVALID_INPUTS:
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    parse_numbers(text)

    def test_error_identifies_invalid_field(self):
        with self.assertRaisesRegex(ValueError, r"\bfield 3\b"):
            parse_numbers("1,2,bad")

    def test_arbitrary_size_integers_are_exact(self):
        digits = "9" * 5000
        expected = 10 ** 5000 - 1
        with localcontext() as context:
            context.prec = 2
            actual = parse_numbers(f"{digits},-{digits},+{digits},-0")
        self.assertTrue(
            actual == [expected, -expected, expected, 0],
            "Large signed integers must retain their exact values",
        )
        self.assertTrue(all(type(value) is int for value in actual))

    def test_long_leading_zeros_are_valid(self):
        zeros = "0" * 5000
        self.assertEqual(parse_numbers(f"{zeros},+{zeros}7,-{zeros}8"), [0, 7, -8])


class CliTests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, "-B", str(APP), *args],
            cwd=APP.parent,
            capture_output=True,
            encoding="utf-8",
            timeout=10,
        )

    def assert_cli_error(self, result):
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("error", result.stderr.lower())
        self.assertNotIn("Traceback", result.stderr)

    def test_valid_cli_journey(self):
        cases = (
            ("1,-2,+3", "2"),
            ("-2,-3", "-5"),
            ("-7", "-7"),
            ("+7", "7"),
            ("-0,+0,000", "0"),
            (" \t+001 ,\n -002 \r, 000 ", "-1"),
            ("\u00a0-4\u2003,\t+5\n", "1"),
        )
        for text, expected in cases:
            with self.subTest(text=text):
                result = self.run_cli(text)
                self.assertEqual(result.returncode, 0)
                self.assertEqual(result.stdout, expected + "\n")
                self.assertEqual(result.stderr, "")

    def test_invalid_input_has_clean_cli_error(self):
        for text in INVALID_INPUTS:
            # NUL cannot be passed through the operating system's argv.
            if "\x00" in text:
                continue
            with self.subTest(text=text):
                result = self.run_cli(text)
                self.assert_cli_error(result)
                self.assertIn("field", result.stderr.lower())

    def test_cli_requires_exactly_one_argument(self):
        for args in [[], ["1", "2"], ["1", "2", "3"], ["-2,-3", "4"]]:
            with self.subTest(args=args):
                result = self.run_cli(*args)
                self.assert_cli_error(result)
                self.assertIn("exactly one", result.stderr.lower())

    def test_arbitrary_size_cli_totals(self):
        digits = "9" * 5000
        cases = (
            ("positive carry", f"{digits},1", "1" + "0" * 5000),
            ("negative carry", f"-{digits},-1", "-1" + "0" * 5000),
            ("cancellation", f"{digits},-{digits},+3", "3"),
            ("leading zeros", "0" * 5000 + "7", "7"),
        )
        for label, text, expected in cases:
            with self.subTest(case=label):
                result = self.run_cli(text)
                self.assertEqual(result.returncode, 0)
                self.assertEqual(result.stdout, expected + "\n")
                self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main()
