"""Auth blueprint: login, logout, current user, password change."""
import time
from flask import Blueprint, request, jsonify, session
from werkzeug.security import check_password_hash
from bcrypt import hashpw, checkpw, gensalt

from ._common import get_db, row, current_user, audit

bp = Blueprint("auth", __name__)

# Rate limiter storage - in-memory tracking of failed login attempts
_login_failures = {}

def _is_rate_limited(ip: str, max_attempts: int = 5, window_seconds: int = 300) -> bool:
    """Check if IP has exceeded failed login attempt limit."""
    now = time.time()
    if ip not in _login_failures:
        return False
    # Clean old attempts
    _login_failures[ip] = [t for t in _login_failures[ip] if now - t < window_seconds]
    return len(_login_failures[ip]) >= max_attempts

def _record_failed_attempt(ip: str):
    now = time.time()
    if ip not in _login_failures:
        _login_failures[ip] = []
    _login_failures[ip].append(now)

def _clear_failed_attempts(ip: str):
    _login_failures.pop(ip, None)


@bp.route("/api/login", methods=["POST"])
def login():
    # Disable CSRF check for API login endpoint
    if request.headers.get("X-CSRF-Token") or request.is_json:
        request.environ["FLASK_WTF_CSRF_ENABLED"] = False
    # Rate limiting by IP
    client_ip = request.remote_addr or "unknown"
    if _is_rate_limited(client_ip):
        return jsonify({"error": "Too many failed login attempts. Please try again later."}), 429

    data = request.get_json(force=True)
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    if not username or not password:
        return jsonify({"error": "username and password required"}), 400
    conn = get_db()
    try:
        u = row(conn, "SELECT * FROM users WHERE username = ?", (username,))
        if not u or not u["active"]:
            _record_failed_attempt(client_ip)
            return jsonify({"error": "invalid credentials"}), 401
        # Check password hash - support multiple formats
        pwd_hash = u["password"]
        valid = False
        if pwd_hash.startswith("$2b$") or pwd_hash.startswith("$2a$"):
            # bcrypt format
            valid = checkpw(password.encode('utf-8'), pwd_hash.encode('utf-8'))
        else:
            # werkzeug formats: pbkdf2:sha256, scrypt, argon2
            valid = check_password_hash(pwd_hash, password)

        if not valid:
            _record_failed_attempt(client_ip)
            return jsonify({"error": "invalid credentials"}), 401

        # Clear failed login attempts counter on successful login
        _clear_failed_attempts(client_ip)

        # Security: Regenerate session to prevent fixation
        session.clear()
        session["user_id"] = u["id"]
        out = dict(u)
        out.pop("password", None)
        return jsonify({"ok": True, "user": out})
    finally:
        conn.close()


@bp.route("/api/me/change-password", methods=["POST"])
def change_password():
    u = current_user()
    if not u:
        return jsonify({"error": "not logged in"}), 401

    d = request.get_json(force=True)
    old_pwd = d.get("old_password")
    new_pwd = d.get("new_password")

    if not old_pwd or not new_pwd:
        return jsonify({"error": "old and new passwords required"}), 400

    if len(new_pwd) < 6:
        return jsonify({"error": "new password too short (min 6)"}), 400

    # Verify old password
    pwd_hash = u["password"]
    if pwd_hash.startswith("$2b$") or pwd_hash.startswith("$2a$"):
        if not checkpw(old_pwd.encode('utf-8'), pwd_hash.encode('utf-8')):
            return jsonify({"error": "incorrect old password"}), 401
    else:
        from werkzeug.security import check_password_hash
        if not check_password_hash(pwd_hash, old_pwd):
            return jsonify({"error": "incorrect old password"}), 401

    # Hash and save new password
    new_hash = hashpw(new_pwd.encode('utf-8'), gensalt()).decode('utf-8')
    conn = get_db()
    try:
        conn.execute("UPDATE users SET password = ? WHERE id = ?", (new_hash, u["id"]))
        audit(conn, u["id"], u["branch_id"], "change_password", "users", u["id"])
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


@bp.route("/api/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"ok": True})


@bp.route("/api/me", methods=["GET"])
def me():
    u = current_user()
    if not u:
        return jsonify({"error": "not logged in"}), 401
    out = dict(u)
    out.pop("password", None)
    return jsonify({"ok": True, "user": out})


@bp.route("/api/csrf-token", methods=["GET"])
def get_csrf_token():
    """Endpoint to provide CSRF token for static HTML pages."""
    from flask_wtf.csrf import generate_csrf
    return jsonify({"token": generate_csrf()})