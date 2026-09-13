import unittest
import json
import uuid
import security
import db

class TestAPISecurity(unittest.TestCase):
    def setUp(self):
        db.init_db()

    def test_input_validation_registration(self):
        # Invalid username (too short, special chars)
        ok, msg = security.validate_register_input("a", "valid@mail.com", "password123")
        self.assertFalse(ok)
        self.assertIn("اسم المستخدم", msg)

        # Invalid email format
        ok, msg = security.validate_register_input("valid_user", "invalid_email_format", "password123")
        self.assertFalse(ok)
        self.assertIn("البريد الإلكتروني", msg)

        # Password too short
        ok, msg = security.validate_register_input("valid_user", "test@test.com", "123")
        self.assertFalse(ok)
        self.assertIn("كلمة المرور", msg)

        # Valid input
        ok, msg = security.validate_register_input("good_student", "student@example.com", "securepass123")
        self.assertTrue(ok)

    def test_rate_limiter_sliding_window(self):
        test_ip = f"test_ip_{uuid.uuid4().hex[:6]}"
        
        # Limit: 3 requests per 10 seconds
        self.assertTrue(security.check_rate_limit(test_ip, max_requests=3, window_seconds=10))
        self.assertTrue(security.check_rate_limit(test_ip, max_requests=3, window_seconds=10))
        self.assertTrue(security.check_rate_limit(test_ip, max_requests=3, window_seconds=10))
        
        # 4th request must be rejected!
        self.assertFalse(security.check_rate_limit(test_ip, max_requests=3, window_seconds=10))

    def test_csrf_token_lifecycle(self):
        session_id = "sample_session_token_123"
        token = security.generate_csrf_token(session_id)
        self.assertTrue(len(token) > 20)

        # Correct token verify
        self.assertTrue(security.verify_csrf_token(session_id, token))

        # Tampered or wrong token verify
        self.assertFalse(security.verify_csrf_token(session_id, "wrong_tampered_token"))
        self.assertFalse(security.verify_csrf_token("different_session", token))

    def test_security_headers_present(self):
        headers = security.SECURITY_HEADERS
        self.assertIn("X-Content-Type-Options", headers)
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertIn("X-Frame-Options", headers)
        self.assertEqual(headers["X-Frame-Options"], "DENY")
        self.assertIn("Content-Security-Policy", headers)

if __name__ == "__main__":
    unittest.main()
