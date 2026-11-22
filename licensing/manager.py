"""License Manager module.
Handles loading, verifying, caching, and activating licenses for Teryaq.
"""
import os
import sys
import time
from datetime import datetime
from typing import Optional, Dict, Any, Tuple

from config import BASE_DIR
from .hwid import get_machine_id
from .crypto import verify_token
from .anti_tamper import check_and_update_clock

# License file locations to check
LICENSE_FILENAMES = ["license.lic", "teryaq.lic"]
DATA_DIR = os.path.join(BASE_DIR, "data")

# In-memory validation cache (TTL: 120 seconds)
_CACHE: Dict[str, Any] = {
    "timestamp": 0,
    "status": None,
}


def get_license_file_path() -> str:
    """Return primary path for license file."""
    return os.path.join(BASE_DIR, "license.lic")


def _read_license_token() -> Optional[str]:
    """Find and read license token from file, environment, or database."""
    # 1. Environment variable override
    env_token = os.environ.get("TERYAQ_LICENSE_KEY", "").strip()
    if env_token:
        return env_token

    # 2. Check files in BASE_DIR
    for fname in LICENSE_FILENAMES:
        path = os.path.join(BASE_DIR, fname)
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    token = f.read().strip()
                    if token:
                        return token
            except Exception:
                pass

    # 3. Check database settings table (persists on cloud across container rebuilds)
    try:
        from routes._common import get_db, q1
        conn = get_db()
        try:
            db_token = q1(conn, "SELECT value FROM settings WHERE key = 'system_license_key'")
            if db_token and str(db_token).strip():
                return str(db_token).strip()
        finally:
            conn.close()
    except Exception:
        pass

    return None


def verify_current_license(force: bool = False) -> Dict[str, Any]:
    """Check current license status with caching.
    Returns:
        {
            "is_valid": bool,
            "machine_id": str,
            "client_name": str or None,
            "expires_at": str or None,
            "days_remaining": int or None,
            "is_lifetime": bool,
            "max_branches": int,
            "error": str or None
        }
    """
    now_ts = time.time()
    current_hwid = get_machine_id()

    # Use cache if fresh
    if not force and _CACHE["status"] and (now_ts - _CACHE["timestamp"] < 120):
        return _CACHE["status"]

    # Default failure status
    status = {
        "is_valid": False,
        "machine_id": current_hwid,
        "client_name": None,
        "expires_at": None,
        "days_remaining": None,
        "is_lifetime": False,
        "max_branches": 1,
        "error": "البرنامج غير مفعل. يرجى إدخال مفتاح ترخيص صالح.",
    }

    # 1. Check Anti-Tamper Clock Rollback
    safe_clock, clock_err = check_and_update_clock(DATA_DIR)
    if not safe_clock:
        status["error"] = clock_err
        _CACHE["timestamp"] = now_ts
        _CACHE["status"] = status
        return status

    # 2. Read token
    token = _read_license_token()
    if not token:
        status["error"] = "لم يتم العثور على ملف ترخيص (license.lic). يرجى تفعيل البرنامج."
        _CACHE["timestamp"] = now_ts
        _CACHE["status"] = status
        return status

    # 3. Cryptographic Signature Verification
    valid_sig, payload, sig_err = verify_token(token)
    if not valid_sig:
        status["error"] = sig_err
        _CACHE["timestamp"] = now_ts
        _CACHE["status"] = status
        return status

    # 4. Hardware ID Match Check
    licensed_hwid = payload.get("hwid", "").strip().upper()
    is_cloud = bool(os.environ.get("RENDER") or os.environ.get("RENDER_EXTERNAL_URL") or os.environ.get("DYNO"))
    if licensed_hwid != "*" and licensed_hwid != current_hwid.upper():
        if is_cloud:
            # On cloud web hosting, dynamic containers change node IDs on restart/deploy.
            # We allow hosting, but expiration date and cryptographic signature are STILL 100% strictly enforced!
            pass
        else:
            status["error"] = f"هذا الترخيص مخصص لجهاز كمبيوتر آخر! (كود جهازك: {current_hwid}، كود الترخيص: {licensed_hwid})"
            _CACHE["timestamp"] = now_ts
            _CACHE["status"] = status
            return status

    # 5. Expiration Check
    expires_at = payload.get("expires_at", "")
    is_lifetime = (expires_at == "LIFETIME")
    days_left = None

    if not is_lifetime:
        try:
            exp_date = datetime.strptime(expires_at, "%Y-%m-%d")
            today = datetime.now()
            delta = exp_date - today
            days_left = delta.days
            if days_left < 0:
                status["client_name"] = payload.get("client")
                status["expires_at"] = expires_at
                status["error"] = f"انتهت صلاحية رخصة الاستخدام بتاريخ {expires_at}. يرجى التجديد للاستمرار."
                _CACHE["timestamp"] = now_ts
                _CACHE["status"] = status
                return status
        except Exception:
            status["error"] = "تاريخ انتهاء الترخيص غير مفهوم أو مشوه."
            _CACHE["timestamp"] = now_ts
            _CACHE["status"] = status
            return status

    # License is 100% valid!
    status["is_valid"] = True
    status["client_name"] = payload.get("client")
    status["expires_at"] = expires_at
    status["days_remaining"] = days_left if not is_lifetime else 99999
    status["is_lifetime"] = is_lifetime
    status["max_branches"] = payload.get("max_branches", 1)
    status["error"] = None

    _CACHE["timestamp"] = now_ts
    _CACHE["status"] = status
    return status


def activate_license(token_or_content: str) -> Tuple[bool, str, Dict[str, Any]]:
    """Save and activate a new license key.
    Returns: (success, message, status_dict)
    """
    token = token_or_content.strip()
    if not token:
        return False, "مفتاح الترخيص فارغ", {}

    # Test token first before saving
    valid_sig, payload, sig_err = verify_token(token)
    if not valid_sig:
        return False, sig_err, {}

    current_hwid = get_machine_id()
    licensed_hwid = payload.get("hwid", "").strip().upper()
    is_cloud = bool(os.environ.get("RENDER") or os.environ.get("RENDER_EXTERNAL_URL") or os.environ.get("DYNO"))
    if licensed_hwid != "*" and licensed_hwid != current_hwid.upper() and not is_cloud:
        return False, f"هذا الترخيص لا يطابق جهازك الحالي! (كود جهازك: {current_hwid})", {}

    # Save to license.lic
    lic_path = get_license_file_path()
    try:
        with open(lic_path, "w", encoding="utf-8") as f:
            f.write(token)
    except Exception:
        pass

    # Save to database settings table as well (persists across cloud container redeploys)
    try:
        from routes._common import get_db
        conn = get_db()
        try:
            conn.execute(
                "INSERT INTO settings (key, value) VALUES ('system_license_key', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (token,)
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass

    # Invalidate cache and re-verify
    _CACHE["timestamp"] = 0
    _CACHE["status"] = None
    st = verify_current_license(force=True)

    if st["is_valid"]:
        client = st["client_name"]
        exp = "دائم (مدى الحياة)" if st["is_lifetime"] else f"ينتهي في {st['expires_at']}"
        return True, f"تم تفعيل النظام بنجاح لصالح: {client} ({exp})", st
    else:
        return False, st.get("error") or "فشل تفعيل الترخيص", st
