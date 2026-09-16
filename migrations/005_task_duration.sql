-- Migration 005: Task Duration Tracking
-- Tracks how many seconds a student spent solving a task

ALTER TABLE task_submissions ADD COLUMN IF NOT EXISTS duration_seconds INTEGER DEFAULT 0;
ALTER TABLE completed_tasks ADD COLUMN IF NOT EXISTS duration_seconds INTEGER DEFAULT 0;
