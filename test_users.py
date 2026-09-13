import unittest
import uuid
import db
import engine

class TestUsersAndProgress(unittest.TestCase):
    def setUp(self):
        db.init_db()

    def test_user_registration_and_login(self):
        uid_rand = uuid.uuid4().hex[:6]
        username = f"user_{uid_rand}"
        email = f"user_{uid_rand}@test.com"
        pwd = "securepassword123"

        # Register
        reg = db.create_user(username, email, pwd)
        self.assertTrue(reg["success"])

        # Login success
        login = db.authenticate_user(username, pwd)
        self.assertTrue(login["success"])
        token = login["session_token"]

        # Validate Session
        user = db.get_user_by_session(token)
        self.assertIsNotNone(user)
        self.assertEqual(user["username"], username)

    def test_isolated_progress_per_user(self):
        uid_rand = uuid.uuid4().hex[:6]
        db.create_user(f"stud_a_{uid_rand}", f"a_{uid_rand}@test.com", "pass123")
        db.create_user(f"stud_b_{uid_rand}", f"b_{uid_rand}@test.com", "pass123")
        
        user_a = db.authenticate_user(f"stud_a_{uid_rand}", "pass123")["user"]
        user_b = db.authenticate_user(f"stud_b_{uid_rand}", "pass123")["user"]

        db.mark_task_done(user_a["id"], "l1_t1", "lesson_01")

        tasks_a = db.get_completed_task_ids(user_a["id"])
        self.assertIn("l1_t1", tasks_a)

        tasks_b = db.get_completed_task_ids(user_b["id"])
        self.assertNotIn("l1_t1", tasks_b)

if __name__ == "__main__":
    unittest.main()
