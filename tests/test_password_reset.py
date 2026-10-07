import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "stayora"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from auth import _generate_reset_code, _normalize_email, _is_reset_code_valid


class PasswordResetHelpersTest(unittest.TestCase):
    def test_normalize_email_and_code_generation(self):
        self.assertEqual(_normalize_email("  User@Example.com  "), "user@example.com")
        code = _generate_reset_code()
        self.assertEqual(len(code), 6)
        self.assertTrue(code.isdigit())

    def test_reset_code_validation_logic(self):
        expires_at = "2099-01-01T00:00:00"
        self.assertTrue(_is_reset_code_valid("123456", "123456", expires_at))
        self.assertFalse(_is_reset_code_valid("123456", "654321", expires_at))


if __name__ == "__main__":
    unittest.main()
