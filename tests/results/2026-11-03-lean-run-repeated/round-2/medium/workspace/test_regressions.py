import subprocess
import sys
import unittest
from pathlib import Path

from app import parse_numbers


APP = Path(__file__).resolve().with_name("app.py")
VALID_CASES = (
    ("1,-2,+3", [1, -2, 3]),
    ("-2,-3", [-2, -3]),
    ("42", [42]),
    ("0,-0,+0,000,-000,+000", [0, 0, 0, 0, 0, 0]),
    ("+00012,-003,004", [12, -3, 4]),
    (" \t+1 \r,\n -2\t, +3\n", [1, -2, 3]),
    ("\u00a01\u2003,\t-2\n", [1, -2]),
)
INVALID_INPUTS = (
    "", " ", "\t\r\n", "\u00a0\u2003",
    ",", ",1", "1,", "1,,2", "1, \t ,2", "1,2,",
    "1_000", "+1_0", "-1_0", "1,2_3,4",
    "1.0", ".5", "1.", "1e3", "-1E+3",
    "\u0661", "\uff11", "\U0001d7d9", "\u00b2", "1\u0662", "1,-\uff12",
    "+", "-", "++1", "--1", "+-1", "-+1", "+ 1", "- 2", "1 2",
    "\u22121", "0x10", "0b10", "NaN", "inf", "one", "1;2", "1,word,2",
    "1\n2", "--help",
)


class ParseNumbersTests(unittest.TestCase):
    def test_valid_values_are_preserved(self):
        for text, expected in VALID_CASES:
            with self.subTest(text=text):
                actual = parse_numbers(text)
                self.assertIsInstance(actual, list)
                self.assertEqual(actual, expected)
                self.assertTrue(all(type(value) is int for value in actual))

    def test_invalid_fields_raise_value_error(self):
        # NUL can reach the parser API, but operating systems reject it in argv.
        for text in INVALID_INPUTS + ("1\x00",):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    parse_numbers(text)

    def test_arbitrary_size_signed_values_and_leading_zeros(self):
        digits = "9" * 5000
        value = 10 ** 5000 - 1
        cases = (
            ("signed values", digits + ",-" + digits + ",+" + digits,
             [value, -value, value]),
            ("leading zeros", "+" + "0" * 5000 + "7,-" + "0" * 5000,
             [7, 0]),
        )
        for label, text, expected in cases:
            with self.subTest(case=label):
                self.assertEqual(parse_numbers(text), expected)


class CLITests(unittest.TestCase):
    def run_cli(self, *arguments):
        return subprocess.run(
            [sys.executable, "-B", str(APP), *arguments],
            cwd=APP.parent,
            capture_output=True,
            text=True,
            timeout=10,
        )

    def test_valid_lists_print_exact_sum(self):
        for text, values in VALID_CASES:
            with self.subTest(text=text):
                result = self.run_cli(text)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, str(sum(values)) + "\n")
                self.assertEqual(result.stderr, "")

    def test_invalid_input_has_clean_error_exit(self):
        for text in INVALID_INPUTS:
            with self.subTest(text=text):
                result = self.run_cli(text)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")
                self.assertIn("error", result.stderr.lower())
                self.assertNotIn("Traceback", result.stderr)

    def test_exactly_one_argument_is_required(self):
        for arguments in ((), ("1", "2"), ("1", "2", "3"), ("-2,-3", "4")):
            with self.subTest(arguments=arguments):
                result = self.run_cli(*arguments)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")
                self.assertIn("usage", result.stderr.lower())
                self.assertIn("exactly one", result.stderr.lower())
                self.assertNotIn("Traceback", result.stderr)

    def test_error_identifies_invalid_field(self):
        result = self.run_cli("1,2,word,4")
        self.assertEqual(result.returncode, 2)
        self.assertIn("field 3", result.stderr.lower())
        self.assertIn("integer", result.stderr.lower())
        self.assertEqual(result.stdout, "")
        self.assertNotIn("Traceback", result.stderr)

    def test_arbitrary_size_sums(self):
        digits = "9" * 5000
        cases = (
            ("positive carry", digits + ",1", "1" + "0" * 5000 + "\n"),
            ("negative carry", "-" + digits + ",-1", "-1" + "0" * 5000 + "\n"),
            ("cancellation", digits + ",-" + digits, "0\n"),
        )
        for label, text, expected in cases:
            with self.subTest(case=label):
                result = self.run_cli(text)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, expected)
                self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main()
