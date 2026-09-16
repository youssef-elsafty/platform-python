"""
Universal Database Access Layer (PostgreSQL & SQLite Fallback)
Features:
- Connects to PostgreSQL via DATABASE_URL if provided (with connection pooling)
- Automatically applies schema migrations
- Seamless fallback to local SQLite for lightweight local offline development
- Full Transactions, Parameterized Queries, and Foreign Keys support
- Admin Dashboard Queries and Activity Logging
"""

import os
import sqlite3
import hashlib
import hmac
import secrets
import uuid
import datetime

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

PG_AVAILABLE = False
pg_pool = None

if DATABASE_URL.startswith("postgres://") or DATABASE_URL.startswith("postgresql://"):
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
            self.conn = sqlite3.connect(SQLITE_FILE, timeout=20.0)
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
            for migration_file in ["001_initial_schema.sql", "002_admin_and_logs.sql", "003_contact_inquiries.sql", "004_task_submissions.sql", "005_task_duration.sql"]:
                m_path = os.path.join(os.path.dirname(__file__), "migrations", migration_file)
                if os.path.exists(m_path):
                    with open(m_path, "r", encoding="utf-8") as f:
                        db.conn.cursor().execute(f.read())
        else:
            db.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    email TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    role TEXT DEFAULT 'student',
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
                CREATE TABLE IF NOT EXISTS login_logs (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    username TEXT NOT NULL,
                    ip_address TEXT,
                    login_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            db.execute("""
                CREATE TABLE IF NOT EXISTS completed_tasks (
                    user_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    lesson_id TEXT NOT NULL,
                    duration_seconds INTEGER DEFAULT 0,
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
            db.execute("""
                CREATE TABLE IF NOT EXISTS contact_inquiries (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    contact_info TEXT NOT NULL,
                    message TEXT NOT NULL,
                    user_id TEXT,
                    ip_address TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            db.execute("""
                CREATE TABLE IF NOT EXISTS task_submissions (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    lesson_id TEXT NOT NULL,
                    code TEXT NOT NULL,
                    passed BOOLEAN NOT NULL DEFAULT 1,
                    output TEXT,
                    duration_seconds INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
                )
            """)
            db.execute("""
                CREATE TABLE IF NOT EXISTS uploaded_submissions (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    task_id TEXT,
                    lesson_id TEXT,
                    original_filename TEXT NOT NULL,
                    saved_filename TEXT NOT NULL,
                    file_size INTEGER NOT NULL,
                    notes TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
                )
            """)

            # Safe SQLite migration for existing databases
            try:
                cols_ts = [c[1] for c in db.conn.execute("PRAGMA table_info(task_submissions)").fetchall()]
                if "duration_seconds" not in cols_ts:
                    db.conn.execute("ALTER TABLE task_submissions ADD COLUMN duration_seconds INTEGER DEFAULT 0")
                cols_ct = [c[1] for c in db.conn.execute("PRAGMA table_info(completed_tasks)").fetchall()]
                if "duration_seconds" not in cols_ct:
                    db.conn.execute("ALTER TABLE completed_tasks ADD COLUMN duration_seconds INTEGER DEFAULT 0")
            except Exception as e:
                print(f"Notice during SQLite duration migration: {e}")

        # Ensure default admin account exists: youssef / admin123
        admin = db.fetchone("SELECT id FROM users WHERE LOWER(username) = ?", ("youssef",))
        if not admin:
            admin_id = str(uuid.uuid4())
            admin_hash = hash_password("admin123")
            db.execute(
                "INSERT INTO users (id, username, email, password_hash, role) VALUES (?, ?, ?, ?, ?)",
                (admin_id, "youssef", "admin@pythonmastery.com", admin_hash, "admin")
            )

def create_user(username: str, email: str, password: str, role: str = "student"):
    user_id = str(uuid.uuid4())
    p_hash = hash_password(password)
    try:
        with get_db() as db:
            db.execute(
                "INSERT INTO users (id, username, email, password_hash, role) VALUES (?, ?, ?, ?, ?)",
                (user_id, username.strip(), email.strip().lower(), p_hash, role)
            )
        return {"success": True, "user": {"id": user_id, "username": username, "email": email, "role": role}}
    except Exception as e:
        err = str(e).lower()
        if "unique" in err or "duplicate" in err:
            if "username" in err:
                return {"success": False, "error": "اسم المستخدم مسجل بالفعل"}
            return {"success": False, "error": "البريد الإلكتروني مسجل بالفعل"}
        return {"success": False, "error": f"حدث خطأ أثناء التسجيل: {str(e)}"}

def log_login_event(user_id: str, username: str, ip_address: str):
    try:
        log_id = str(uuid.uuid4())
        with get_db() as db:
            db.execute(
                "INSERT INTO login_logs (id, user_id, username, ip_address) VALUES (?, ?, ?, ?)",
                (log_id, user_id, username, ip_address)
            )
    except Exception as e:
        print(f"Error logging login event: {e}")

def authenticate_user(username_or_email: str, password: str, ip_address: str = "127.0.0.1"):
    identifier = username_or_email.strip().lower()
    with get_db() as db:
        user = db.fetchone(
            "SELECT id, username, email, password_hash, role FROM users WHERE LOWER(username) = ? OR LOWER(email) = ?",
            (identifier, identifier)
        )
        
        if not user or not verify_password(user["password_hash"], password):
            return {"success": False, "error": "اسم المستخدم أو كلمة المرور غير صحيحة"}

        token = secrets.token_urlsafe(32)
        db.execute("INSERT INTO sessions (session_token, user_id) VALUES (?, ?)", (token, user["id"]))
        
        # Log this successful login directly within the connection
        log_id = str(uuid.uuid4())
        db.execute(
            "INSERT INTO login_logs (id, user_id, username, ip_address) VALUES (?, ?, ?, ?)",
            (log_id, user["id"], user["username"], ip_address)
        )

        return {
            "success": True,
            "session_token": token,
            "user": {
                "id": user["id"],
                "username": user["username"],
                "email": user["email"],
                "role": user.get("role", "student")
            }
        }

def get_user_by_session(token: str):
    if not token:
        return None
    with get_db() as db:
        return db.fetchone("""
            SELECT u.id, u.username, u.email, u.role 
            FROM sessions s
            JOIN users u ON s.user_id = u.id
            WHERE s.session_token = ?
        """, (token,))

def delete_session(token: str):
    if not token:
        return
    with get_db() as db:
        db.execute("DELETE FROM sessions WHERE session_token = ?", (token,))

def mark_task_done(user_id: str, task_id: str, lesson_id: str, duration_seconds: int = 0):
    with get_db() as db:
        if db.is_pg:
            db.execute("""
                INSERT INTO completed_tasks (user_id, task_id, lesson_id, duration_seconds)
                VALUES (?, ?, ?, ?)
                ON CONFLICT (user_id, task_id) DO UPDATE SET duration_seconds = EXCLUDED.duration_seconds
            """, (user_id, task_id, lesson_id, duration_seconds))
        else:
            db.execute("""
                INSERT INTO completed_tasks (user_id, task_id, lesson_id, duration_seconds)
                VALUES (?, ?, ?, ?)
                ON CONFLICT (user_id, task_id) DO UPDATE SET duration_seconds = excluded.duration_seconds
            """, (user_id, task_id, lesson_id, duration_seconds))

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

def get_user_avg_solve_seconds(user_id: str):
    if not user_id:
        return 0
    with get_db() as db:
        res = db.fetchone("SELECT ROUND(AVG(duration_seconds), 1) as avg_sec FROM task_submissions WHERE user_id = ? AND passed = 1 AND duration_seconds > 0", (user_id,))
        return res["avg_sec"] if res and res["avg_sec"] is not None else 0

def record_task_submission(user_id: str, task_id: str, lesson_id: str, code: str, passed: bool, output: str = "", duration_seconds: int = 0):
    sub_id = str(uuid.uuid4())
    try:
        with get_db() as db:
            db.execute("""
                INSERT INTO task_submissions (id, user_id, task_id, lesson_id, code, passed, output, duration_seconds)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (sub_id, user_id, task_id, lesson_id, code, 1 if passed else 0, output[:2000] if output else "", duration_seconds))
    except Exception as e:
        print(f"Error recording task submission: {e}")

# ================= ADMIN DASHBOARD QUERIES =================
def get_admin_dashboard_stats():
    with get_db() as db:
        total_users = db.fetchone("SELECT COUNT(*) as count FROM users")["count"]
        total_tasks_solved = db.fetchone("SELECT COUNT(*) as count FROM completed_tasks")["count"]
        total_lessons_completed = db.fetchone("SELECT COUNT(*) as count FROM completed_lessons")["count"]
        total_inquiries = db.fetchone("SELECT COUNT(*) as count FROM contact_inquiries")["count"]
        
        # Average solve time across all passed tasks
        avg_solve_res = db.fetchone("SELECT ROUND(AVG(duration_seconds), 1) as avg_sec FROM task_submissions WHERE passed = 1 AND duration_seconds > 0")
        avg_solve_seconds = avg_solve_res["avg_sec"] if avg_solve_res and avg_solve_res["avg_sec"] is not None else 0

        # Recent Logins (Who logged in, when, from which IP)
        recent_logins = db.fetchall("""
            SELECT username, ip_address, login_time 
            FROM login_logs 
            ORDER BY rowid DESC 
            LIMIT 25
        """)

        # Student Progress Overview
        students = db.fetchall("""
            SELECT 
                u.id, 
                u.username, 
                u.email, 
                u.role,
                u.created_at,
                (SELECT COUNT(*) FROM completed_tasks ct WHERE ct.user_id = u.id) as solved_tasks,
                (SELECT COUNT(*) FROM completed_lessons cl WHERE cl.user_id = u.id) as finished_lessons,
                (SELECT MAX(login_time) FROM login_logs ll WHERE ll.user_id = u.id) as last_login,
                (SELECT ROUND(AVG(ts.duration_seconds), 1) FROM task_submissions ts WHERE ts.user_id = u.id AND ts.passed = 1 AND ts.duration_seconds > 0) as avg_solve_seconds
            FROM users u
            ORDER BY u.created_at DESC
        """)

        # Recent Task Solutions Submitted (Who solved what, the actual python code, timestamp, duration_seconds)
        task_submissions = db.fetchall("""
            SELECT 
                ts.id,
                ts.user_id,
                u.username,
                ts.task_id,
                ts.lesson_id,
                ts.code,
                ts.passed,
                ts.output,
                COALESCE(ts.duration_seconds, 0) as duration_seconds,
                ts.created_at
            FROM task_submissions ts
            JOIN users u ON ts.user_id = u.id
            ORDER BY ts.created_at DESC
            LIMIT 50
        """)

        # Recent Contact Inquiries (Calls / Messages)
        inquiries = db.fetchall("""
            SELECT id, name, contact_info, message, user_id, ip_address, created_at
            FROM contact_inquiries
            ORDER BY created_at DESC
            LIMIT 50
        """)

        # Uploaded Submissions (Assignments / Files submitted by students)
        uploaded_submissions = db.fetchall("""
            SELECT 
                us.id,
                us.user_id,
                u.username,
                us.task_id,
                us.lesson_id,
                us.original_filename,
                us.saved_filename,
                us.file_size,
                us.notes,
                us.created_at
            FROM uploaded_submissions us
            JOIN users u ON us.user_id = u.id
            ORDER BY us.created_at DESC
            LIMIT 50
        """)

        return {
            "total_users": total_users,
            "total_tasks_solved": total_tasks_solved,
            "total_lessons_completed": total_lessons_completed,
            "total_inquiries": total_inquiries,
            "total_uploaded_submissions": len(uploaded_submissions),
            "avg_solve_seconds": avg_solve_seconds,
            "recent_logins": recent_logins,
            "students": students,
            "inquiries": inquiries,
            "task_submissions": task_submissions,
            "uploaded_submissions": uploaded_submissions
        }

def save_uploaded_submission(user_id: str, original_filename: str, saved_filename: str, file_size: int, task_id: str = None, lesson_id: str = None, notes: str = ""):
    sub_id = str(uuid.uuid4())
    try:
        with get_db() as db:
            db.execute("""
                INSERT INTO uploaded_submissions (id, user_id, task_id, lesson_id, original_filename, saved_filename, file_size, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (sub_id, user_id, task_id, lesson_id, original_filename, saved_filename, file_size, notes))
        return {"success": True, "id": sub_id}
    except Exception as e:
        print(f"Error saving uploaded submission: {e}")
        return {"success": False, "error": str(e)}

def save_contact_inquiry(name: str, contact_info: str, message: str, user_id: str = None, ip_address: str = "127.0.0.1"):
    inquiry_id = str(uuid.uuid4())
    try:
        with get_db() as db:
            db.execute("""
                INSERT INTO contact_inquiries (id, name, contact_info, message, user_id, ip_address)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (inquiry_id, name.strip(), contact_info.strip(), message.strip(), user_id, ip_address))
        return {"success": True, "message": "تم إرسال رسالتك بنجاح! سيتواصل معك البشمهندس يوسف في أقرب وقت."}
    except Exception as e:
        return {"success": False, "error": f"حدث خطأ أثناء إرسال الرسالة: {str(e)}"}

def delete_user(user_id: str):
    if not user_id:
        return {"success": False, "error": "معرف المستخدم مطلوب"}
    with get_db() as db:
        user = db.fetchone("SELECT id, role, username FROM users WHERE id = ?", (user_id,))
        if not user:
            return {"success": False, "error": "المستخدم غير موجود"}
        if user["role"] == "admin":
            return {"success": False, "error": "لا يمكن حذف حساب المشرف الرئيسي"}
        
        db.execute("DELETE FROM completed_tasks WHERE user_id = ?", (user_id,))
        db.execute("DELETE FROM completed_lessons WHERE user_id = ?", (user_id,))
        db.execute("DELETE FROM task_submissions WHERE user_id = ?", (user_id,))
        db.execute("DELETE FROM uploaded_submissions WHERE user_id = ?", (user_id,))
        db.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        db.execute("DELETE FROM login_logs WHERE user_id = ?", (user_id,))
        db.execute("DELETE FROM contact_inquiries WHERE user_id = ?", (user_id,))
        db.execute("DELETE FROM users WHERE id = ?", (user_id,))
        return {"success": True, "message": f"تم حذف المستخدم {user['username']} بنجاح"}
