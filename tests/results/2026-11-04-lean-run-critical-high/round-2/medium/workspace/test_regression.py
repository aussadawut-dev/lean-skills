import subprocess
import sys
import unittest
from pathlib import Path

from app import parse_numbers


WORKSPACE = Path(__file__).resolve().parent
APP = WORKSPACE / "app.py"

EMPTY_LISTS = ("", " \t\r\n", ",", ",,", ",1", "1,", "1,,2", "1, \t,2")
INVALID_FIELDS = (
    "1_000", "+1_0", "-1_0", "1.0", ".5", "1e3", "-2E-3",
    "0x10", "0b10", "NaN", "inf", "abc", "1tail", "head1",
    "\u0661\u0662", "\uff11\uff12", "\U0001d7d9", "\u00b2", "1\u0662", "\u2162",
    "+", "-", "++1", "--1", "+-1", "-+1", "\u22121",
    "1 2", "+ 1", "-\t2", "1\n2", "1\x002", "1\u200b", "1;2", "1\uff0c2",
)


class ParserRegressionTests(unittest.TestCase):
    def test_signed_values_zeros_and_field_order(self):
        cases = (
            ("0", [0]),
            ("-0,+0,000,-000,+000", [0, 0, 0, 0, 0]),
            ("+12,-34,005,+0006,-0007", [12, -34, 5, 6, -7]),
            (" \t+12 \n,\r -34\t, \v0\f", [12, -34, 0]),
            ("\u00a0+7\u2003,\u202f-8\u0085", [7, -8]),
        )
        for text, expected in cases:
            with self.subTest(text=text):
                actual = parse_numbers(text)
                self.assertIsInstance(actual, list)
                self.assertEqual(actual, expected)
                self.assertTrue(all(type(value) is int for value in actual))

    def test_empty_fields_are_never_dropped(self):
        for text in EMPTY_LISTS:
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    parse_numbers(text)

    def test_non_ascii_or_non_decimal_fields_are_rejected(self):
        for field in INVALID_FIELDS:
            for text in (field, f"1, {field} ,2"):
                with self.subTest(text=text):
                    with self.assertRaises(ValueError):
                        parse_numbers(text)

    def test_decimal_magnitudes_and_signs(self):
        values = [0, 1, -1]
        for exponent in (8, 9, 10, 17, 18, 19, 27):
            for offset in (-1, 0, 1):
                value = 10 ** exponent + offset
                values.extend((value, -value))
        self.assertEqual(parse_numbers(",".join(map(str, values))), values)

    def test_arbitrary_size_signed_integers_and_leading_zeros(self):
        digits = "9" * 5000
        value = 10 ** 5000 - 1
        self.assertEqual(
            parse_numbers(f"+{digits}, -{digits}, 000{digits}, -0"),
            [value, -value, value, 0],
        )
        self.assertEqual(parse_numbers("0" * 5000 + "7"), [7])

    def test_invalid_field_after_a_large_integer_is_rejected(self):
        for invalid in ("", " ", "1_0", "\u0661"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    parse_numbers("9" * 5000 + "," + invalid)


class CLIRegressionTests(unittest.TestCase):
    def run_cli(self, *arguments):
        return subprocess.run(
            [sys.executable, "-B", str(APP), *arguments],
            cwd=WORKSPACE,
            capture_output=True,
            text=True,
            timeout=10,
        )

    def assert_success(self, result, output):
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, output + "\n")
        self.assertEqual(result.stderr, "")

    def assert_input_error(self, result):
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertTrue(result.stderr.strip())
        self.assertIn("error", result.stderr.lower())
        self.assertNotIn("Traceback", result.stderr)

    def test_documented_example(self):
        self.assert_success(self.run_cli("1,-2,+3"), "2")

    def test_leading_negative_list(self):
        self.assert_success(self.run_cli("-2,-3"), "-5")

    def test_whitespace_signs_and_exact_integer_arithmetic(self):
        text = " \t-2,\n+003, 000, +9007199254740993, -9007199254740992 \r"
        self.assert_success(self.run_cli(text), "2")

    def test_zero_and_decimal_output(self):
        cases = (
            ("-0,+000,0", "0"),
            ("999999999,1", "1000000000"),
            ("-999999999,-1", "-1000000000"),
            ("1000000000000000000000000000,7", "1000000000000000000000000007"),
            ("-1000000000000000000000000000,-7", "-1000000000000000000000000007"),
        )
        for text, expected in cases:
            with self.subTest(text=text):
                self.assert_success(self.run_cli(text), expected)

    def test_exactly_one_argument_is_required(self):
        for arguments in ((), ("1", "2"), ("1,2", "bad"), ("1", "2", "3"), ("--", "1,2")):
            with self.subTest(arguments=arguments):
                result = self.run_cli(*arguments)
                self.assert_input_error(result)
                self.assertIn("exactly one", result.stderr.lower())

    def test_empty_fields_and_malformed_values_have_clean_errors(self):
        # NUL cannot be passed in an OS argument; it is checked through the parser.
        fields = [field for field in INVALID_FIELDS if "\x00" not in field]
        for text in (*EMPTY_LISTS, *fields, "--help", "--"):
            with self.subTest(text=text):
                result = self.run_cli(text)
                self.assert_input_error(result)
                self.assertIn("field", result.stderr.lower())

    def test_invalid_later_field_produces_no_partial_output(self):
        result = self.run_cli("1,-2,nope,4")
        self.assert_input_error(result)
        self.assertIn("3", result.stderr)

    def test_arbitrary_size_sum_and_carry(self):
        digits = "9" * 5000
        self.assert_success(self.run_cli(digits + ",1"), "1" + "0" * 5000)

    def test_arbitrary_size_negative_sum_and_cancellation(self):
        digits = "9" * 5000
        self.assert_success(self.run_cli("-" + digits + ",-1"), "-1" + "0" * 5000)
        self.assert_success(self.run_cli(f"{digits},-{digits},+7"), "7")

    def test_arbitrary_size_output_with_internal_zeroes(self):
        digits = "1" + "0" * 4999 + "7"
        self.assert_success(self.run_cli(digits), digits)

    def test_corrected_input_recovers_after_rejection(self):
        self.assert_input_error(self.run_cli("1, ,3"))
        self.assert_success(self.run_cli("1,+2,3"), "6")


if __name__ == "__main__":
    unittest.main()
