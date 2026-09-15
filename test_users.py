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

    def test_contact_inquiries_logging_and_stats(self):
        uid_rand = uuid.uuid4().hex[:6]
        name = f"Inquirer_{uid_rand}"
        phone = "01050333949"
        msg = "أرغب في الاستفسار عن كورس بايثون المتقدم"

        save_res = db.save_contact_inquiry(name, phone, msg)
        self.assertTrue(save_res["success"])

        stats = db.get_admin_dashboard_stats()
        self.assertGreaterEqual(stats["total_inquiries"], 1)
        found = any(iq["name"] == name for iq in stats["inquiries"])
        self.assertTrue(found)

    def test_university_track_independent_state(self):
        uid_rand = uuid.uuid4().hex[:6]
        reg = db.create_user(f"uni_stud_{uid_rand}", f"uni_{uid_rand}@test.com", "pass123")
        self.assertTrue(reg["success"])
        user = db.authenticate_user(f"uni_stud_{uid_rand}", "pass123")["user"]

        state = engine.get_platform_state(user["id"])
        uni_lessons = [l for l in state["lessons"] if l.get("track") == "university"]
        self.assertGreaterEqual(len(uni_lessons), 2)
        # First university lesson should be unlocked
        self.assertTrue(uni_lessons[0]["unlocked"])
        # Second university lesson should be locked initially
        self.assertFalse(uni_lessons[1]["unlocked"])

    def test_uploaded_submissions_saving_and_admin_stats(self):
        uid_rand = uuid.uuid4().hex[:6]
        reg = db.create_user(f"up_stud_{uid_rand}", f"up_{uid_rand}@test.com", "pass123")
        user = db.authenticate_user(f"up_stud_{uid_rand}", "pass123")["user"]

        res = db.save_uploaded_submission(
            user_id=user["id"],
            original_filename="assignment_01.py",
            saved_filename=f"{user['username']}_123_assignment_01.py",
            file_size=1024,
            task_id="uni_t1",
            lesson_id="uni_lesson_01",
            notes="University Assignment Solution"
        )
        self.assertTrue(res["success"])

        stats = db.get_admin_dashboard_stats()
        self.assertIn("uploaded_submissions", stats)
        self.assertGreaterEqual(stats["total_uploaded_submissions"], 1)
        found = any(sub["original_filename"] == "assignment_01.py" for sub in stats["uploaded_submissions"])
        self.assertTrue(found)

if __name__ == "__main__":
    unittest.main()
