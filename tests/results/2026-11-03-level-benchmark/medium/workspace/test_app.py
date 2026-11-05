import subprocess
import sys
import unittest
from pathlib import Path

from app import parse_numbers


APP = Path(__file__).resolve().with_name("app.py")
EMPTY_INPUTS = ("", " \t\n", ",", ",1", "1,", "1,,2", "1, \t,2")
INVALID_FIELDS = (
    "1_000", "1.0", "1e2", "0x10", "0b10", "nan", "inf", "word",
    "+", "-", "++1", "--1", "+-1", "+ 1", "1 2", "1\n2",
    "\u0661", "\uff12", "1\u0662", "\u22121", "1\x00",
)


class ParseNumbersTests(unittest.TestCase):
    def test_preserves_signed_values_zeros_and_order(self):
        self.assertEqual(
            parse_numbers("1,-2,+3,0,-0,+000,00012,-00012,42,42"),
            [1, -2, 3, 0, 0, 0, 12, -12, 42, 42],
        )

    def test_accepts_surrounding_whitespace_and_a_single_value(self):
        self.assertEqual(parse_numbers(" \t-2\n,\r +3 \t, 0 "), [-2, 3, 0])
        self.assertEqual(parse_numbers(" \t+42\n"), [42])

    def test_rejects_empty_input_and_fields(self):
        for text in EMPTY_INPUTS:
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_numbers(text)

    def test_rejects_non_ascii_or_non_integer_fields(self):
        for field in INVALID_FIELDS:
            for text in (field, f"1,{field},2"):
                with self.subTest(text=text), self.assertRaises(ValueError):
                    parse_numbers(text)

    def test_preserves_arbitrary_size_integers(self):
        digits = "9" * 5000
        expected = 10 ** 5000 - 1
        self.assertEqual(parse_numbers(f"+{digits},-{digits}"), [expected, -expected])

    def test_accepts_long_zero_padded_integers(self):
        zeros = "0" * 5000
        self.assertEqual(parse_numbers(f"{zeros},+{zeros}42,-{zeros}7"), [0, 42, -7])


class CommandLineTests(unittest.TestCase):
    def run_cli(self, *arguments):
        return subprocess.run(
            [sys.executable, "-B", str(APP), *arguments],
            cwd=APP.parent,
            capture_output=True,
            text=True,
            timeout=10,
        )

    def assert_cli_error(self, result):
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertTrue(result.stderr.strip(), "Expected a useful error on stderr")
        self.assertNotIn("Traceback", result.stderr)

    def test_valid_lists_print_only_the_sum(self):
        for text, expected in (
            ("1,-2,+3", "2\n"),
            ("-2,-3", "-5\n"),
            ("-2", "-2\n"),
            (" \t+1, -2\n, +3 ", "2\n"),
            ("0,-0,+000", "0\n"),
            ("42", "42\n"),
        ):
            with self.subTest(text=text):
                result = self.run_cli(text)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, expected)
                self.assertEqual(result.stderr, "")

    def test_requires_exactly_one_argument(self):
        for arguments in ((), ("1", "2"), ("1", "2", "3"), ("-2,-3", "4")):
            with self.subTest(arguments=arguments):
                result = self.run_cli(*arguments)
                self.assert_cli_error(result)
                self.assertIn("argument", result.stderr.lower())

    def test_invalid_input_has_clean_error(self):
        # NUL cannot be supplied in an operating system argument; it is tested
        # through parse_numbers above instead.
        for text in (*EMPTY_INPUTS, *INVALID_FIELDS[:-1], "1,no,2", "--help"):
            with self.subTest(text=text):
                self.assert_cli_error(self.run_cli(text))

    def test_arbitrary_size_input_and_output(self):
        digits = "9" * 5000
        interior_zeros = "1" + "0" * 4998 + "7"
        for name, text, expected in (
            ("positive carry", f"{digits},1", "1" + "0" * 5000),
            ("negative carry", f"-{digits},-1", "-1" + "0" * 5000),
            ("cancellation", f"{digits},-{digits}", "0"),
            ("interior zeros", interior_zeros, interior_zeros),
            ("leading zeros", "+" + "0" * 5000 + "42", "42"),
        ):
            with self.subTest(name=name):
                result = self.run_cli(text)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, expected + "\n")
                self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main()
