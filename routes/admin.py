"""Admin: users, branches, settings, audit log, backup/restore."""
import os
import re
import sqlite3

from flask import Blueprint, request, jsonify, session, send_file
from bcrypt import hashpw, gensalt, checkpw

from ._common import (get_db, close_db, row, rows, q1, now, audit, require_role, require_auth,
                      BACKUP_DIR, DB_PATH, _safe_path, IS_POSTGRES,
                      get_sync_state, set_sync_state, probe_supabase, _ensure_local_sqlite_schema)
from config import MIN_PASSWORD_LENGTH
from licensing.manager import verify_current_license
from .validation import UserCreateRequest, validate_payload
from . import _pg_backup

bp = Blueprint("admin", __name__)

ROLES = ("admin", "pharmacist", "sales")


@bp.route("/api/users", methods=["GET"])
def list_users():
    require_role("admin")
    conn = get_db()
    try:
        rs = rows(conn, "SELECT id, username, full_name, role, branch_id, active, warning_msg, created_at FROM users ORDER BY id")
        return jsonify({"users": [dict(r) for r in rs]})
    finally:
        conn.close()


@bp.route("/api/users/<int:uid>", methods=["GET"])
def get_user(uid):
    require_role("admin")
    conn = get_db()
    try:
        u = row(conn, "SELECT id, username, full_name, role, branch_id, active, warning_msg, created_at FROM users WHERE id = ?", (uid,))
        if not u:
            return jsonify({"error": "user not found"}), 404
        return jsonify(dict(u))
    finally:
        conn.close()


@bp.route("/api/users", methods=["POST"])
def create_user():
    admin_u = require_role("admin")
    d = request.get_json(force=True) or {}
    val_data, err = validate_payload(UserCreateRequest, d)
    if err:
        return jsonify({"error": err}), 400
    username = val_data["username"]
    password = val_data["password"]
    role = val_data.get("role") or "sales"
    conn = get_db()
    try:
        existing = row(conn, "SELECT id FROM users WHERE LOWER(username) = LOWER(?)", (username,))
        if existing:
            return jsonify({"error": "اسم المستخدم مسجل بالفعل"}), 409
        pwd_hash = hashpw(password.encode('utf-8'), gensalt()).decode('utf-8')
        cur = conn.execute(
            "INSERT INTO users (username, password, full_name, role, branch_id) VALUES (?,?,?,?,?)",
            (username, pwd_hash, val_data.get("full_name"), role, val_data.get("branch_id")),
        )
        audit(conn, admin_u["id"], val_data.get("branch_id"), "create_user", "users", cur.lastrowid, username)
        conn.commit()
        return jsonify({"ok": True, "id": cur.lastrowid})
    except sqlite3.IntegrityError:
        return jsonify({"error": "اسم المستخدم مسجل بالفعل"}), 409
    finally:
        conn.close()


@bp.route("/api/users/<int:uid>/warning", methods=["POST"])
def warn_user(uid):
    admin_u = require_role("admin")
    d = request.get_json(force=True)
    conn = get_db()
    try:
        conn.execute("UPDATE users SET warning_msg=? WHERE id=?", (d.get("warning_msg"), uid))
        audit(conn, admin_u["id"], admin_u["branch_id"], "warn_user", "users", uid, d.get("warning_msg"))
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


@bp.route("/api/users/<int:uid>/suspend", methods=["POST"])
def suspend_user(uid):
    admin_u = require_role("admin")
    d = request.get_json(force=True) or {}
    conn = get_db()
    try:
        # Toggle active status
        user = row(conn, "SELECT * FROM users WHERE id = ?", (uid,))
        if not user:
            return jsonify({"error": "user not found"}), 404
        if uid == 1 or user["username"] == "admin":
            return jsonify({"error": "cannot suspend seed admin"}), 403
        if uid == admin_u["id"]:
            return jsonify({"error": "لا يمكنك تجميد حسابك الحالي"}), 400

        new_status = 0 if user["active"] else 1
        if new_status == 0 and user["role"] == "admin":
            active_admins = q1(conn, "SELECT COUNT(*) FROM users WHERE role = 'admin' AND active = 1 AND id != ?", (uid,)) or 0
            if active_admins == 0:
                return jsonify({"error": "لا يمكن تجميد آخر مدير نشط في النظام"}), 400

        conn.execute("UPDATE users SET active = ?, warning_msg = ? WHERE id = ?",
                     (new_status, d.get("warning_msg", ""), uid))
        audit(conn, admin_u["id"], admin_u["branch_id"], "suspend_user" if not new_status else "unsuspend_user",
              "users", uid, f"status={'suspended' if not new_status else 'active'}")
        conn.commit()
        return jsonify({"ok": True, "active": bool(new_status)})
    finally:
        conn.close()


@bp.route("/api/users/<int:uid>", methods=["PUT"])
def update_user(uid):
    admin_u = require_role("admin")
    d = request.get_json(force=True)
    conn = get_db()
    try:
        user = row(conn, "SELECT * FROM users WHERE id = ?", (uid,))
        if not user:
            return jsonify({"error": "user not found"}), 404

        # Validate role if provided
        role = d.get("role")
        if role and role not in ROLES:
            return jsonify({"error": "invalid role"}), 400

        # Cannot demote self
        if "role" in d and role != "admin" and uid == admin_u["id"]:
            return jsonify({"error": "لا يمكنك إزالة صلاحيات الإدارة أو تغيير دور حسابك الحالي"}), 400

        # Cannot demote the last active admin
        if "role" in d and role != "admin" and user["role"] == "admin":
            active_admins = q1(conn, "SELECT COUNT(*) FROM users WHERE role = 'admin' AND active = 1 AND id != ?", (uid,)) or 0
            if active_admins == 0:
                return jsonify({"error": "لا يمكن تغيير دور آخر مدير نشط في النظام"}), 400

        # Update allowed fields
        updates = []
        params = []
        if "full_name" in d:
            updates.append("full_name = ?")
            params.append(d["full_name"])
        if "role" in d and uid != 1 and user["username"] != "admin":  # Cannot change seed admin role
            updates.append("role = ?")
            params.append(role)
        if "branch_id" in d:
            updates.append("branch_id = ?")
            params.append(d["branch_id"])
        if d.get("password"):
            if len(d["password"]) < MIN_PASSWORD_LENGTH:
                return jsonify({"error": f"كلمة المرور يجب أن تكون {MIN_PASSWORD_LENGTH} أحرف على الأقل"}), 400
            updates.append("password = ?")
            params.append(hashpw(d["password"].encode('utf-8'), gensalt()).decode('utf-8'))

        if updates:
            params.append(uid)
            conn.execute(f"UPDATE users SET {','.join(updates)} WHERE id = ?", params)
            audit(conn, admin_u["id"], admin_u["branch_id"], "update_user", "users", uid,
                  f"updated: {','.join(d.keys())}")

        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


@bp.route("/api/users/<int:uid>/password", methods=["POST"])
def change_user_password(uid):
    admin_user = require_role("admin")
    d = request.get_json(force=True) or {}
    new_pwd = d.get("new_password") or d.get("password") or ""
    if len(new_pwd) < MIN_PASSWORD_LENGTH:
        return jsonify({"error": f"كلمة المرور الجديدة يجب أن تكون {MIN_PASSWORD_LENGTH} أحرف على الأقل"}), 400
    conn = get_db()
    try:
        target = row(conn, "SELECT id, username FROM users WHERE id = ?", (uid,))
        if not target:
            return jsonify({"error": "المستخدم غير موجود"}), 404
        new_hash = hashpw(new_pwd.encode("utf-8"), gensalt()).decode("utf-8")
        conn.execute("UPDATE users SET password = ? WHERE id = ?", (new_hash, uid))
        audit(conn, admin_user["id"], admin_user["branch_id"], "change_user_password", "users", uid, target["username"])
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


@bp.route("/api/users/<int:uid>", methods=["DELETE"])
def delete_user(uid):
    admin_u = require_role("admin")
    if uid == 1:
        return jsonify({"error": "cannot delete seed admin"}), 403
    if uid == admin_u["id"]:
        return jsonify({"error": "لا يمكنك حذف حسابك الحالي"}), 400
    conn = get_db()
    try:
        user = row(conn, "SELECT * FROM users WHERE id = ?", (uid,))
        if not user:
            return jsonify({"error": "user not found"}), 404
        if user["username"] == "admin":
            return jsonify({"error": "cannot delete seed admin"}), 403
        if user["role"] == "admin":
            active_admins = q1(conn, "SELECT COUNT(*) FROM users WHERE role = 'admin' AND active = 1 AND id != ?", (uid,)) or 0
            if active_admins == 0:
                return jsonify({"error": "لا يمكن حذف آخر مدير نشط في النظام"}), 400

        # Check if user has invoices
        has_invoices = q1(conn, "SELECT COUNT(*) FROM sales WHERE user_id = ?", (uid,))
        if has_invoices > 0:
            # If invoices exist, just deactivate
            conn.execute("UPDATE users SET active = 0 WHERE id = ?", (uid,))
            audit(conn, admin_u["id"], admin_u["branch_id"], "deactivate_user", "users", uid, f"has sales: {has_invoices}")
            conn.commit()
            return jsonify({"message": "User has invoices, deactivated instead of deleted"}), 200

        conn.execute("DELETE FROM users WHERE id = ?", (uid,))
        audit(conn, admin_u["id"], admin_u["branch_id"], "delete_user", "users", uid, user["username"])
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


@bp.route("/api/system/reset", methods=["POST"])
def reset_system():
    u = require_role("admin")
    d = request.get_json(force=True) or {}
    password = d.get("password")
    if not password:
        return jsonify({"error": "كلمة مرور المدير مطلوبة لتأكيد إعادة ضبط النظام"}), 400

    # Verify admin password safely
    try:
        if not checkpw(str(password).encode('utf-8'), u["password"].encode('utf-8')):
            return jsonify({"error": "كلمة المرور غير صحيحة"}), 401
    except Exception:
        return jsonify({"error": "كلمة المرور غير صحيحة"}), 401

    conn = get_db()
    try:
        # Tables to reset in child-first order to respect foreign keys
        tables = [
            "loyalty_ledger", "loyalty_rewards", "sale_payments", "sale_items",
            "returns", "sales", "purchase_items", "supplier_payments", "purchases",
            "inventory_adjustments", "batches", "product_requests", "promotions",
            "expenses", "shifts", "branch_product_limits", "products", "categories", "customers", "suppliers",
            "sales_seq", "purchases_seq", "audit_log", "exchange_rate_history"
        ]
        for table in tables:
            try:
                conn.execute(f"DELETE FROM {table}")
            except Exception:
                pass
        conn.commit()
        audit(conn, u["id"], None, "reset_system", None, None, "Full system reset performed")
        return jsonify({"ok": True})
    finally:
        conn.close()



@bp.route("/api/branches", methods=["GET"])
def list_branches():
    require_auth()
    conn = get_db()
    try:
        lic = verify_current_license()
        max_branches = lic.get("max_branches", 1) if lic else 1
        return jsonify({
            "branches": [dict(r) for r in rows(conn, "SELECT * FROM branches ORDER BY id")],
            "max_branches": max_branches,
            "license_valid": lic.get("is_valid", False) if lic else False
        })
    finally:
        conn.close()


@bp.route("/api/branches", methods=["POST"])
def create_branch():
    admin_u = require_role("admin")
    d = request.get_json(force=True)
    if not (d.get("name") or "").strip():
        return jsonify({"error": "اسم الفرع مطلوب"}), 400
    conn = get_db()
    try:
        lic = verify_current_license()
        max_branches = lic.get("max_branches", 1) if lic else 1
        current_branches = q1(conn, "SELECT COUNT(*) FROM branches") or 0
        if current_branches >= max_branches:
            return jsonify({
                "error": f"تم استنفاد الحد الأقصى للفروع المصرح بها في باقة اشتراكك ({max_branches} فرع). يرجى ترقية الترخيص لإضافة فروع جديدة."
            }), 403

        cur = conn.execute("INSERT INTO branches (name, phone, address) VALUES (?,?,?)",
                           (d["name"].strip(), d.get("phone"), d.get("address")))
        user_branch = admin_u.get("branch_id") if hasattr(admin_u, "get") else admin_u["branch_id"]
        audit(conn, admin_u["id"], user_branch, "create_branch", "branches", cur.lastrowid, d["name"])
        conn.commit()
        return jsonify({"ok": True, "id": cur.lastrowid})
    finally:
        conn.close()


@bp.route("/api/settings", methods=["GET"])
def get_settings():
    require_role("admin")
    conn = get_db()
    try:
        out = {r["key"]: r["value"] for r in rows(conn, "SELECT * FROM settings")}
        return jsonify({"settings": out})
    finally:
        conn.close()


@bp.route("/api/settings", methods=["PUT"])
def put_settings():
    require_role("admin")
    d = request.get_json(force=True) or {}
    conn = get_db()
    try:
        for k, v in d.items():
            conn.execute("INSERT INTO settings (key, value) VALUES (?,?) "
                         "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(k), str(v)))
        audit(conn, None, None, "update_settings", "settings", None, ",".join(d.keys()))
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


@bp.route("/api/settings/exchange-rate", methods=["GET"])
def get_exchange_rate():
    """Get current USD exchange rate and recent history."""
    require_auth()
    conn = get_db()
    try:
        rate_val = q1(conn, "SELECT value FROM settings WHERE key = 'usd_exchange_rate'")
        current_rate = float(rate_val) if rate_val else 1.0
        
        hist_rows = rows(conn, """
            SELECT h.id, h.old_rate, h.new_rate, h.created_at, u.full_name as user_name, u.username
            FROM exchange_rate_history h
            LEFT JOIN users u ON u.id = h.changed_by
            ORDER BY h.id DESC
            LIMIT 20
        """)
        
        last_updated = hist_rows[0]["created_at"] if hist_rows else None
        total_products = q1(conn, "SELECT COUNT(*) FROM products WHERE active = 1") or 0
        usd_products = q1(conn, "SELECT COUNT(*) FROM products WHERE active = 1 AND (sale_price_usd > 0 OR purchase_price_usd > 0)") or 0

        return jsonify({
            "rate": current_rate,
            "last_updated": last_updated,
            "total_products": total_products,
            "usd_products": usd_products,
            "history": [dict(r) for r in hist_rows]
        })
    finally:
        conn.close()


@bp.route("/api/settings/exchange-rate", methods=["POST"])
def update_exchange_rate():
    """Update USD exchange rate, record history, and batch-update all products priced in USD."""
    u = require_role("admin")
    d = request.get_json(force=True) or {}
    try:
        new_rate = float(d.get("rate") or 0)
    except (ValueError, TypeError):
        return jsonify({"error": "سعر الصرف غير صالح"}), 400

    if new_rate <= 0:
        return jsonify({"error": "سعر الصرف يجب أن يكون أكبر من الصفر"}), 400

    conn = get_db()
    try:
        old_val = q1(conn, "SELECT value FROM settings WHERE key = 'usd_exchange_rate'")
        old_rate = float(old_val) if old_val else None

        # Save to settings
        conn.execute(
            "INSERT INTO settings (key, value) VALUES ('usd_exchange_rate', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(new_rate),)
        )

        # Record in history
        conn.execute(
            "INSERT INTO exchange_rate_history (old_rate, new_rate, changed_by) VALUES (?,?,?)",
            (old_rate, new_rate, u["id"])
        )

        # Batch update: sale_price rounded to nearest integer, purchase_price rounded to 2 decimals
        cur = conn.execute("""
            UPDATE products
            SET sale_price = ROUND(CAST(sale_price_usd * ? AS NUMERIC)),
                purchase_price = ROUND(CAST(purchase_price_usd * ? AS NUMERIC), 2)
            WHERE sale_price_usd > 0 OR purchase_price_usd > 0
        """, (new_rate, new_rate))
        updated_count = cur.rowcount

        user_branch = u.get("branch_id") if hasattr(u, "get") else u["branch_id"]
        audit(conn, u["id"], user_branch, "update_exchange_rate", "settings", None,
              f"old={old_rate} new={new_rate} updated={updated_count}")
        conn.commit()

        return jsonify({
            "ok": True,
            "rate": new_rate,
            "updated_products": updated_count,
            "message": f"تم تحديث سعر الصرف بنجاح وتحديث أسعار {updated_count} صنف بالمخزون"
        })
    finally:
        conn.close()


@bp.route("/api/settings/exchange-rate/initial-sync", methods=["POST"])
def initial_sync_exchange_rate():
    """Initial conversion: calculate USD prices for existing products from their local currency prices."""
    u = require_role("admin")
    conn = get_db()
    try:
        rate_val = q1(conn, "SELECT value FROM settings WHERE key = 'usd_exchange_rate'")
        if not rate_val or float(rate_val) <= 0:
            return jsonify({"error": "يرجى تحديد وحفظ سعر الصرف أولاً قبل إجراء التحويل الأولي"}), 400
        rate = float(rate_val)

        cur = conn.execute("""
            UPDATE products
            SET sale_price_usd = ROUND(CAST(sale_price / ? AS NUMERIC), 2),
                purchase_price_usd = ROUND(CAST(purchase_price / ? AS NUMERIC), 2)
            WHERE (sale_price_usd = 0 OR sale_price_usd IS NULL)
              AND (sale_price > 0 OR purchase_price > 0)
        """, (rate, rate))
        synced_count = cur.rowcount

        user_branch = u.get("branch_id") if hasattr(u, "get") else u["branch_id"]
        audit(conn, u["id"], user_branch, "initial_sync_exchange_rate", "products", None,
              f"rate={rate} synced={synced_count}")
        conn.commit()

        return jsonify({
            "ok": True,
            "synced_products": synced_count,
            "message": f"تم بنجاح احتساب أسعار الدولار لـ {synced_count} صنف من واقع أسعارها الحالية"
        })
    finally:
        conn.close()


@bp.route("/api/settings/test-drug-api", methods=["GET", "POST"])
def test_drug_api():
    """Test connectivity to OpenFDA drug database with current or provided API key."""
    require_role("admin")
    api_key = None
    if request.method == "POST":
        d = request.get_json(silent=True) or {}
        api_key = d.get("api_key")
    if not api_key:
        from .drug_service import get_api_key
        conn = get_db()
        try:
            api_key = get_api_key(conn)
        finally:
            conn.close()

    from .drug_service import test_openfda_connection
    ok, msg = test_openfda_connection(api_key)
    return jsonify({"ok": ok, "message": msg})


@bp.route("/api/audit", methods=["GET"])
def list_audit():
    require_role("admin")
    limit = request.args.get("limit", 200, type=int)
    user_id = request.args.get("user_id", "").strip()
    action = request.args.get("action", "").strip()
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()

    where_clauses = []
    params = []

    if user_id:
        where_clauses.append("a.user_id = ?")
        params.append(int(user_id))

    if action:
        where_clauses.append("a.action = ?")
        params.append(action)

    if date_from:
        where_clauses.append("a.created_at >= ?")
        params.append(date_from)

    if date_to:
        where_clauses.append("a.created_at < ?")
        end_date = date_to + " 23:59:59"
        params.append(end_date)

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    conn = get_db()
    try:
        sql = f"""SELECT a.*, u.full_name AS user_name FROM audit_log a
                 LEFT JOIN users u ON u.id = a.user_id {where_sql}
                 ORDER BY a.id DESC LIMIT ?"""
        params.append(limit)
        return jsonify({"entries": [dict(r) for r in rows(conn, sql, tuple(params))]})
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Backup / restore
#   SQLite mode  -> *.db snapshot files (sqlite3 backup API)
#   Postgres mode -> *.json.gz snapshot files (routes/_pg_backup.py)
# Files live in BACKUP_DIR on this machine and can also be downloaded to /
# uploaded from the user's device.
# ---------------------------------------------------------------------------
_BACKUP_EXT = _pg_backup.EXT if IS_POSTGRES else ".db"
_BACKUP_RE = re.compile(r"[\w.\-]+\.(?:db(?:\.prerestore)?|json\.gz)")


def _backup_name(prefix="pharmacy", ext=None):
    return f"{prefix}-{now().replace(':', '-').replace(' ', '_')}{ext or _BACKUP_EXT}"


def _valid_backup_name(name):
    name = os.path.basename((name or "").strip())
    return name if _BACKUP_RE.fullmatch(name) else None


def _write_snapshot(dest_path):
    if IS_POSTGRES:
        _pg_backup.dump_to_file(dest_path)
        return
    src = sqlite3.connect(DB_PATH)
    try:
        dst = sqlite3.connect(dest_path)
        src.backup(dst)
        dst.close()
    finally:
        src.close()


def _audit_now(user_id, action, detail):
    conn = get_db()
    try:
        audit(conn, user_id, None, action, None, None, detail)
        conn.commit()
    finally:
        conn.close()


@bp.route("/api/backup", methods=["POST"])
def take_backup():
    u = require_role("admin")
    os.makedirs(BACKUP_DIR, exist_ok=True)
    name = _backup_name()
    _write_snapshot(_safe_path(BACKUP_DIR, name, "backup file"))
    _audit_now(u["id"], "backup", name)
    return jsonify({"ok": True, "file": name})


@bp.route("/api/backups", methods=["GET"])
def list_backups():
    require_role("admin")
    out = []
    if os.path.exists(BACKUP_DIR):
        for fn in sorted(os.listdir(BACKUP_DIR), reverse=True):
            if _BACKUP_RE.fullmatch(fn):
                st = os.stat(os.path.join(BACKUP_DIR, fn))
                out.append({"file": fn, "size": st.st_size, "mtime": st.st_mtime})
    out.sort(key=lambda b: b["mtime"], reverse=True)
    return jsonify({"backups": out, "mode": "postgres" if IS_POSTGRES else "sqlite"})


@bp.route("/api/backups/<name>/download", methods=["GET"])
def download_backup(name):
    require_role("admin")
    name = _valid_backup_name(name)
    if not name:
        return jsonify({"error": "invalid backup file"}), 400
    path = _safe_path(BACKUP_DIR, name, "backup file")
    if not os.path.isfile(path):
        return jsonify({"error": "backup file not found"}), 404
    return send_file(path, as_attachment=True, download_name=name)


@bp.route("/api/backups/upload", methods=["POST"])
def upload_backup():
    """Upload a backup file from the user's device into the backups list (does NOT restore)."""
    u = require_role("admin")
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "لم يتم اختيار ملف"}), 400
    fn_lower = f.filename.lower()
    if fn_lower.endswith(".json.gz"):
        up_ext = ".json.gz"
    elif fn_lower.endswith(".db") or fn_lower.endswith(".db.prerestore"):
        up_ext = ".db"
    else:
        return jsonify({"error": "صيغة الملف يجب أن تكون .db أو .json.gz"}), 400
    os.makedirs(BACKUP_DIR, exist_ok=True)
    name = _backup_name("uploaded", up_ext)
    path = _safe_path(BACKUP_DIR, name, "backup file")
    f.save(path)
    try:
        _pg_backup.load_file(path)
    except ValueError as e:
        os.remove(path)
        return jsonify({"error": str(e)}), 400
    _audit_now(u["id"], "backup_upload", f"{name} <- {os.path.basename(f.filename)}")
    return jsonify({"ok": True, "file": name})


@bp.route("/api/restore", methods=["POST"])
def restore_backup():
    u = require_role("admin")
    close_db()
    d = request.get_json(force=True)
    name = _valid_backup_name(d.get("file"))
    if not name:
        return jsonify({"error": "invalid backup file"}), 400
    src_path = _safe_path(BACKUP_DIR, name, "backup file")
    if not os.path.isfile(src_path):
        return jsonify({"error": "backup file not found"}), 404

    if IS_POSTGRES:
        try:
            payload = _pg_backup.load_file(src_path)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        # Safety snapshot of current data first (appears in the list, restorable)
        safety = _backup_name("prerestore")
        _pg_backup.dump_to_file(_safe_path(BACKUP_DIR, safety, "safety file"))
        _pg_backup.restore_from_payload(payload)
        try:
            _ensure_local_sqlite_schema()
            _pg_backup.restore_payload_to_sqlite(payload, DB_PATH)
            set_sync_state(offline_mode=False, dirty=False, last_sync=now())
        except Exception:
            pass
    else:
        safety = _backup_name("prerestore", ".db")
        live = sqlite3.connect(DB_PATH)
        try:
            dst = sqlite3.connect(_safe_path(BACKUP_DIR, safety, "safety file"))
            live.backup(dst)
            dst.close()
        finally:
            live.close()
        if _pg_backup._is_sqlite_file(src_path):
            src = sqlite3.connect(src_path)
            try:
                dst = sqlite3.connect(DB_PATH)
                src.backup(dst)
                dst.close()
            finally:
                src.close()
        else:
            try:
                payload = _pg_backup.load_file(src_path)
                _pg_backup.restore_payload_to_sqlite(payload, DB_PATH)
            except ValueError as e:
                return jsonify({"error": str(e)}), 400

    # The acting user may not exist in the restored data -> log without user id
    _audit_now(None, "restore", f"{name} (by user {u['id']} / {u['username']})")
    return jsonify({"ok": True, "prerestore": safety})


# ---------------------------------------------------------------------------
# Online (Supabase) / Offline (Local SQLite) Status & Sync Endpoints
# ---------------------------------------------------------------------------
@bp.route("/api/sync/status", methods=["GET"])
def sync_status():
    require_auth()
    force = request.args.get("force") == "1"
    online = probe_supabase(timeout=3, force=force) if IS_POSTGRES else False
    st = get_sync_state()
    if IS_POSTGRES:
        if not online and not st.get("offline_mode"):
            st = set_sync_state(offline_mode=True)
        elif online and st.get("offline_mode") and not st.get("dirty"):
            st = set_sync_state(offline_mode=False)
    return jsonify({
        "configured_supabase": bool(IS_POSTGRES),
        "supabase_online": bool(online),
        "offline_mode": bool(st.get("offline_mode")),
        "dirty": bool(st.get("dirty")),
        "last_sync": st.get("last_sync"),
    })


@bp.route("/api/sync/now", methods=["POST"])
def sync_now():
    u = require_auth()
    if not IS_POSTGRES:
        return jsonify({"error": "النظام يعمل في الوضع المحلي فقط (لم يتم تفعيل الربط السحابي)"}), 400
    online = probe_supabase(timeout=5, force=True)
    if not online:
        set_sync_state(offline_mode=True)
        return jsonify({
            "error": "لا يوجد اتصال بالسيرفر حالياً — يستمر النظام بالعمل محلياً وحفظ بياناتك حتى يعود الإنترنت"
        }), 503

    _ensure_local_sqlite_schema()
    st = get_sync_state()
    try:
        if st.get("dirty") or st.get("offline_mode"):
            payload = _pg_backup._load_sqlite_file(DB_PATH)
            _pg_backup.restore_from_payload(payload)
            ts = now()
            set_sync_state(offline_mode=False, dirty=False, last_sync=ts)
            _audit_now(u["id"], "sync_push", f"Synced offline local data to remote server at {ts}")
            return jsonify({
                "ok": True,
                "direction": "push",
                "last_sync": ts,
                "message": "تمت مزامنة ورفع البيانات المحلية إلى السيرفر السحابي بنجاح!",
            })
        else:
            payload, _ = _pg_backup.dump_to_payload()
            _pg_backup.restore_payload_to_sqlite(payload, DB_PATH)
            ts = now()
            set_sync_state(offline_mode=False, dirty=False, last_sync=ts)
            _audit_now(u["id"], "sync_pull", f"Updated local offline cache from remote server at {ts}")
            return jsonify({
                "ok": True,
                "direction": "pull",
                "last_sync": ts,
                "message": "تمت مزامنة البيانات مع السيرفر السحابي وتحديث النسخة المحلية بنجاح!",
            })
    except Exception as e:
        return jsonify({"error": f"فشلت عملية المزامنة: {e}"}), 500

