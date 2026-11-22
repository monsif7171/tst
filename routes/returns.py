"""Returns API: customer returns."""
from flask import Blueprint, request, jsonify
from ._common import get_db, row, rows, q1, now, audit, require_auth, require_role, branch_scope, resolve_branch
from .sales import _restock

bp = Blueprint("returns", __name__)

@bp.route("/api/returns/customer/bulk", methods=["POST"])
def bulk_customer_return():
    u = require_role("admin", "pharmacist", "sales")
    d = request.get_json(force=True)
    sale_id = d.get("sale_id")
    items = d.get("items") or []

    if not sale_id or not items:
        return jsonify({"error": "sale_id and items required"}), 400

    conn = get_db()
    try:
        sale = row(conn, "SELECT * FROM sales WHERE id = ?", (sale_id,))
        if not sale:
            return jsonify({"error": "sale not found"}), 404
        if u["role"] != "admin" and sale["branch_id"] != u["branch_id"]:
            return jsonify({"error": "غير مصرح: لا يمكن إرجاع أصناف لفاتورة تابعة لفرع آخر"}), 403

        total_refund = 0.0
        returned_items_count = 0

        for item in items:
            pid = item.get("product_id")
            qty = float(item.get("qty") or 0)
            reason = item.get("reason") or d.get("reason")

            if not pid or qty <= 0:
                continue

            si = row(conn, "SELECT * FROM sale_items WHERE sale_id = ? AND product_id = ?", (sale_id, pid))
            if not si:
                continue

            prev_returned = q1(conn, "SELECT COALESCE(SUM(qty), 0) FROM returns WHERE sale_id = ? AND product_id = ? AND type = 'customer'", (sale_id, pid)) or 0
            available_to_return = max(0.0, float(si["qty"]) - float(prev_returned))
            if available_to_return <= 0:
                continue

            actual_qty = min(qty, available_to_return)

            _restock(conn, sale["branch_id"], pid, actual_qty, si["batch_no"], si["expiry_date"])
            amount = actual_qty * float(si["price"])
            total_refund += amount
            returned_items_count += 1

            conn.execute(
                "INSERT INTO returns (branch_id, user_id, sale_id, type, product_id, qty, amount, reason, return_date) VALUES (?,?,?,?,?,?,?,?,?)",
                (sale["branch_id"], u["id"], sale_id, "customer", pid, actual_qty, amount, reason, now())
            )

            # Adjust customer loyalty points if applicable
            if sale["customer_id"] and float(sale["total"] or 0) > 0:
                points_to_deduct = round(amount / 10.0, 2)
                conn.execute("UPDATE customers SET points = MAX(0, points - ?) WHERE id = ?", (points_to_deduct, sale["customer_id"]))
                conn.execute("INSERT INTO loyalty_ledger (customer_id, sale_id, points, type) VALUES (?,?,?,?)",
                             (sale["customer_id"], sale_id, -points_to_deduct, "redeem"))

        if returned_items_count == 0:
            return jsonify({"error": "No valid items to return"}), 400

        audit(conn, u["id"], sale["branch_id"], "customer_return_bulk", "returns", None, f"sale={sale_id} items_count={returned_items_count} refund={total_refund}")
        conn.commit()
        return jsonify({"ok": True, "refund": total_refund})
    finally:
        conn.close()


@bp.route("/api/returns/customer", methods=["POST"])
def customer_return():
    u = require_role("admin", "pharmacist", "sales")
    d = request.get_json(force=True)
    sale_id = d.get("sale_id")
    pid = d.get("product_id")
    qty = float(d.get("qty") or 0)
    if not sale_id or not pid or qty <= 0:
        return jsonify({"error": "sale_id, product_id, and positive qty required"}), 400
    conn = get_db()
    try:
        sale = row(conn, "SELECT * FROM sales WHERE id = ?", (sale_id,))
        if not sale:
            return jsonify({"error": "sale not found"}), 404
        if u["role"] != "admin" and sale["branch_id"] != u["branch_id"]:
            return jsonify({"error": "غير مصرح: لا يمكن إرجاع أصناف لفاتورة تابعة لفرع آخر"}), 403
        si = row(conn, "SELECT * FROM sale_items WHERE sale_id = ? AND product_id = ?", (sale_id, pid))
        if not si:
            return jsonify({"error": "item not found in this sale"}), 400

        # Prevent returning more than available remaining quantity
        prev_returned = q1(conn, "SELECT COALESCE(SUM(qty), 0) FROM returns WHERE sale_id = ? AND product_id = ? AND type = 'customer'", (sale_id, pid)) or 0
        available_to_return = max(0.0, float(si["qty"]) - float(prev_returned))
        if available_to_return <= 0:
            return jsonify({"error": "item has already been fully returned"}), 400
        qty = min(qty, available_to_return)

        _restock(conn, sale["branch_id"], pid, qty, si["batch_no"], si["expiry_date"])
        amount = qty * float(si["price"])
        conn.execute(
            "INSERT INTO returns (branch_id, user_id, sale_id, type, product_id, qty, amount, reason, return_date) VALUES (?,?,?,?,?,?,?,?,?)",
            (sale["branch_id"], u["id"], sale_id, "customer", pid, qty, amount, d.get("reason"), now())
        )

        # Adjust customer loyalty points if applicable
        if sale["customer_id"] and float(sale["total"] or 0) > 0:
            points_to_deduct = round(amount / 10.0, 2)
            conn.execute("UPDATE customers SET points = MAX(0, points - ?) WHERE id = ?", (points_to_deduct, sale["customer_id"]))
            conn.execute("INSERT INTO loyalty_ledger (customer_id, sale_id, points, type) VALUES (?,?,?,?)",
                         (sale["customer_id"], sale_id, -points_to_deduct, "redeem"))
        audit(conn, u["id"], sale["branch_id"], "customer_return", "returns", None, f"sale={sale_id} product={pid} qty={qty}")
        conn.commit()
        return jsonify({"ok": True, "refund": amount})
    finally:
        conn.close()
