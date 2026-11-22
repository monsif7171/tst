"""Loyalty system: settings, rewards catalog, redemption, points history."""
from flask import Blueprint, request, jsonify

from ._common import get_db, row, rows, q1, now, audit, require_auth, require_role, resolve_branch

bp = Blueprint("loyalty", __name__)

LOYALTY_DEFAULTS = {
    "loyalty_earn_rate": "10",       # currency units per 1 point
    "loyalty_point_value": "0.5",    # value of 1 point in currency when redeeming as discount
    "loyalty_min_redeem": "50",      # minimum points to redeem
    "loyalty_max_discount_pct": "30",  # max % of purchase that can be paid with points
    "loyalty_exclude_prescription": "1",  # exclude prescription drugs from earning
}


def get_loyalty_settings(conn):
    settings = {}
    for key, default in LOYALTY_DEFAULTS.items():
        val = q1(conn, "SELECT value FROM settings WHERE key = ?", (key,))
        settings[key] = val if val is not None else default
    return settings


@bp.route("/api/loyalty/settings", methods=["GET"])
def loyalty_settings():
    require_auth()
    conn = get_db()
    try:
        return jsonify({"settings": get_loyalty_settings(conn)})
    finally:
        conn.close()


@bp.route("/api/loyalty/settings", methods=["PUT"])
def update_loyalty_settings():
    u = require_role("admin")
    d = request.get_json(force=True) or {}
    conn = get_db()
    try:
        for k, v in d.items():
            if k in LOYALTY_DEFAULTS:
                conn.execute("INSERT INTO settings (key, value) VALUES (?,?) "
                             "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (k, str(v)))
        audit(conn, u["id"], None, "update_loyalty_settings", "settings", None, ",".join(d.keys()))
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


@bp.route("/api/loyalty/rewards", methods=["GET"])
def list_rewards():
    require_auth()
    conn = get_db()
    try:
        rs = rows(conn, """
            SELECT lr.*, p.name as product_name, p.sale_price, p.barcode
            FROM loyalty_rewards lr JOIN products p ON p.id = lr.product_id
            WHERE lr.active = 1 ORDER BY lr.points_cost
        """)
        return jsonify({"rewards": [dict(r) for r in rs]})
    finally:
        conn.close()


@bp.route("/api/loyalty/rewards", methods=["POST"])
def create_reward():
    u = require_role("admin")
    d = request.get_json(force=True)
    product_id = d.get("product_id")
    points_cost = float(d.get("points_cost") or 0)
    if not product_id or points_cost <= 0:
        return jsonify({"error": "product_id and points_cost required"}), 400
    conn = get_db()
    try:
        p = row(conn, "SELECT * FROM products WHERE id = ?", (product_id,))
        if not p:
            return jsonify({"error": "product not found"}), 404
        existing = q1(conn, "SELECT id FROM loyalty_rewards WHERE product_id = ? AND active = 1", (product_id,))
        if existing:
            conn.execute("UPDATE loyalty_rewards SET points_cost = ?, max_per_month = ? WHERE id = ?",
                         (points_cost, int(d.get("max_per_month") or 1), existing))
        else:
            conn.execute("INSERT INTO loyalty_rewards (product_id, points_cost, max_per_month) VALUES (?,?,?)",
                         (product_id, points_cost, int(d.get("max_per_month") or 1)))
        audit(conn, u["id"], None, "create_reward", "loyalty_rewards", product_id, f"cost={points_cost}")
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


@bp.route("/api/loyalty/rewards/<int:rid>", methods=["DELETE"])
def delete_reward(rid):
    u = require_role("admin")
    conn = get_db()
    try:
        conn.execute("UPDATE loyalty_rewards SET active = 0 WHERE id = ?", (rid,))
        audit(conn, u["id"], None, "deactivate_reward", "loyalty_rewards", rid)
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


@bp.route("/api/loyalty/redeem-discount", methods=["POST"])
def redeem_discount():
    """Calculate discount from points for a sale. Called before sale creation."""
    u = require_auth()
    d = request.get_json(force=True)
    customer_id = d.get("customer_id")
    points_to_use = float(d.get("points") or 0)
    if not customer_id or points_to_use <= 0:
        return jsonify({"error": "customer_id and points required"}), 400
    conn = get_db()
    try:
        settings = get_loyalty_settings(conn)
        c = row(conn, "SELECT * FROM customers WHERE id = ?", (customer_id,))
        if not c:
            return jsonify({"error": "customer not found"}), 404
        if c["points"] < points_to_use:
            return jsonify({"error": "insufficient_points", "available": c["points"]}), 400
        if points_to_use < float(settings["loyalty_min_redeem"]):
            return jsonify({"error": f"الحد الأدنى للاستبدال هو {settings['loyalty_min_redeem']} نقطة"}), 400
        discount_value = points_to_use * float(settings["loyalty_point_value"])
        return jsonify({"ok": True, "discount_value": round(discount_value, 2), "points_used": points_to_use})
    finally:
        conn.close()


@bp.route("/api/loyalty/redeem-product", methods=["POST"])
def redeem_product():
    """Redeem points for a specific reward product."""
    u = require_auth()
    d = request.get_json(force=True)
    customer_id = d.get("customer_id")
    reward_id = d.get("reward_id")
    if not customer_id or not reward_id:
        return jsonify({"error": "customer_id and reward_id required"}), 400
    conn = get_db()
    try:
        settings = get_loyalty_settings(conn)
        c = row(conn, "SELECT * FROM customers WHERE id = ?", (customer_id,))
        if not c:
            return jsonify({"error": "customer not found"}), 404
        reward = row(conn, """
            SELECT lr.*, p.name as product_name, p.barcode
            FROM loyalty_rewards lr JOIN products p ON p.id = lr.product_id
            WHERE lr.id = ? AND lr.active = 1
        """, (reward_id,))
        if not reward:
            return jsonify({"error": "reward not found"}), 404

        # Check monthly limit
        month_start = now()[:7] + "-01"
        redeemed_this_month = q1(conn, """
            SELECT COUNT(*) FROM loyalty_ledger
            WHERE customer_id = ? AND type = 'redeem_product'
            AND note LIKE ? AND created_at >= ?
        """, (customer_id, f"%reward:{reward_id}%", month_start)) or 0
        if redeemed_this_month >= reward["max_per_month"]:
            return jsonify({"error": f"تم استبدال هذا المنتج {reward['max_per_month']} مرة هذا الشهر (الحد الأقصى)"}), 400

        if c["points"] < reward["points_cost"]:
            return jsonify({"error": "insufficient_points", "available": c["points"],
                            "required": reward["points_cost"]}), 400

        # Consume 1 physical unit from branch inventory using FEFO
        branch_id = resolve_branch(u, d)
        from .sales import _consume_stock
        err, batch_info = _consume_stock(conn, branch_id, reward["product_id"], 1)
        if err:
            return jsonify({"error": "المنتج غير متوفر في المخزون المتاح للصرف حالياً في هذا الفرع"}), 400

        batch_str = f" [تشغيلة: {batch_info[0]['batch_no']}]" if batch_info and batch_info[0].get("batch_no") else ""
        conn.execute("UPDATE customers SET points = points - ? WHERE id = ?",
                     (reward["points_cost"], customer_id))
        conn.execute(
            "INSERT INTO loyalty_ledger (customer_id, points, type, note) VALUES (?,?,?,?)",
            (customer_id, -reward["points_cost"], "redeem_product",
             f"استبدال: {reward['product_name']} | reward:{reward_id}{batch_str}")
        )
        audit(conn, u["id"], branch_id, "redeem_product", "loyalty_ledger", customer_id,
              f"reward={reward_id} points={reward['points_cost']} product_id={reward['product_id']}")
        conn.commit()
        return jsonify({"ok": True, "product_name": reward["product_name"],
                        "points_spent": reward["points_cost"],
                        "remaining_points": c["points"] - reward["points_cost"]})
    finally:
        conn.close()


@bp.route("/api/loyalty/history/<int:customer_id>", methods=["GET"])
def points_history(customer_id):
    require_auth()
    limit = request.args.get("limit", 50, type=int)
    conn = get_db()
    try:
        entries = rows(conn, """
            SELECT ll.*, s.invoice_no FROM loyalty_ledger ll
            LEFT JOIN sales s ON s.id = ll.sale_id
            WHERE ll.customer_id = ? ORDER BY ll.id DESC LIMIT ?
        """, (customer_id, limit))
        return jsonify({"history": [dict(e) for e in entries]})
    finally:
        conn.close()
