import os
import sys
import json
import base64
import uuid
import urllib.parse
from http.server import HTTPServer, SimpleHTTPRequestHandler
import db
import engine
import security

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

PORT = int(os.environ.get("PORT", 8080))
ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "") # Empty means strict origin or same-origin
MAX_PAYLOAD_SIZE = 10 * 1024 * 1024 # 10 MB maximum request body for file uploads

class PythonLearningHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        # 1. Apply Security Headers (CSP, X-Frame-Options, X-Content-Type-Options, etc.)
        for header, val in security.SECURITY_HEADERS.items():
            self.send_header(header, val)

        # 2. Strict Origin / CORS Policy (Never '*')
        origin = self.headers.get("Origin", "")
        host = self.headers.get("Host", "")
        
        if ALLOWED_ORIGIN and origin == ALLOWED_ORIGIN:
            self.send_header('Access-Control-Allow-Origin', ALLOWED_ORIGIN)
            self.send_header('Access-Control-Allow-Credentials', 'true')
        elif origin and (f"localhost:{PORT}" in origin or f"127.0.0.1:{PORT}" in origin or host in origin):
            self.send_header('Access-Control-Allow-Origin', origin)
            self.send_header('Access-Control-Allow-Credentials', 'true')

        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, X-CSRF-Token')
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def get_client_ip(self):
        # Handle X-Forwarded-For if behind a reverse proxy (Render / Cloudflare)
        xff = self.headers.get("X-Forwarded-For")
        if xff:
            return xff.split(",")[0].strip()
        return self.client_address[0]

    def get_session_token(self):
        cookie_header = self.headers.get("Cookie", "")
        for item in cookie_header.split(";"):
            item = item.strip()
            if item.startswith("session="):
                return item.split("=", 1)[1]
        return None

    def get_current_user(self):
        token = self.get_session_token()
        if token:
            return db.get_user_by_session(token)
        return None

    def send_json(self, data, status=200, set_cookie=None):
        response_bytes = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(response_bytes)))
        if set_cookie:
            self.send_header('Set-Cookie', set_cookie)
        self.end_headers()
        self.wfile.write(response_bytes)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        client_ip = self.get_client_ip()

        # Rate Limit for General GET APIs (60 requests per minute)
        if not security.check_rate_limit(f"get_{client_ip}", max_requests=60, window_seconds=60):
            return self.send_json({"error": "تم تجاوز الحد المسموح من الطلبات. يرجى الانتظار قليلاً."}, status=429)

        # Serve static frontend home
        if path == "/" or path == "/index.html":
            self.path = "/templates/index.html"
            return super().do_GET()

        # Graceful redirect for removed admin dashboard
        if path in ("/admin", "/admin.html"):
            self.send_response(302)
            self.send_header("Location", "/")
            self.end_headers()
            return

        current_user = self.get_current_user()
        session_token = self.get_session_token()

        # Admin Dashboard Statistics
        if path == "/api/admin/stats":
            if not current_user or current_user.get("role") != "admin":
                return self.send_json({"error": "غير مصرح: للمشرف فقط"}, status=403)
            stats = db.get_admin_dashboard_stats()
            return self.send_json(stats)

        # 1. Auth Me Endpoint + CSRF token provisioning
        if path == "/api/auth/me":
            if current_user:
                csrf_token = security.generate_csrf_token(session_token)
                return self.send_json({
                    "authenticated": True,
                    "user": current_user,
                    "csrf_token": csrf_token
                })
            return self.send_json({"authenticated": False, "user": None, "csrf_token": ""})

        # 2. Platform Status Endpoint
        if path == "/api/status":
            uid = current_user["id"] if current_user else None
            state = engine.get_platform_state(user_id=uid)
            state["user"] = current_user
            state["csrf_token"] = security.generate_csrf_token(session_token) if session_token else ""
            refresh_cookie = f"session={session_token}; Path=/; Max-Age=315360000; HttpOnly; SameSite=Lax" if (session_token and current_user) else None
            return self.send_json(state, set_cookie=refresh_cookie)

        # 3. Lesson Detail Endpoint
        if path.startswith("/api/lesson/"):
            lesson_id = path.replace("/api/lesson/", "").strip("/")
            lesson = engine.get_lesson_by_id(lesson_id)
            if not lesson:
                return self.send_json({"error": "الدرس غير موجود"}, status=404)
            
            uid = current_user["id"] if current_user else None
            state = engine.get_platform_state(user_id=uid)
            lesson_status = next((l for l in state["lessons"] if l["id"] == lesson_id), None)
            
            if not lesson_status or not lesson_status["unlocked"]:
                return self.send_json({
                    "error": "هذا الدرس مقفل! يجب إنهاء مهام ومراجعات الدروس السابقة أولاً لتتمكن من فتحه 🔒"
                }, status=403)
            
            completed_tasks = set(state["completed_tasks"])
            task_status_map = db.get_task_status_map()
            
            tasks = []
            for t in lesson.get("tasks", []):
                t_copy = dict(t)
                t_copy["completed"] = t["id"] in completed_tasks
                t_copy["is_open"] = task_status_map.get(t["id"], True)
                tasks.append(t_copy)

            cumulative_tasks = []
            for ct in lesson.get("cumulative_tasks", []):
                ct_copy = dict(ct)
                ct_copy["completed"] = ct["id"] in completed_tasks
                ct_copy["is_open"] = task_status_map.get(ct["id"], True)
                cumulative_tasks.append(ct_copy)

            response_data = dict(lesson)
            response_data["tasks"] = tasks
            response_data["cumulative_tasks"] = cumulative_tasks
            response_data["is_completed"] = lesson_status["completed"]
            response_data["is_open"] = task_status_map.get(lesson_id, True)
            return self.send_json(response_data)

        # 4. Download / View Uploaded Submission File (Admin only)
        if path.startswith("/api/admin/download-submission/"):
            if not current_user or current_user.get("role") != "admin":
                return self.send_json({"error": "غير مصرح: للمشرف فقط"}, status=403)
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

        # 5. Exams List Endpoint
        if path == "/api/exams":
            is_admin = current_user and current_user.get("role") == "admin"
            exams = db.get_all_exams() if is_admin else db.get_open_exams()
            return self.send_json({"exams": exams})

        # 6. Single Exam Detail Endpoint
        if path.startswith("/api/exam/"):
            exam_id = path.replace("/api/exam/", "").strip("/")
            exam = db.get_exam_by_id(exam_id)
            if not exam:
                return self.send_json({"error": "الامتحان غير موجود"}, status=404)
            is_admin = current_user and current_user.get("role") == "admin"
            if not is_admin and not exam.get("is_open"):
                return self.send_json({"error": "هذا الامتحان مغلق وسري حالياً من قِبل المشرف 🔒"}, status=403)
            return self.send_json({"exam": exam})

        return super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        client_ip = self.get_client_ip()

        # 1. Request Body Size Limit (Anti-DoS)
        try:
            content_length = int(self.headers.get('Content-Length', 0))
        except ValueError:
            return self.send_json({"error": "Content-Length غير صالح"}, status=400)

        if content_length > MAX_PAYLOAD_SIZE:
            return self.send_json({"error": "حجم الطلب تجاوز الحد المسموح به (64KB)"}, status=413)

        post_body = self.rfile.read(content_length).decode('utf-8', errors='replace')
        try:
            body_data = json.loads(post_body) if post_body else {}
        except Exception:
            return self.send_json({"error": "صيغة البيانات المرسلة غير صالحة (Invalid JSON)"}, status=400)

        current_user = self.get_current_user()
        session_token = self.get_session_token()

        # 2. Rate Limiting for Sensitive Endpoints
        if path in ("/api/auth/login", "/api/auth/register"):
            # Max 5 attempts per minute per IP
            if not security.check_rate_limit(f"auth_{client_ip}", max_requests=5, window_seconds=60):
                return self.send_json({"error": "محاولات كثيرة جداً. يرجى الانتظار دقيقة قبل المحاولة مجدداً."}, status=429)

        if path == "/api/contact":
            # Max 5 contact submissions per minute per IP
            if not security.check_rate_limit(f"contact_{client_ip}", max_requests=5, window_seconds=60):
                return self.send_json({"error": "تم إرسال عدة رسائل مؤخراً. يرجى الانتظار قليلاً قبل المحاولة مجدداً."}, status=429)

        if path in ("/api/run", "/api/submit-task"):
            # Max 15 execution requests per minute per User or IP
            rate_key = f"exec_{current_user['id'] if current_user else client_ip}"
            if not security.check_rate_limit(rate_key, max_requests=15, window_seconds=60):
                return self.send_json({"error": "تم تجاوز معدل تشغيل الأكواد (الحد 15 طلباً بالدقيقة). تمهل قليلاً."}, status=429)

        # Contact / Support Form
        if path == "/api/contact":
            name = str(body_data.get("name", "")).strip()
            contact_info = str(body_data.get("contact_info", "")).strip()
            message = str(body_data.get("message", "")).strip()

            if not name or len(name) < 2 or len(name) > 100:
                return self.send_json({"success": False, "error": "يرجى كتابة الاسم بشكل صحيح (بين 2 و 100 حرف)."}, status=400)
            if not contact_info or len(contact_info) < 5 or len(contact_info) > 120:
                return self.send_json({"success": False, "error": "يرجى إدخال رقم الهاتف أو البريد الإلكتروني للتواصل."}, status=400)
            if not message or len(message) < 3 or len(message) > 2000:
                return self.send_json({"success": False, "error": "يرجى كتابة رسالتك أو استفسارك (بين 3 و 2000 حرف)."}, status=400)

            user_id = current_user["id"] if current_user else None
            res = db.save_contact_inquiry(name, contact_info, message, user_id=user_id, ip_address=client_ip)
            return self.send_json(res, status=200 if res["success"] else 400)

        # 3. Auth: Register (Strict Validation)
        if path == "/api/auth/register":
            username = str(body_data.get("username", "")).strip()
            email = str(body_data.get("email", "")).strip().lower()
            password = str(body_data.get("password", ""))

            valid, err_msg = security.validate_register_input(username, email, password)
            if not valid:
                return self.send_json({"success": False, "error": err_msg}, status=400)

            reg_res = db.create_user(username, email, password)
            if not reg_res["success"]:
                return self.send_json(reg_res, status=400)

            # Auto-login with persistent permanent cookie (10 years)
            login_res = db.authenticate_user(username, password, ip_address=client_ip)
            cookie = f"session={login_res['session_token']}; Path=/; Max-Age=315360000; HttpOnly; SameSite=Lax"
            return self.send_json(login_res, status=200, set_cookie=cookie)

        # 4. Auth: Login
        if path == "/api/auth/login":
            username_or_email = str(body_data.get("username_or_email", "")).strip()
            password = str(body_data.get("password", ""))
            
            if not username_or_email or not password:
                return self.send_json({"success": False, "error": "يرجى إدخال اسم المستخدم وكلمة المرور"}, status=400)

            login_res = db.authenticate_user(username_or_email, password, ip_address=client_ip)
            if not login_res["success"]:
                return self.send_json(login_res, status=401)

            # Persistent permanent cookie (10 years)
            cookie = f"session={login_res['session_token']}; Path=/; Max-Age=315360000; HttpOnly; SameSite=Lax"
            return self.send_json(login_res, status=200, set_cookie=cookie)

        # 5. Auth: Logout
        if path == "/api/auth/logout":
            if session_token:
                db.delete_session(session_token)
            cookie = "session=; Path=/; Expires=Thu, 01 Jan 1970 00:00:00 GMT"
            return self.send_json({"success": True}, status=200, set_cookie=cookie)

        # 6. Authorization Guard: Endpoints requiring active login
        if path in ("/api/submit-task", "/api/save-code-draft", "/api/reset", "/api/admin/delete-user", "/api/upload-submission", "/api/admin/create-task", "/api/admin/tasks/toggle-status", "/api/admin/tasks/delete", "/api/admin/users/update-role", "/api/admin/users/toggle-active"):
            if not current_user:
                return self.send_json({"error": "غير مصرح (Unauthorized): يرجى تسجيل الدخول أولاً للمتابعة."}, status=401)

        # Admin: Delete User
        if path == "/api/admin/delete-user":
            if current_user.get("role") != "admin":
                return self.send_json({"error": "غير مصرح: للمشرف فقط"}, status=403)
            user_to_delete = str(body_data.get("user_id", "")).strip()
            res = db.delete_user(user_to_delete)
            status_code = 200 if res["success"] else 400
            return self.send_json(res, status=status_code)

        # Admin: Update User Role (Promote / Demote)
        if path == "/api/admin/users/update-role":
            if current_user.get("role") != "admin":
                return self.send_json({"error": "غير مصرح: للمشرف فقط"}, status=403)
            user_id = str(body_data.get("user_id", "")).strip()
            role = str(body_data.get("role", "student")).strip()
            res = db.update_user_role(user_id, role)
            return self.send_json(res, status=200 if res["success"] else 400)

        # Admin: Toggle User Status (Activate / Ban)
        if path == "/api/admin/users/toggle-active":
            if current_user.get("role") != "admin":
                return self.send_json({"error": "غير مصرح: للمشرف فقط"}, status=403)
            user_id = str(body_data.get("user_id", "")).strip()
            is_active = bool(body_data.get("is_active", True))
            res = db.toggle_user_status(user_id, is_active)
            return self.send_json(res, status=200 if res["success"] else 400)

        # Admin: Toggle Task Status (Open 🟢 / Lock 🔴)
        if path == "/api/admin/tasks/toggle-status":
            if current_user.get("role") != "admin":
                return self.send_json({"error": "غير مصرح: للمشرف فقط"}, status=403)
            task_id = str(body_data.get("task_id", "")).strip()
            is_open = bool(body_data.get("is_open", False))
            res = db.toggle_task_status(task_id, is_open)
            return self.send_json(res, status=200 if res["success"] else 400)

        # Admin: Delete Task or Lesson
        if path == "/api/admin/tasks/delete":
            if current_user.get("role") != "admin":
                return self.send_json({"error": "غير مصرح: للمشرف فقط"}, status=403)
            target_id = str(body_data.get("target_id", "")).strip()
            res = engine.delete_task_or_lesson(target_id)
            return self.send_json(res, status=200 if res["success"] else 400)

        # Save Code Draft (Student Auto-Save)
        if path == "/api/save-code-draft":
            task_id = str(body_data.get("task_id", "")).strip()
            code = str(body_data.get("code", ""))
            if not task_id:
                return self.send_json({"success": False, "error": "رمز المهمة غير محدد"}, status=400)
            db.save_user_task_code(current_user["id"], task_id, code)
            return self.send_json({"success": True, "message": "تم حفظ المسودة بنجاح"})

        # Reset Progress
        if path == "/api/reset":
            db.reset_user_progress(current_user["id"])
            return self.send_json({"success": True, "message": "تم إعادة ضبط التقدم بنجاح"})

        # Run Code (Test only)
        if path == "/api/run":
            code = str(body_data.get("code", ""))
            if len(code) > 10000:
                return self.send_json({"success": False, "stderr": "حجم الكود تجاوز الحد الأقصى (10,000 حرف)."}, status=400)
            result = engine.execute_code_safely(code)
            return self.send_json(result)

        # Submit Task
        if path == "/api/submit-task":
            lesson_id = body_data.get("lesson_id")
            task_id = body_data.get("task_id")
            code = str(body_data.get("code", ""))
            try:
                duration_seconds = int(body_data.get("duration_seconds") or 0)
                if duration_seconds < 0:
                    duration_seconds = 0
                elif duration_seconds > 86400:
                    duration_seconds = 86400
            except (ValueError, TypeError):
                duration_seconds = 0

            if len(code) > 10000:
                return self.send_json({"passed": False, "feedback": "حجم الكود تجاوز الحد الأقصى المسموح به."}, status=400)

            # Always save the student's code permanently whenever they submit
            db.save_user_task_code(current_user["id"], task_id, code)

            # Check if task is locked by admin
            task_status_map = db.get_task_status_map()
            if not task_status_map.get(task_id, True) and current_user.get("role") != "admin":
                return self.send_json({"passed": False, "feedback": "عذراً! هذه المهمة مغلقة وسرية حالياً من قِبل المشرف ولا يمكن حلها 🔒"}, status=403)

            lesson = engine.get_lesson_by_id(lesson_id)
            if not lesson:
                return self.send_json({"passed": False, "feedback": "الدرس غير موجود"}, status=404)

            all_tasks = lesson.get("tasks", []) + lesson.get("cumulative_tasks", [])
            target_task = next((t for t in all_tasks if t["id"] == task_id), None)
            
            if not target_task:
                return self.send_json({"passed": False, "feedback": "المهمة غير موجودة"}, status=404)

            eval_res = engine.evaluate_task(target_task, code)
            eval_res["duration_seconds"] = duration_seconds
            
            # Record submission for the admin dashboard to inspect actual code, timestamp, user, duration, and status
            db.record_task_submission(
                user_id=current_user["id"],
                task_id=task_id,
                lesson_id=lesson_id,
                code=code,
                passed=eval_res["passed"],
                output=eval_res.get("output", ""),
                duration_seconds=duration_seconds
            )

            if eval_res["passed"]:
                db.mark_task_done(current_user["id"], task_id, lesson_id, duration_seconds=duration_seconds)
                state = engine.get_platform_state(user_id=current_user["id"])
                lesson_status = next((l for l in state["lessons"] if l["id"] == lesson_id), None)
                eval_res["lesson_completed"] = lesson_status["completed"] if lesson_status else False
            else:
                eval_res["lesson_completed"] = False

            return self.send_json(eval_res)

        # Upload Submission File (Student assignments)
        if path == "/api/upload-submission":
            original_filename = str(body_data.get("filename", "")).strip()
            file_b64 = str(body_data.get("file_content_base64", "")).strip()
            task_id = str(body_data.get("task_id", "")).strip() or None
            lesson_id = str(body_data.get("lesson_id", "")).strip() or None
            notes = str(body_data.get("notes", "")).strip()

            if not original_filename or not file_b64:
                return self.send_json({"success": False, "error": "يرجى اختيار ملف صالح للرفع."}, status=400)

            # Security sanitization on filename and extension
            safe_basename = os.path.basename(original_filename).replace(" ", "_")
            ext = os.path.splitext(safe_basename)[1].lower()
            allowed_exts = {".py", ".txt", ".pdf", ".zip", ".ipynb"}
            if ext not in allowed_exts:
                return self.send_json({"success": False, "error": "نوع الملف غير مدعوم. المسموح: .py, .ipynb, .pdf, .zip, .txt"}, status=400)

            try:
                file_bytes = base64.b64decode(file_b64)
            except Exception:
                return self.send_json({"success": False, "error": "بيانات الملف التالفة أو غير صالحة (Base64 Error)."}, status=400)

            if len(file_bytes) > 8 * 1024 * 1024:
                return self.send_json({"success": False, "error": "حجم الملف تجاوز الحد الأقصى المسموح به (8MB)."}, status=400)

            # Unique stored filename: user_timestamp_uuid_name.ext
            clean_name = "".join(c for c in safe_basename if c.isalnum() or c in "._-")
            saved_filename = f"{current_user['username']}_{int(uuid.uuid1().time)}_{clean_name}"
            upload_dir = os.path.join(os.path.dirname(__file__), "uploads", "submissions")
            os.makedirs(upload_dir, exist_ok=True)
            saved_path = os.path.join(upload_dir, saved_filename)

            with open(saved_path, "wb") as f:
                f.write(file_bytes)

            # Save in database
            save_res = db.save_uploaded_submission(
                user_id=current_user["id"],
                original_filename=safe_basename,
                saved_filename=saved_filename,
                file_size=len(file_bytes),
                task_id=task_id,
                lesson_id=lesson_id,
                notes=notes
            )

            # If it's a python script or text, also extract text to send back to editor if needed
            extracted_code = ""
            if ext in (".py", ".txt"):
                try:
                    extracted_code = file_bytes.decode("utf-8", errors="replace")
                except Exception:
                    pass

            return self.send_json({
                "success": True,
                "message": f"تم رفع الملف '{safe_basename}' بنجاح وحفظه في سجلاتك الأكاديمية.",
                "filename": safe_basename,
                "saved_filename": saved_filename,
                "extracted_code": extracted_code
            })

        # Admin: Create New Lesson / Task
        if path == "/api/admin/create-task":
            if current_user.get("role") != "admin":
                return self.send_json({"error": "غير مصرح: للمشرف فقط"}, status=403)

            title = str(body_data.get("title", "")).strip()
            track = str(body_data.get("track", "general")).strip()
            category = str(body_data.get("category", "مقررات بايثون")).strip()
            description = str(body_data.get("description", "")).strip()
            content = str(body_data.get("content", "")).strip()
            task_title = str(body_data.get("task_title", "")).strip()
            instruction = str(body_data.get("instruction", "")).strip()
            starter_code = str(body_data.get("starter_code", "# اكتب الكود هنا\n"))
            expected_output = str(body_data.get("expected_output", "")).strip()
            hint = str(body_data.get("hint", "")).strip()

            if not title or not task_title or not instruction or not expected_output:
                return self.send_json({"success": False, "error": "يرجى تعبئة جميع الحقول المطلوبة (عنوان الدرس، عنوان المهمة، التعليمات، والمخرجات المتوقعة)."}, status=400)

            # Generate IDs and determine next order for this track
            all_lessons = engine.load_all_lessons()
            track_lessons = [l for l in all_lessons if l.get("track", "general") == track]
            next_order = len(track_lessons) + 1
            prefix = "uni" if track == "university" else "custom"
            lesson_id = f"{prefix}_lesson_{int(uuid.uuid1().time)}"
            task_id = f"{prefix}_task_{int(uuid.uuid1().time)}"

            new_lesson_obj = {
                "id": lesson_id,
                "track": track,
                "order": next_order,
                "title": f"{next_order}. {title}",
                "category": category,
                "description": description or f"مهمة تطبيقية عملية في {title}",
                "content": content or f"### {title}\n\nتطبيق عملي وتمرين مباشر وممتع تم نشره عبر المشرف.",
                "tasks": [
                    {
                        "id": task_id,
                        "type": "lesson_task",
                        "title": task_title,
                        "instruction": instruction,
                        "starter_code": starter_code,
                        "test_cases": [
                            {
                                "type": "exact_output",
                                "expected": expected_output
                            }
                        ],
                        "hint": hint or "ركز في المطلوب بدقة واطبع الناتج تماماً كما هو محدد."
                    }
                ],
                "cumulative_tasks": []
            }

            lessons_dir = os.path.join(os.path.dirname(__file__), "lessons")
            filename = f"{prefix}_{next_order:02d}_{int(uuid.uuid1().time)}.json"
            filepath = os.path.join(lessons_dir, filename)

            try:
                with open(filepath, "w", encoding="utf-8") as f:
                    json.dump(new_lesson_obj, f, ensure_ascii=False, indent=2)
                return self.send_json({
                    "success": True,
                    "message": f"تم نشر الدرس والمهمة '{title}' بنجاح في { 'قسم الجامعات' if track == 'university' else 'المسار العام' }!",
                    "lesson_id": lesson_id
                })
            except Exception as e:
                return self.send_json({"success": False, "error": f"فشل حفظ المهمة: {str(e)}"}, status=500)

        # Admin: Create New Exam
        if path == "/api/admin/exams/create":
            if not current_user or current_user.get("role") != "admin":
                return self.send_json({"error": "غير مصرح: للمشرف فقط"}, status=403)
            title = str(body_data.get("title", "")).strip()
            description = str(body_data.get("description", "")).strip()
            instructions = str(body_data.get("instructions", "")).strip()
            try:
                duration_minutes = int(body_data.get("duration_minutes", 0))
            except (ValueError, TypeError):
                duration_minutes = 0
            questions_json = json.dumps(body_data.get("questions", []), ensure_ascii=False) if isinstance(body_data.get("questions"), list) else str(body_data.get("questions_json", "[]"))
            attached_file = str(body_data.get("attached_file", "")).strip()
            is_open = bool(body_data.get("is_open", False))

            if not title:
                return self.send_json({"success": False, "error": "يرجى كتابة عنوان الامتحان"}, status=400)

            res = db.create_exam(title, description, instructions, duration_minutes, questions_json, attached_file, is_open)
            return self.send_json(res, status=200 if res["success"] else 400)

        # Admin: Toggle Exam Status (Open 🟢 / Lock 🔴)
        if path == "/api/admin/exams/toggle-status":
            if not current_user or current_user.get("role") != "admin":
                return self.send_json({"error": "غير مصرح: للمشرف فقط"}, status=403)
            exam_id = str(body_data.get("exam_id", "")).strip()
            is_open = bool(body_data.get("is_open", False))
            res = db.toggle_exam_status(exam_id, is_open)
            return self.send_json(res, status=200 if res["success"] else 400)

        # Admin: Delete Exam
        if path == "/api/admin/exams/delete":
            if not current_user or current_user.get("role") != "admin":
                return self.send_json({"error": "غير مصرح: للمشرف فقط"}, status=403)
            exam_id = str(body_data.get("exam_id", "")).strip()
            res = db.delete_exam(exam_id)
            return self.send_json(res, status=200 if res["success"] else 400)

        # Admin: Get Exam Submissions
        if path == "/api/admin/exams/submissions":
            if not current_user or current_user.get("role") != "admin":
                return self.send_json({"error": "غير مصرح: للمشرف فقط"}, status=403)
            exam_id = str(body_data.get("exam_id", "")).strip() or None
            subs = db.get_exam_submissions(exam_id)
            return self.send_json({"submissions": subs})

        # Student / User: Submit Exam Solution
        if path == "/api/exam/submit":
            if not current_user:
                return self.send_json({"error": "يرجى تسجيل الدخول لتسليم الامتحان"}, status=401)
            exam_id = str(body_data.get("exam_id", "")).strip()
            answers = body_data.get("answers", {})
            file_b64 = str(body_data.get("file_content_base64", "")).strip()
            original_filename = str(body_data.get("filename", "")).strip()

            exam = db.get_exam_by_id(exam_id)
            if not exam:
                return self.send_json({"success": False, "error": "الامتحان غير موجود"}, status=404)
            is_admin = current_user.get("role") == "admin"
            if not is_admin and not exam.get("is_open"):
                return self.send_json({"success": False, "error": "عذراً! تم قفل هذا الامتحان من قِبل المشرف ولا يمكن استقبال أي تسليمات 🔒"}, status=403)

            saved_filename = ""
            if file_b64 and original_filename:
                safe_basename = os.path.basename(original_filename).replace(" ", "_")
                ext = os.path.splitext(safe_basename)[1].lower()
                allowed_exts = {".py", ".txt", ".pdf", ".zip", ".ipynb"}
                if ext in allowed_exts:
                    try:
                        file_bytes = base64.b64decode(file_b64)
                        clean_name = "".join(c for c in safe_basename if c.isalnum() or c in "._-")
                        saved_filename = f"exam_{current_user['username']}_{int(uuid.uuid1().time)}_{clean_name}"
                        upload_dir = os.path.join(os.path.dirname(__file__), "uploads", "submissions")
                        os.makedirs(upload_dir, exist_ok=True)
                        with open(os.path.join(upload_dir, saved_filename), "wb") as f:
                            f.write(file_bytes)
                    except Exception as e:
                        print(f"Error saving exam file submission: {e}")

            answers_json = json.dumps(answers, ensure_ascii=False) if isinstance(answers, (dict, list)) else str(answers)
            
            score = 0
            max_score = 0
            try:
                questions = json.loads(exam.get("questions_json", "[]")) if exam.get("questions_json") else []
                max_score = len(questions) * 10
                if isinstance(answers, dict) and questions:
                    for q_idx, q in enumerate(questions):
                        ans_code = answers.get(str(q_idx), "") or answers.get(q_idx, "")
                        if ans_code and q.get("test_cases"):
                            eval_res = engine.evaluate_task(q, ans_code)
                            if eval_res["passed"]:
                                score += 10
            except Exception as ex:
                print(f"Error evaluating exam answers: {ex}")

            save_res = db.save_exam_submission(
                user_id=current_user["id"],
                exam_id=exam_id,
                score=score,
                max_score=max_score,
                answers_json=answers_json,
                uploaded_file=saved_filename
            )

            return self.send_json({
                "success": True,
                "message": "تم تسليم إجابتك في الامتحان بنجاح وحفظها في سجل المشرف 🚀",
                "score": score,
                "max_score": max_score,
                "submission_id": save_res.get("submission_id")
            })

        return self.send_json({"error": "Endpoint not found"}, status=404)

def run_server():
    db.init_db()
    server_address = ('', PORT)
    httpd = HTTPServer(server_address, PythonLearningHandler)
    print("==================================================")
    print(f"Python Mastery Platform running on PORT {PORT} (Phase 5 Secured)")
    print(f"Open in browser: http://localhost:{PORT}")
    print("==================================================")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server...")
        httpd.server_close()

if __name__ == "__main__":
    run_server()
