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
            return self.send_json(state)

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
            
            tasks = []
            for t in lesson.get("tasks", []):
                t_copy = dict(t)
                t_copy["completed"] = t["id"] in completed_tasks
                tasks.append(t_copy)

            cumulative_tasks = []
            for ct in lesson.get("cumulative_tasks", []):
                ct_copy = dict(ct)
                ct_copy["completed"] = ct["id"] in completed_tasks
                cumulative_tasks.append(ct_copy)

            response_data = dict(lesson)
            response_data["tasks"] = tasks
            response_data["cumulative_tasks"] = cumulative_tasks
            response_data["is_completed"] = lesson_status["completed"]
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

            # Auto-login with persistent cookie (30 days)
            login_res = db.authenticate_user(username, password, ip_address=client_ip)
            cookie = f"session={login_res['session_token']}; Path=/; Max-Age=2592000; HttpOnly; SameSite=Lax"
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

            # Persistent cookie (30 days)
            cookie = f"session={login_res['session_token']}; Path=/; Max-Age=2592000; HttpOnly; SameSite=Lax"
            return self.send_json(login_res, status=200, set_cookie=cookie)

        # 5. Auth: Logout
        if path == "/api/auth/logout":
            if session_token:
                db.delete_session(session_token)
            cookie = "session=; Path=/; Expires=Thu, 01 Jan 1970 00:00:00 GMT"
            return self.send_json({"success": True}, status=200, set_cookie=cookie)

        # 6. Authorization Guard: Endpoints requiring active login
        if path in ("/api/submit-task", "/api/reset", "/api/admin/delete-user", "/api/upload-submission"):
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

            if len(code) > 10000:
                return self.send_json({"passed": False, "feedback": "حجم الكود تجاوز الحد الأقصى المسموح به."}, status=400)

            lesson = engine.get_lesson_by_id(lesson_id)
            if not lesson:
                return self.send_json({"passed": False, "feedback": "الدرس غير موجود"}, status=404)

            all_tasks = lesson.get("tasks", []) + lesson.get("cumulative_tasks", [])
            target_task = next((t for t in all_tasks if t["id"] == task_id), None)
            
            if not target_task:
                return self.send_json({"passed": False, "feedback": "المهمة غير موجودة"}, status=404)

            eval_res = engine.evaluate_task(target_task, code)
            
            # Record submission for the admin dashboard to inspect actual code, timestamp, user, and status
            db.record_task_submission(
                user_id=current_user["id"],
                task_id=task_id,
                lesson_id=lesson_id,
                code=code,
                passed=eval_res["passed"],
                output=eval_res.get("output", "")
            )

            if eval_res["passed"]:
                db.mark_task_done(current_user["id"], task_id, lesson_id)
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
