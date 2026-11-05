from pathlib import Path
import subprocess
import sys
import unittest

from app import parse_numbers


APP = Path(__file__).resolve().with_name("app.py")


class ParseNumbersTests(unittest.TestCase):
    def test_signed_values_whitespace_and_zeros(self):
        cases = (
            ("1,-2,+3", [1, -2, 3]),
            ("-2,-3", [-2, -3]),
            (" \t+001 , -002 , 0, -0,+0,00 \r\n", [1, -2, 0, 0, 0, 0]),
            ("\u2003+7\u00a0,\t-8\n", [7, -8]),
        )
        for text, expected in cases:
            with self.subTest(text=text):
                actual = parse_numbers(text)
                self.assertEqual(actual, expected)
                self.assertIs(type(actual), list)
                self.assertTrue(all(type(number) is int for number in actual))

    def test_empty_fields_are_rejected(self):
        for text in ("", " ", "\t\r\n", ",", ",1", "1,", "1,,2", "1, ,2", "1,\t\n,2"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_numbers(text)

    def test_non_integer_syntax_is_rejected_in_every_position(self):
        invalid_fields = (
            "1_000", "+1_0", "0x10", "0b10", "0o10", "1.0", ".5", "1.",
            "1e2", "1E+2", "nan", "inf", "word", "+", "-", "++1", "--1",
            "+-1", "-+1", "+ 1", "-\t2", "1 2", "1\n2", "\u0661", "\uff11\uff12",
            "\u00b2", "\u22121", "\uff0b1", "1\u200b", "\x001",
        )
        for field in invalid_fields:
            for text in (field, f"{field},2", f"2,{field},3", f"2,{field}"):
                with self.subTest(text=text), self.assertRaises(ValueError):
                    parse_numbers(text)

    def test_values_order_and_duplicates_are_preserved(self):
        self.assertEqual(
            parse_numbers("123456789012345678901,-3,42,42,-987654321098765432109"),
            [123456789012345678901, -3, 42, 42, -987654321098765432109],
        )

    def test_arbitrary_size_signed_values_and_leading_zeros(self):
        digits = "1" + "0" * 4997 + "123"
        expected = 10 ** 5000 + 123
        self.assertEqual(
            parse_numbers(f"{digits},-{digits},+{digits}"),
            [expected, -expected, expected],
        )
        zeros = "0" * 5001
        self.assertEqual(parse_numbers(f"{zeros}17,-{zeros},+{zeros}"), [17, 0, 0])


class CliTests(unittest.TestCase):
    def run_cli(self, *arguments):
        return subprocess.run(
            [sys.executable, "-B", str(APP), *arguments],
            cwd=APP.parent,
            capture_output=True,
            text=True,
            timeout=5,
        )

    def assert_cli_error(self, result, diagnostic):
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertIn(diagnostic, result.stderr.lower())
        self.assertNotIn("Traceback", result.stderr)

    def test_valid_lists(self):
        cases = (
            ("1,-2,+3", "2\n"),
            ("-2,-3", "-5\n"),
            ("-7", "-7\n"),
            (" \t-0002, +0003, -0 \n", "1\n"),
            ("0,+0,-0", "0\n"),
            ("123456789012345678901,-987654321098765432109", "-864197532086419753208\n"),
        )
        for text, expected in cases:
            with self.subTest(text=text):
                result = self.run_cli(text)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, expected)
                self.assertEqual(result.stderr, "")

    def test_exactly_one_argument_is_required(self):
        for arguments in ((), ("1", "2"), ("1", "2", "3"), ("--", "-2,-3"), ("1", "--ignored")):
            with self.subTest(arguments=arguments):
                self.assert_cli_error(self.run_cli(*arguments), "argument")

    def test_invalid_lists_have_clean_errors(self):
        for text in ("", " ", "1,,2", ",1", "1,", "1, ,2", "1,word", "1_000", "\u0661,2", "1.5", "1e2", "+", "--help"):
            with self.subTest(text=text):
                self.assert_cli_error(self.run_cli(text), "integer")

    def test_arbitrary_size_sums_and_cancellation(self):
        nines = "9" * 5000
        cases = (
            ("carry", f"{nines},1", "1" + "0" * 5000 + "\n"),
            ("negative", f"-{nines},-1", "-1" + "0" * 5000 + "\n"),
            ("cancellation", f"{nines},-{nines}", "0\n"),
            ("leading zeros", "0" * 5001 + "7", "7\n"),
        )
        for label, text, expected in cases:
            with self.subTest(case=label):
                result = self.run_cli(text)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, expected)
                self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main()
