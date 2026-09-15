-- Migration 003: Contact and Support Inquiries

CREATE TABLE IF NOT EXISTS contact_inquiries (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    contact_info TEXT NOT NULL,
    message TEXT NOT NULL,
    user_id TEXT,
    ip_address TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_contact_inquiries_created_at ON contact_inquiries (created_at);
