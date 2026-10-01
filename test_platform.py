import unittest
import json
import db
import engine

class TestPlatform(unittest.TestCase):
    def setUp(self):
        db.init_db()
        self.test_user_id = "test_platform_runner_user"
        db.reset_user_progress(self.test_user_id)

    def test_lessons_loading(self):
        lessons = engine.load_all_lessons()
        self.assertGreaterEqual(len(lessons), 3)
        self.assertEqual(lessons[0]["id"], "lesson_01")
        self.assertEqual(lessons[1]["id"], "lesson_02")

    def test_lesson_gating(self):
        state = engine.get_platform_state(user_id=self.test_user_id)
        l1 = next(l for l in state["lessons"] if l["id"] == "lesson_01")
        l2 = next(l for l in state["lessons"] if l["id"] == "lesson_02")
        
        # Lesson 1 should be unlocked, Lesson 2 locked initially
        self.assertTrue(l1["unlocked"])
        self.assertFalse(l2["unlocked"])

        # Solve Lesson 1 tasks for this user
        lesson1_data = engine.get_lesson_by_id("lesson_01")
        for task in lesson1_data["tasks"]:
            db.mark_task_done(self.test_user_id, task["id"], "lesson_01")

        # Re-check state: Lesson 2 should now be unlocked!
        new_state = engine.get_platform_state(user_id=self.test_user_id)
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

    def test_different_student_implementations(self):
        # Simulate a task where the admin provided reference code (even collapsed single-line code)
        task = {
            "starter_code": "score = 75\n",
            "test_cases": [
                {
                    "type": "exact_output",
                    "expected": "score = 75  if score >= 50:     print(\"Passed\") else:     print(\"Failed\")"
                }
            ]
        }

        # 1. Standard if/else
        code_style_1 = "score = 75\nif score >= 50:\n    print('Passed')\nelse:\n    print('Failed')"
        self.assertTrue(engine.evaluate_task(task, code_style_1)["passed"])

        # 2. Ternary expression with different variable name
        code_style_2 = "my_grade = 75\nprint('Passed' if my_grade >= 50 else 'Failed')"
        self.assertTrue(engine.evaluate_task(task, code_style_2)["passed"])

        # 3. Reversed condition (< 50)
        code_style_3 = "x = 75\nif x < 50:\n    print('Failed')\nelse:\n    print('Passed')"
        self.assertTrue(engine.evaluate_task(task, code_style_3)["passed"])

        # 4. Function-based implementation
        code_style_4 = "def check(s):\n    if s >= 50:\n        return 'Passed'\n    return 'Failed'\nprint(check(75))"
        self.assertTrue(engine.evaluate_task(task, code_style_4)["passed"])

        # 5. Cheating attempt: hardcoded print('Passed') without any condition or variable logic
        cheat_code = "print('Passed')"
        self.assertFalse(engine.evaluate_task(task, cheat_code)["passed"])

        # 6. Student uses input() instead of hardcoded score = 75
        input_code = 'score = int(input("enter your number:")) \nif score >= 50:\n    print("Passed")\nelse:\n    print("Failed")'
        self.assertTrue(engine.evaluate_task(task, input_code)["passed"])

        # 7. Student uses input() with minor syntax slips (missing closing paren, '> =', 'Pass')
        slip_code = 'score=int(input("enter your grade ")\nif score > = 50:\n print("Pass")\nelse:\n print("Failed")'
        self.assertTrue(engine.evaluate_task(task, slip_code)["passed"])

        # 8. Student uses a different variable name and a different initial value (e.g. x = 30)
        diff_val_code = "x = 30\nif x >= 50:\n    print('Passed')\nelse:\n    print('Failed')"
        self.assertTrue(engine.evaluate_task(task, diff_val_code)["passed"])

        # 9. Student defines a function without calling print()
        func_only_code = "def evaluate_grade(g):\n    return 'Passed' if g >= 50 else 'Failed'"
        self.assertTrue(engine.evaluate_task(task, func_only_code)["passed"])

    def test_model_free_smart_grading(self):
        # Task created WITHOUT expected_output and WITHOUT reference_code
        instruction = "اكتب برنامج يختبر درجة الطالب إذا كانت 50 فأكثر يطبع ناجح وإلا راسب"
        _, _, cases = engine.build_task_test_cases("", "", "", instruction=instruction)
        open_task = {
            "id": "open_task_1",
            "title": "اختبار النجاح",
            "instruction": instruction,
            "expected_output": "",
            "test_cases": cases
        }

        self.assertTrue(engine.evaluate_task(open_task, 's = int(input("grade: "))\nif s >= 50:\n    print("Passed")\nelse:\n    print("Failed")')["passed"])
        self.assertTrue(engine.evaluate_task(open_task, 'deg = 80\nprint("ناجح" if deg >= 50 else "راسب")')["passed"])
        self.assertFalse(engine.evaluate_task(open_task, 'print("Passed")')["passed"])

        # Loop accumulation without print() (e.g. counting numbers > 50)
        count_task = {
            "id": "count_task",
            "instruction": "Count numbers > 50",
            "starter_code": "grades = [30, 55, 80, 45, 90, 60, 20]\ncount = 0\n",
            "expected_output": "4",
            "test_cases": [{"type": "exact_output", "expected": "4"}]
        }
        no_print_loop = "grades = [30, 55, 80, 45, 90, 60, 20]\ncount = 0\nfor g in grades:\n    if g > 50:\n        count += 1"
        self.assertTrue(engine.evaluate_task(count_task, no_print_loop)["passed"])

if __name__ == "__main__":
    unittest.main()

