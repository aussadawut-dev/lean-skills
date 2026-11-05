from pathlib import Path
import subprocess
import sys
import unittest

from app import parse_numbers


APP = Path(__file__).resolve().with_name('app.py')


class ParserRegressionTests(unittest.TestCase):
    def test_preserves_order_signs_zeros_and_surrounding_whitespace(self):
        self.assertEqual(
            parse_numbers(' \t+0012\n, -0034 ,0,-0,+0,000,12,12'),
            [12, -34, 0, 0, 0, 0, 12, 12],
        )
        self.assertEqual(parse_numbers('\u2003+12\u00a0,\t-34\n'), [12, -34])

    def test_rejects_empty_input_and_every_empty_field_position(self):
        for text in ('', ' ', '\n\t', ',', ',1', '1,', '1,,2', '1, \t ,2'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_numbers(text)

    def test_rejects_non_decimal_syntax_and_non_numbers(self):
        for field in (
            '1_000', '-1_0', '1.0', '.5', '1e3', '1E+3', '0x10', '0b11',
            '1 2', '1\n2', '+', '-', '++1', '--1', '+-1', '-+1', '+ 1',
            '- 1', 'one', 'NaN', 'Infinity', '2\x00',
        ):
            with self.subTest(field=field), self.assertRaises(ValueError):
                parse_numbers(f'7,{field},9')

    def test_rejects_unicode_numerals_and_signs(self):
        for field in ('١', '２', '१२', '²', '1٢', '−2', '＋2'):
            with self.subTest(field=field), self.assertRaises(ValueError):
                parse_numbers(field)

    def test_preserves_large_signed_values(self):
        text = '9' * 5000
        expected = 10 ** 5000 - 1
        self.assertEqual(
            parse_numbers(f'{text},-{text},+{text}'),
            [expected, -expected, expected],
        )
        self.assertEqual(parse_numbers('0' * 5000 + '7'), [7])
        self.assertEqual(parse_numbers('-' + '0' * 5000), [0])


class CliRegressionTests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, '-B', str(APP), *args],
            cwd=APP.parent,
            capture_output=True,
            text=True,
            timeout=10,
        )

    def assert_cli_success(self, text, expected):
        result = self.run_cli(text)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, expected + '\n')
        self.assertEqual(result.stderr, '')

    def assert_cli_error(self, args):
        result = self.run_cli(*args)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, '')
        self.assertIn('error:', result.stderr.lower())
        self.assertNotIn('Traceback', result.stderr)
        return result.stderr

    def test_signed_negative_and_whitespace_lists(self):
        for text, expected in (
            ('1,-2,+3', '2'), ('-2,-3', '-5'), ('-2', '-2'),
            (' \t+0012\n, -0034 ,0,-0,+0,000 ', '-22'), ('0', '0'),
        ):
            with self.subTest(text=text):
                self.assert_cli_success(text, expected)

    def test_requires_exactly_one_argument(self):
        for args in ((), ('1', '2'), ('1', '2', '3'), ('--', '1')):
            with self.subTest(args=args):
                self.assertIn('exactly one', self.assert_cli_error(args))

    def test_invalid_lists_have_clean_errors(self):
        for text in (
            '', ' ', ',', ',1', '1,', '1,,2', '1, \t ,2', '1_000',
            '1.0', '1e3', '١', '２', '+', '--1', '--help', '1,nope',
        ):
            with self.subTest(text=text):
                self.assertIn('ASCII decimal integer', self.assert_cli_error((text,)))
        self.assertIn('field 2', self.assert_cli_error(('1,nope,3',)))

    def test_large_integer_output_sum_carry_and_cancellation(self):
        nines = '9' * 5000
        for label, text, expected in (
            ('positive', nines, nines),
            ('negative', '-' + nines, '-' + nines),
            ('carry', nines + ',1', '1' + '0' * 5000),
            ('negative carry', '-' + nines + ',-1', '-1' + '0' * 5000),
            ('cancellation', nines + ',-' + nines, '0'),
            ('leading zeros', '0' * 5000 + '7', '7'),
        ):
            with self.subTest(case=label):
                self.assert_cli_success(text, expected)


if __name__ == '__main__':
    unittest.main()
