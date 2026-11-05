from decimal import localcontext
from pathlib import Path
import os
import subprocess
import sys
import unittest

from app import parse_numbers


INVALID_LISTS = (
    "", " ", "\t\n", ",", ",1", "1,", "1,,2", "1, \t,2", "1,2,",
    "1_000", "_1", "1_", "1.0", "-0.5", "1e3", "1E-3", "0x10", "0b10",
    "١", "１２", "-٢", "+３", "1٢", "²", "−1",
    "+", "-", "++1", "--1", "+-1", "-+1", "+ 1", "1 2", "1\n2",
    "nope", "NaN", "Infinity", "1;2", "1\x00", "1,2,nope",
)


class ParseNumbersRegressionTests(unittest.TestCase):
    def test_signed_values_whitespace_leading_zeroes_and_zero_fields(self):
        self.assertEqual(
            parse_numbers(" \t+001 , -002,\n0, -0, +000, 5\r "),
            [1, -2, 0, 0, 0, 5],
        )
        self.assertEqual(parse_numbers("\u2003-2\u00a0,\t+3\n"), [-2, 3])

    def test_single_integers(self):
        for text, expected in (("1", 1), ("-2", -2), ("+3", 3), ("0", 0)):
            with self.subTest(text=text):
                self.assertEqual(parse_numbers(text), [expected])

    def test_rejects_invalid_fields_without_dropping_them(self):
        for text in INVALID_LISTS:
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    parse_numbers(text)

    def test_large_integers_are_exact_and_preserve_the_process_digit_limit(self):
        digits = "9" * 5001
        limit_before = sys.get_int_max_str_digits()
        with localcontext() as context:
            context.prec = 1
            numbers = parse_numbers(f"+{digits},-{digits},0")
        expected = 10 ** 5001 - 1
        self.assertTrue(all(type(number) is int for number in numbers))
        self.assertTrue(numbers == [expected, -expected, 0])
        self.assertEqual(sys.get_int_max_str_digits(), limit_before)


class CLIRegressionTests(unittest.TestCase):
    def run_cli(self, *arguments, digit_limit=None):
        environment = os.environ.copy()
        if digit_limit is not None:
            environment["PYTHONINTMAXSTRDIGITS"] = str(digit_limit)
        return subprocess.run(
            [sys.executable, "-B", str(Path(__file__).with_name("app.py")), *arguments],
            capture_output=True,
            text=True,
            env=environment,
            timeout=10,
        )

    def assert_success(self, result, expected):
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertEqual(result.stdout, expected + "\n")

    def assert_input_error(self, result):
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertTrue(result.stderr.strip())
        self.assertIn("error", result.stderr.lower())
        self.assertNotIn("Traceback", result.stderr)

    def test_signed_sum_including_a_leading_negative_list(self):
        for text, expected in (
            ("1,-2,+3", "2"), ("-2,-3", "-5"), ("-2", "-2"),
            (" \t+001,-002,0,-0,+000,5\n", "4"), ("0,0,0", "0"),
        ):
            with self.subTest(text=text):
                self.assert_success(self.run_cli(text), expected)

    def test_exactly_one_argument_is_required(self):
        for arguments in ((), ("1", "2"), ("1", "2", "3"), ("1", "")):
            with self.subTest(arguments=arguments):
                self.assert_input_error(self.run_cli(*arguments))

    def test_invalid_lists_report_errors_without_output_or_tracebacks(self):
        for text in INVALID_LISTS + ("--help",):
            with self.subTest(text=text):
                # NUL cannot be passed in an OS process argument; the API covers it.
                if "\x00" in text:
                    continue
                self.assert_input_error(self.run_cli(text))

    def test_large_values_and_large_output_under_a_strict_digit_limit(self):
        nines = "9" * 5001
        for text, expected in (
            (f"{nines},1", "1" + "0" * 5001),
            (f"-{nines},-1", "-1" + "0" * 5001),
            (f"+{nines},-{nines},+3", "3"),
        ):
            with self.subTest(expected_sign=expected[0], output_length=len(expected)):
                self.assert_success(self.run_cli(text, digit_limit=640), expected)

    def test_sum_can_exceed_the_digit_limit_even_when_inputs_do_not(self):
        self.assert_success(
            self.run_cli("9" * 640 + ",1", digit_limit=640),
            "1" + "0" * 640,
        )

    def test_large_malformed_input_reports_a_clean_error(self):
        self.assert_input_error(self.run_cli("9" * 5001 + "x", digit_limit=640))


if __name__ == "__main__":
    unittest.main()
