import unittest
import json
import urllib.request
import threading
from app import PythonLearningHandler
from http.server import HTTPServer
import db
import engine

PORT = 8089

class TestAIAndNotifications(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db.init_db()
        db.add_notification("تنبيه تجريبي", "مرحباً بكم في مسار بايثون")
        cls.server = HTTPServer(('127.0.0.1', PORT), PythonLearningHandler)
        cls.server_thread = threading.Thread(target=cls.server.serve_forever)
        cls.server_thread.daemon = True
        cls.server_thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_get_notifications(self):
        req = urllib.request.Request(f"http://127.0.0.1:{PORT}/api/notifications")
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode('utf-8'))
            self.assertIn("notifications", data)
            self.assertTrue(len(data["notifications"]) > 0)

    def test_post_ai_chat(self):
        payload = json.dumps({"message": "شرح المتغيرات", "code": "x = 10"}).encode('utf-8')
        req = urllib.request.Request(
            f"http://127.0.0.1:{PORT}/api/ai/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode('utf-8'))
            self.assertTrue(data["success"])
            self.assertIn("reply", data)
            self.assertTrue(len(data["reply"]) > 0)

if __name__ == "__main__":
    unittest.main()
