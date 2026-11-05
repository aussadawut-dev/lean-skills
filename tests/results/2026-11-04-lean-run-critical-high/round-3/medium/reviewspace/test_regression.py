from pathlib import Path
import subprocess
import sys
import unittest

from app import parse_numbers


APP = Path(__file__).resolve().with_name("app.py")
LARGE_DIGITS = 5000


class ParseNumbersTests(unittest.TestCase):
    def test_signed_values_order_zeros_and_whitespace(self):
        cases = [
            ("1,-2,+3", [1, -2, 3]),
            ("-2,-3", [-2, -3]),
            ("0,+0,-0,000,+007,-002", [0, 0, 0, 0, 7, -2]),
            ("\u2003 +12\t,\n-3\r,\v0\f", [12, -3, 0]),
            ("42", [42]),
            ("123456789012345678901,-98765432109876543210",
             [123456789012345678901, -98765432109876543210]),
        ]
        for text, expected in cases:
            with self.subTest(text=text):
                actual = parse_numbers(text)
                self.assertIs(type(actual), list)
                self.assertEqual(actual, expected)
                self.assertTrue(all(type(value) is int for value in actual))

    def test_empty_input_or_fields_are_rejected(self):
        for text in ("", " \t\n", ",", ",1", "1,", "1,,2", "1, \t,2"):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    parse_numbers(text)

    def test_invalid_integer_syntax_is_rejected_in_every_field(self):
        invalid = (
            "1_000", "1.0", ".5", "1e2", "1E+2", "0x10", "0b10",
            "+", "-", "++1", "--1", "+-1", "-+1", "+ 1", "1 2",
            "1\n2", "NaN", "inf", "one", "1;2", "1\x00", "1\u200b",
        )
        for token in invalid:
            for text in (token, f"7,{token},9", f"7,9,{token}"):
                with self.subTest(text=text):
                    with self.assertRaises(ValueError):
                        parse_numbers(text)

    def test_unicode_numerals_and_signs_are_rejected(self):
        for token in ("١", "１２", "1٢", "²", "𝟙", "−2", "＋3"):
            with self.subTest(token=token):
                with self.assertRaises(ValueError):
                    parse_numbers(f"1,{token},2")

    def test_integers_beyond_python_decimal_conversion_limit(self):
        digits = "1" + "0" * LARGE_DIGITS
        expected = 10 ** LARGE_DIGITS
        self.assertEqual(parse_numbers(f"+{digits},-{digits}"),
                         [expected, -expected])
        self.assertEqual(parse_numbers("0" * LARGE_DIGITS + "7,-000"), [7, 0])


class CommandLineTests(unittest.TestCase):
    def run_cli(self, *arguments):
        return subprocess.run(
            [sys.executable, "-B", str(APP), *arguments],
            cwd=APP.parent, text=True, capture_output=True, timeout=10,
        )

    def assert_success(self, arguments, expected):
        result = self.run_cli(*arguments)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, expected + "\n")
        self.assertEqual(result.stderr, "")

    def assert_error(self, arguments, message_word):
        result = self.run_cli(*arguments)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertIn(message_word, result.stderr.lower())
        self.assertNotIn("Traceback", result.stderr)

    def test_valid_lists_including_leading_negative(self):
        for text, expected in (
            ("1,-2,+3", "2"), ("-2,-3", "-5"), ("-2", "-2"),
            (" +007 , -2 ", "5"), ("-0,0,+000", "0"),
            ("1000000000000000000,5", "1000000000000000005"),
        ):
            with self.subTest(text=text):
                self.assert_success([text], expected)

    def test_invalid_lists_report_clean_errors(self):
        for text in ("", "1,,2", "1,", "1_000,2", "１２,3", "1.5,2",
                     "1e3,2", "word", "-", "--help"):
            with self.subTest(text=text):
                self.assert_error([text], "integer")

    def test_exactly_one_argument_is_required(self):
        for arguments in ([], ["1", "2"], ["1,-2", "+3", "4"]):
            with self.subTest(arguments=arguments):
                self.assert_error(arguments, "argument")

    def test_arbitrary_size_sum_output_and_cancellation(self):
        nines = "9" * LARGE_DIGITS
        power = "1" + "0" * LARGE_DIGITS
        for name, text, expected in (
            ("positive carry", f"{nines},1", power),
            ("negative carry", f"-{nines},-1", "-" + power),
            ("cancellation", f"{power},-{power},+7", "7"),
        ):
            with self.subTest(case=name):
                self.assert_success([text], expected)


if __name__ == "__main__":
    unittest.main()
