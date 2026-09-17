import unittest
import os
import db
import engine

class TestPersistenceAndControls(unittest.TestCase):
    def setUp(self):
        db.init_db()
        self.test_username = "testpersuser"
        self.test_email = "testpers@example.com"
        
        with db.get_db() as conn:
            conn.execute("DELETE FROM users WHERE LOWER(username) = ?", (self.test_username,))
        
        res = db.create_user(self.test_username, self.test_email, "pass123")
        self.assertTrue(res["success"], f"Failed to create test user: {res.get('error')}")
        self.test_user_id = res["user"]["id"]

    def tearDown(self):
        db.delete_user(self.test_user_id)

    def test_user_code_persistence(self):
        task_id = "unit_test_task_1"
        code_sample = "print('Hello Persistent World')"

        # 1. Save code
        success = db.save_user_task_code(self.test_user_id, task_id, code_sample)
        self.assertTrue(success)

        # 2. Retrieve codes
        codes_map = db.get_user_task_codes(self.test_user_id)
        self.assertIn(task_id, codes_map)
        self.assertEqual(codes_map[task_id], code_sample)

        # 3. Update code draft
        updated_code = "print('Updated Code Draft')"
        db.save_user_task_code(self.test_user_id, task_id, updated_code)
        codes_map_updated = db.get_user_task_codes(self.test_user_id)
        self.assertEqual(codes_map_updated[task_id], updated_code)

    def test_task_status_toggle(self):
        task_id = "unit_test_task_toggle_1"

        # 1. Toggle task status to False (Closed)
        res_close = db.toggle_task_status(task_id, False)
        self.assertTrue(res_close["success"])
        self.assertFalse(res_close["is_open"])

        status_map = db.get_task_status_map()
        self.assertIn(task_id, status_map)
        self.assertFalse(status_map[task_id])

        # 2. Toggle task status to True (Open)
        res_open = db.toggle_task_status(task_id, True)
        self.assertTrue(res_open["success"])
        self.assertTrue(res_open["is_open"])

        status_map_open = db.get_task_status_map()
        self.assertTrue(status_map_open[task_id])

    def test_user_role_and_active_toggle(self):
        # 1. Toggle active to False (Ban student)
        res_ban = db.toggle_user_status(self.test_user_id, False)
        self.assertTrue(res_ban["success"])

        # Attempt login while banned
        login_res = db.authenticate_user(self.test_username, "pass123")
        self.assertFalse(login_res["success"])
        self.assertIn("حظر", login_res["error"])

        # 2. Unban user
        res_unban = db.toggle_user_status(self.test_user_id, True)
        self.assertTrue(res_unban["success"])

        login_res_ok = db.authenticate_user(self.test_username, "pass123")
        self.assertTrue(login_res_ok["success"])

        # 3. Update role to admin
        res_role = db.update_user_role(self.test_user_id, "admin")
        self.assertTrue(res_role["success"])

        # Admin cannot be banned protection check
        res_ban_admin = db.toggle_user_status(self.test_user_id, False)
        self.assertFalse(res_ban_admin["success"])

if __name__ == "__main__":
    unittest.main()
