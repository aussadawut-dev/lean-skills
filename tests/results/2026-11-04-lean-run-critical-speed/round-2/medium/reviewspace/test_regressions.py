import subprocess
import sys
import unittest
from pathlib import Path

from app import parse_numbers


VALID_LISTS = (
    ("1,-2,+3", [1, -2, 3]),
    ("-2,-3", [-2, -3]),
    ("0", [0]),
    (" +001, -002 ,0,-0,+000 ", [1, -2, 0, 0, 0]),
    ("\t1\n,\r-2\v,\f+3\u00a0", [1, -2, 3]),
)
EMPTY_FIELDS = ("", " \t\n", ",", ",1", "1,", "1,,2", "1, ,2", "1,2, ")
INVALID_FIELDS = (
    "1_000", "1.0", "1e3", "0x10", "word", "NaN", "inf",
    "\u0661", "\uff11", "\u00b2", "1\u0662", "\u22121",
    "+", "-", "++1", "--1", "+-1", "-+1",
    "1 2", "+ 1", "-\t1", "1\n2", "--help", "--",
)
APP = Path(__file__).resolve().with_name("app.py")


class ParserRegressionTests(unittest.TestCase):
    def test_preserves_signed_values_zeros_and_all_fields(self):
        for text, expected in VALID_LISTS:
            with self.subTest(text=text):
                self.assertEqual(parse_numbers(text), expected)

    def test_rejects_empty_fields_instead_of_dropping_them(self):
        for text in EMPTY_FIELDS:
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_numbers(text)

    def test_rejects_non_ascii_integer_syntax_in_any_field(self):
        for field in (*INVALID_FIELDS, "1\x002"):
            for text in (field, f"1,{field},2"):
                with self.subTest(text=text), self.assertRaises(ValueError):
                    parse_numbers(text)

    def test_integer_conversion_boundaries_and_arbitrary_size(self):
        for length in (1, 8, 9, 10, 17, 18, 19, 100, 5000):
            expected = 10 ** length - 1
            for sign in ("", "+", "-"):
                with self.subTest(length=length, sign=sign):
                    self.assertEqual(
                        parse_numbers(sign + "9" * length),
                        [-expected if sign == "-" else expected],
                    )

    def test_large_values_with_zero_padding_and_cancellation(self):
        huge = "1" + "0" * 4999 + "7"
        expected = 10 ** 5000 + 7
        self.assertEqual(
            parse_numbers("+" + "0" * 5000 + "7," + huge + ",-" + huge),
            [7, expected, -expected],
        )


class CLIRegressionTests(unittest.TestCase):
    def run_cli(self, *arguments):
        return subprocess.run(
            [sys.executable, "-B", str(APP), *arguments],
            cwd=APP.parent,
            capture_output=True,
            text=True,
            timeout=10,
        )

    def assert_success(self, result, expected):
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, expected + "\n")
        self.assertEqual(result.stderr, "")

    def assert_input_error(self, result):
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("error", result.stderr.lower())
        self.assertNotIn("Traceback", result.stderr)

    def test_valid_lists_including_leading_negative_argument(self):
        for text, expected in VALID_LISTS:
            with self.subTest(text=text):
                self.assert_success(self.run_cli(text), str(sum(expected)))

    def test_invalid_input_has_clean_error_and_no_stdout(self):
        for text in (*EMPTY_FIELDS, *INVALID_FIELDS, "1,word,2", "1,\uff12,3"):
            with self.subTest(text=text):
                result = self.run_cli(text)
                self.assert_input_error(result)
                self.assertIn("integer", result.stderr.lower())

    def test_exactly_one_argument_is_required(self):
        for arguments in ((), ("1", "2"), ("1", "2", "3"), ("1,2", "--help")):
            with self.subTest(arguments=arguments):
                result = self.run_cli(*arguments)
                self.assert_input_error(result)
                self.assertIn("argument", result.stderr.lower())

    def test_arbitrary_size_sums_and_decimal_rendering(self):
        nines = "9" * 5000
        power = "1" + "0" * 5000
        cases = (
            (nines + ",1", power),
            ("-" + nines + ",-1", "-" + power),
            (nines + ",-" + nines, "0"),
            (power + ",-1", nines),
            ("1" + "0" * 4999 + "7,3", "1" + "0" * 4998 + "10"),
            ("+" + "0" * 5000 + "7", "7"),
        )
        for index, (text, expected) in enumerate(cases):
            with self.subTest(case=index):
                self.assert_success(self.run_cli(text), expected)


if __name__ == "__main__":
    unittest.main()
