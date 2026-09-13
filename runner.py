"""
Isolated and Secure Code Runner
Enforces:
1. Static Analysis (AST guard): Blocks dangerous modules (os, sys, subprocess, shutil, socket, etc.)
   and dangerous built-in functions (eval, exec, compile, open, __import__, etc.).
2. Resource Restrictions: Code length limits and execution timeout.
3. Isolated Subprocess with unbuffered, clean environment without inherited parent privileges.
"""

import ast
import subprocess
import sys
import tempfile
import os
import json
import urllib.request
import urllib.error

RUNNER_URL = os.environ.get("RUNNER_URL", "").rstrip("/")
RUNNER_SECRET = os.environ.get("RUNNER_SECRET", "dev_runner_secret_key_123")


# Maximum permitted character length for submitted code
MAX_CODE_LENGTH = 10000

# Forbidden modules that could interact with OS, files, networks, or processes
FORBIDDEN_MODULES = {
    "os", "sys", "subprocess", "shutil", "socket", "urllib", "requests",
    "http", "ftplib", "smtplib", "telnetlib", "ssl", "pathlib", "glob",
    "posix", "nt", "importlib", "pip", "pty", "commands", "ctypes",
    "multiprocessing", "threading", "asyncio", "signal", "inspect",
    "pdb", "trace", "webbrowser", "winreg", "_winapi", "code", "codeop"
}

# Forbidden built-in functions and identifiers
FORBIDDEN_BUILTINS = {
    "eval", "exec", "compile", "__import__", "open", "input",
    "breakpoint", "help", "globals", "locals", "vars", "memoryview"
}

# Forbidden attributes / dunder lookups that try to escape sandboxes
FORBIDDEN_ATTRIBUTES = {
    "__subclasses__", "__bases__", "__mro__", "__globals__", "__code__",
    "__builtins__", "__loader__", "__spec__", "__class__"
}

class SecurityViolation(Exception):
    pass

class SafetyASTVisitor(ast.NodeVisitor):
    def visit_Import(self, node):
        for alias in node.names:
            base_mod = alias.name.split(".")[0]
            if base_mod in FORBIDDEN_MODULES:
                raise SecurityViolation(f"محاولة غير مسموح بها: استيراد المكتبة المحظورة '{alias.name}'.")
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        if node.module:
            base_mod = node.module.split(".")[0]
            if base_mod in FORBIDDEN_MODULES:
                raise SecurityViolation(f"محاولة غير مسموح بها: استيراد دوال من المكتبة المحظورة '{node.module}'.")
        self.generic_visit(node)

    def visit_Call(self, node):
        # Prevent direct calls to forbidden functions e.g. open(), eval(), exec()
        if isinstance(node.func, ast.Name):
            if node.func.id in FORBIDDEN_BUILTINS:
                raise SecurityViolation(f"محاولة غير مسموح بها: استخدام الدالة المحظورة '{node.func.id}()'.")
        self.generic_visit(node)

    def visit_Attribute(self, node):
        # Prevent sandbox escapes via dunder lookups (e.g. obj.__class__.__subclasses__())
        if node.attr in FORBIDDEN_ATTRIBUTES:
            raise SecurityViolation(f"محاولة غير مسموح بها: الوصول للخاصية المحظورة '{node.attr}'.")
        self.generic_visit(node)

def validate_code_safety(code: str):
    """Parses code into AST and performs strict structural security validation."""
    if len(code) > MAX_CODE_LENGTH:
        return False, f"حجم الكود كبير جداً! الحد الأقصى المسموح به هو {MAX_CODE_LENGTH} حرف."
    
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        # Let Python runtime handle standard syntax errors cleanly
        return True, ""
    
    visitor = SafetyASTVisitor()
    try:
        visitor.visit(tree)
    except SecurityViolation as sv:
        return False, str(sv)

    return True, ""

def execute_via_remote_runner(code: str, timeout: int = 4):
    """Calls the isolated Runner Microservice via HTTP API"""
    target_url = f"{RUNNER_URL}/execute"
    payload = json.dumps({"code": code, "timeout": timeout}).encode("utf-8")
    
    req = urllib.request.Request(
        target_url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "X-Runner-Secret": RUNNER_SECRET
        },
        method="POST"
    )
    
    try:
        with urllib.request.urlopen(req, timeout=timeout + 3) as response:
            result = json.loads(response.read().decode("utf-8"))
            return result
    except Exception as e:
        return {
            "success": False,
            "stdout": "",
            "stderr": f"خطأ في الاتصال بخدمة الساندبوكس: {str(e)}",
            "exit_code": -1,
            "mode": "remote_error"
        }

def run_isolated_code(code: str, timeout: int = 4):
    """
    Executes Python code.
    Checks AST safety first, then delegates to Remote Docker Runner if configured,
    otherwise runs in local protected subprocess.
    """
    is_safe, security_msg = validate_code_safety(code)
    if not is_safe:
        return {
            "success": False,
            "stdout": "",
            "stderr": f"⛔ تنبيه أمني (Security Sandbox):\n{security_msg}",
            "exit_code": -1,
            "mode": "ast_rejected"
        }

    # Production Mode: Delegate to Remote Docker Runner Service if configured
    if RUNNER_URL:
        return execute_via_remote_runner(code, timeout=timeout)

    # Restrict execution environment
    clean_env = {
        "PYTHONUNBUFFERED": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PATH": os.environ.get("PATH", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", "")
    }

    # Write code to a secure temporary file
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8-sig") as temp_file:
            temp_file.write(code)
            temp_path = temp_file.name

        proc = subprocess.run(
            [sys.executable, "-I", "-B", temp_path], # -I isolates from user environment & site-packages
            capture_output=True,
            text=True,
            timeout=timeout,
            env=clean_env,
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
            "stderr": f"انتهى الوقت المحدد لتنفيذ الكود (Timeout: {timeout}s). تأكد من عدم وجود حلقات تكرار لا نهائية (Infinite Loop).",
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
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass
