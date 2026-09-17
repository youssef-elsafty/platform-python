-- Migration 007: User Saved Code & Task Status Controls
CREATE TABLE IF NOT EXISTS user_saved_code (
    user_id VARCHAR(64) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    task_id VARCHAR(128) NOT NULL,
    code TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, task_id)
);

CREATE TABLE IF NOT EXISTS task_status_controls (
    task_id VARCHAR(128) PRIMARY KEY,
    is_open BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE users ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE;
