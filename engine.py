import os
import sys
import json
import glob
from runner import run_isolated_code
from db import (
    init_db, mark_task_done, mark_lesson_done,
    get_completed_task_ids, get_completed_lesson_ids, reset_user_progress,
    get_user_avg_solve_seconds, get_user_task_codes, get_task_status_map
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
    # Sort general track first, then by order
    lessons.sort(key=lambda x: (0 if x.get("track", "general") == "general" else 1, x.get("order", 999)))
    return lessons

def get_lesson_by_id(lesson_id):
    lessons = load_all_lessons()
    for l in lessons:
        if l["id"] == lesson_id:
            return l
    return None

def get_platform_state(user_id=None):
    lessons = load_all_lessons()
    completed_tasks = get_completed_task_ids(user_id) if user_id else set()
    completed_lessons = get_completed_lesson_ids(user_id) if user_id else set()
    user_codes = get_user_task_codes(user_id) if user_id else {}
    task_status = get_task_status_map()
    
    lesson_statuses = []

    # Track-based unlocking: group lessons by track
    track_lessons = {}
    for lesson in lessons:
        track = lesson.get("track", "general")
        if track not in track_lessons:
            track_lessons[track] = []
        track_lessons[track].append(lesson)

    for track, t_lessons in track_lessons.items():
        for idx, lesson in enumerate(t_lessons):
            lid = lesson["id"]
            all_tasks = lesson.get("tasks", []) + lesson.get("cumulative_tasks", [])
            total_tasks_count = len(all_tasks)
            done_tasks_count = sum(1 for t in all_tasks if t["id"] in completed_tasks)
            
            is_completed = (total_tasks_count > 0 and done_tasks_count == total_tasks_count)
            if is_completed and user_id and lid not in completed_lessons:
                mark_lesson_done(user_id, lid)
                completed_lessons.add(lid)

            if idx == 0:
                unlocked = True
            else:
                prev_lesson = t_lessons[idx - 1]
                unlocked = prev_lesson["id"] in completed_lessons

            lesson_statuses.append({
                "id": lid,
                "track": track,
                "order": lesson.get("order", idx + 1),
                "title": lesson.get("title", ""),
                "category": lesson.get("category", "General"),
                "description": lesson.get("description", ""),
                "unlocked": unlocked,
                "completed": is_completed,
                "total_tasks": total_tasks_count,
                "completed_tasks": done_tasks_count,
                "is_open": task_status.get(lid, True)
            })

    avg_speed = get_user_avg_solve_seconds(user_id) if user_id else 0

    return {
        "lessons": lesson_statuses,
        "completed_tasks": list(completed_tasks),
        "completed_lessons": list(completed_lessons),
        "user_codes": user_codes,
        "task_status_map": task_status,
        "avg_speed_seconds": avg_speed
    }

def delete_task_or_lesson(target_id):
    """Deletes a lesson JSON file or removes a specific task from a lesson JSON file."""
    if not target_id:
        return {"success": False, "error": "المعرف مطلوب"}
    
    files = glob.glob(os.path.join(LESSONS_DIR, "*.json"))
    
    # 1. Check if target_id matches a lesson ID
    for filepath in files:
        try:
            with open(filepath, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
            if data.get("id") == target_id:
                os.remove(filepath)
                return {"success": True, "message": f"تم حذف الدرس بالكامل '{data.get('title')}' بنجاح!"}
        except Exception as e:
            print(f"Error checking {filepath}: {e}")

    # 2. Check if target_id matches a task ID inside any lesson
    for filepath in files:
        try:
            with open(filepath, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
            
            modified = False
            tasks = data.get("tasks", [])
            cum_tasks = data.get("cumulative_tasks", [])

            new_tasks = [t for t in tasks if t.get("id") != target_id]
            if len(new_tasks) < len(tasks):
                data["tasks"] = new_tasks
                modified = True

            new_cum_tasks = [t for t in cum_tasks if t.get("id") != target_id]
            if len(new_cum_tasks) < len(cum_tasks):
                data["cumulative_tasks"] = new_cum_tasks
                modified = True

            if modified:
                with open(filepath, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                return {"success": True, "message": f"تم حذف المهمة البرمجية (ID: {target_id}) بنجاح!"}
        except Exception as e:
            print(f"Error modifying {filepath}: {e}")

    return {"success": False, "error": "لم يتم العثور على الدرس أو المهمة المطلوبة"}

def execute_code_safely(code, timeout=4):
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
