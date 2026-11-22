"""Inventory Adjustments API: damages, returns, expiry, and stock differences."""
from flask import Blueprint, request, jsonify
from ._common import get_db, row, rows, q1, now, audit, require_role, resolve_branch, branch_scope

bp = Blueprint("adjustments", __name__)

@bp.route("/api/adjustments", methods=["GET"])
def list_adjustments():
    u = require_role("admin", "pharmacist")
    b = branch_scope(u)
    req_b = request.args.get("branch_id", type=int)
    effective_b = b if b is not None else req_b
    conn = get_db()
    try:
        sql = """
            SELECT ia.*, p.name as product_name, u.full_name as adjusted_by_name, br.name as branch_name
            FROM inventory_adjustments ia
            JOIN products p ON p.id = ia.product_id
            JOIN users u ON u.id = ia.adjusted_by
            LEFT JOIN branches br ON br.id = ia.branch_id
            WHERE 1=1
        """
        params = []
        if effective_b is not None:
            sql += " AND ia.branch_id = ?"
            params.append(effective_b)
        sql += " ORDER BY ia.adjustment_date DESC"
        return jsonify({"adjustments": [dict(r) for r in rows(conn, sql, params)]})
    finally:
        conn.close()

@bp.route("/api/adjustments", methods=["POST"])
def create_adjustment():
    u = require_role("admin", "pharmacist")
    d = request.get_json(force=True)
    product_id = d.get("product_id")
    qty = float(d.get("qty") or 0)
    reason_type = d.get("reason_type")

    if not product_id or qty == 0 or reason_type not in ("damage", "expiry", "return", "stock_difference"):
        return jsonify({"error": "Invalid adjustment data"}), 400

    branch_id = resolve_branch(u, d)
    conn = get_db()
    try:
        batch_id = d.get("batch_id")
        if batch_id:
            b_chk = row(conn, "SELECT id FROM batches WHERE id = ? AND branch_id = ? AND product_id = ?",
                        (batch_id, branch_id, product_id))
            if not b_chk:
                return jsonify({"error": "التشغيلة المحددة غير موجودة أو لا تنتمي لنفس الفرع والمنتج"}), 400
            conn.execute("UPDATE batches SET qty = MAX(0, qty + ?) WHERE id = ?", (qty, batch_id))
        else:
            b = row(conn, "SELECT id FROM batches WHERE branch_id = ? AND product_id = ? ORDER BY id DESC LIMIT 1", (branch_id, product_id))
            if b:
                batch_id = b["id"]
                conn.execute("UPDATE batches SET qty = MAX(0, qty + ?) WHERE id = ?", (qty, batch_id))
            elif qty > 0:
                cost = q1(conn, "SELECT COALESCE(purchase_price, 0) FROM products WHERE id = ?", (product_id,)) or 0
                b_cur = conn.execute(
                    "INSERT INTO batches (branch_id, product_id, batch_no, expiry_date, qty, cost) VALUES (?,?,?,?,?,?)",
                    (branch_id, product_id, "ADJ", None, qty, cost)
                )
                batch_id = b_cur.lastrowid

        cur = conn.execute(
            "INSERT INTO inventory_adjustments (branch_id, product_id, batch_id, qty, reason_type, reason_note, adjusted_by) VALUES (?,?,?,?,?,?,?)",
            (branch_id, product_id, batch_id, qty, reason_type, d.get("reason_note"), u["id"])
        )
        audit(conn, u["id"], branch_id, "adjust_inventory", "inventory_adjustments", cur.lastrowid, f"{reason_type}: {qty}")
        conn.commit()
        return jsonify({"ok": True, "id": cur.lastrowid})
    finally:
        conn.close()