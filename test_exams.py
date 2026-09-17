import unittest
import json
import db

class TestExamsControl(unittest.TestCase):
    def setUp(self):
        db.init_db()

    def test_exam_creation_default_closed(self):
        # Create a new exam
        res = db.create_exam(
            title="امتحان تجريبي للاختبارات",
            description="اختبار الأمان والسرية",
            instructions="اقرأ كل سؤال بدقة",
            duration_minutes=30,
            questions_json=json.dumps([{"title": "سؤال 1", "instruction": "طباعة 10"}]),
            is_open=False
        )
        self.assertTrue(res["success"])
        exam_id = res["exam_id"]

        # Ensure exam is fetched by admin
        exam = db.get_exam_by_id(exam_id)
        self.assertIsNotNone(exam)
        self.assertEqual(exam["title"], "امتحان تجريبي للاختبارات")
        self.assertFalse(exam["is_open"])

        # Ensure open exams list for students DOES NOT contain this exam!
        open_exams = db.get_open_exams()
        open_ids = [e["id"] for e in open_exams]
        self.assertNotIn(exam_id, open_ids, "الامتحان المغلق يجب ألا يظهر في قائمة امتحانات الطلاب!")

        # Clean up
        db.delete_exam(exam_id)

    def test_exam_toggle_visibility(self):
        # 1. Create exam
        res = db.create_exam(
            title="امتحان التحكم بالفتح والقفل",
            duration_minutes=45,
            is_open=False
        )
        exam_id = res["exam_id"]

        # 2. Check hidden initially
        open_exams_before = db.get_open_exams()
        self.assertNotIn(exam_id, [e["id"] for e in open_exams_before])

        # 3. Toggle Open (🟢 فتح الامتحان)
        toggle_res = db.toggle_exam_status(exam_id, True)
        self.assertTrue(toggle_res["success"])
        self.assertTrue(toggle_res["is_open"])

        # Check visible to students now
        open_exams_after = db.get_open_exams()
        self.assertIn(exam_id, [e["id"] for e in open_exams_after])

        # 4. Toggle Lock (🔴 قفل الامتحان)
        lock_res = db.toggle_exam_status(exam_id, False)
        self.assertTrue(lock_res["success"])
        self.assertFalse(lock_res["is_open"])

        # Check hidden from students again
        open_exams_locked = db.get_open_exams()
        self.assertNotIn(exam_id, [e["id"] for e in open_exams_locked])

        # Clean up
        db.delete_exam(exam_id)

    def test_exam_submission_and_cleanup(self):
        # 1. Create exam and open it
        res = db.create_exam(title="امتحان التسليم", duration_minutes=15, is_open=True)
        exam_id = res["exam_id"]

        # Create a test student user
        user_res = db.create_user("student_exam_tester", "student_exam@test.com", "password123")
        user_id = user_res["user"]["id"]

        # 2. Save submission
        sub_res = db.save_exam_submission(
            user_id=user_id,
            exam_id=exam_id,
            score=10,
            max_score=10,
            answers_json=json.dumps({"0": "print(10)"}),
            uploaded_file=""
        )
        self.assertTrue(sub_res["success"])

        # Verify submission recorded
        subs = db.get_exam_submissions(exam_id)
        self.assertEqual(len(subs), 1)
        self.assertEqual(subs[0]["username"], "student_exam_tester")
        self.assertEqual(subs[0]["score"], 10)

        # 3. Delete exam and ensure submissions are cascade deleted
        db.delete_exam(exam_id)
        subs_after = db.get_exam_submissions(exam_id)
        self.assertEqual(len(subs_after), 0)

        # Delete test user
        db.delete_user(user_id)

if __name__ == "__main__":
    unittest.main()
