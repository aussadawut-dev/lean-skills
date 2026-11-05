from pathlib import Path
import subprocess
import sys
import unittest

from app import parse_numbers


class ParserRegressionTests(unittest.TestCase):
    def test_signed_values_zeros_and_surrounding_whitespace(self):
        cases = [
            ("1,-2,+3", [1, -2, 3]),
            ("-2,-3", [-2, -3]),
            ("0,-0,+0,000,+000,-000", [0, 0, 0, 0, 0, 0]),
            ("\t+001 ,\n -002\r, 003\v", [1, -2, 3]),
            ("\u00a0-12\u2003,\t+34\n", [-12, 34]),
            ("42", [42]),
            ("123456789012345678901234567890", [123456789012345678901234567890]),
        ]
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(parse_numbers(text), expected)

    def test_empty_fields_are_never_dropped(self):
        for text in ("", " \t\n", ",", ",1", "1,", "1,,2", "1, \t,2", ",1,"):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    parse_numbers(text)

    def test_only_ascii_decimal_integer_syntax_is_accepted(self):
        invalid_fields = (
            "1_000", "0_0", "1.0", ".5", "1e3", "-2E4", "0x10", "0b10",
            "\u0661\u0662", "\uff11\uff12", "1\u0662", "\u00b2", "\u22121",
            "+", "-", "++1", "--1", "+-1", "-+1", "+ 1", "-\t2",
            "1 2", "1\n2", "1\u00a02", "nan", "inf", "word", "1;2", "1\x00",
        )
        for field in invalid_fields:
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    parse_numbers(f"7,{field},9")

    def test_arbitrary_size_values_and_leading_zeros(self):
        power_text = "1" + "0" * 5000
        nines = "9" * 5000
        self.assertEqual(
            parse_numbers(f"{power_text},-{nines},+{nines}," + "0" * 5000 + "42"),
            [10 ** 5000, -(10 ** 5000 - 1), 10 ** 5000 - 1, 42],
        )
        self.assertEqual(parse_numbers("-" + "0" * 5000), [0])

    def test_errors_identify_the_invalid_field(self):
        with self.assertRaisesRegex(ValueError, "field 2"):
            parse_numbers("1,,3")


class CliRegressionTests(unittest.TestCase):
    def run_cli(self, *arguments):
        return subprocess.run(
            [sys.executable, "-B", str(Path(__file__).with_name("app.py")), *arguments],
            capture_output=True,
            text=True,
            timeout=10,
        )

    def assert_success(self, arguments, expected):
        result = self.run_cli(*arguments)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, expected + "\n")
        self.assertEqual(result.stderr, "")

    def assert_input_error(self, arguments):
        result = self.run_cli(*arguments)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertIn("error:", result.stderr.lower())
        self.assertNotIn("Traceback", result.stderr)
        return result.stderr

    def test_valid_signed_lists(self):
        for text, expected in (
            ("1,-2,+3", "2"),
            ("-2,-3", "-5"),
            ("-7", "-7"),
            ("\t+001, -02 ,\n0\r", "-1"),
            ("0,-0,+0", "0"),
            ("1000000000,1", "1000000001"),
        ):
            with self.subTest(text=text):
                self.assert_success([text], expected)

    def test_invalid_lists(self):
        for text in (
            "", " ", ",1", "1,", "1,,2", "-1, ,2", "1_000", "\uff11\uff12",
            "1.5", "1e3", "word", "--help", "--",
        ):
            with self.subTest(text=text):
                self.assertIn("field", self.assert_input_error([text]))

    def test_exactly_one_argument_is_required(self):
        for arguments in ([], ["1", "2"], ["1,-2", "3", "4"], ["--", "1"]):
            with self.subTest(arguments=arguments):
                self.assertIn("exactly one", self.assert_input_error(arguments))

    def test_arbitrary_size_input_and_output(self):
        nines = "9" * 5000
        power_text = "1" + "0" * 5000
        cases = [
            (nines + ",1", power_text),
            ("-" + nines + ",-1", "-" + power_text),
            (power_text + ",-" + power_text, "0"),
            (power_text + ",42", "1" + "0" * 4998 + "42"),
        ]
        for index, (text, expected) in enumerate(cases):
            with self.subTest(case=index):
                self.assert_success([text], expected)


if __name__ == "__main__":
    unittest.main()
