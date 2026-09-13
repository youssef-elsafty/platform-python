import os
import sys
import json
import urllib.parse
from http.server import HTTPServer, SimpleHTTPRequestHandler
import db
import engine

# Ensure UTF-8 output in Windows terminal
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

PORT = 8080

class PythonLearningHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def send_json(self, data, status=200):
        response_bytes = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(response_bytes)))
        self.end_headers()
        self.wfile.write(response_bytes)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        # Serve static frontend home
        if path == "/" or path == "/index.html":
            self.path = "/templates/index.html"
            return super().do_GET()

        # API endpoints
        if path == "/api/status":
            state = engine.get_platform_state()
            return self.send_json(state)

        if path.startswith("/api/lesson/"):
            lesson_id = path.replace("/api/lesson/", "").strip("/")
            lesson = engine.get_lesson_by_id(lesson_id)
            if not lesson:
                return self.send_json({"error": "الدرس غير موجود"}, status=404)
            
            state = engine.get_platform_state()
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

        if path == "/api/reset":
            db.reset_all_progress()
            return self.send_json({"success": True, "message": "تم إعادة ضبط التقدم بنجاح"})

        if path == "/api/run":
            code = body_data.get("code", "")
            result = engine.execute_code_safely(code)
            return self.send_json(result)

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
                db.mark_task_done(task_id, lesson_id)
                state = engine.get_platform_state()
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
