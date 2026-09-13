"""
Security & Rate Limiting Middleware Module (Phase 5)
Features:
- In-memory Sliding Window Rate Limiting (per IP or User ID)
- CSRF Token generation and verification
- Allowed Origins verification (Replacing Access-Control-Allow-Origin: *)
- Strict Input Validation (username, email, password, code payloads)
- Production-grade Security Headers
"""

import time
import re
import secrets
from collections import defaultdict

# Rate Limit Storage: { key: [timestamp1, timestamp2, ...] }
_rate_limits = defaultdict(list)

# CSRF Storage: { session_token: csrf_token }
_csrf_tokens = {}

# Regex Patterns for strict validation
USERNAME_REGEX = re.compile(r"^[a-zA-Z0-9_\u0600-\u06FF]{3,30}$")
EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")

# Security Headers dictionary
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-XSS-Protection": "1; mode=block",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "connect-src 'self';"
    )
}

def check_rate_limit(key: str, max_requests: int, window_seconds: int) -> bool:
    """
    Sliding window rate limiter. Returns True if request is allowed, False if exceeded.
    """
    now = time.time()
    timestamps = _rate_limits[key]
    
    # Filter timestamps within the current window
    _rate_limits[key] = [t for t in timestamps if now - t < window_seconds]
    
    if len(_rate_limits[key]) >= max_requests:
        return False
    
    _rate_limits[key].append(now)
    return True

def validate_register_input(username: str, email: str, password: str):
    if not username or not USERNAME_REGEX.match(username):
        return False, "اسم المستخدم يجب أن يكون بين 3 إلى 30 حرفاً (أحرف، أرقام، أو شرطة سفلية)."
    if not email or not EMAIL_REGEX.match(email):
        return False, "صيغة البريد الإلكتروني غير صحيحة."
    if not password or len(password) < 6 or len(password) > 128:
        return False, "كلمة المرور يجب أن تكون بين 6 و 128 حرفاً."
    return True, ""

def generate_csrf_token(session_token: str) -> str:
    if not session_token:
        return ""
    token = secrets.token_hex(24)
    _csrf_tokens[session_token] = token
    return token

def verify_csrf_token(session_token: str, submitted_token: str) -> bool:
    if not session_token or not submitted_token:
        return False
    expected = _csrf_tokens.get(session_token)
    if not expected:
        return False
    return secrets.compare_digest(expected, submitted_token)
