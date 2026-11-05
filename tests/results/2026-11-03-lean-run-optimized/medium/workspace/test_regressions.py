from pathlib import Path
import subprocess
import sys
import unittest

from app import parse_numbers


APP = Path(__file__).resolve().with_name("app.py")


class ParseNumbersTests(unittest.TestCase):
    def test_signed_values_zeros_and_surrounding_whitespace(self):
        cases = [
            ("1,-2,+3", [1, -2, 3]),
            ("-7", [-7]),
            ("0,-0,+0,000", [0, 0, 0, 0]),
            ("\t +001 , -002\n, 003 \r", [1, -2, 3]),
            ("\u2003+4\u00a0, -5", [4, -5]),
        ]
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(parse_numbers(text), expected)

    def test_rejects_empty_input_and_every_empty_field(self):
        for text in ("", " \t\n", ",", ",1", "1,", "1,,2", "1, \t,2"):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    parse_numbers(text)

    def test_rejects_non_ascii_integer_grammar(self):
        invalid_fields = (
            "1_000", "_1", "1_", "1.0", ".5", "1e3", "1E-2",
            "\u0661\u0662", "\uff11\uff12", "\u00b2", "\u216b", "\u22122",
            "+", "-", "--1", "+-1", "1 2", "- 2", "1\n2",
            "1\x00", "0x10", "NaN", "inf", "word",
        )
        for field in invalid_fields:
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    parse_numbers("2," + field + ",3")

    def test_preserves_integers_beyond_the_default_digit_limit(self):
        digits = "9" * 5000
        expected = 10 ** 5000 - 1
        self.assertEqual(
            parse_numbers(digits + ",-" + digits + ",+" + digits),
            [expected, -expected, expected],
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

    def assert_cli_error(self, arguments):
        result = self.run_cli(*arguments)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertRegex(
            result.stderr.lower(),
            r"invalid|empty|integer|argument|expected|required|usage",
        )
        self.assertNotIn("Traceback", result.stderr)

    def test_valid_lists_include_leading_negatives(self):
        cases = [
            ("1,-2,+3", "2\n"),
            ("-2,-3", "-5\n"),
            ("-7", "-7\n"),
            (" +000 , -00 , 0 ", "0\n"),
            ("\t4 , +5, -2\n", "7\n"),
        ]
        for text, expected in cases:
            with self.subTest(text=text):
                result = self.run_cli(text)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, expected)
                self.assertEqual(result.stderr, "")

    def test_requires_exactly_one_argument(self):
        for arguments in ((), ("1", "2"), ("-2,-3", "0")):
            with self.subTest(arguments=arguments):
                self.assert_cli_error(arguments)

    def test_invalid_input_is_reported_without_partial_output(self):
        invalid = (
            "", " ", ",1", "1,", "1,,2", "1, \t,2", "1_000",
            "\u0661", "\uff11", "1.0", "1e2", "+", "--1", "2,word,3",
        )
        for text in invalid:
            with self.subTest(text=text):
                self.assert_cli_error((text,))

    def test_large_sums_are_rendered_exactly(self):
        digits = "9" * 5000
        expected = "1" + "0" * 5000 + "\n"
        for sign in ("", "-"):
            with self.subTest(sign=sign):
                result = self.run_cli(sign + digits + "," + sign + "1")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, sign + expected)
                self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main()
