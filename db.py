import sqlite3
import os
import json

DB_FILE = "progress.db"

def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS completed_tasks (
                task_id TEXT PRIMARY KEY,
                lesson_id TEXT NOT NULL,
                completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS completed_lessons (
                lesson_id TEXT PRIMARY KEY,
                completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()

def mark_task_done(task_id, lesson_id):
    with get_db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO completed_tasks (task_id, lesson_id) VALUES (?, ?)",
            (task_id, lesson_id)
        )
        conn.commit()

def mark_lesson_done(lesson_id):
    with get_db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO completed_lessons (lesson_id) VALUES (?)",
            (lesson_id,)
        )
        conn.commit()

def get_completed_task_ids():
    with get_db() as conn:
        rows = conn.execute("SELECT task_id FROM completed_tasks").fetchall()
        return set(row["task_id"] for row in rows)

def get_completed_lesson_ids():
    with get_db() as conn:
        rows = conn.execute("SELECT lesson_id FROM completed_lessons").fetchall()
        return set(row["lesson_id"] for row in rows)

def reset_all_progress():
    with get_db() as conn:
        conn.execute("DELETE FROM completed_tasks")
        conn.execute("DELETE FROM completed_lessons")
        conn.commit()
