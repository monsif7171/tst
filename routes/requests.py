"""Product requests for out-of-stock items."""
from flask import Blueprint, request, jsonify
from ._common import get_db, row, rows, q1, now, audit, require_auth, require_role, resolve_branch

bp = Blueprint("requests", __name__)


@bp.route("/api/product-requests", methods=["POST"])
def create_request():
    """Create a product request from POS."""
    u = require_auth()
    d = request.get_json(force=True)
    product_name = (d.get("product_name") or "").strip()
    customer_name = d.get("customer_name", "").strip()
    customer_phone = d.get("customer_phone", "").strip()
    note = d.get("note", "").strip()

    if not product_name:
        return jsonify({"error": "product_name required"}), 400

    branch_id = resolve_branch(u, d)
    conn = get_db()
    try:
        cur = conn.execute(
            "INSERT INTO product_requests (product_name, customer_name, customer_phone, note, branch_id, user_id) VALUES (?,?,?,?,?,?)",
            (product_name, customer_name, customer_phone, note, branch_id, u["id"])
        )
        conn.commit()
        audit(conn, u["id"], branch_id, "create_product_request", "product_requests", cur.lastrowid, product_name)
        return jsonify({"ok": True, "id": cur.lastrowid})
    finally:
        conn.close()


@bp.route("/api/product-requests", methods=["GET"])
def list_requests():
    """List product requests. Admin sees all, others see their branch only."""
    u = require_role("admin", "pharmacist")
    status_filter = request.args.get("status")
    search = (request.args.get("search") or "").strip()
    conn = get_db()
    try:
        if u["role"] == "admin":
            sql = """SELECT pr.*, b.name AS branch_name, usr.username AS user_name
                     FROM product_requests pr
                     LEFT JOIN branches b ON b.id = pr.branch_id
                     LEFT JOIN users usr ON usr.id = pr.user_id
                     WHERE 1=1"""
            params = []
            if status_filter:
                sql += " AND pr.status = ?"
                params.append(status_filter)
            if search:
                sql += " AND (pr.product_name LIKE ? OR pr.customer_name LIKE ? OR pr.customer_phone LIKE ? OR pr.note LIKE ?)"
                params.extend([f"%{search}%", f"%{search}%", f"%{search}%", f"%{search}%"])
            sql += " ORDER BY pr.id DESC"
        else:
            sql = """SELECT pr.*, b.name AS branch_name, usr.username AS user_name
                     FROM product_requests pr
                     LEFT JOIN branches b ON b.id = pr.branch_id
                     LEFT JOIN users usr ON usr.id = pr.user_id
                     WHERE pr.branch_id = ?"""
            params = [u["branch_id"]]
            if status_filter:
                sql += " AND pr.status = ?"
                params.append(status_filter)
            if search:
                sql += " AND (pr.product_name LIKE ? OR pr.customer_name LIKE ? OR pr.customer_phone LIKE ? OR pr.note LIKE ?)"
                params.extend([f"%{search}%", f"%{search}%", f"%{search}%", f"%{search}%"])
            sql += " ORDER BY pr.id DESC"
        return jsonify({"requests": [dict(r) for r in rows(conn, sql, params)]})
    finally:
        conn.close()


@bp.route("/api/product-requests/<int:rid>/status", methods=["POST"])
def update_status(rid):
    """Update request status (ordered, fulfilled, cancelled)."""
    u = require_role("admin", "pharmacist")
    d = request.get_json(force=True)
    status = d.get("status")
    if status not in ("pending", "ordered", "fulfilled", "cancelled"):
        return jsonify({"error": "invalid status"}), 400

    conn = get_db()
    try:
        req = row(conn, "SELECT id, branch_id FROM product_requests WHERE id = ?", (rid,))
        if not req:
            return jsonify({"error": "الطلب غير موجود"}), 404
        if u["role"] != "admin" and req["branch_id"] != u["branch_id"]:
            return jsonify({"error": "غير مصرح: لا يمكن تعديل حالة طلب لفرع آخر"}), 403

        conn.execute("UPDATE product_requests SET status = ? WHERE id = ?", (status, rid))
        audit(conn, u["id"], req["branch_id"], "update_request_status", "product_requests", rid, status)
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


@bp.route("/api/product-requests/<int:rid>", methods=["DELETE"])
def delete_request(rid):
    """Delete a product request (admin only)."""
    u = require_role("admin")
    conn = get_db()
    try:
        req = row(conn, "SELECT id, branch_id, product_name FROM product_requests WHERE id = ?", (rid,))
        if not req:
            return jsonify({"error": "الطلب غير موجود"}), 404
        conn.execute("DELETE FROM product_requests WHERE id = ?", (rid,))
        audit(conn, u["id"], req["branch_id"], "delete_product_request", "product_requests", rid, req["product_name"])
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()
