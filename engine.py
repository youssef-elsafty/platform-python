import os
import sys
import json
import glob
from runner import run_isolated_code
from db import (
    init_db, mark_task_done, mark_lesson_done,
    get_completed_task_ids, get_completed_lesson_ids, reset_all_progress
)

LESSONS_DIR = "lessons"

def load_all_lessons():
    files = glob.glob(os.path.join(LESSONS_DIR, "*.json"))
    lessons = []
    for filepath in files:
        try:
            with open(filepath, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
                lessons.append(data)
        except Exception as e:
            print(f"Error loading {filepath}: {e}")
    lessons.sort(key=lambda x: x.get("order", 999))
    return lessons

def get_lesson_by_id(lesson_id):
    lessons = load_all_lessons()
    for l in lessons:
        if l["id"] == lesson_id:
            return l
    return None

def get_platform_state():
    lessons = load_all_lessons()
    completed_tasks = get_completed_task_ids()
    completed_lessons = get_completed_lesson_ids()
    
    lesson_statuses = []

    for idx, lesson in enumerate(lessons):
        lid = lesson["id"]
        all_tasks = lesson.get("tasks", []) + lesson.get("cumulative_tasks", [])
        total_tasks_count = len(all_tasks)
        done_tasks_count = sum(1 for t in all_tasks if t["id"] in completed_tasks)
        
        is_completed = (total_tasks_count > 0 and done_tasks_count == total_tasks_count)
        if is_completed and lid not in completed_lessons:
            mark_lesson_done(lid)
            completed_lessons.add(lid)

        if idx == 0:
            unlocked = True
        else:
            prev_lesson = lessons[idx - 1]
            unlocked = prev_lesson["id"] in completed_lessons

        lesson_statuses.append({
            "id": lid,
            "order": lesson.get("order", idx + 1),
            "title": lesson.get("title", ""),
            "category": lesson.get("category", "General"),
            "description": lesson.get("description", ""),
            "unlocked": unlocked,
            "completed": is_completed,
            "total_tasks": total_tasks_count,
            "completed_tasks": done_tasks_count
        })

    return {
        "lessons": lesson_statuses,
        "completed_tasks": list(completed_tasks),
        "completed_lessons": list(completed_lessons)
    }

def execute_code_safely(code, timeout=4):
    """Delegates to the secure, isolated runner sandbox."""
    return run_isolated_code(code, timeout=timeout)

def evaluate_task(task, submitted_code):
    run_result = execute_code_safely(submitted_code)
    
    if not run_result["success"] and run_result["exit_code"] != 0:
        return {
            "passed": False,
            "output": run_result["stdout"],
            "error": run_result["stderr"],
            "feedback": "حدث خطأ أثناء تشغيل الكود (Error or Security Violation)."
        }

    actual_output = run_result["stdout"].strip()
    test_cases = task.get("test_cases", [])
    all_passed = True
    feedback = ""

    for tc in test_cases:
        tc_type = tc.get("type", "exact_output")
        expected = str(tc.get("expected", "")).strip()
        
        if tc_type == "exact_output":
            if actual_output != expected:
                all_passed = False
                feedback = f"المخرجات غير مطابقة للمطلوب.\nالمتوقع:\n{expected}\n\nالمُخرج من كودك:\n{actual_output}"
                break
        elif tc_type == "contains":
            if expected not in actual_output:
                all_passed = False
                feedback = f"يجب أن تحتوي مخرجات الكود على: {expected}"
                break

    if all_passed:
        feedback = "أحسنت! إجابة صحيحة واجتزت جميع الاختبارات بنجاح 🎉"

    return {
        "passed": all_passed,
        "output": actual_output,
        "error": run_result["stderr"],
        "feedback": feedback
    }
