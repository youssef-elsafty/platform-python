import os
import sys
import json
import urllib.parse
from http.server import HTTPServer, SimpleHTTPRequestHandler
import db
import engine

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

PORT = int(os.environ.get("PORT", 8080))

class PythonLearningHandler(SimpleHTTPRequestHandler):
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
        super().end_headers()
        self.wfile.write(response_bytes)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/" or path == "/index.html":
            self.path = "/templates/index.html"
            return super().do_GET()

        current_user = self.get_current_user()

        # Auth state check
        if path == "/api/auth/me":
            if current_user:
                return self.send_json({"authenticated": True, "user": current_user})
            return self.send_json({"authenticated": False, "user": None})

        # Platform status for logged in user (or guest)
        if path == "/api/status":
            uid = current_user["id"] if current_user else None
            state = engine.get_platform_state(user_id=uid)
            state["user"] = current_user
            return self.send_json(state)

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

        return super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        
        content_length = int(self.headers.get('Content-Length', 0))
        post_body = self.rfile.read(content_length).decode('utf-8')
        
        try:
            body_data = json.loads(post_body) if post_body else {}
        except Exception:
            body_data = {}

        current_user = self.get_current_user()

        # Auth: Register
        if path == "/api/auth/register":
            username = body_data.get("username", "")
            email = body_data.get("email", "")
            password = body_data.get("password", "")
            if len(username) < 3 or len(password) < 6:
                return self.send_json({"success": False, "error": "اسم المستخدم 3 أحرف على الأقل، وكلمة المرور 6 على الأقل"}, status=400)
            
            reg_res = db.create_user(username, email, password)
            if not reg_res["success"]:
                return self.send_json(reg_res, status=400)
            
            # Auto-login after registration
            login_res = db.authenticate_user(username, password)
            cookie = f"session={login_res['session_token']}; Path=/; HttpOnly; SameSite=Lax"
            return self.send_json(login_res, status=200, set_cookie=cookie)

        # Auth: Login
        if path == "/api/auth/login":
            username_or_email = body_data.get("username_or_email", "")
            password = body_data.get("password", "")
            login_res = db.authenticate_user(username_or_email, password)
            if not login_res["success"]:
                return self.send_json(login_res, status=401)
            
            cookie = f"session={login_res['session_token']}; Path=/; HttpOnly; SameSite=Lax"
            return self.send_json(login_res, status=200, set_cookie=cookie)

        # Auth: Logout
        if path == "/api/auth/logout":
            token = self.get_session_token()
            db.delete_session(token)
            cookie = "session=; Path=/; Expires=Thu, 01 Jan 1970 00:00:00 GMT"
            return self.send_json({"success": True}, status=200, set_cookie=cookie)

        # Reset Progress for current authenticated user
        if path == "/api/reset":
            if current_user:
                db.reset_user_progress(current_user["id"])
            return self.send_json({"success": True, "message": "تم إعادة ضبط التقدم بنجاح"})

        # Run code (Test only)
        if path == "/api/run":
            code = body_data.get("code", "")
            result = engine.execute_code_safely(code)
            return self.send_json(result)

        # Submit task
        if path == "/api/submit-task":
            lesson_id = body_data.get("lesson_id")
            task_id = body_data.get("task_id")
            code = body_data.get("code", "")

            lesson = engine.get_lesson_by_id(lesson_id)
            if not lesson:
                return self.send_json({"passed": False, "feedback": "الدرس غير موجود"}, status=404)

            all_tasks = lesson.get("tasks", []) + lesson.get("cumulative_tasks", [])
            target_task = next((t for t in all_tasks if t["id"] == task_id), None)
            
            if not target_task:
                return self.send_json({"passed": False, "feedback": "المهمة غير موجودة"}, status=404)

            eval_res = engine.evaluate_task(target_task, code)
            if eval_res["passed"]:
                uid = current_user["id"] if current_user else None
                if uid:
                    db.mark_task_done(uid, task_id, lesson_id)
                state = engine.get_platform_state(user_id=uid)
                lesson_status = next((l for l in state["lessons"] if l["id"] == lesson_id), None)
                eval_res["lesson_completed"] = lesson_status["completed"] if lesson_status else False
            else:
                eval_res["lesson_completed"] = False

            return self.send_json(eval_res)

        return self.send_json({"error": "Endpoint not found"}, status=404)

def run_server():
    db.init_db()
    server_address = ('', PORT)
    httpd = HTTPServer(server_address, PythonLearningHandler)
    print("==================================================")
    print(f"Python Learning Platform is running on PORT {PORT}!")
    print(f"Open in browser: http://localhost:{PORT}")
    print("==================================================")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server...")
        httpd.server_close()

if __name__ == "__main__":
    run_server()
