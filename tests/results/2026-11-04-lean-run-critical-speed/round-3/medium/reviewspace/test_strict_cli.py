import subprocess
import sys
import unittest
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
    "1, \t ,2",
    "1_000",
    "1.0",
    "1e3",
    "0x10",
    "0b10",
    "١",
    "２",
    "1٢",
    "²",
    "−1",
    "＋1",
    "+",
    "-",
    "++1",
    "--1",
    "+-1",
    "-+1",
    "+ 1",
    "1 2",
    "1\n2",
    "NaN",
    "Infinity",
    "word",
    "1;2",
    "1,word,3",
)


class ParseNumbersTests(unittest.TestCase):
    def test_signed_values_whitespace_and_zero_fields_are_preserved(self):
        cases = (
            ("1,-2,+3", [1, -2, 3]),
            ("-2,-3", [-2, -3]),
            ("0", [0]),
            (" \t+0012\r,\n-0007\v, 000 , -0, +0 ", [12, -7, 0, 0, 0]),
            ("\u2003+12\u00a0, -3", [12, -3]),
        )
        for text, expected in cases:
            with self.subTest(text=text):
                result = parse_numbers(text)
                self.assertIsInstance(result, list)
                self.assertEqual(result, expected)
                self.assertTrue(all(type(value) is int for value in result))

    def test_invalid_fields_raise_value_error(self):
        for text in INVALID_INPUTS:
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    parse_numbers(text)

    def test_invalid_field_error_identifies_its_position(self):
        for text in ("1,,3", "1,word,3"):
            with self.subTest(text=text):
                with self.assertRaisesRegex(ValueError, r"field 2"):
                    parse_numbers(text)

    def test_integers_beyond_python_decimal_digit_limit(self):
        digits = "9" * 5000
        expected = 10 ** 5000 - 1
        self.assertEqual(
            parse_numbers(digits + ",-" + digits + ",+" + digits),
            [expected, -expected, expected],
        )

    def test_long_leading_zero_fields(self):
        zeros = "0" * 5000
        self.assertEqual(
            parse_numbers(zeros + ",+" + zeros + "7,-" + zeros + "8"),
            [0, 7, -8],
        )


class CommandLineTests(unittest.TestCase):
    def run_cli(self, *arguments):
        return subprocess.run(
            [sys.executable, "-B", str(APP), *arguments],
            cwd=APP.parent,
            capture_output=True,
            text=True,
            timeout=10,
        )

    def assert_success(self, text, expected):
        result = self.run_cli(text)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, expected + "\n")
        self.assertEqual(result.stderr, "")

    def assert_error(self, arguments):
        result = self.run_cli(*arguments)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertIn("error", result.stderr.lower())
        self.assertNotIn("Traceback", result.stderr)
        return result.stderr

    def test_valid_lists_print_exact_sums(self):
        for text, expected in (
            ("1,-2,+3", "2"),
            ("-2,-3", "-5"),
            ("-2", "-2"),
            ("\t+00012, -0007, 0, -0, +0 \n", "5"),
            ("+0,-0,000", "0"),
        ):
            with self.subTest(text=text):
                self.assert_success(text, expected)

    def test_invalid_input_has_clean_error_and_no_stdout(self):
        for text in INVALID_INPUTS:
            with self.subTest(text=text):
                stderr = self.assert_error([text])
                self.assertIn("integer", stderr.lower())

    def test_exactly_one_argument_is_required(self):
        for arguments in ([], ["1", "2"], ["-2,-3", "4", "5"]):
            with self.subTest(arguments=arguments):
                stderr = self.assert_error(arguments)
                self.assertIn("exactly one argument", stderr.lower())

    def test_huge_positive_negative_and_cancelled_sums(self):
        digits = "9" * 5000
        cases = (
            (digits + ",1", "1" + "0" * 5000),
            ("-" + digits + ",-1", "-1" + "0" * 5000),
            (digits + ",-" + digits + ",+7", "7"),
        )
        for index, (text, expected) in enumerate(cases):
            with self.subTest(case=index):
                self.assert_success(text, expected)


if __name__ == "__main__":
    unittest.main()
