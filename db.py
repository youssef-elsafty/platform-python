"""
Universal Database Access Layer (PostgreSQL & SQLite Fallback)
Features:
- Connects to PostgreSQL via DATABASE_URL if provided (with connection pooling)
- Automatically applies schema migrations
- Seamless fallback to local SQLite for lightweight local offline development
- Full Transactions, Parameterized Queries, and Foreign Keys support
"""

import os
import sqlite3
import hashlib
import hmac
import secrets
import uuid

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

# Check if psycopg2 or psycopg is available for PostgreSQL
PG_AVAILABLE = False
pg_pool = None

if DATABASE_URL.startswith("postgres://") or DATABASE_URL.startswith("postgresql://"):
    # Fix Render/Heroku postgres:// URLs to postgresql://
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    try:
        import psycopg2
        from psycopg2 import pool
        from psycopg2.extras import RealDictCursor
        pg_pool = pool.SimpleConnectionPool(1, 20, DATABASE_URL)
        PG_AVAILABLE = True
        print("Connected to PostgreSQL Connection Pool successfully.")
    except Exception as e:
        print(f"Warning: PostgreSQL configured but failed to initialize driver/connection: {e}")
        print("Falling back to local SQLite.")
        PG_AVAILABLE = False

SQLITE_FILE = "progress.db"

class DBConnection:
    def __init__(self):
        self.is_pg = PG_AVAILABLE
        self.conn = None

    def __enter__(self):
        if self.is_pg:
            self.conn = pg_pool.getconn()
            return self
        else:
            self.conn = sqlite3.connect(SQLITE_FILE)
            self.conn.row_factory = sqlite3.Row
            return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.conn:
            if exc_type:
                self.conn.rollback()
            else:
                self.conn.commit()

            if self.is_pg:
                pg_pool.putconn(self.conn)
            else:
                self.conn.close()

    def execute(self, query: str, params: tuple = ()):
        if self.is_pg:
            # Replace sqlite ? with postgres %s
            pg_query = query.replace("?", "%s")
            cur = self.conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(pg_query, params)
            return cur
        else:
            return self.conn.execute(query, params)

    def fetchone(self, query: str, params: tuple = ()):
        cursor = self.execute(query, params)
        row = cursor.fetchone()
        if cursor and hasattr(cursor, "close"):
            cursor.close()
        return dict(row) if row else None

    def fetchall(self, query: str, params: tuple = ()):
        cursor = self.execute(query, params)
        rows = cursor.fetchall()
        if cursor and hasattr(cursor, "close"):
            cursor.close()
        return [dict(r) for r in rows]

def get_db():
    return DBConnection()

# Password Hashing using PBKDF2-HMAC-SHA256
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
    """Initializes schema and runs migrations"""
    with get_db() as db:
        if db.is_pg:
            # Read migration 001
            migration_path = os.path.join(os.path.dirname(__file__), "migrations", "001_initial_schema.sql")
            if os.path.exists(migration_path):
                with open(migration_path, "r", encoding="utf-8") as f:
                    db.conn.cursor().execute(f.read())
        else:
            # SQLite Schema
            db.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    email TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            db.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_token TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
                )
            """)
            db.execute("""
                CREATE TABLE IF NOT EXISTS completed_tasks (
                    user_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    lesson_id TEXT NOT NULL,
                    completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, task_id),
                    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
                )
            """)
            db.execute("""
                CREATE TABLE IF NOT EXISTS completed_lessons (
                    user_id TEXT NOT NULL,
                    lesson_id TEXT NOT NULL,
                    completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, lesson_id),
                    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
                )
            """)

# User Operations
def create_user(username: str, email: str, password: str):
    user_id = str(uuid.uuid4())
    p_hash = hash_password(password)
    try:
        with get_db() as db:
            db.execute(
                "INSERT INTO users (id, username, email, password_hash) VALUES (?, ?, ?, ?)",
                (user_id, username.strip(), email.strip().lower(), p_hash)
            )
        return {"success": True, "user": {"id": user_id, "username": username, "email": email}}
    except Exception as e:
        err = str(e).lower()
        if "unique" in err or "duplicate" in err:
            if "username" in err:
                return {"success": False, "error": "اسم المستخدم مسجل بالفعل"}
            return {"success": False, "error": "البريد الإلكتروني مسجل بالفعل"}
        return {"success": False, "error": f"حدث خطأ أثناء التسجيل: {str(e)}"}

def authenticate_user(username_or_email: str, password: str):
    identifier = username_or_email.strip().lower()
    with get_db() as db:
        user = db.fetchone(
            "SELECT id, username, email, password_hash FROM users WHERE LOWER(username) = ? OR LOWER(email) = ?",
            (identifier, identifier)
        )
        
        if not user or not verify_password(user["password_hash"], password):
            return {"success": False, "error": "اسم المستخدم أو كلمة المرور غير صحيحة"}

        token = secrets.token_urlsafe(32)
        db.execute("INSERT INTO sessions (session_token, user_id) VALUES (?, ?)", (token, user["id"]))

        return {
            "success": True,
            "session_token": token,
            "user": {
                "id": user["id"],
                "username": user["username"],
                "email": user["email"]
            }
        }

def get_user_by_session(token: str):
    if not token:
        return None
    with get_db() as db:
        return db.fetchone("""
            SELECT u.id, u.username, u.email 
            FROM sessions s
            JOIN users u ON s.user_id = u.id
            WHERE s.session_token = ?
        """, (token,))

def delete_session(token: str):
    if not token:
        return
    with get_db() as db:
        db.execute("DELETE FROM sessions WHERE session_token = ?", (token,))

# Progress Tracking Operations
def mark_task_done(user_id: str, task_id: str, lesson_id: str):
    with get_db() as db:
        if db.is_pg:
            db.execute("""
                INSERT INTO completed_tasks (user_id, task_id, lesson_id)
                VALUES (?, ?, ?)
                ON CONFLICT (user_id, task_id) DO NOTHING
            """, (user_id, task_id, lesson_id))
        else:
            db.execute(
                "INSERT OR IGNORE INTO completed_tasks (user_id, task_id, lesson_id) VALUES (?, ?, ?)",
                (user_id, task_id, lesson_id)
            )

def mark_lesson_done(user_id: str, lesson_id: str):
    with get_db() as db:
        if db.is_pg:
            db.execute("""
                INSERT INTO completed_lessons (user_id, lesson_id)
                VALUES (?, ?)
                ON CONFLICT (user_id, lesson_id) DO NOTHING
            """, (user_id, lesson_id))
        else:
            db.execute(
                "INSERT OR IGNORE INTO completed_lessons (user_id, lesson_id) VALUES (?, ?)",
                (user_id, lesson_id)
            )

def get_completed_task_ids(user_id: str):
    if not user_id:
        return set()
    with get_db() as db:
        rows = db.fetchall("SELECT task_id FROM completed_tasks WHERE user_id = ?", (user_id,))
        return set(r["task_id"] for r in rows)

def get_completed_lesson_ids(user_id: str):
    if not user_id:
        return set()
    with get_db() as db:
        rows = db.fetchall("SELECT lesson_id FROM completed_lessons WHERE user_id = ?", (user_id,))
        return set(r["lesson_id"] for r in rows)

def reset_user_progress(user_id: str):
    if not user_id:
        return
    with get_db() as db:
        db.execute("DELETE FROM completed_tasks WHERE user_id = ?", (user_id,))
        db.execute("DELETE FROM completed_lessons WHERE user_id = ?", (user_id,))
