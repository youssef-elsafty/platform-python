import unittest
import db

class TestAdminDashboard(unittest.TestCase):
    def setUp(self):
        db.init_db()

    def test_default_admin_created(self):
        admin = db.authenticate_user("youssef", "admin123")
        self.assertTrue(admin["success"])
        self.assertEqual(admin["user"]["role"], "admin")

    def test_login_logging(self):
        # Authenticate admin from a specific test IP
        db.authenticate_user("youssef", "admin123", ip_address="192.168.1.50")
        
        stats = db.get_admin_dashboard_stats()
        self.assertGreater(stats["total_users"], 0)
        self.assertTrue(len(stats["recent_logins"]) > 0)
        
        # Latest login must be youssef from 192.168.1.50
        latest = stats["recent_logins"][0]
        self.assertEqual(latest["username"], "youssef")
        self.assertEqual(latest["ip_address"], "192.168.1.50")

if __name__ == "__main__":
    unittest.main()
