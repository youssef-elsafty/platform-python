-- Migration 004: Task Submissions History and Solutions
-- Stores all submitted solutions (code, pass/fail status, output, error, timestamp)

CREATE TABLE IF NOT EXISTS task_submissions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    lesson_id TEXT NOT NULL,
    code TEXT NOT NULL,
    passed BOOLEAN NOT NULL DEFAULT TRUE,
    output TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_task_submissions_user_id ON task_submissions (user_id);
CREATE INDEX IF NOT EXISTS idx_task_submissions_created_at ON task_submissions (created_at);
