import os
import sys
import subprocess
import tempfile
import json
import glob
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
    first_unlocked_set = False

    for idx, lesson in enumerate(lessons):
        lid = lesson["id"]
        # All tasks in this lesson: lesson_tasks + cumulative_tasks
        all_tasks = lesson.get("tasks", []) + lesson.get("cumulative_tasks", [])
        total_tasks_count = len(all_tasks)
        done_tasks_count = sum(1 for t in all_tasks if t["id"] in completed_tasks)
        
        is_completed = (total_tasks_count > 0 and done_tasks_count == total_tasks_count)
        if is_completed and lid not in completed_lessons:
            mark_lesson_done(lid)
            completed_lessons.add(lid)

        # Unlock rule:
        # Lesson 1 is always unlocked.
        # Lesson N is unlocked if Lesson N-1 is completed!
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

def execute_code_safely(code, timeout=5):
    """Executes python code in a separate process with a strict timeout"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8-sig") as temp_file:
        temp_file.write(code)
        temp_path = temp_file.name

    try:
        proc = subprocess.run(
            [sys.executable, temp_path],
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8-sig",
            errors="replace"
        )
        return {
            "success": proc.returncode == 0,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "exit_code": proc.returncode
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "stdout": "",
            "stderr": "انتهى الوقت المحدد لتنفيذ الكود (Timeout: 5s). تأكد من عدم وجود حلقات تكرار لا نهائية (Infinite Loop).",
            "exit_code": -1
        }
    except Exception as e:
        return {
            "success": False,
            "stdout": "",
            "stderr": str(e),
            "exit_code": -1
        }
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except:
                pass

def evaluate_task(task, submitted_code):
    run_result = execute_code_safely(submitted_code)
    
    if not run_result["success"] and run_result["exit_code"] != 0:
        return {
            "passed": False,
            "output": run_result["stdout"],
            "error": run_result["stderr"],
            "feedback": "حدث خطأ أثناء تشغيل الكود (Syntax or Runtime Error)."
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
