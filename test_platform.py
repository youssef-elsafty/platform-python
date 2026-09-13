import unittest
import json
import db
import engine

class TestPlatform(unittest.TestCase):
    def setUp(self):
        db.init_db()
        db.reset_all_progress()

    def test_lessons_loading(self):
        lessons = engine.load_all_lessons()
        self.assertGreaterEqual(len(lessons), 3)
        self.assertEqual(lessons[0]["id"], "lesson_01")
        self.assertEqual(lessons[1]["id"], "lesson_02")

    def test_lesson_gating(self):
        state = engine.get_platform_state()
        l1 = next(l for l in state["lessons"] if l["id"] == "lesson_01")
        l2 = next(l for l in state["lessons"] if l["id"] == "lesson_02")
        
        # Lesson 1 should be unlocked, Lesson 2 locked initially
        self.assertTrue(l1["unlocked"])
        self.assertFalse(l2["unlocked"])

        # Solve Lesson 1 tasks
        lesson1_data = engine.get_lesson_by_id("lesson_01")
        for task in lesson1_data["tasks"]:
            db.mark_task_done(task["id"], "lesson_01")

        # Re-check state: Lesson 2 should now be unlocked!
        new_state = engine.get_platform_state()
        new_l2 = next(l for l in new_state["lessons"] if l["id"] == "lesson_02")
        self.assertTrue(new_l2["unlocked"])

    def test_code_evaluation(self):
        task = {
            "test_cases": [{"type": "exact_output", "expected": "Hello Python"}]
        }
        res_pass = engine.evaluate_task(task, "print('Hello Python')")
        self.assertTrue(res_pass["passed"])

        res_fail = engine.evaluate_task(task, "print('Wrong')")
        self.assertFalse(res_fail["passed"])

if __name__ == "__main__":
    unittest.main()
