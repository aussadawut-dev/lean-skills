import unittest
from app import parse_numbers
class PublicTests(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(parse_numbers('1,-2,+3'), [1,-2,3])
