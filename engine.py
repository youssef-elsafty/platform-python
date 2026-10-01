import os
import sys
import json
import glob
import re
import ast
import difflib
from runner import run_isolated_code
from db import (
    init_db, mark_task_done, mark_lesson_done,
    get_completed_task_ids, get_completed_lesson_ids, reset_user_progress,
    get_user_avg_solve_seconds, get_user_task_codes, get_task_status_map,
    get_user_task_overrides, get_separated_task_overrides
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
    all_overrides, user_overrides = get_separated_task_overrides(user_id)
    effective_status_map = dict(task_status)
    
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
                seq_unlocked = True
            else:
                prev_lesson = t_lessons[idx - 1]
                seq_unlocked = prev_lesson["id"] in completed_lessons

            # Determine explicit lesson-level states (None if not explicitly set)
            user_lesson_open = user_overrides.get(lid, None)
            if lid in all_overrides:
                global_lesson_open = all_overrides[lid]
            elif lid in task_status:
                global_lesson_open = task_status[lid]
            else:
                global_lesson_open = None

            tasks_open_map = {}
            any_task_explicitly_unlocked = False
            for t in all_tasks:
                tid = t["id"]
                if tid in user_overrides:
                    t_open = user_overrides[tid]
                    if t_open:
                        any_task_explicitly_unlocked = True
                elif user_lesson_open is not None:
                    t_open = user_lesson_open
                    if t_open:
                        any_task_explicitly_unlocked = True
                elif tid in all_overrides:
                    t_open = all_overrides[tid]
                    if t_open:
                        any_task_explicitly_unlocked = True
                elif tid in task_status:
                    t_open = task_status[tid]
                    if t_open:
                        any_task_explicitly_unlocked = True
                elif global_lesson_open is not None:
                    t_open = global_lesson_open
                    if t_open:
                        any_task_explicitly_unlocked = True
                else:
                    t_open = seq_unlocked

                tasks_open_map[tid] = t_open
                effective_status_map[tid] = t_open

            if total_tasks_count > 0:
                unlocked = any(tasks_open_map.values())
                lesson_is_open = unlocked
            else:
                if user_lesson_open is not None:
                    unlocked = user_lesson_open
                elif global_lesson_open is not None:
                    unlocked = global_lesson_open
                else:
                    unlocked = seq_unlocked
                lesson_is_open = unlocked

            effective_status_map[lid] = lesson_is_open

            lesson_statuses.append({
                "id": lid,
                "track": track,
                "order": lesson.get("order", idx + 1),
                "title": lesson.get("title", ""),
                "category": lesson.get("category", "General"),
                "description": lesson.get("description", ""),
                "unlocked": unlocked,
                "force_unlocked": any_task_explicitly_unlocked or (user_lesson_open is True) or (global_lesson_open is True),
                "completed": is_completed,
                "total_tasks": total_tasks_count,
                "completed_tasks": done_tasks_count,
                "is_open": lesson_is_open,
                "tasks_open_map": tasks_open_map
            })

    avg_speed = get_user_avg_solve_seconds(user_id) if user_id else 0
    task_overrides = get_user_task_overrides(user_id) if user_id else dict(all_overrides)

    return {
        "lessons": lesson_statuses,
        "completed_tasks": list(completed_tasks),
        "completed_lessons": list(completed_lessons),
        "user_codes": user_codes,
        "task_status_map": effective_status_map,
        "raw_task_status_map": task_status,
        "avg_speed_seconds": avg_speed,
        "task_overrides": task_overrides
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

def translate_python_error(stderr: str) -> str:
    """Translates common Python tracebacks and errors into friendly Arabic educational guidance."""
    if not stderr:
        return ""
    
    if "Security Sandbox" in stderr or "محاولة غير مسموح بها" in stderr:
        return "⛔ تنبيه أمني: حاول كودك استخدام موديولات أو دوال خطيرة محظورة في بيئة الساندبوكس."
    
    if "SyntaxError" in stderr:
        return "💡 خطأ في الصيغة (SyntaxError): تحقق من القواعد النحوية للكود، كإغلاق الأقواس () أو علامات التنصيص \"\" أو النقطتين الرأسيتين : بعد if/for."
    elif "IndentationError" in stderr:
        return "💡 خطأ في المسافات البادئة (IndentationError): في بايثون المسافات مهمة جداً! تأكد من محاذاة الأسطر تحت if أو for أو def بـ 4 مسافات."
    elif "NameError" in stderr:
        return "💡 اسم غير معروف (NameError): استخدمت متغيراً أو دالة لم تقم بتعريفها أو قمت بكتابة اسمها بشكل غير صحيح."
    elif "TypeError" in stderr:
        return "💡 خطأ في نوع البيانات (TypeError): حاولت دمج أو قراءة أنواع بيانات غير متوافقة (مثلاً جمع نص Str مع رقم Int)."
    elif "ZeroDivisionError" in stderr:
        return "💡 القسمة على صفر (ZeroDivisionError): لا يمكن القسمة على الصفر برمجياً. تحقق من قيمة القاسم."
    elif "IndexError" in stderr:
        return "💡 خطأ في المؤشر (IndexError): حاولت الوصول لعنصر في قائمة index خارج نطاق العناصر الموجودة."
    elif "KeyError" in stderr:
        return "💡 المفتاح غير موجود (KeyError): حاولت الوصول لمفتاح key غير موجود داخل القاموس dictionary."
    elif "ValueError" in stderr:
        return "💡 خطأ في القيمة (ValueError): القيمة الممررة للدالة غير مناسبة (مثلاً تحويل نص حرفي إلى int)."
    elif "AttributeError" in stderr:
        return "💡 خاصية غير موجودة (AttributeError): الدالة أو الخاصية التي استدعيتها غير موجودة على هذا النوع من البيانات."
    elif "Timeout" in stderr or "انتهى الوقت" in stderr:
        return "⏱️ انتهى وقت التنفيذ (Timeout): قد يحتوي الكود على حلقة تكرارية لانهائية (while loop بدون شرط توقف)."

    return "تنبيه: تحقق من رسالة الخطأ وراجع خطوات الكود خطوة بخطوة."

def execute_code_safely(code, timeout=4, stdin_inputs=None):
    return run_isolated_code(code, timeout=timeout, stdin_inputs=stdin_inputs)


def normalize_text(text: str) -> str:
    """
    Cleans and normalizes Arabic and English text:
    - Lowercases English text
    - Normalizes Arabic variations (أ, إ, آ -> ا), (ة -> ه), (ى -> ي)
    - Removes punctuation and symbols
    - Normalizes multi-spaces to single space
    """
    if not text:
        return ""
    text = str(text).lower()

    # Arabic normalizations
    text = re.sub(r"[أإآ]", "ا", text)
    text = re.sub(r"ة", "ه", text)
    text = re.sub(r"ى", "ي", text)

    # Strip common punctuation: quotes, commas, dots, colons, brackets, etc.
    text = re.sub(r"[\.,;:!\?\"\'\(\)\[\]\{\}«»\-_\/\\]", " ", text)

    # Normalize multiple whitespace to single space
    text = re.sub(r"\s+", " ", text).strip()
    return text


SYNONYM_GROUPS = [
    {"passed", "pass", "ناجح", "نجاح", "succeeded", "success"},
    {"failed", "fail", "راسب", "رسوب", "failure"},
    {"true", "صح", "صحيح", "yes", "نعم"},
    {"false", "خطا", "خطأ", "no", "لا"},
    {"greater", "bigger", "larger", "اكبر", "أكبر"},
    {"smaller", "less", "lower", "اصغر", "أصغر"},
    {"safe", "امن", "آمن"},
    {"danger", "خطر"},
    {"access granted", "granted", "allowed", "مسموح", "تم الدخول"},
    {"access denied", "denied", "rejected", "مرفوض", "غير مسموح"},
]


def get_synonyms(term: str) -> set:
    norm = normalize_text(term)
    res = {norm}
    for grp in SYNONYM_GROUPS:
        norm_grp = {normalize_text(x) for x in grp}
        if norm in norm_grp:
            res |= norm_grp
    return res


def get_contradictory_terms(term: str) -> set:
    """Returns terms that mean the opposite branch (e.g. Passed vs Failed) to prevent print('Passed Failed') cheats."""
    opposites = [
        ({"passed", "pass", "ناجح", "نجاح", "succeeded", "success"}, {"failed", "fail", "راسب", "رسوب", "failure"}),
        ({"true", "صح", "صحيح", "yes", "نعم"}, {"false", "خطا", "خطأ", "no", "لا"}),
        ({"greater", "bigger", "larger", "اكبر"}, {"smaller", "less", "lower", "اصغر"}),
        ({"safe", "امن"}, {"danger", "خطر"}),
        ({"access granted", "granted", "allowed"}, {"access denied", "denied", "rejected"}),
    ]
    norm = normalize_text(term)
    for side_a, side_b in opposites:
        na = {normalize_text(x) for x in side_a}
        nb = {normalize_text(x) for x in side_b}
        if norm in na:
            return nb
        if norm in nb:
            return na
    return set()


def parse_accepted_alternatives(expected_field) -> list:
    """
    Splits string by '|' or ',' or newline to extract list of acceptable answers/synonyms.
    e.g. 'list | قائمة | مصفوفة | array' -> ['list', 'قائمة', 'مصفوفة', 'array']
    """
    if isinstance(expected_field, list):
        return [str(x).strip() for x in expected_field if str(x).strip()]
    raw = str(expected_field or "")
    if "|" in raw:
        items = raw.split("|")
    elif "," in raw and not any(k in raw for k in ("def ", "import ", "print", "[", "{", "Hello,")):
        items = raw.split(",")
    elif "\n" in raw and not any(k in raw for k in ("def ", "import ", "print")):
        items = [raw]  # Keep multi-line expected output intact as primary, and individual lines handled in compare_outputs
    else:
        items = [raw]
    return [x.strip() for x in items if x.strip()]


def looks_like_python_code(text: str) -> bool:
    """Detects whether an expected answer string is actually a Python code snippet."""
    if not text:
        return False
    s = str(text).strip()
    code_patterns = [
        r"\bprint\s*\(",
        r"\bdef\s+\w+\s*\(",
        r"\bif\s+.+:",
        r"\bfor\s+\w+\s+in\s+",
        r"\bwhile\s+.+:",
        r"\belse\s*:",
        r"\belif\s+.+:",
        r"^\s*[a-zA-Z_]\w*\s*=\s*.+"
    ]
    matches = sum(1 for p in code_patterns if re.search(p, s, re.MULTILINE))
    return matches >= 1 and ("print(" in s or "return " in s or ":" in s)


def heal_common_syntax_slips(code_str: str) -> str:
    """
    Automatically heals minor beginner syntax slips without altering code logic:
    - Smart quotes (“”‘’) -> standard quotes (""'')
    - Spaced comparison operators ('> =', '< =', '= =', '! =') -> ('>=', '<=', '==', '!=')
    - Unclosed parentheses at the end of a line, e.g. 'score = int(input("enter number")' -> adds ')'
    - Missing colon ':' at the end of if/elif/else/for/while/def/class headers
    """
    s = str(code_str or "").strip()
    if not s:
        return ""
    try:
        ast.parse(s)
        return s
    except SyntaxError:
        pass

    healed = s.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    healed = re.sub(r">\s+=", ">=", healed)
    healed = re.sub(r"<\s+=", "<=", healed)
    healed = re.sub(r"!\s+=", "!=", healed)
    healed = re.sub(r"=\s+=", "==", healed)

    fixed_lines = []
    for line in healed.split("\n"):
        stripped = line.rstrip()
        if not stripped or stripped.lstrip().startswith("#"):
            fixed_lines.append(line)
            continue

        # Balance unclosed '(' on single lines such as: score = int(input("enter grade")
        open_parens = stripped.count("(") - stripped.count(")")
        if open_parens > 0 and not stripped.endswith((",", "\\")):
            stripped = stripped + (")" * open_parens)

        # Add missing ':' on control flow headers
        if re.match(r"^\s*(?:if\s+.+|elif\s+.+|else|for\s+.+\s+in\s+.+|while\s+.+|def\s+\w+\s*\(.*\)|class\s+\w+(?:\(.*\))?)\s*$", stripped):
            if not stripped.endswith(":"):
                stripped = stripped + ":"

        fixed_lines.append(stripped)

    candidate = "\n".join(fixed_lines)
    try:
        ast.parse(candidate)
        return candidate
    except SyntaxError:
        return normalize_collapsed_python_code(candidate)


def normalize_collapsed_python_code(code_str: str) -> str:
    """
    Reconstructs valid multi-line indented Python code even if it was pasted into
    a single-line input box (where newlines were collapsed into spaces).
    """
    s = str(code_str or "").strip()
    if not s:
        return ""
    try:
        ast.parse(s)
        return s
    except SyntaxError:
        pass

    reconstructed = re.sub(r"\s+(if\s+|elif\s+|else\s*:|for\s+|while\s+|def\s+)", r"\n\1", s)
    lines = []
    indent_level = 0
    for raw_line in reconstructed.split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        if re.match(r"^(elif\s+|else\s*:)", line):
            indent_level = max(0, indent_level - 1)

        m = re.match(r"^((?:if|elif|else|for|while|def)\b[^:]*:)\s*(.+)$", line)
        if m:
            header, body = m.group(1).strip(), m.group(2).strip()
            lines.append(("    " * indent_level) + header)
            indent_level += 1
            sub_stmts = re.split(r"\s{2,}(?=[a-zA-Z_]\w*\s*=|print\s*\(|return\b)", body)
            for stmt in sub_stmts:
                lines.append(("    " * indent_level) + stmt.strip())
        else:
            lines.append(("    " * indent_level) + line)
            if line.endswith(":"):
                indent_level += 1

    candidate = "\n".join(lines)
    try:
        ast.parse(candidate)
        return candidate
    except SyntaxError:
        return s


def extract_top_level_assignments(code_str: str) -> dict:
    """Extracts top-level variable assignments {var_name: value_source_str} from Python code."""
    res = {}
    if not code_str or not code_str.strip():
        return res
    try:
        healed = heal_common_syntax_slips(code_str)
        tree = ast.parse(healed)
        for node in tree.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                var_name = node.targets[0].id
                val_src = ast.get_source_segment(healed, node.value)
                if val_src is not None:
                    res[var_name] = val_src.strip()
    except Exception:
        pass
    return res


def _strip_outer_quotes(val_src: str) -> str:
    s = str(val_src or "").strip()
    if len(s) >= 2 and ((s[0] == '"' and s[-1] == '"') or (s[0] == "'" and s[-1] == "'")):
        return s[1:-1]
    return s


def override_code_variables(code: str, setup_code: str, starter_code: str = "") -> str:
    """
    Injects test case variable values (from setup_code, e.g., 'score = 30') into student or reference code.
    Works seamlessly across all student coding styles:
    - Same variable name ('score = 75')
    - Renamed variable with same or different initial value ('my_grade = 20')
    - Dynamic input() calls ('score = int(input("enter number"))' or 'x = int(input())')
    - Function arguments ('print(check(75))')
    """
    healed_code = heal_common_syntax_slips(code)
    if not setup_code or not setup_code.strip():
        return healed_code

    overrides = extract_top_level_assignments(setup_code)
    if not overrides:
        return setup_code + "\n" + healed_code

    starter_defaults = extract_top_level_assignments(starter_code)
    student_assigns = extract_top_level_assignments(healed_code)

    modified_lines = healed_code.split("\n")
    replaced_vars = set()
    stdin_vals = [_strip_outer_quotes(v) for v in overrides.values()]

    for var_name, new_val_src in overrides.items():
        # 1. Direct variable name match (e.g. score = ...)
        pattern = re.compile(rf"^(\s*{re.escape(var_name)}\s*=\s*)(.+)$")
        for i, line in enumerate(modified_lines):
            if pattern.match(line):
                modified_lines[i] = f"{var_name} = {new_val_src}"
                replaced_vars.add(var_name)
                break

        # 2. If student renamed the variable, match by starter value (e.g. x = 75)
        if var_name not in replaced_vars and var_name in starter_defaults:
            orig_val = starter_defaults[var_name].strip()
            val_pattern = re.compile(rf"^(\s*[a-zA-Z_]\w*\s*=\s*){re.escape(orig_val)}(\s*(?:#.*)?)$")
            for i, line in enumerate(modified_lines):
                m = val_pattern.match(line)
                if m:
                    modified_lines[i] = f"{m.group(1)}{new_val_src}{m.group(2)}"
                    replaced_vars.add(var_name)
                    break

        # 3. If student used input() with a different variable name (e.g. x = int(input("...")))
        if var_name not in replaced_vars:
            inp_pattern = re.compile(rf"^(\s*[a-zA-Z_]\w*\s*=\s*)(?:int|float|str|eval)?\s*\(?\s*input\s*\(.*$")
            for i, line in enumerate(modified_lines):
                m = inp_pattern.match(line)
                if m:
                    modified_lines[i] = f"{m.group(1)}{new_val_src}"
                    replaced_vars.add(var_name)
                    break

        # 4. If student renamed the variable AND chose a different test constant (e.g. x = 20 instead of score = 75)
        if var_name not in replaced_vars and len(overrides) == 1 and len(student_assigns) >= 1:
            first_stu_var = next(iter(student_assigns.keys()))
            stu_pattern = re.compile(rf"^(\s*{re.escape(first_stu_var)}\s*=\s*)(.+)$")
            for i, line in enumerate(modified_lines):
                if stu_pattern.match(line):
                    modified_lines[i] = f"{first_stu_var} = {new_val_src}"
                    replaced_vars.add(var_name)
                    break

        # 5. Fallback if student used literal inside a function call, e.g. check(75)
        if var_name not in replaced_vars and var_name in starter_defaults:
            orig_val = starter_defaults[var_name].strip()
            if orig_val:
                lit_pattern = re.compile(rf"\b{re.escape(orig_val)}\b")
                new_text, count = lit_pattern.subn(new_val_src, "\n".join(modified_lines), count=1)
                if count > 0:
                    modified_lines = new_text.split("\n")
                    replaced_vars.add(var_name)

    remaining_setup = [f"{k} = {v}" for k, v in overrides.items() if k not in replaced_vars]
    result_code = "\n".join(modified_lines)
    if remaining_setup:
        result_code = "\n".join(remaining_setup) + "\n" + result_code

    # Also bind input() queue in case input() is called inside expressions/functions
    if "input" in result_code and stdin_vals:
        preamble = f"input = (lambda _q={repr(stdin_vals)}: lambda _p='': str(_q.pop(0)) if _q else {repr(stdin_vals[-1])})()\n"
        result_code = preamble + result_code

    return result_code


def execute_student_code_smart(code: str, setup_code: str = "", starter_code: str = "", reference_code: str = "") -> dict:
    """
    Runs student code with smart behavioral support:
    1. Heals minor syntax slips (like unclosed paren in int(input("")) or '> =').
    2. Injects setup_code (or starter/reference defaults when student uses input() or custom test values).
    3. If student computed the result in a variable or function without calling print(), automatically
       evaluates and prints the computed variable or function return value!
    """
    healed = heal_common_syntax_slips(code)
    effective_setup = str(setup_code or "").strip()

    # If no explicit setup_code on TC1, check if starter_code or reference_code has initial input variables
    if not effective_setup:
        defaults = extract_top_level_assignments(starter_code) or extract_top_level_assignments(reference_code)
        if defaults and ("input" in healed or not set(defaults.keys()).issubset(set(extract_top_level_assignments(healed).keys()))):
            effective_setup = "\n".join(f"{k} = {v}" for k, v in defaults.items())
        elif defaults:
            # Even if student used same variable name, if they changed its initial test value (e.g. score = 20 instead of 75)
            # while the code has conditionals/loops, test with the starter default so TC1 matches TC1's expected output!
            stu_assigns = extract_top_level_assignments(healed)
            try:
                tree = ast.parse(healed)
                has_logic = any(isinstance(n, (ast.If, ast.IfExp, ast.For, ast.While, ast.FunctionDef)) for n in ast.walk(tree))
            except Exception:
                has_logic = False
            if has_logic and any(stu_assigns.get(k) != v for k, v in defaults.items() if k in stu_assigns):
                effective_setup = "\n".join(f"{k} = {v}" for k, v in defaults.items())

    code_to_run = override_code_variables(healed, effective_setup, starter_code) if effective_setup else healed
    res = execute_code_safely(code_to_run)

    if not res["success"] or res["stdout"].strip():
        return res

    # Smart Fallback A: Student wrote a function (def ...) but didn't call print(func(...))
    try:
        tree = ast.parse(code_to_run)
        func_defs = [n for n in tree.body if isinstance(n, ast.FunctionDef)]
        if func_defs:
            fn = func_defs[-1]
            defaults = extract_top_level_assignments(effective_setup or starter_code or reference_code)
            args_str = ", ".join(defaults.values()) if defaults and len(fn.args.args) == len(defaults) else ""
            if not args_str and len(fn.args.args) == 1:
                args_str = "75"
            call_code = code_to_run + f"\n_res = {fn.name}({args_str})\nif _res is not None:\n    print(_res)\n"
            call_res = execute_code_safely(call_code)
            if call_res["success"] and call_res["stdout"].strip():
                return call_res

        # Smart Fallback B: Student computed answer in a variable (e.g. count += 1 or total = x + y) but forgot print()
        setup_vars = set(extract_top_level_assignments(effective_setup or starter_code).keys())
        assigned_vars = []
        for n in ast.walk(tree):
            if isinstance(n, ast.Assign):
                for t in n.targets:
                    if isinstance(t, ast.Name) and t.id not in setup_vars and not t.id.startswith("_"):
                        assigned_vars.append(t.id)
            elif isinstance(n, ast.AugAssign) and isinstance(n.target, ast.Name):
                assigned_vars.append(n.target.id)
        if assigned_vars:
            last_var = assigned_vars[-1]
            var_res = execute_code_safely(code_to_run + f"\nprint({last_var})\n")
            if var_res["success"] and var_res["stdout"].strip():
                return var_res
    except Exception:
        pass

    return res


def resolve_expected_output(expected_raw: str, reference_code: str = "", setup_code: str = "", starter_code: str = "") -> str:
    """
    Determines the true expected output for a test case:
    - If explicit reference_code is provided and setup_code is used, runs the reference_code with setup_code.
    - If expected_raw itself is Python code (e.g. pasted solution code), normalizes and runs it to extract stdout!
    - Otherwise returns expected_raw as-is.
    """
    raw = str(expected_raw or "").strip()
    ref = str(reference_code or "").strip()

    if ref and (setup_code or not raw or looks_like_python_code(raw)):
        norm_ref = heal_common_syntax_slips(ref)
        code_to_run = override_code_variables(norm_ref, setup_code, starter_code) if setup_code else norm_ref
        res = execute_code_safely(code_to_run)
        if res["success"] and res["stdout"].strip():
            return res["stdout"].strip()

    if looks_like_python_code(raw):
        norm_code = heal_common_syntax_slips(raw)
        code_to_run = override_code_variables(norm_code, setup_code, starter_code) if setup_code else norm_code
        res = execute_code_safely(code_to_run)
        if res["success"] and res["stdout"].strip():
            return res["stdout"].strip()

    return raw


def _numbers_in_text(s: str) -> list:
    nums = []
    for m in re.findall(r"-?\d+(?:\.\d+)?", str(s)):
        try:
            nums.append(float(m))
        except ValueError:
            pass
    return nums


def compare_outputs(actual_output: str, expected_resolved: str, tc_type: str = "exact_output") -> bool:
    """
    Compares student code execution output against expected output flexibly:
    - Ignores trailing spaces, quote differences, and minor casing/formatting variations
    - Supports multiple accepted alternatives separated by '|'
    - Supports semantic synonyms (e.g. 'Pass' == 'Passed' == 'ناجح')
    - Supports float/int numeric equivalence (e.g. '84.0' == '84')
    - Supports extra descriptive labels in print() (e.g. 'Result: Passed' or 'Average: 84')
    """
    actual_clean = str(actual_output or "").strip()
    expected_clean = str(expected_resolved or "").strip()
    if not expected_clean:
        return bool(actual_clean)

    norm_actual = normalize_text(actual_clean)
    alts = parse_accepted_alternatives(expected_clean)

    # Expand alternatives with built-in synonym groups (e.g. Passed -> Pass, ناجح)
    expanded_alts = []
    for a in alts:
        expanded_alts.append(a)
        for syn in get_synonyms(a):
            if syn not in expanded_alts:
                expanded_alts.append(syn)

    norm_alts = [normalize_text(a) for a in expanded_alts if a]

    if tc_type == "contains":
        return any(a in actual_clean or na in norm_actual for a, na in zip(expanded_alts, norm_alts))

    # 1. Direct or normalized match
    if any(actual_clean.lower() == a.lower() or norm_actual == na for a, na in zip(expanded_alts, norm_alts)):
        return True

    # 2. Numeric equivalence (e.g., 84.0 vs 84, or multi-line numbers 84.0\n95 vs 84\n95)
    actual_nums = _numbers_in_text(actual_clean)
    for a in alts:
        exp_nums = _numbers_in_text(a)
        # If expected is purely numeric (one or more numbers) and student output has the exact same numbers
        if exp_nums and len(re.sub(r"[-?\d\.\s,;\[\]\(\)]", "", a)) == 0:
            if actual_nums == exp_nums:
                return True

    # 3. Descriptive label containment (e.g. student printed "Status: Passed" when expected is "Passed")
    actual_words = set(norm_actual.split())
    for a, na in zip(expanded_alts, norm_alts):
        if not na:
            continue
        contradictions = get_contradictory_terms(na)
        has_contradiction = any(c in actual_words or c in norm_actual for c in contradictions)
        if not has_contradiction and (na in actual_words or (len(na) >= 3 and na in norm_actual)):
            return True

    # 4. Fuzzy similarity match for minor spelling differences
    if len(norm_actual) >= 3:
        if any(difflib.SequenceMatcher(None, norm_actual, na).ratio() >= 0.82 for na in norm_alts if na):
            return True

    return False


def infer_spec_from_instruction(instruction: str, starter_code: str = "") -> dict:
    """
    Model-Free Task Analyzer:
    Automatically extracts expected behavior, conditions, or test cases from the Arabic/English
    instruction and starter_code when the Admin does not specify a rigid model!
    """
    inst = str(instruction or "").strip()
    starter_vars = extract_top_level_assignments(starter_code)

    # Check if instruction describes a conditional branch (e.g. score >= 50 -> Passed else Failed)
    cond_match = re.search(r"([a-zA-Z_]\w*)\s*(>=|<=|>|<|==)\s*(\d+(?:\.\d+)?)", inst)
    if cond_match:
        var_name, op, thresh_str = cond_match.group(1), cond_match.group(2), cond_match.group(3)
        thresh = float(thresh_str) if "." in thresh_str else int(thresh_str)
        # Look for English tokens like Passed / Failed or Greater / Smaller
        eng_words = [
            w for w in re.findall(r"\b[A-Z][a-zA-Z]+\b", inst)
            if w.lower() not in {var_name.lower(), "python", "true", "false", "if", "else", "elif", "print", "input", "int", "str", "float"}
        ]
        unique_words = []
        for w in eng_words:
            if w not in unique_words:
                unique_words.append(w)
        if len(unique_words) >= 2:
            true_out, false_out = unique_words[0], unique_words[1]
            if op in (">=", ">"):
                val_true, val_false = thresh + 25, max(0, thresh - 20)
            elif op in ("<=", "<"):
                val_true, val_false = max(0, thresh - 20), thresh + 25
            else:
                val_true, val_false = thresh, thresh + 10
            return {
                "mode": "conditional",
                "test_cases": [
                    {"type": "exact_output", "setup_code": f"{var_name} = {val_true}", "expected": true_out},
                    {"type": "exact_output", "setup_code": f"{var_name} = {val_false}", "expected": false_out},
                ]
            }

    return {
        "mode": "smart_auto",
        "test_cases": [{"type": "smart_auto", "expected": ""}]
    }


def evaluate_smart_open_task(task: dict, clean_sub: str, run_result: dict) -> dict:
    """
    Evaluates a task in Model-Free / Open Smart Mode when no rigid expected output was locked:
    - Verifies the student's code is valid Python and executes without runtime errors.
    - Checks that the student's code implements the core constructs mentioned in the instruction
      (e.g. conditional if/else, loop for/while, function def, class, or output print).
    - Rejects empty/comment-only or trivial no-op submissions.
    """
    healed = heal_common_syntax_slips(clean_sub)
    try:
        tree = ast.parse(healed)
    except SyntaxError as se:
        return {
            "passed": False,
            "output": run_result.get("stdout", ""),
            "error": str(se),
            "feedback": "يوجد خطأ في صياغة الكود (SyntaxError). يرجى مراجعة الأقواس وعلامات التنصيص والنقطتين (:)."
        }

    stmts = [n for n in tree.body if not isinstance(n, ast.Pass) and not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))]
    if not stmts:
        return {
            "passed": False,
            "output": "",
            "error": "",
            "feedback": "الكود فارغ أو لا يحتوي على أوامر برمجية فعلية."
        }

    inst = str(task.get("instruction", "")).lower()
    starter = str(task.get("starter_code", "")).strip()
    if starter and healed.strip() == starter:
        return {
            "passed": False,
            "output": run_result.get("stdout", ""),
            "error": "",
            "feedback": "لم تقم بكتابة الحل بعد (الكود مطابق لكود البداية فقط)."
        }

    # Check structural alignment with prompt keywords if explicitly requested
    if ("class " in inst or "كلاس" in inst) and not any(isinstance(n, ast.ClassDef) for n in ast.walk(tree)):
        return {
            "passed": False,
            "output": run_result.get("stdout", ""),
            "error": "",
            "feedback": "💡 المطلوب في السؤال يتضمن تعريف كلاس (class)، تأكد من استخدام كلمة class في حلك."
        }

    if any(w in inst for w in ("if ", "شرط", "إذا", "اذا", "لو ")) and not any(isinstance(n, (ast.If, ast.IfExp, ast.Match, ast.Compare)) for n in ast.walk(tree)):
        return {
            "passed": False,
            "output": run_result.get("stdout", ""),
            "error": "",
            "feedback": "💡 المطلوب في السؤال يتضمن التحقق بشرط (if / else)، تأكد من كتابة الشرط البرمجي بدل طباعة نص ثابت."
        }

    # If the code has conditionals, verify both branches execute cleanly without errors
    if any(isinstance(n, (ast.If, ast.IfExp)) for n in ast.walk(tree)):
        out_high = execute_student_code_smart(healed, setup_code="score = 85", starter_code=starter)
        out_low = execute_student_code_smart(healed, setup_code="score = 25", starter_code=starter)
        if out_high["success"] and out_low["success"]:
            if out_high["stdout"].strip() and out_low["stdout"].strip() and out_high["stdout"].strip() != out_low["stdout"].strip():
                return {
                    "passed": True,
                    "output": out_high["stdout"].strip(),
                    "error": "",
                    "feedback": "أحسنت! تم فحص منطق الكود وتجربته على أكثر من قيمة بنجاح (تصحيح ذكي حر بدون التقيد بمودل ثابت) 🎉"
                }

    actual_out = run_result.get("stdout", "").strip()
    return {
        "passed": True,
        "output": actual_out,
        "error": "",
        "feedback": "أحسنت! الكود سليم برمجياً ونفّذ المطلوب بنجاح (تصحيح ذكي مرن يقبل أي طريقة حل صحيحة) 🎉"
    }


def evaluate_task(task, submitted_code):
    """
    Smart Universal Evaluator (Model-Free & Multi-Way Behavioral Engine):
    Supports:
    1. Any valid Python solution method:
       - Using input() (e.g. score = int(input("enter number")))
       - Using any variable names or initial test values (e.g. x = 30 instead of score = 75)
       - Using functions (def), ternary expressions, reversed conditions, loops, or classes
       - Minor syntax slips (like unclosed paren in int(input("")) or '> =') healed automatically
       - Synonym outputs ('Pass' vs 'Passed', '84.0' vs '84', descriptive labels in print)
    2. Model-Free Tasks:
       - If the Admin creates a task without a rigid model (no reference_code or expected_output),
         or writes branch alternatives like 'Passed | Failed', the engine dynamically tests the
         student's logic across multiple inputs and accepts any correct implementation!
    """
    clean_sub = str(submitted_code or "").strip()
    if not clean_sub:
        return {
            "passed": False,
            "output": "",
            "error": "لم يتم إدخال أي إجابة.",
            "feedback": "يرجى كتابة الإجابة أو الكود المطلوب أولاً."
        }

    q_type = task.get("type", "lesson_task")
    test_cases = list(task.get("test_cases", []))
    starter_code = task.get("starter_code", "")
    reference_code = task.get("reference_code", "")
    instruction = task.get("instruction", "")

    # Check if this task requires executing Python code
    is_code_task = (
        q_type in ("lesson_task", "cumulative_task", "code") or
        bool(starter_code and starter_code.strip() != "# اكتب الكود هنا") or
        bool(reference_code) or
        any(tc.get("type") in ("exact_output", "stdout", "code_behavior", "smart_auto") for tc in test_cases) or
        any(looks_like_python_code(tc.get("expected", "")) for tc in test_cases) or
        any(k in clean_sub for k in ("def ", "print", "input", "import ", "for ", "while ", "return ", "if ", "="))
    )

    # -------------------------------------------------------------
    # CASE A: Conceptual / Short Text Answer (Non-executing)
    # -------------------------------------------------------------
    if not is_code_task:
        norm_student = normalize_text(clean_sub)
        alternatives = []
        keywords = []

        for tc in test_cases:
            exp = tc.get("expected", "")
            tc_type = tc.get("type", "flexible")
            if tc_type == "keywords" or tc.get("keywords"):
                keywords.extend(parse_accepted_alternatives(tc.get("keywords", exp)))
            else:
                alternatives.extend(parse_accepted_alternatives(exp))

        if "expected_output" in task:
            alternatives.extend(parse_accepted_alternatives(task["expected_output"]))
        if "accepted_answers" in task:
            alternatives.extend(parse_accepted_alternatives(task["accepted_answers"]))

        # If no rigid model answer was set for this text question, accept any non-empty thoughtful answer
        if not alternatives and not keywords:
            if len(norm_student) >= 2:
                return {
                    "passed": True,
                    "output": clean_sub,
                    "error": "",
                    "feedback": "تم قبول إجابتك بنجاح ✓"
                }

        expanded_alts = []
        for a in alternatives:
            if a:
                expanded_alts.append(a)
                for syn in get_synonyms(a):
                    expanded_alts.append(syn)

        norm_alts = [normalize_text(a) for a in expanded_alts if a]
        norm_keywords = [normalize_text(k) for k in keywords if k]

        for alt in norm_alts:
            if norm_student == alt:
                return {
                    "passed": True,
                    "output": clean_sub,
                    "error": "",
                    "feedback": "إجابة صحيحة ونموذجية تماماً! أحسنت 🎉"
                }

        for alt in norm_alts:
            if len(alt) >= 2 and (alt in norm_student or norm_student in alt):
                return {
                    "passed": True,
                    "output": clean_sub,
                    "error": "",
                    "feedback": "إجابة مقبولة وصحيحة! تم التعرف على المفهوم بنجاح ✓"
                }

        if norm_keywords:
            matched_kw = [kw for kw in norm_keywords if kw in norm_student]
            if len(matched_kw) == len(norm_keywords) or (len(matched_kw) >= 1 and len(norm_keywords) <= 2):
                return {
                    "passed": True,
                    "output": clean_sub,
                    "error": "",
                    "feedback": f"إجابة ممتازة! تضمنت الكلمات المفتاحية المطلوبة ({', '.join(matched_kw)}) 🚀"
                }

        for alt in norm_alts:
            sim = difflib.SequenceMatcher(None, norm_student, alt).ratio()
            if sim >= 0.78:
                return {
                    "passed": True,
                    "output": clean_sub,
                    "error": "",
                    "feedback": "إجابة صحيحة (تم قبولها مع مراعاة الفروق الإملائية البسيطة) ✓"
                }

        expected_sample = alternatives[0] if alternatives else "المطلوب"
        return {
            "passed": False,
            "output": clean_sub,
            "error": "",
            "feedback": f"المفهوم المتوقع يدور حول: {expected_sample}\nإجابتك: {clean_sub}"
        }

    # -------------------------------------------------------------
    # CASE B: Python Code Execution Task (Model-Free & Multi-Way)
    # -------------------------------------------------------------
    healed_sub = heal_common_syntax_slips(clean_sub)

    # Detect if any test case has Python reference code inside 'expected'
    inferred_ref_code = reference_code
    if not inferred_ref_code:
        for tc in test_cases:
            exp_str = str(tc.get("expected", "")).strip()
            if looks_like_python_code(exp_str):
                inferred_ref_code = heal_common_syntax_slips(exp_str)
                break

    # First run the student's code with smart input/variable/function support
    first_tc_setup = str(test_cases[0].get("setup_code", "") or test_cases[0].get("input", "")).strip() if test_cases else ""
    run_result = execute_student_code_smart(
        healed_sub,
        setup_code=first_tc_setup,
        starter_code=starter_code,
        reference_code=inferred_ref_code
    )

    if not run_result["success"] and run_result["exit_code"] != 0:
        friendly = translate_python_error(run_result["stderr"])
        return {
            "passed": False,
            "output": run_result["stdout"],
            "error": run_result["stderr"],
            "feedback": f"حدث خطأ أثناء تشغيل الكود.\n{friendly}"
        }

    # Check if this task has NO rigid model (empty test_cases or smart_auto type)
    has_non_empty_expected = any(str(tc.get("expected", "")).strip() for tc in test_cases if tc.get("type") != "smart_auto")
    if not test_cases or (not has_non_empty_expected and not inferred_ref_code):
        inferred_spec = infer_spec_from_instruction(instruction, starter_code)
        if inferred_spec["mode"] == "conditional":
            test_cases = inferred_spec["test_cases"]
        else:
            return evaluate_smart_open_task(task, healed_sub, run_result)

    actual_output = run_result["stdout"].strip()
    all_passed = True
    feedback = ""

    for idx, tc in enumerate(test_cases):
        tc_type = tc.get("type", "exact_output")
        if tc_type == "smart_auto" and not str(tc.get("expected", "")).strip() and not inferred_ref_code:
            return evaluate_smart_open_task(task, healed_sub, run_result)

        setup_code = str(tc.get("setup_code", "") or tc.get("input", "")).strip()
        expected_raw = str(tc.get("expected", "")).strip()

        expected_resolved = resolve_expected_output(
            expected_raw=expected_raw,
            reference_code=inferred_ref_code,
            setup_code=setup_code,
            starter_code=starter_code
        )

        if idx == 0 and not setup_code:
            tc_actual = actual_output
        else:
            tc_run = execute_student_code_smart(
                healed_sub,
                setup_code=setup_code,
                starter_code=starter_code,
                reference_code=inferred_ref_code
            )
            if not tc_run["success"] and tc_run["exit_code"] != 0:
                all_passed = False
                friendly = translate_python_error(tc_run["stderr"])
                feedback = f"حدث خطأ عند اختبار الكود بحالة الاختبار ({setup_code}):\n{friendly}"
                break
            tc_actual = tc_run["stdout"].strip()

        if not compare_outputs(tc_actual, expected_resolved, tc_type):
            all_passed = False
            alts = parse_accepted_alternatives(expected_resolved)
            shown_expected = alts[0] if alts else expected_resolved
            if setup_code:
                feedback = (
                    f"الكود نجح في الحالة الأولى لكنه لم يعطِ الناتج الصحيح عند تجربة ({setup_code}).\n"
                    f"المتوقع في هذه الحالة:\n{shown_expected}\n\nالمُخرج من كودك:\n{tc_actual}"
                )
            else:
                feedback = f"المخرجات غير مطابقة للمطلوب.\nالمتوقع:\n{shown_expected}\n\nالمُخرج من كودك:\n{tc_actual}"
            break

    # Automatic Behavioral Verification against Reference Code (if reference code has conditionals/variables
    # and only 1 static test case was defined, test with mutated input values so any valid code style passes
    # while hardcoded print() cheats are caught!)
    if all_passed and inferred_ref_code and len(test_cases) <= 1:
        try:
            ref_tree = ast.parse(inferred_ref_code)
            has_branch_or_op = any(
                isinstance(n, (ast.If, ast.IfExp, ast.For, ast.While, ast.Compare, ast.BinOp))
                for n in ast.walk(ref_tree)
            )
            if has_branch_or_op:
                candidate_vars = {}
                for n in ref_tree.body:
                    if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
                        if isinstance(n.value, ast.Constant) and isinstance(n.value.value, (int, float)) and not isinstance(n.value.value, bool):
                            candidate_vars[n.targets[0].id] = n.value.value
                comp_nums = [
                    n.value for n in ast.walk(ref_tree)
                    if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)) and not isinstance(n.value, bool)
                ]
                for var_name, orig_val in list(candidate_vars.items())[:1]:
                    test_vals = {0, orig_val + 15, max(0, orig_val - 50)}
                    for cn in comp_nums:
                        test_vals.add(cn - 10)
                        test_vals.add(cn + 10)
                    test_vals.discard(orig_val)
                    for tv in list(test_vals)[:2]:
                        probe_setup = f"{var_name} = {tv}"
                        ref_probe = execute_code_safely(override_code_variables(inferred_ref_code, probe_setup, starter_code))
                        if not ref_probe["success"] or not ref_probe["stdout"].strip():
                            continue
                        ref_out = ref_probe["stdout"].strip()
                        stu_probe = execute_student_code_smart(
                            healed_sub,
                            setup_code=probe_setup,
                            starter_code=starter_code,
                            reference_code=inferred_ref_code
                        )
                        if not stu_probe["success"] or not compare_outputs(stu_probe["stdout"].strip(), ref_out, "exact_output"):
                            all_passed = False
                            feedback = (
                                f"تنبيه ذكي: كودك طبع الناتج لحالة ({var_name} = {orig_val}) فقط، "
                                f"لكنه لم يعمل بشكل صحيح عند تغير القيمة إلى ({probe_setup})!\n"
                                f"المتوقع عند ({probe_setup}): {ref_out}\n"
                                f"المُخرج من كودك: {stu_probe['stdout'].strip() or '(خطأ أو فارغ)'}\n"
                                f"💡 تأكد من كتابة الشرط أو المعادلة البرمجية بدلاً من طباعة الناتج النهائي مباشرة."
                            )
                            break
        except Exception:
            pass

    # Also guard against single-print cheats when expected_raw had 'Passed | Failed' without reference_code
    if all_passed and not inferred_ref_code and len(test_cases) == 1:
        exp_raw_single = str(test_cases[0].get("expected", "")).strip()
        if "|" in exp_raw_single and ("if " in instruction.lower() or "شرط" in instruction):
            try:
                stu_tree = ast.parse(healed_sub)
                has_cond = any(isinstance(n, (ast.If, ast.IfExp, ast.Match, ast.Compare)) for n in ast.walk(stu_tree))
                if not has_cond:
                    all_passed = False
                    feedback = "💡 تنبيه ذكي: السؤال يتطلب استخدام جملة شرطية (if / else) لفحص القيمة وليس طباعة النتيجة مباشرة."
            except Exception:
                pass

    if all_passed:
        feedback = "أحسنت! إجابة صحيحة واجتزت جميع الاختبارات بنجاح (تم التحقق من صحة منطق الكود ومخرجاته بأي طريقة حل) 🎉"

    return {
        "passed": all_passed,
        "output": actual_output,
        "error": run_result["stderr"],
        "feedback": feedback
    }


def build_task_test_cases(expected_output: str = "", reference_code: str = "", extra_test_cases=None, starter_code: str = "", instruction: str = ""):
    """
    Helper for Admin Task Creation:
    - Supports Model-Free Task Creation! If both expected_output and reference_code are empty,
      automatically infers test cases from instruction/starter_code or sets 'smart_auto' mode.
    - Automatically detects if 'expected_output' is actually Python reference code.
    - Normalizes and runs reference_code to extract the true stdout expected output.
    - Parses optional extra_test_cases (e.g. 'score = 30 => Failed' or 'score = 30').
    Returns: (resolved_expected_str, normalized_reference_code, test_cases_list)
    """
    raw_exp = str(expected_output or "").strip()
    raw_ref = str(reference_code or "").strip()

    if not raw_ref and looks_like_python_code(raw_exp):
        raw_ref = heal_common_syntax_slips(raw_exp)
    elif raw_ref:
        raw_ref = heal_common_syntax_slips(raw_ref)

    # Model-Free mode: neither expected_output nor reference_code provided
    if not raw_exp and not raw_ref and not extra_test_cases:
        inferred = infer_spec_from_instruction(instruction, starter_code)
        tcs = inferred["test_cases"]
        summary_exp = " | ".join(tc.get("expected", "") for tc in tcs if tc.get("expected")) or "تصحيح ذكي حر (بدون مودل مقيد)"
        return summary_exp, "", tcs

    resolved_main_expected = resolve_expected_output(
        expected_raw=raw_exp,
        reference_code=raw_ref,
        setup_code="",
        starter_code=starter_code
    )
    if not resolved_main_expected and raw_exp:
        resolved_main_expected = raw_exp

    test_cases = [
        {
            "type": "exact_output" if resolved_main_expected else "smart_auto",
            "expected": resolved_main_expected
        }
    ]

    if extra_test_cases:
        lines = extra_test_cases if isinstance(extra_test_cases, list) else str(extra_test_cases).split("\n")
        for item in lines:
            if isinstance(item, dict):
                sc = str(item.get("setup_code", "")).strip()
                ex = str(item.get("expected", "")).strip()
            else:
                line = str(item).strip()
                if not line:
                    continue
                if "=>" in line:
                    parts = line.split("=>", 1)
                    sc, ex = parts[0].strip(), parts[1].strip()
                elif "->" in line:
                    parts = line.split("->", 1)
                    sc, ex = parts[0].strip(), parts[1].strip()
                else:
                    sc, ex = line, ""

            if not sc:
                continue
            if not ex and raw_ref:
                ex = resolve_expected_output("", reference_code=raw_ref, setup_code=sc, starter_code=starter_code)
            if ex:
                test_cases.append({
                    "type": "exact_output",
                    "setup_code": sc,
                    "expected": ex
                })

    return resolved_main_expected or "تصحيح ذكي حر", raw_ref, test_cases

