import os
import json
import uuid
import urllib.parse
from http.server import HTTPServer, SimpleHTTPRequestHandler
import db
import engine

PORT = 8081

class AdminHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def send_json(self, data, status=200):
        response = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path in ("/", "/admin", "/admin.html", "/dashboard"):
            self.path = "/templates/admin.html"
            return super().do_GET()

        if path == "/api/admin/stats":
            stats = db.get_admin_dashboard_stats()
            # Also attach lessons & tasks overview
            try:
                all_lessons = engine.load_all_lessons()
                stats["all_lessons_meta"] = [
                    {
                        "id": l.get("id"),
                        "title": l.get("title"),
                        "category": l.get("category", "مقررات بايثون"),
                        "track": l.get("track", "general"),
                        "order": l.get("order", 1),
                        "tasks": l.get("tasks", []),
                        "cumulative_tasks": l.get("cumulative_tasks", []),
                        "tasks_count": len(l.get("tasks", [])) + len(l.get("cumulative_tasks", []))
                    }
                    for l in all_lessons
                ]
            except Exception as e:
                stats["all_lessons_meta"] = []
            return self.send_json(stats)

        if path == "/api/status":
            state = engine.get_platform_state()
            return self.send_json(state)

        if path == "/api/calendar":
            events = db.get_calendar_events()
            return self.send_json(events)

        if path == "/api/notifications":
            notifs = db.get_notifications()
            return self.send_json(notifs)

        if path == "/api/overrides":
            overrides = db.get_all_overrides()
            return self.send_json(overrides)
            
        if path == "/api/users":
            with db.get_db() as d:
                users = d.fetchall("SELECT id, username, email, role, is_active FROM users")
            return self.send_json(users)

        if path in ("/api/exams", "/api/admin/exams"):
            exams = db.get_all_exams()
            return self.send_json({"exams": exams})

        if path == "/api/admin/exams/submissions":
            query_params = urllib.parse.parse_qs(parsed.query)
            exam_id = query_params.get("exam_id", [None])[0]
            subs = db.get_exam_submissions(exam_id)
            return self.send_json({"submissions": subs})

        if path.startswith("/api/admin/download-submission/"):
            filename = os.path.basename(path.replace("/api/admin/download-submission/", "").strip("/"))
            file_path = os.path.join(os.path.dirname(__file__), "uploads", "submissions", filename)
            if not os.path.exists(file_path):
                return self.send_json({"error": "الملف غير موجود"}, status=404)
            
            try:
                with open(file_path, "rb") as f:
                    file_content = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
                self.send_header("Content-Length", str(len(file_content)))
                self.end_headers()
                self.wfile.write(file_content)
                return
            except Exception as e:
                return self.send_json({"error": f"فشل قراءة الملف: {str(e)}"}, status=500)

        return super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length).decode('utf-8')
        
        try:
            data = json.loads(body) if body else {}
        except Exception:
            data = {}

        if path == "/api/login":
            username = data.get("username")
            password = data.get("password")
            if username in ('youssef', 'يوسف') and password == 'admin123':
                return self.send_json({"success": True})
            return self.send_json({"error": "بيانات الدخول غير صحيحة"}, 401)

        if path == "/api/calendar":
            db.add_calendar_event(data.get("title", ""), data.get("event_date", ""), data.get("description", ""))
            return self.send_json({"success": True})

        if path == "/api/notifications":
            db.add_notification(data.get("title", ""), data.get("message", ""))
            return self.send_json({"success": True})

        if path == "/api/overrides":
            res = db.set_user_task_override(data.get("user_id"), data.get("task_id"), data.get("is_unlocked", True))
            return self.send_json(res, status=200 if res.get("success") else 400)

        if path == "/api/admin/overrides/remove":
            override_id = str(data.get("override_id", "")).strip()
            if override_id:
                db.remove_task_override(override_id)
                return self.send_json({"success": True})
            return self.send_json({"success": False, "error": "معرف الاستثناء مطلوب"}, status=400)

        if path == "/api/admin/delete-user":
            user_id = str(data.get("user_id", "")).strip()
            res = db.delete_user(user_id)
            return self.send_json(res, status=200 if res.get("success") else 400)

        if path == "/api/admin/users/update-role":
            user_id = str(data.get("user_id", "")).strip()
            role = str(data.get("role", "student")).strip()
            res = db.update_user_role(user_id, role)
            return self.send_json(res, status=200 if res.get("success") else 400)

        if path == "/api/admin/users/toggle-active":
            user_id = str(data.get("user_id", "")).strip()
            is_active = bool(data.get("is_active", True))
            res = db.toggle_user_status(user_id, is_active)
            return self.send_json(res, status=200 if res.get("success") else 400)

        if path == "/api/admin/tasks/toggle-status":
            task_id = str(data.get("task_id", "")).strip()
            raw_is_open = data.get("is_open", False)
            if raw_is_open is None or raw_is_open == "sequential":
                is_open_val = "sequential"
            else:
                is_open_val = bool(raw_is_open)
            res = db.toggle_task_status(task_id, is_open_val)
            # If task_id is a lesson ID, also cascade to its tasks so lesson & tasks stay in sync
            lesson = engine.get_lesson_by_id(task_id)
            if lesson:
                for t in lesson.get("tasks", []) + lesson.get("cumulative_tasks", []):
                    db.toggle_task_status(t["id"], is_open_val)
            return self.send_json(res, status=200 if res.get("success") else 400)

        if path == "/api/admin/tasks/bulk-toggle":
            action = str(data.get("action", "")).strip()
            all_lessons = engine.load_all_lessons()
            all_ids = []
            for l in all_lessons:
                all_ids.append(l["id"])
                for t in l.get("tasks", []) + l.get("cumulative_tasks", []):
                    all_ids.append(t["id"])
            res = db.bulk_toggle_tasks(action, all_ids)
            return self.send_json(res, status=200 if res.get("success") else 400)

        if path == "/api/admin/tasks/delete":
            target_id = str(data.get("target_id", "")).strip()
            res = engine.delete_task_or_lesson(target_id)
            return self.send_json(res, status=200 if res.get("success") else 400)

        if path == "/api/admin/inquiries/delete":
            inquiry_id = str(data.get("inquiry_id", "")).strip()
            res = db.delete_contact_inquiry(inquiry_id)
            return self.send_json(res, status=200 if res.get("success") else 400)

        if path == "/api/admin/submissions/approve":
            sub_id = str(data.get("submission_id", "")).strip()
            res = db.approve_task_submission(sub_id)
            return self.send_json(res, status=200 if res.get("success") else 400)

        if path == "/api/admin/run-reference-code":
            ref_code = str(data.get("reference_code", "")).strip()
            if not ref_code:
                return self.send_json({"success": False, "error": "يرجى كتابة كود الحل النموذجي أولاً."}, status=400)
            norm_ref = engine.heal_common_syntax_slips(ref_code)
            res = engine.execute_code_safely(norm_ref)
            return self.send_json({
                "success": res["success"],
                "stdout": res["stdout"].strip(),
                "stderr": res["stderr"],
                "normalized_code": norm_ref
            })

        if path == "/api/admin/create-task":
            title = str(data.get("title", "")).strip()
            track = str(data.get("track", "general")).strip()
            category = str(data.get("category", "مقررات بايثون")).strip()
            description = str(data.get("description", "")).strip()
            content = str(data.get("content", "")).strip()
            task_title = str(data.get("task_title", "")).strip()
            instruction = str(data.get("instruction", "")).strip()
            starter_code = str(data.get("starter_code", "# اكتب الكود هنا\n"))
            expected_output = str(data.get("expected_output", "")).strip()
            reference_code = str(data.get("reference_code", "")).strip()
            extra_test_cases = data.get("extra_test_cases", "")
            hint = str(data.get("hint", "")).strip()
            initial_status = str(data.get("initial_status", "open_all")).strip()

            if not title or not task_title or not instruction:
                return self.send_json({"success": False, "error": "يرجى تعبئة الحقول الأساسية فقط (عنوان الدرس، عنوان المهمة، ونص المطلوب)."}, status=400)

            resolved_expected, norm_ref, test_cases = engine.build_task_test_cases(
                expected_output=expected_output,
                reference_code=reference_code,
                extra_test_cases=extra_test_cases,
                starter_code=starter_code,
                instruction=instruction
            )

            all_lessons = engine.load_all_lessons()
            track_lessons = [l for l in all_lessons if l.get("track", "general") == track]
            next_order = len(track_lessons) + 1
            prefix = "uni" if track == "university" else "custom"
            lesson_id = f"{prefix}_lesson_{int(uuid.uuid1().time)}"
            task_id = f"{prefix}_task_{int(uuid.uuid1().time)}"

            task_obj = {
                "id": task_id,
                "type": "lesson_task",
                "title": task_title,
                "instruction": instruction,
                "starter_code": starter_code,
                "test_cases": test_cases,
                "hint": hint or "ركز في المطلوب بدقة؛ يمكنك كتابة الحل بأي طريقة برمجية صحيحة."
            }
            if norm_ref:
                task_obj["reference_code"] = norm_ref

            new_lesson_obj = {
                "id": lesson_id,
                "track": track,
                "order": next_order,
                "title": f"{next_order}. {title}",
                "category": category,
                "description": description or f"مهمة تطبيقية عملية في {title}",
                "content": content or f"### {title}\n\nتطبيق عملي وتمرين مباشر وممتع تم نشره عبر المشرف.",
                "tasks": [task_obj],
                "cumulative_tasks": []
            }

            lessons_dir = os.path.join(os.path.dirname(__file__), "lessons")
            filename = f"{prefix}_{next_order:02d}_{int(uuid.uuid1().time)}.json"
            filepath = os.path.join(lessons_dir, filename)

            try:
                with open(filepath, "w", encoding="utf-8") as f:
                    json.dump(new_lesson_obj, f, ensure_ascii=False, indent=2)
                if initial_status == "open_all":
                    db.toggle_task_status(lesson_id, True)
                    db.toggle_task_status(task_id, True)
                elif initial_status == "locked":
                    db.toggle_task_status(lesson_id, False)
                    db.toggle_task_status(task_id, False)
                return self.send_json({
                    "success": True,
                    "message": f"تم نشر الدرس والمهمة '{title}' بنجاح (نظام التقييم: {resolved_expected})!",
                    "lesson_id": lesson_id,
                    "task_id": task_id,
                    "resolved_expected": resolved_expected
                })
            except Exception as e:
                return self.send_json({"success": False, "error": f"فشل حفظ المهمة: {str(e)}"}, status=500)

        if path == "/api/admin/exams/create":
            title = str(data.get("title", "")).strip()
            description = str(data.get("description", "")).strip()
            instructions = str(data.get("instructions", "")).strip()
            try:
                duration_minutes = int(data.get("duration_minutes", 0))
            except (ValueError, TypeError):
                duration_minutes = 0
            questions_json = json.dumps(data.get("questions", []), ensure_ascii=False) if isinstance(data.get("questions"), list) else str(data.get("questions_json", "[]"))
            attached_file = str(data.get("attached_file", "")).strip()
            is_open = bool(data.get("is_open", False))

            if not title:
                return self.send_json({"success": False, "error": "يرجى كتابة عنوان الامتحان"}, status=400)

            res = db.create_exam(title, description, instructions, duration_minutes, questions_json, attached_file, is_open)
            return self.send_json(res, status=200 if res.get("success") else 400)

        if path == "/api/admin/exams/toggle-status":
            exam_id = str(data.get("exam_id", "")).strip()
            is_open = bool(data.get("is_open", False))
            res = db.toggle_exam_status(exam_id, is_open)
            return self.send_json(res, status=200 if res.get("success") else 400)

        if path == "/api/admin/exams/delete":
            exam_id = str(data.get("exam_id", "")).strip()
            res = db.delete_exam(exam_id)
            return self.send_json(res, status=200 if res.get("success") else 400)

        if path == "/api/admin/exams/grade-submission":
            sub_id = str(data.get("submission_id", "")).strip()
            new_score = int(data.get("new_score", 0))
            res = db.update_exam_submission_score(sub_id, new_score)
            return self.send_json(res, status=200 if res.get("success") else 400)


        self.send_response(404)
        self.end_headers()

    def do_DELETE(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path.startswith("/api/calendar/"):
            event_id = path.split("/")[-1]
            db.delete_calendar_event(event_id)
            return self.send_json({"success": True})

        if path.startswith("/api/notifications/"):
            notif_id = path.split("/")[-1]
            db.delete_notification(notif_id)
            return self.send_json({"success": True})

        if path.startswith("/api/overrides/"):
            override_id = path.split("/")[-1]
            db.remove_task_override(override_id)
            return self.send_json({"success": True})

        if path.startswith("/api/inquiries/"):
            inq_id = path.split("/")[-1]
            db.delete_contact_inquiry(inq_id)
            return self.send_json({"success": True})

        self.send_response(404)
        self.end_headers()

def run_admin_server():
    db.init_db()
    server_address = ('', PORT)
    httpd = HTTPServer(server_address, AdminHandler)
    print("==================================================")
    print(f"Admin Dashboard running on PORT {PORT}")
    print(f"Open in browser: http://localhost:{PORT}")
    print("==================================================")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.server_close()

if __name__ == "__main__":
    run_admin_server()
