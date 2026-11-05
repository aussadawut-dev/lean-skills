import subprocess
import sys
import unittest
from decimal import localcontext
from pathlib import Path

from app import parse_numbers


APP_PATH = Path(__file__).resolve().with_name("app.py")
VALID_LISTS = (
    ("1,-2,+3", [1, -2, 3]),
    ("-2,-3", [-2, -3]),
    ("7", [7]),
    ("42,42,42", [42, 42, 42]),
    ("0,+0,-0,000,-000,+000", [0, 0, 0, 0, 0, 0]),
    (" \t+001 , -002\r\n,3 \v\f", [1, -2, 3]),
    ("\u2003+1\u00a0,\u2002-2\u2009", [1, -2]),
    ("9223372036854775808,-9223372036854775809", [2**63, -(2**63 + 1)]),
)
INVALID_LISTS = {
    "empty fields": ("", " \t\r\n", ",", ",1", "1,", "1,,2", "1, \t ,2"),
    "underscores": ("1_000", "1,2_0,3"),
    "other numeric syntax": ("1.0", "-0.5", "1e3", "-2E+2", "0x10", "0b10", "0o10"),
    "Unicode numerals": ("\u0661", "\uff11\uff12", "1\u0662", "\u00b2"),
    "invalid signs": ("+", "-", "++1", "--1", "+-1", "-+1", "\u22121", "+ 1"),
    "non-numbers": ("text", "NaN", "inf", "1;2", "1,wrong,2", "--help"),
    "internal whitespace and controls": ("1 2", "1\n2", "-\t1", "1\u200b"),
}


class ParseNumbersTests(unittest.TestCase):
    def test_valid_lists_preserve_values_and_fields(self):
        for text, expected in VALID_LISTS:
            with self.subTest(text=text):
                actual = parse_numbers(text)
                self.assertEqual(actual, expected)
                self.assertTrue(all(type(value) is int for value in actual))

    def test_invalid_lists_raise_value_error(self):
        for category, examples in INVALID_LISTS.items():
            for text in examples:
                with self.subTest(category=category, text=text):
                    with self.assertRaises(ValueError):
                        parse_numbers(text)

    def test_embedded_null_is_invalid(self):
        # OS argument vectors cannot contain NUL, but the public parser can.
        with self.assertRaises(ValueError):
            parse_numbers("1,2\x00,3")

    def test_arbitrary_size_signed_values_are_exact(self):
        digits = "9" * 5000
        expected = 10**5000 - 1
        with localcontext() as context:
            context.prec = 2
            self.assertEqual(
                parse_numbers(f"{digits},-{digits},+{digits}"),
                [expected, -expected, expected],
            )

    def test_long_zero_padding_preserves_values(self):
        zeros = "0" * 5000
        self.assertEqual(parse_numbers(f"{zeros}7,-{zeros}8,+{zeros}"), [7, -8, 0])


class CliTests(unittest.TestCase):
    def run_cli(self, *arguments):
        return subprocess.run(
            [sys.executable, "-B", str(APP_PATH), *arguments],
            cwd=APP_PATH.parent,
            capture_output=True,
            text=True,
            timeout=10,
        )

    def assert_success(self, result, expected):
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, expected + "\n")
        self.assertEqual(result.stderr, "")

    def assert_invalid(self, result):
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertTrue(result.stderr.strip())
        self.assertNotIn("Traceback", result.stderr)

    def test_valid_lists_print_exact_sum(self):
        for text, expected in VALID_LISTS:
            with self.subTest(text=text):
                self.assert_success(self.run_cli(text), str(sum(expected)))

    def test_invalid_lists_report_errors_without_output(self):
        for category, examples in INVALID_LISTS.items():
            for text in examples:
                with self.subTest(category=category, text=text):
                    result = self.run_cli(text)
                    self.assert_invalid(result)
                    self.assertIn("integer", result.stderr.lower())

    def test_exactly_one_argument_is_required(self):
        for arguments in ((), ("1", "2"), ("1", "2", "3"), ("1", "")):
            with self.subTest(arguments=arguments):
                result = self.run_cli(*arguments)
                self.assert_invalid(result)
                self.assertIn("argument", result.stderr.lower())

    def test_arbitrary_size_sums(self):
        digits = "9" * 5000
        zeros = "0" * 5000
        cases = (
            ("positive carry", f"{digits},1", "1" + zeros),
            ("negative carry", f"-{digits},-1", "-1" + zeros),
            ("cancellation", f"{digits},-{digits}", "0"),
            ("padded zero", f"-{zeros},+{zeros}", "0"),
        )
        for label, text, expected in cases:
            with self.subTest(case=label):
                self.assert_success(self.run_cli(text), expected)

    def test_sum_can_exceed_integer_string_limit(self):
        self.assert_success(self.run_cli("9" * 4300 + ",1"), "1" + "0" * 4300)


if __name__ == "__main__":
    unittest.main()
