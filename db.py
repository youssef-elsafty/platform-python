import sqlite3
import os
import hashlib
import hmac
import secrets
import uuid
import datetime

DB_FILE = "progress.db"

def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

# Secure Password Hashing using PBKDF2-HMAC-SHA256 (Standard secure library built-in)
def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100000)
    return f"{salt}:{key.hex()}"

def verify_password(stored_password_hash: str, provided_password: str) -> bool:
    try:
        salt, key_hex = stored_password_hash.split(":")
        new_key = hashlib.pbkdf2_hmac("sha256", provided_password.encode("utf-8"), salt.encode("utf-8"), 100000)
        return hmac.compare_digest(new_key.hex(), key_hex)
    except Exception:
        return False

def init_db():
    with get_db() as conn:
        # Users Table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # User Sessions Table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_token TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
            )
        """)
        # User Completed Tasks Table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS completed_tasks (
                user_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                lesson_id TEXT NOT NULL,
                completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, task_id),
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
            )
        """)
        # User Completed Lessons Table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS completed_lessons (
                user_id TEXT NOT NULL,
                lesson_id TEXT NOT NULL,
                completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, lesson_id),
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
            )
        """)
        conn.commit()

# User Management
def create_user(username, email, password):
    user_id = str(uuid.uuid4())
    p_hash = hash_password(password)
    try:
        with get_db() as conn:
            conn.execute(
                "INSERT INTO users (id, username, email, password_hash) VALUES (?, ?, ?, ?)",
                (user_id, username.strip(), email.strip().lower(), p_hash)
            )
            conn.commit()
        return {"success": True, "user": {"id": user_id, "username": username, "email": email}}
    except sqlite3.IntegrityError as e:
        err_msg = str(e).lower()
        if "username" in err_msg:
            return {"success": False, "error": "اسم المستخدم مسجل بالفعل"}
        if "email" in err_msg:
            return {"success": False, "error": "البريد الإلكتروني مسجل بالفعل"}
        return {"success": False, "error": "حدث خطأ أثناء إنشاء الحساب"}

def authenticate_user(username_or_email, password):
    identifier = username_or_email.strip().lower()
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE LOWER(username) = ? OR LOWER(email) = ?",
            (identifier, identifier)
        ).fetchone()
        
        if not row:
            return {"success": False, "error": "اسم المستخدم أو كلمة المرور غير صحيحة"}
        
        if not verify_password(row["password_hash"], password):
            return {"success": False, "error": "اسم المستخدم أو كلمة المرور غير صحيحة"}

        token = secrets.token_urlsafe(32)
        conn.execute("INSERT INTO sessions (session_token, user_id) VALUES (?, ?)", (token, row["id"]))
        conn.commit()

        return {
            "success": True,
            "session_token": token,
            "user": {
                "id": row["id"],
                "username": row["username"],
                "email": row["email"]
            }
        }

def get_user_by_session(token):
    if not token:
        return None
    with get_db() as conn:
        row = conn.execute("""
            SELECT u.id, u.username, u.email 
            FROM sessions s
            JOIN users u ON s.user_id = u.id
            WHERE s.session_token = ?
        """, (token,)).fetchone()
        if row:
            return dict(row)
    return None

def delete_session(token):
    if not token:
        return
    with get_db() as conn:
        conn.execute("DELETE FROM sessions WHERE session_token = ?", (token,))
        conn.commit()

# Progress tracking PER USER
def mark_task_done(user_id, task_id, lesson_id):
    with get_db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO completed_tasks (user_id, task_id, lesson_id) VALUES (?, ?, ?)",
            (user_id, task_id, lesson_id)
        )
        conn.commit()

def mark_lesson_done(user_id, lesson_id):
    with get_db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO completed_lessons (user_id, lesson_id) VALUES (?, ?)",
            (user_id, lesson_id)
        )
        conn.commit()

def get_completed_task_ids(user_id):
    if not user_id:
        return set()
    with get_db() as conn:
        rows = conn.execute("SELECT task_id FROM completed_tasks WHERE user_id = ?", (user_id,)).fetchall()
        return set(row["task_id"] for row in rows)

def get_completed_lesson_ids(user_id):
    if not user_id:
        return set()
    with get_db() as conn:
        rows = conn.execute("SELECT lesson_id FROM completed_lessons WHERE user_id = ?", (user_id,)).fetchall()
        return set(row["lesson_id"] for row in rows)

def reset_user_progress(user_id):
    if not user_id:
        return
    with get_db() as conn:
        conn.execute("DELETE FROM completed_tasks WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM completed_lessons WHERE user_id = ?", (user_id,))
        conn.commit()
