import os
import sys
from functools import lru_cache

FROZEN = getattr(sys, "frozen", False)

if FROZEN:
    ASSET_DIR = sys._MEIPASS
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    ASSET_DIR = BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Load .env automatically (from next to EXE or project folder, or bundled inside EXE)
try:
    from dotenv import load_dotenv
    for _env_candidate in (
        os.path.join(BASE_DIR, ".env"),
        os.path.join(ASSET_DIR, ".env"),
    ):
        if os.path.exists(_env_candidate):
            load_dotenv(_env_candidate, override=False)
            break
except ImportError:
    pass


# =============================================================================
# SECURITY CONFIGURATION
# =============================================================================

# Strong secret key from environment - REQUIRED for session security
# Generate with: python -c "import secrets; print(secrets.token_hex(32))"
SECRET_KEY = os.environ.get("SECRET_KEY", os.urandom(32).hex())

# Rate limiting - Enabled by default for security
RATELIMIT_ENABLED = os.environ.get("RATELIMIT_ENABLED", "true").lower() == "true"
RATELIMIT_DEFAULT = "100/hour"
RATELIMIT_STORED_REQUESTS = int(os.environ.get("RATELIMIT_STORED_REQUESTS", "2000"))
RATELIMIT_STORAGE_URL = os.environ.get("RATELIMIT_STORAGE_URL", f"memory://#{RATELIMIT_STORED_REQUESTS}")

# Session security - Secure cookies enabled only for HTTPS in production
SESSION_REFRESH_RATE = 0.5
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "true" if os.environ.get("RENDER_EXTERNAL_URL") else "false").lower() == "true"

# File upload limits
MAX_CONTENT_LENGTH = int(os.environ.get("MAX_CONTENT_LENGTH", "10485760"))  # 10MB default
ALLOWED_EXTENSIONS = {"csv", "xlsx", "xltx", "xls"}

# Flask Debug Mode - Default to False for security
DEBUG = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
HOST = "127.0.0.1" if not DEBUG else "0.0.0.0"


# =============================================================================
# DIRECTORY PATHS
# =============================================================================

STATIC_DIR = os.path.join(ASSET_DIR, "static")
SCHEMA_PATH = os.path.join(ASSET_DIR, "schema.sql")
SCHEMA_POSTGRES_PATH = os.path.join(ASSET_DIR, "schema_postgres.sql")
BACKUP_DIR = os.path.join(BASE_DIR, "backups")

# Database URL for PostgreSQL / Supabase (if set, uses Postgres instead of SQLite)
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
IS_POSTGRES = DATABASE_URL.startswith(("postgres://", "postgresql://"))

# Drug Database API (OpenFDA)
OPENFDA_API_KEY = os.environ.get("OPENFDA_API_KEY", os.environ.get("DRUG_API_KEY", "")).strip()
DRUG_API_URL = os.environ.get("DRUG_API_URL", "https://api.fda.gov/drug/ndc.json").strip()



# =============================================================================
# DATABASE SAFETY FUNCTIONS
# =============================================================================

def _safe_path(base, user_path, name="path"):
    """Resolve and validate a path stays within base directory."""
    if not user_path:
        raise ValueError(f"{name} is required")
    user_path = str(user_path).strip()
    resolved = os.path.normpath(os.path.join(base, user_path))
    base_resolved = os.path.normpath(base)
    try:
        if os.path.commonpath([resolved, base_resolved]) != base_resolved:
            raise ValueError(f"{name} traversal attempt blocked: {user_path}")
    except (ValueError, Exception):
        raise ValueError(f"{name} traversal attempt blocked: {user_path}")
    return resolved


@lru_cache(maxsize=1)
def get_db_path_cached():
    """Cached DB path construction to prevent repeated operations."""
    db_path = os.environ.get("DB_PATH")
    if db_path:
        return os.path.abspath(db_path)
    return os.path.join(BASE_DIR, "data", "pharmacy.db")


DB_PATH = get_db_path_cached()


# =============================================================================
# DEFAULT CONSTANTS
# =============================================================================

MIN_PASSWORD_LENGTH = 6
MAX_CART_ITEMS = 20
DEFAULT_EXPIRY_ALERT_DAYS = 30
DEFAULT_LIST_LIMIT = 50

