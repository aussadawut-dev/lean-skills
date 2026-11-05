import unittest

from app import parse_numbers


class ParseTests(unittest.TestCase):
    def test_signed_and_padded_fields(self):
        self.assertEqual(parse_numbers(' +1 , -2,0003'), [1, -2, 3])

    def test_empty_field_is_rejected(self):
        for text in ('', '1,,2', ',1', '1,'):
            with self.assertRaises(ValueError):
                parse_numbers(text)


if __name__ == '__main__':
    unittest.main()
