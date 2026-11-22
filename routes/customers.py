"""Customers: register, search by phone/name, look up by exact phone for POS."""
import sqlite3
from flask import Blueprint, request, jsonify

from ._common import get_db, row, rows, audit, require_auth, require_role
from .validation import CustomerRequest, validate_payload

bp = Blueprint("customers", __name__)


@bp.route("/api/customers", methods=["GET"])
def list_customers():
    require_auth()
    search = (request.args.get("search") or "").strip()
    conn = get_db()
    try:
        sql = "SELECT * FROM customers"
        params = []
        if search:
            like = f"%{search}%"
            sql += " WHERE name LIKE ? OR phone LIKE ? OR loyalty_no LIKE ?"
            params = [like, like, like]
        sql += " ORDER BY id DESC LIMIT 100"
        return jsonify({"customers": [dict(r) for r in rows(conn, sql, params)]})
    finally:
        conn.close()


@bp.route("/api/customers", methods=["POST"])
def create_customer():
    u = require_auth()
    d = request.get_json(force=True)
    val_data, err = validate_payload(CustomerRequest, d)
    if err:
        return jsonify({"error": err}), 400
    phone = (val_data.get("phone") or "").strip()
    loyalty_no = (val_data.get("loyalty_no") or "").strip() or None
    conn = get_db()
    try:
        if phone:
            existing = row(conn, "SELECT id, name FROM customers WHERE phone = ?", (phone,))
            if existing:
                return jsonify({"error": f"رقم الهاتف مسجل بالفعل للعميل: {existing['name']}"}), 409
        if loyalty_no:
            existing_loyalty = row(conn, "SELECT id, name FROM customers WHERE loyalty_no = ?", (loyalty_no,))
            if existing_loyalty:
                return jsonify({"error": f"رقم بطاقة الولاء مسجل بالفعل للعميل: {existing_loyalty['name']}"}), 409
        cur = conn.execute(
            "INSERT INTO customers (name, phone, loyalty_no) VALUES (?,?,?)",
            (val_data.get("name"), phone or None, loyalty_no),
        )
        conn.commit()
        return jsonify({"ok": True, "id": cur.lastrowid})
    except sqlite3.IntegrityError as e:
        err_msg = str(e)
        if "loyalty_no" in err_msg:
            return jsonify({"error": "رقم بطاقة الولاء مسجل بالفعل"}), 409
        return jsonify({"error": "رقم الهاتف مسجل بالفعل"}), 409
    finally:
        conn.close()


@bp.route("/api/customers/by-phone/<phone>", methods=["GET"])
def by_phone(phone):
    require_auth()
    conn = get_db()
    try:
        c = row(conn, "SELECT * FROM customers WHERE phone = ?", (phone,))
        if not c:
            return jsonify({"error": "not found"}), 404
        return jsonify(dict(c))
    finally:
        conn.close()


@bp.route("/api/customers/<int:cid>", methods=["PUT"])
def update_customer(cid):
    u = require_auth()
    d = request.get_json(force=True)
    phone = (d.get("phone") or "").strip()
    loyalty_no = (d.get("loyalty_no") or "").strip() or None
    conn = get_db()
    try:
        if phone:
            existing = row(conn, "SELECT id, name FROM customers WHERE phone = ? AND id != ?", (phone, cid))
            if existing:
                return jsonify({"error": f"رقم الهاتف مسجل بالفعل للعميل: {existing['name']}"}), 409
        if loyalty_no:
            existing_loyalty = row(conn, "SELECT id, name FROM customers WHERE loyalty_no = ? AND id != ?", (loyalty_no, cid))
            if existing_loyalty:
                return jsonify({"error": f"رقم بطاقة الولاء مسجل بالفعل للعميل: {existing_loyalty['name']}"}), 409
        conn.execute("UPDATE customers SET name=?, phone=?, loyalty_no=? WHERE id=?",
                     (d.get("name"), phone or None, loyalty_no, cid))
        conn.commit()
        return jsonify({"ok": True})
    except sqlite3.IntegrityError as e:
        err_msg = str(e)
        if "loyalty_no" in err_msg:
            return jsonify({"error": "رقم بطاقة الولاء مسجل بالفعل"}), 409
        return jsonify({"error": "رقم الهاتف مسجل بالفعل"}), 409
    finally:
        conn.close()