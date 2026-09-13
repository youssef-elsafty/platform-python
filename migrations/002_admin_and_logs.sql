-- Migration 002: Add Role and Login Activity Tracking

-- Add role to users if not exists (default: 'student', admin: 'admin')
-- For SQLite & PostgreSQL compatibility

CREATE TABLE IF NOT EXISTS login_logs (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    username TEXT NOT NULL,
    ip_address TEXT,
    login_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_login_logs_user_id ON login_logs (user_id);
CREATE INDEX IF NOT EXISTS idx_login_logs_time ON login_logs (login_time);
