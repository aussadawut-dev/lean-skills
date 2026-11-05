from pathlib import Path
import subprocess
import sys
import unittest

from app import parse_numbers


APP = Path(__file__).resolve().with_name("app.py")


class ParserRegressionTests(unittest.TestCase):
    def test_preserves_signed_values_zeros_and_every_field(self):
        self.assertEqual(
            parse_numbers("\t+0017 , -0008\r,\n0, -0 , +0 , 000,17 \t"),
            [17, -8, 0, 0, 0, 0, 17],
        )
        self.assertEqual(parse_numbers("\u00a0-2\u2003,\t+3\n"), [-2, 3])
        self.assertEqual(parse_numbers("42"), [42])

    def test_rejects_empty_input_and_fields(self):
        for text in ("", " ", "\t\r\n", ",", ",1", "1,", "1,,2", "1, \t ,2"):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    parse_numbers(text)

    def test_rejects_non_integer_spellings(self):
        invalid = (
            "1_000", "1.0", ".5", "1.", "1e3", "-2E+4", "NaN", "Infinity",
            "abc", "0x10", "+", "-", "--1", "++1", "+-1", "1 2", "+ 1",
            "-\t2", "1\n2", "1;2", "1\uff0c2", "2\x00",
        )
        for text in invalid:
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    parse_numbers(text)

    def test_rejects_unicode_numerals_and_signs(self):
        for text in ("\u0661", "\uff11\uff12", "\u00b2", "\U0001d7da", "\u22122", "\uff0b2", "\u200b1"):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    parse_numbers(text)

    def test_invalid_middle_field_is_reported(self):
        for text in ("1,,2", "1,x,2"):
            with self.subTest(text=text):
                with self.assertRaisesRegex(ValueError, "field 2"):
                    parse_numbers(text)

    def test_arbitrary_size_values_are_exact_python_integers(self):
        digits = "9" * 5000
        values = parse_numbers(f"+{digits},-{digits}," + "0" * 5001)
        expected = 10 ** 5000 - 1
        self.assertEqual(values, [expected, -expected, 0])
        self.assertTrue(all(type(value) is int for value in values))


class CliRegressionTests(unittest.TestCase):
    def run_cli(self, *arguments):
        return subprocess.run(
            [sys.executable, "-B", str(APP), *arguments],
            cwd=APP.parent,
            capture_output=True,
            text=True,
            timeout=10,
        )

    def assert_cli_error(self, result):
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("error:", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_valid_lists(self):
        for argument, output in (
            ("1,-2,+3", "2\n"),
            ("-2,-3", "-5\n"),
            ("-2", "-2\n"),
            (" \t+0017, -0008, 0 \n", "9\n"),
            ("0,-0,+0", "0\n"),
        ):
            with self.subTest(argument=argument):
                result = self.run_cli(argument)
                self.assertEqual(result.returncode, 0)
                self.assertEqual(result.stdout, output)
                self.assertEqual(result.stderr, "")

    def test_requires_exactly_one_argument(self):
        for arguments in ((), ("1", "2"), ("1,2", "3", "4")):
            with self.subTest(arguments=arguments):
                result = self.run_cli(*arguments)
                self.assert_cli_error(result)
                self.assertIn("exactly one", result.stderr)

    def test_invalid_lists_have_clean_errors(self):
        for argument in (
            "", " ", ",1", "1,", "1,,2", "1, \t ,2", "1_000", "1.5",
            "1e2", "\u0661", "NaN", "1,word,2", "--help", "-",
        ):
            with self.subTest(argument=argument):
                result = self.run_cli(argument)
                self.assert_cli_error(result)
                self.assertIn("ASCII decimal integer", result.stderr)

    def test_arbitrary_size_sums_print_exact_decimal_output(self):
        digits = "9" * 5000
        for argument, output in (
            (f"{digits},1", "1" + "0" * 5000 + "\n"),
            (f"-{digits},-1", "-1" + "0" * 5000 + "\n"),
            (f"{digits},-{digits},3", "3\n"),
        ):
            with self.subTest(sign=argument[0], output_length=len(output)):
                result = self.run_cli(argument)
                self.assertEqual(result.returncode, 0)
                self.assertEqual(result.stdout, output)
                self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main()
