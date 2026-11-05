import subprocess
import sys
import unittest
from pathlib import Path

from app import parse_numbers


APP = Path(__file__).resolve().with_name("app.py")


class ParseNumbersTests(unittest.TestCase):
    def test_signed_values_zeros_and_field_whitespace(self):
        cases = [
            ("1,-2,+3", [1, -2, 3]),
            ("-2,-3", [-2, -3]),
            ("42", [42]),
            ("123456789012345678901234567890,-1000000001,+1000000000",
             [123456789012345678901234567890, -1000000001, 1000000000]),
            ("\t +001 ,\n-02\r, 000, +0, -0 \t", [1, -2, 0, 0, 0]),
            ("\u2003+12\u00a0,\t-7\r\n", [12, -7]),
            ("0,0,0", [0, 0, 0]),
        ]
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(parse_numbers(text), expected)

    def test_empty_input_and_empty_fields_raise_value_error(self):
        for text in ("", " ", "\t\n", ",", ",1", "1,", "1,,2", "1,  ,2", ",1,", ",,"):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    parse_numbers(text)

    def test_non_decimal_syntax_raises_value_error(self):
        invalid_fields = (
            "1_000", "+1_0", "-1_0", "1.0", "-1.0", ".1", "1.",
            "1e3", "1E+3", "0x10", "0b10", "0o10", "NaN", "inf", "abc",
            "+", "-", "++1", "--1", "+-1", "-+1", "+ 1", "- 1",
            "1 2", "1\t2", "1\n2", "1\x002", "1;2",
        )
        for field in invalid_fields:
            for text in (field, f"10,{field},20"):
                with self.subTest(text=text):
                    with self.assertRaises(ValueError):
                        parse_numbers(text)

    def test_unicode_numerals_raise_value_error(self):
        for field in ("١", "２", "३", "²", "𝟜", "-٢", "+１", "1٢"):
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    parse_numbers(f"10,{field},20")

    def test_arbitrary_size_signed_integers(self):
        digits = "9" * 5000
        value = 10 ** 5000 - 1
        self.assertEqual(parse_numbers(f"{digits},-{digits},+{digits}"), [value, -value, value])

    def test_long_fields_with_leading_zeros(self):
        zeros = "0" * 5000
        self.assertEqual(parse_numbers(f"{zeros}7,-{zeros}7,+{zeros}"), [7, -7, 0])


class CliTests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, "-B", str(APP), *args],
            cwd=APP.parent,
            capture_output=True,
            text=True,
            timeout=10,
        )

    def assert_success(self, result, expected_stdout):
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertTrue(
            result.stdout == expected_stdout,
            f"Unexpected stdout: {result.stdout[:80]!r} (length {len(result.stdout)}); "
            f"expected {expected_stdout[:80]!r} (length {len(expected_stdout)})",
        )

    def assert_input_error(self, result):
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertTrue(result.stderr.strip(), "Expected a useful error on stderr")
        self.assertIn("error", result.stderr.lower())
        self.assertNotIn("Traceback", result.stderr)

    def test_valid_lists_through_cli(self):
        cases = [
            ("1,-2,+3", "2\n"),
            ("-2,-3", "-5\n"),
            ("+3", "3\n"),
            (" \t+001, -02, 000, +0,-0 \r\n", "-1\n"),
            ("0", "0\n"),
            ("-0", "0\n"),
            ("-3,3", "0\n"),
            ("123456789012345678901234567890,10", "123456789012345678901234567900\n"),
            ("1000000000000000001", "1000000000000000001\n"),
            ("1000000000000000001,-1", "1000000000000000000\n"),
        ]
        for text, expected in cases:
            with self.subTest(text=text):
                self.assert_success(self.run_cli(text), expected)

    def test_exactly_one_positional_argument_is_required(self):
        for args in ((), ("1", "2"), ("1", "2", "3")):
            with self.subTest(args=args):
                result = self.run_cli(*args)
                self.assert_input_error(result)
                self.assertRegex(result.stderr.lower(), r"argument|usage")

    def test_invalid_lists_through_cli(self):
        cases = (
            "", " \t", ",1", "1,", "1,,2", "1, ,2", "1_000", "1.0",
            "1e3", "١", "２", "abc", "+", "--1", "- 2", "1,2,x", "--help",
        )
        for text in cases:
            with self.subTest(text=text):
                result = self.run_cli(text)
                self.assert_input_error(result)
                self.assertRegex(result.stderr.lower(), r"integer|field|list|input")

    def test_arbitrary_size_sum_and_decimal_output(self):
        digits = "9" * 5000
        cases = [
            (f"{digits},1", "1" + "0" * 5000 + "\n"),
            (f"-{digits},-1", "-1" + "0" * 5000 + "\n"),
            (f"{digits},-{digits}", "0\n"),
            (f"{digits},-{digits},+7", "7\n"),
            (f"{'9' * 4300},1", "1" + "0" * 4300 + "\n"),
            (f"{'0' * 5000}7", "7\n"),
        ]
        for index, (text, expected) in enumerate(cases):
            with self.subTest(case=index):
                self.assert_success(self.run_cli(text), expected)


if __name__ == "__main__":
    unittest.main()
