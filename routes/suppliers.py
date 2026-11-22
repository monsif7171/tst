"""Suppliers API: list, create, update, payments."""
from flask import Blueprint, request, jsonify
from ._common import get_db, row, rows, q1, now, audit, require_auth, require_role, resolve_branch
from .validation import SupplierRequest, PaymentRequest, validate_payload

bp = Blueprint("suppliers", __name__)

DUE_EXPR = """s.balance
    + COALESCE((SELECT SUM(total - paid) FROM purchases WHERE supplier_id = s.id), 0)
    - COALESCE((SELECT SUM(amount) FROM supplier_payments WHERE supplier_id = s.id), 0)"""

DUE_USD_EXPR = """s.balance_usd
    + COALESCE((SELECT SUM((CASE WHEN total_usd > 0 THEN total_usd ELSE total / (CASE WHEN rate > 0 THEN rate ELSE 1.0 END) END) - (paid / (CASE WHEN rate > 0 THEN rate ELSE 1.0 END))) FROM purchases WHERE supplier_id = s.id), 0)
    - COALESCE((SELECT SUM(CASE WHEN amount_usd > 0 THEN amount_usd ELSE amount / (CASE WHEN rate > 0 THEN rate ELSE 1.0 END) END) FROM supplier_payments WHERE supplier_id = s.id), 0)"""

@bp.route("/api/suppliers", methods=["GET"])
def list_suppliers():
    require_auth()
    conn = get_db()
    try:
        sql = f"SELECT s.*, ({DUE_EXPR}) AS due, ({DUE_USD_EXPR}) AS due_usd FROM suppliers s ORDER BY s.name"
        return jsonify({"suppliers": [dict(r) for r in rows(conn, sql)]})
    finally:
        conn.close()

@bp.route("/api/suppliers", methods=["POST"])
def create_supplier():
    u = require_role("admin", "pharmacist")
    d = request.get_json(force=True)
    val_data, err = validate_payload(SupplierRequest, d)
    if err:
        return jsonify({"error": err}), 400
    conn = get_db()
    try:
        cur = conn.execute(
            "INSERT INTO suppliers (name, phone, email, address, balance) VALUES (?,?,?,?,?)",
            (val_data["name"].strip(), val_data.get("phone"), val_data.get("email"), val_data.get("address"), float(val_data.get("balance") or 0))
        )
        audit(conn, u["id"], u["branch_id"], "create_supplier", "suppliers", cur.lastrowid, val_data["name"])
        conn.commit()
        return jsonify({"ok": True, "id": cur.lastrowid})
    finally:
        conn.close()

@bp.route("/api/suppliers/<int:sid>/payments", methods=["POST"])
def pay_supplier(sid):
    u = require_role("admin", "pharmacist")
    d = request.get_json(force=True)
    val_data, err = validate_payload(PaymentRequest, d)
    if err:
        return jsonify({"error": err}), 400
    amount = float(val_data["amount"])
    branch_id = resolve_branch(u, val_data)
    conn = get_db()
    try:
        if not q1(conn, "SELECT id FROM suppliers WHERE id = ?", (sid,)):
            return jsonify({"error": "supplier not found"}), 404

        rate_val = q1(conn, "SELECT value FROM settings WHERE key = 'usd_exchange_rate'")
        current_rate = float(rate_val) if rate_val and float(rate_val) > 0 else 1.0
        try:
            rate = float(d.get("rate") or current_rate)
        except (ValueError, TypeError):
            rate = current_rate
        if rate <= 0:
            rate = current_rate if current_rate > 0 else 1.0
        amount_usd = float(d.get("amount_usd") or 0)
        if amount_usd > 0 and amount == 0:
            amount = round(amount_usd * rate, 2)
        elif amount > 0 and amount_usd == 0:
            amount_usd = round(amount / rate, 2) if rate > 0 else 0.0

        cur = conn.execute(
            "INSERT INTO supplier_payments (branch_id, supplier_id, user_id, amount, rate, amount_usd, pay_date, note) VALUES (?,?,?,?,?,?,?,?)",
            (branch_id, sid, u["id"], amount, rate, amount_usd, now(), val_data.get("note"))
        )
        audit(conn, u["id"], branch_id, "pay_supplier", "supplier_payments", cur.lastrowid, f"supplier={sid} amount={amount} rate={rate}")
        conn.commit()
        due = q1(conn, f"SELECT ({DUE_EXPR}) FROM suppliers s WHERE s.id = ?", (sid,))
        due_usd = q1(conn, f"SELECT ({DUE_USD_EXPR}) FROM suppliers s WHERE s.id = ?", (sid,))
        return jsonify({"ok": True, "due": due, "due_usd": due_usd})
    finally:
        conn.close()

@bp.route("/api/suppliers/<int:sid>/detail", methods=["GET"])
def supplier_detail(sid):
    require_auth()
    conn = get_db()
    try:
        sup = row(conn, "SELECT * FROM suppliers WHERE id = ?", (sid,))
        if not sup:
            return jsonify({"error": "Supplier not found"}), 404
        due = q1(conn, f"SELECT ({DUE_EXPR}) FROM suppliers s WHERE s.id = ?", (sid,))
        due_usd = q1(conn, f"SELECT ({DUE_USD_EXPR}) FROM suppliers s WHERE s.id = ?", (sid,))
        purchases = rows(conn, """
            SELECT pu.*, s.name AS supplier_name
            FROM purchases pu LEFT JOIN suppliers s ON s.id = pu.supplier_id
            WHERE pu.supplier_id = ?
            ORDER BY pu.id DESC
        """, (sid,))
        payments = rows(conn, """
            SELECT * FROM supplier_payments
            WHERE supplier_id = ?
            ORDER BY id DESC
        """, (sid,))
        return jsonify({
            "supplier": dict(sup),
            "due": due or 0,
            "due_usd": due_usd or 0,
            "purchases": [dict(p) for p in purchases],
            "payments": [dict(p) for p in payments],
        })
    finally:
        conn.close()
