"""Purchases API: record inbound invoices and update batches."""
from flask import Blueprint, request, jsonify
from ._common import get_db, row, rows, q1, now, audit, require_auth, require_role, branch_scope, resolve_branch, next_invoice

bp = Blueprint("purchases", __name__)

@bp.route("/api/purchases", methods=["POST"])
def create_purchase():
    u = require_role("admin", "pharmacist")
    d = request.get_json(force=True)
    items = d.get("items") or []
    if not items:
        return jsonify({"error": "no items"}), 400
    branch_id = resolve_branch(u, d)
    conn = get_db()
    try:
        # Validate items before processing
        for it in items:
            if not isinstance(it, dict) or not it.get("product_id"):
                return jsonify({"error": "بيانات صنف الشراء غير صالحة"}), 400
            try:
                iqty = float(it.get("qty") or 0)
                icost = float(it.get("cost") or 0)
            except (ValueError, TypeError):
                return jsonify({"error": "الكمية أو التكلفة غير صالحة"}), 400
            if iqty <= 0:
                return jsonify({"error": f"الكمية للمنتج {it.get('product_id')} يجب أن تكون أكبر من الصفر"}), 400
            if icost < 0:
                return jsonify({"error": f"التكلفة للمنتج {it.get('product_id')} لا يمكن أن تكون سالبة"}), 400

        rate_val = q1(conn, "SELECT value FROM settings WHERE key = 'usd_exchange_rate'")
        current_rate = float(rate_val) if rate_val and float(rate_val) > 0 else 1.0
        try:
            rate = float(d.get("rate") or current_rate)
        except (ValueError, TypeError):
            rate = current_rate
        if rate <= 0:
            rate = current_rate if current_rate > 0 else 1.0

        # Process each item with USD and local cost
        processed_items = []
        for it in items:
            qty = float(it.get("qty") or 0)
            cost_usd = float(it.get("cost_usd") or 0)
            cost = float(it.get("cost") or 0)

            if cost_usd > 0 and cost == 0:
                cost = round(cost_usd * rate, 2)
            elif cost > 0 and cost_usd == 0:
                cost_usd = round(cost / rate, 2)
            elif cost == 0 and cost_usd == 0:
                cost = 0.0
                cost_usd = 0.0

            processed_items.append({
                "product_id": int(it["product_id"]),
                "qty": qty,
                "cost": cost,
                "cost_usd": cost_usd,
                "batch_no": it.get("batch_no") or "DEFAULT",
                "expiry_date": it.get("expiry_date") or None
            })

        subtotal = sum(it["cost"] * it["qty"] for it in processed_items)
        discount = float(d.get("discount") or 0)
        extra_cost = float(d.get("extra_cost") or 0)
        total = max(0.0, subtotal - discount + extra_cost)
        total_usd = round(total / rate, 2) if rate > 0 else 0.0
        paid = min(float(d.get("paid") or 0), total)
        invoice = d.get("invoice_no") or next_invoice(conn, "purchases", branch_id, "PUR")
        cur = conn.execute(
            "INSERT INTO purchases (branch_id, supplier_id, invoice_no, purchase_date, subtotal, discount, extra_cost, total, rate, total_usd, paid, note) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (branch_id, d.get("supplier_id"), invoice, now(), subtotal, discount, extra_cost, total, rate, total_usd, paid, d.get("note"))
        )
        purchase_id = cur.lastrowid
        for it in processed_items:
            qty = it["qty"]
            cost = it["cost"]
            cost_usd = it["cost_usd"]
            b_no = it["batch_no"]
            exp = it["expiry_date"]
            conn.execute(
                "INSERT INTO purchase_items (purchase_id, product_id, qty, cost, cost_usd, batch_no, expiry_date) VALUES (?,?,?,?,?,?,?)",
                (purchase_id, it["product_id"], qty, cost, cost_usd, b_no, exp)
            )
            conn.execute(
                "INSERT INTO batches (branch_id, product_id, batch_no, expiry_date, qty, cost) VALUES (?,?,?,?,?,?)",
                (branch_id, it["product_id"], b_no, exp, qty, cost)
            )
            conn.execute(
                "UPDATE products SET purchase_price = ?, purchase_price_usd = ? WHERE id = ?",
                (cost, cost_usd, it["product_id"])
            )
        audit(conn, u["id"], branch_id, "create_purchase", "purchases", purchase_id, f"{invoice} total={total}")
        conn.commit()
        return jsonify({"ok": True, "purchase_id": purchase_id, "invoice_no": invoice, "total": total, "due": total - paid})
    finally:
        conn.close()

@bp.route("/api/purchases", methods=["GET"])
def list_purchases():
    u = require_auth()
    b = branch_scope(u)
    req_b = request.args.get("branch_id", type=int)
    effective_b = b if b is not None else req_b
    conn = get_db()
    try:
        sql = """SELECT pu.*, s.name AS supplier_name, br.name AS branch_name
                 FROM purchases pu
                 LEFT JOIN suppliers s ON s.id = pu.supplier_id
                 LEFT JOIN branches br ON br.id = pu.branch_id
                 WHERE 1=1"""
        params = []
        if effective_b is not None:
            sql += " AND pu.branch_id = ?"
            params.append(effective_b)
        sql += " ORDER BY pu.id DESC LIMIT 50"
        return jsonify({"purchases": [dict(r) for r in rows(conn, sql, params)]})
    finally:
        conn.close()

@bp.route("/api/purchases/<int:pid>", methods=["GET"])
def get_purchase(pid):
    u = require_auth()
    conn = get_db()
    try:
        purchase = row(conn, """SELECT pu.*, s.name AS supplier_name, s.phone AS supplier_phone,
                                 s.address AS supplier_address, br.name AS branch_name
                                 FROM purchases pu
                                 LEFT JOIN suppliers s ON s.id = pu.supplier_id
                                 LEFT JOIN branches br ON br.id = pu.branch_id
                                 WHERE pu.id = ?""", (pid,))
        if not purchase:
            return jsonify({"error": "Purchase not found"}), 404
        if u["role"] != "admin" and purchase["branch_id"] != u["branch_id"]:
            return jsonify({"error": "غير مصرح: لا يمكن استعراض مشتريات فرع آخر"}), 403
        items = rows(conn, """
            SELECT pi.*, p.name AS product_name
            FROM purchase_items pi
            JOIN products p ON p.id = pi.product_id
            WHERE pi.purchase_id = ?
        """, (pid,))
        return jsonify({"purchase": dict(purchase), "items": [dict(i) for i in items]})
    finally:
        conn.close()
