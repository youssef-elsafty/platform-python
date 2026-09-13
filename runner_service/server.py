import os
import sys
import json
import subprocess
import tempfile
import urllib.parse
from http.server import HTTPServer, SimpleHTTPRequestHandler

PORT = int(os.environ.get("PORT", 8081))
RUNNER_SECRET = os.environ.get("RUNNER_SECRET", "dev_runner_secret_key_123")
SANDBOX_IMAGE = os.environ.get("SANDBOX_IMAGE", "python-sandbox:latest")

# Hard limits for sandbox container execution
EXECUTION_TIMEOUT = int(os.environ.get("EXECUTION_TIMEOUT", 4)) # seconds
MEMORY_LIMIT = os.environ.get("MEMORY_LIMIT", "128m")
CPU_LIMIT = os.environ.get("CPU_LIMIT", "0.5")
PIDS_LIMIT = os.environ.get("PIDS_LIMIT", "16")

def check_docker_available():
    try:
        res = subprocess.run(["docker", "info"], capture_output=True, timeout=2)
        return res.returncode == 0
    except Exception:
        return False

def execute_in_docker(code: str, timeout: int = 4):
    """
    Executes student code inside a strictly quarantined Docker Container:
    --network none (completely disconnected from internet/LAN)
    --read-only (immutable root filesystem)
    --tmpfs (ephemeral tmp storage only)
    --memory 128m (hard RAM ceiling)
    --cpus 0.5 (CPU quota)
    --pids-limit 16 (anti-fork-bomb)
    --cap-drop ALL (no Linux system capabilities)
    --security-opt no-new-privileges
    """
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as tf:
        tf.write(code)
        temp_file_path = tf.name

    container_name = f"sandbox_run_{os.path.basename(temp_file_path).replace('.py', '')}"
    
    # Mount only this single read-only code file to /home/sandboxuser/app/solution.py
    docker_cmd = [
        "docker", "run", "--rm",
        "--name", container_name,
        "--network", "none",
        "--read-only",
        "--memory", MEMORY_LIMIT,
        "--memory-swap", MEMORY_LIMIT,
        "--cpus", CPU_LIMIT,
        "--pids-limit", PIDS_LIMIT,
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--tmpfs", "/tmp:rw,noexec,nosuid,size=16m",
        "-v", f"{os.path.abspath(temp_file_path)}:/home/sandboxuser/app/solution.py:ro",
        SANDBOX_IMAGE
    ]

    try:
        proc = subprocess.run(
            docker_cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace"
        )
        return {
            "success": proc.returncode == 0,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "exit_code": proc.returncode,
            "mode": "docker_sandbox"
        }
    except subprocess.TimeoutExpired:
        # Force terminate runaway container if still alive
        subprocess.run(["docker", "kill", container_name], capture_output=True)
        return {
            "success": False,
            "stdout": "",
            "stderr": f"انتهى الوقت المحدد لتنفيذ الكود (Timeout: {timeout}s).",
            "exit_code": -1,
            "mode": "docker_sandbox"
        }
    except Exception as e:
        return {
            "success": False,
            "stdout": "",
            "stderr": f"خطأ في بيئة الساندبوكس: {str(e)}",
            "exit_code": -1,
            "mode": "docker_sandbox"
        }
    finally:
        if os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
            except Exception:
                pass

class RunnerServiceHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        super().end_headers()

    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            docker_ready = check_docker_available()
            return self.send_json({
                "status": "healthy",
                "service": "code_runner_service",
                "docker_available": docker_ready
            })
        return self.send_json({"error": "Not Found"}, status=404)

    def do_POST(self):
        # Security: Internal Shared Secret Auth between Web App and Runner Service
        auth_header = self.headers.get("X-Runner-Secret", "")
        if auth_header != RUNNER_SECRET:
            return self.send_json({"error": "Unauthorized: Invalid Runner Secret"}, status=401)

        if self.path == "/execute":
            content_length = int(self.headers.get('Content-Length', 0))
            payload = self.rfile.read(content_length).decode('utf-8')
            try:
                data = json.loads(payload)
            except Exception:
                return self.send_json({"error": "Invalid JSON"}, status=400)

            code = data.get("code", "")
            timeout = int(data.get("timeout", EXECUTION_TIMEOUT))

            result = execute_in_docker(code, timeout=timeout)
            return self.send_json(result)

        return self.send_json({"error": "Not Found"}, status=404)

def run_service():
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding='utf-8')
            sys.stderr.reconfigure(encoding='utf-8')
        except Exception:
            pass

    server_address = ('', PORT)
    httpd = HTTPServer(server_address, RunnerServiceHandler)
    print("==================================================")
    print(f"Runner Microservice listening on PORT {PORT}")
    print(f"Docker available: {check_docker_available()}")
    print("==================================================")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.server_close()

if __name__ == "__main__":
    run_service()
