import os
import re
from flask import Flask, send_from_directory, jsonify, abort, session, request, redirect
from werkzeug.middleware.proxy_fix import ProxyFix
from flask_wtf.csrf import CSRFProtect
from config import (
    BASE_DIR, STATIC_DIR, SECRET_KEY, DEBUG, HOST,
    MAX_CONTENT_LENGTH, SESSION_COOKIE_HTTPONLY,
    SESSION_COOKIE_SAMESITE, SESSION_COOKIE_SECURE,
    SESSION_REFRESH_RATE, RATELIMIT_ENABLED, RATELIMIT_DEFAULT, RATELIMIT_STORAGE_URL
)
from logging_config import setup_logging

# Allowed static files whitelist - security fix for path traversal
ALLOWED_STATIC_FILES = {
    "login.html", "index.html", "admin.html", "customers.html",
    "expenses.html", "pos.html", "products.html", "purchases.html",
    "returns.html", "shifts.html", "suppliers.html", "dashboard.html",
    "promotions.html", "adjustments.html", "reports.html", "requests.html",
    "terms.html", "privacy.html", "manifest.json", "favicon.ico", "activate.html"
}

app = Flask(__name__, static_folder=None)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
loggers = setup_logging(app)
app.secret_key = SECRET_KEY
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH
app.config['SESSION_COOKIE_HTTPONLY'] = SESSION_COOKIE_HTTPONLY
app.config['SESSION_COOKIE_SAMESITE'] = SESSION_COOKIE_SAMESITE
app.config['SESSION_COOKIE_SECURE'] = SESSION_COOKIE_SECURE
app.config['SESSION_REFRESH_RATE'] = SESSION_REFRESH_RATE
app.config['WTF_CSRF_ENABLED'] = True
app.config['WTF_CSRF_TIME_LIMIT'] = 3600 * 2

# Initialize CSRF protection
csrf = CSRFProtect(app)

# Allowed origins for CSRF exemption (for API clients)
ALLOWED_ORIGINS = {"https://pharmacy.local", "http://localhost:5000", "http://127.0.0.1:5000"}
if os.environ.get("RENDER_EXTERNAL_URL"):
    ALLOWED_ORIGINS.add(os.environ.get("RENDER_EXTERNAL_URL").rstrip("/"))

def is_allowed_origin(origin: str) -> bool:
    """Check if origin is in allowed list or matches current request host."""
    if not origin:
        return False
    if origin in ALLOWED_ORIGINS:
        return True
    try:
        from urllib.parse import urlparse
        parsed = urlparse(origin)
        if request and parsed.netloc == request.headers.get("Host"):
            return True
    except Exception:
        pass
    return False

# Security Headers Middleware
@app.after_request
def add_security_headers(response):
    """Add security headers to all responses."""
    # HSTS - Force HTTPS for 1 year (only in production)
    if not DEBUG:
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains; preload'

    # Content Security Policy
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "img-src 'self' data: https:; "
        "font-src 'self' https://cdn.jsdelivr.net; "
        "connect-src 'self' https://cdn.jsdelivr.net; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self';"
    )

    # Prevent clickjacking
    response.headers['X-Frame-Options'] = 'DENY'

    # Prevent MIME type sniffing
    response.headers['X-Content-Type-Options'] = 'nosniff'

    # XSS Protection filter
    response.headers['X-XSS-Protection'] = '1; mode=block'

    # Referrer Policy
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'

    # Permissions Policy (formerly Feature Policy)
    response.headers['Permissions-Policy'] = (
        "accelerometer=(), camera=(self), geolocation=(), gyroscope=(), "
        "magnetometer=(), microphone=(), payment=(), usb=()"
    )

    # Cache control for sensitive API endpoints (prevent browser/proxy caching of medical & financial data)
    if request.path.startswith('/api/'):
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, private'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'

    return response

# CSRF Protection for API endpoints
@app.before_request
def csrf_protect():
    """CSRF protection for state-changing API requests."""
    # Skip CSRF check for:
    # - GET, HEAD, OPTIONS (safe methods)
    # - Login/Logout endpoints (handled separately)
    # - Static files
    if request.method in ('GET', 'HEAD', 'OPTIONS'):
        return None

    if request.path.startswith('/static/') or request.path.startswith('/data/'):
        return None

    # Exempt login/logout from CSRF (pre-auth endpoints)
    if request.path in ('/api/login', '/api/logout', '/api/auth/login', '/api/auth/logout'):
        return None

    # For API endpoints, check CSRF token or Origin header
    if request.path.startswith('/api/'):
        # Check for CSRF token in header
        csrf_token = request.headers.get('X-CSRF-Token') or request.headers.get('X-CSRFToken')
        if csrf_token:
            # Validate CSRF token using Flask-WTF
            from flask_wtf.csrf import validate_csrf
            try:
                validate_csrf(csrf_token)
                return None
            except Exception:
                return jsonify({"error": "Invalid CSRF token"}), 403
        # Check for CSRF token in JSON payload (e.g., AJAX POST with JSON)
        if request.is_json:
            json_data = request.get_json(silent=True) or {}
            csrf_token = json_data.get('csrf_token') or json_data.get('csrf')
            if csrf_token:
                from flask_wtf.csrf import validate_csrf
                try:
                    validate_csrf(csrf_token)
                    return None
                except Exception:
                    return jsonify({"error": "Invalid CSRF token in JSON body"}), 403

        # Fallback: Check Origin header for same-origin requests
        origin = request.headers.get('Origin')
        referer = request.headers.get('Referer')
        host = request.headers.get('Host')

        if origin and is_allowed_origin(origin):
            return None

        if referer:
            try:
                from urllib.parse import urlparse
                parsed = urlparse(referer)
                if parsed.netloc == host:
                    return None
            except Exception:
                pass

        # If we reach here, CSRF check failed
        return jsonify({"error": "CSRF validation failed. Please include X-CSRF-Token header."}), 403

    return None

from routes._common import init_db, close_db
try:
    init_db()
except Exception as _init_err:
    loggers['error'].exception(f"Warning: initial database bootstrap failed: {_init_err}")
app.teardown_appcontext(close_db)

from licensing.manager import verify_current_license

# Explicit disable override only if manually specified (defaults to False everywhere, including cloud/web)
DISABLE_LICENSE_CHECK = os.environ.get("DISABLE_LICENSE_CHECK", "false").lower() == "true"

@app.before_request
def check_license_guard():
    if DISABLE_LICENSE_CHECK:
        return None

    path = request.path
    # Exempt unauthenticated/public static paths, activate page, and license API endpoints
    if (
        path == "/activate.html"
        or path.startswith(("/static/", "/data/", "/css/", "/js/", "/fonts/", "/img/"))
        or path.startswith("/api/license/")
        or path == "/api/csrf-token"
        or path == "/api/health"
        or path == "/api/ready"
        or path == "/favicon.ico"
    ):
        return None

    # Check license
    lic_status = verify_current_license()
    if not lic_status.get("is_valid"):
        if path.startswith("/api/"):
            return jsonify({
                "error": "LICENSE_REQUIRED",
                "message": lic_status.get("error") or "البرنامج غير مفعل أو انتهت صلاحية الترخيص",
                "redirect": "/activate.html"
            }), 403

        return redirect("/activate.html")

    return None

from routes.license import bp as license_bp
from routes.auth import bp as auth_bp
from routes.products import bp as products_bp
from routes.suppliers import bp as suppliers_bp
from routes.purchases import bp as purchases_bp
from routes.sales import bp as sales_bp
from routes.expenses import bp as expenses_bp
from routes.customers import bp as customers_bp
from routes.admin import bp as admin_bp
from routes.dashboard import bp as dashboard_bp
from routes.returns import bp as returns_bp
from routes.shifts import bp as shifts_bp
from routes.reports import bp as reports_bp
from routes.promotions import bp as promotions_bp
from routes.adjustments import bp as adjustments_bp
from routes.requests import bp as requests_bp
from routes.loyalty import bp as loyalty_bp

for _bp in (license_bp, auth_bp, products_bp, suppliers_bp, purchases_bp, sales_bp,
            expenses_bp, customers_bp, admin_bp, dashboard_bp, returns_bp, shifts_bp, reports_bp, promotions_bp, adjustments_bp, requests_bp, loyalty_bp):
    app.register_blueprint(_bp)

# Exempt pre-auth blueprints from Flask-WTF CSRFProtect
csrf.exempt(auth_bp)
csrf.exempt(license_bp)

@app.route("/data/barcodes/<path:filename>")
def serve_barcode(filename):
    filename = os.path.basename(filename)
    if not re.match(r"^\d+\.(png|svg)$", filename, re.I):
        abort(403)
    full_path = os.path.join("data/barcodes", filename)
    if os.path.exists(full_path):
        return send_from_directory("data/barcodes", filename)
    # Dynamically generate barcode if file does not exist on ephemeral cloud disk
    m = re.match(r"^(\d+)\.(png|svg)$", filename, re.I)
    if m:
        import io
        from flask import Response
        from routes._common import get_db, row
        pid = int(m.group(1))
        conn = get_db()
        try:
            p = row(conn, "SELECT barcode FROM products WHERE id = ?", (pid,))
            if p and p["barcode"]:
                from barcode import get as bc_get
                buf = io.BytesIO()
                bc_get("code128", str(p["barcode"])).write(buf)
                buf.seek(0)
                return Response(buf.read(), mimetype="image/svg+xml")
        except Exception:
            pass
        finally:
            conn.close()
    abort(404)


@app.route("/")
def index():
    return send_from_directory(STATIC_DIR, "login.html")

@app.route("/<path:page>")
def pages(page):
    """Serve static files with whitelist validation - prevents path traversal."""
    page = os.path.normpath(page).replace("\\", "/")
    if ".." in page or page.startswith("/"):
        abort(403, description="Access denied")
    sensitive_extensions = {".db", ".sql", ".env", ".py", ".pyc", ".log", ".key", ".pem", ".bat", ".spec"}
    if any(page.lower().endswith(ext) for ext in sensitive_extensions):
        abort(403, description="Access denied")

    # Known HTML pages
    if page in ALLOWED_STATIC_FILES:
        return send_from_directory(STATIC_DIR, page)

    # Allowed asset directories and extensions (CSS, JS, Fonts, Images)
    if re.match(r"^(css|js|fonts|img)/[\w\-./]+\.(css|js|otf|ttf|woff|woff2|eot|png|jpg|jpeg|svg|gif|ico|webp)$", page, re.I):
        return send_from_directory(STATIC_DIR, page)

    abort(404)

@app.errorhandler(Exception)
def handle_error(e):
    code = getattr(e, 'code', 500)
    req_path = request.path if request else "unknown"
    if code == 500:
        loggers['error'].exception(f"Internal server error on request {req_path}: {e}")
    else:
        loggers['app'].warning(f"HTTP {code} on {req_path}: {e}")
    return jsonify({"error": "Internal server error" if code == 500 and not DEBUG else str(e)}), code

@app.errorhandler(403)
def forbidden(e):
    return jsonify({"error": "Access denied"}), 403

@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Not found"}), 404

@app.route("/api/health")
def health_check():
    """Health check endpoint for monitoring."""
    return jsonify({"status": "healthy"})

@app.route("/api/ready")
def ready_check():
    """Readiness check endpoint for load balancers."""
    return jsonify({"status": "ready"}), 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=DEBUG, host="0.0.0.0" if os.environ.get("PORT") else HOST, port=port)