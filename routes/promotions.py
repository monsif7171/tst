"""Promotions and Discounts Management API."""
from datetime import datetime as _dt, timedelta as _td
from flask import Blueprint, request, jsonify
from ._common import get_db, rows, row, q1, now, require_role, require_auth, audit

bp = Blueprint("promotions", __name__)

@bp.route("/api/promotions", methods=["GET"])
def list_promotions():
    u = require_auth()
    conn = get_db()
    try:
        sql = "SELECT * FROM promotions ORDER BY start_date DESC"
        return jsonify({"promotions": [dict(r) for r in rows(conn, sql)]})
    finally:
        conn.close()

@bp.route("/api/promotions", methods=["POST"])
def create_promotion():
    u = require_role("admin")
    d = request.get_json(force=True)
    conn = get_db()
    try:
        p_ids = d.get("product_ids")
        c_ids = d.get("category_ids")
        cur = conn.execute(
            "INSERT INTO promotions (name, discount_type, discount_value, start_date, end_date, apply_to, product_ids, category_ids, conditions, created_by, approved_by, approved_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                d.get("name"),
                d.get("discount_type", "percentage"),
                float(d.get("discount_value", 0)),
                d.get("start_date"),
                d.get("end_date"),
                d.get("apply_to", "all"),
                str(p_ids) if isinstance(p_ids, list) else p_ids,
                str(c_ids) if isinstance(c_ids, list) else c_ids,
                d.get("conditions"),
                u["id"],
                u["id"],
                now(),
            )
        )
        audit(conn, u["id"], u["branch_id"], "create_promotion", "promotions", cur.lastrowid, d.get("name"))
        conn.commit()
        return jsonify({"ok": True, "id": cur.lastrowid})
    finally:
        conn.close()

@bp.route("/api/promotions/<int:pid>", methods=["DELETE"])
def delete_promotion(pid):
    u = require_role("admin")
    conn = get_db()
    try:
        conn.execute("DELETE FROM promotions WHERE id = ?", (pid,))
        audit(conn, u["id"], u["branch_id"], "delete_promotion", "promotions", pid)
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


@bp.route("/api/promotions/<int:pid>", methods=["GET"])
def get_promotion(pid):
    require_role("admin", "pharmacist")
    conn = get_db()
    try:
        p = row(conn, "SELECT * FROM promotions WHERE id = ?", (pid,))
        if not p:
            return jsonify({"error": "not found"}), 404
        return jsonify(dict(p))
    finally:
        conn.close()


@bp.route("/api/promotions/<int:pid>", methods=["PUT"])
def update_promotion(pid):
    u = require_role("admin")
    d = request.get_json(force=True)
    conn = get_db()
    try:
        updates = []
        params = []
        if "name" in d:
            updates.append("name = ?")
            params.append(d["name"])
        if "discount_type" in d:
            updates.append("discount_type = ?")
            params.append(d["discount_type"])
        if "discount_value" in d:
            updates.append("discount_value = ?")
            params.append(d["discount_value"])
        if "start_date" in d:
            updates.append("start_date = ?")
            params.append(d["start_date"])
        if "end_date" in d:
            updates.append("end_date = ?")
            params.append(d["end_date"])
        if "apply_to" in d:
            updates.append("apply_to = ?")
            params.append(d["apply_to"])
        if "product_ids" in d:
            updates.append("product_ids = ?")
            params.append(str(d["product_ids"]) if isinstance(d["product_ids"], list) else d["product_ids"])
        if "category_ids" in d:
            updates.append("category_ids = ?")
            params.append(str(d["category_ids"]) if isinstance(d["category_ids"], list) else d["category_ids"])
        if "active" in d:
            updates.append("active = ?")
            params.append(1 if d["active"] else 0)
        if "conditions" in d:
            updates.append("conditions = ?")
            params.append(d["conditions"])
        # Re-approve when fields change: set approved_by/approved_at to current admin
        if any(k in d for k in ("name", "discount_type", "discount_value", "start_date", "end_date", "apply_to", "product_ids", "category_ids")):
            updates.append("approved_by = ?")
            params.append(u["id"])
            updates.append("approved_at = ?")
            params.append(now())

        if updates:
            params.append(pid)
            conn.execute(f"UPDATE promotions SET {','.join(updates)} WHERE id = ?", params)
            audit(conn, u["id"], u["branch_id"], "update_promotion", "promotions", pid, d.get("name"))

        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


@bp.route("/api/promotions/<int:pid>/approve", methods=["POST"])
def approve_promotion(pid):
    """Approve (activate) a promotion. Only the creator (admin) can do this."""
    u = require_role("admin")
    conn = get_db()
    try:
        p = row(conn, "SELECT * FROM promotions WHERE id = ?", (pid,))
        if not p:
            return jsonify({"error": "not found"}), 404
        conn.execute(
            "UPDATE promotions SET active = 1, approved_by = ?, approved_at = ? WHERE id = ?",
            (u["id"], now(), pid)
        )
        audit(conn, u["id"], u["branch_id"], "approve_promotion", "promotions", pid, p["name"])
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


@bp.route("/api/promotions/<int:pid>/reject", methods=["POST"])
def reject_promotion(pid):
    """Reject a promotion (deactivate without deleting)."""
    u = require_role("admin")
    conn = get_db()
    try:
        p = row(conn, "SELECT * FROM promotions WHERE id = ?", (pid,))
        if not p:
            return jsonify({"error": "not found"}), 404
        conn.execute(
            "UPDATE promotions SET active = 0 WHERE id = ?", (pid,)
        )
        audit(conn, u["id"], u["branch_id"], "reject_promotion", "promotions", pid, p["name"])
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


@bp.route("/api/reports/promotions", methods=["GET"])
def promotion_performance_report():
    """Sales comparison during and outside promotion periods per promotion."""
    require_role("admin")
    start = request.args.get("start")
    end = request.args.get("end")
    conn = get_db()
    try:
        sql = """
            SELECT p.id, p.name, p.discount_type, p.discount_value,
                   p.start_date, p.end_date, p.conditions,
                   p.active,
                   p.created_by AS created_by_id,
                   COALESCE(cb.full_name, '') AS created_by_name,
                   p.approved_by AS approved_by_id,
                   COALESCE(ab.full_name, '') AS approved_by_name,
                   p.approved_at
            FROM promotions p
            LEFT JOIN users cb ON cb.id = p.created_by
            LEFT JOIN users ab ON ab.id = p.approved_by
            WHERE 1=1
        """
        params = []
        if start:
            sql += " AND date(p.start_date) >= date(?)"
            params.append(start)
        if end:
            sql += " AND date(p.end_date) <= date(?)"
            params.append(end)
        sql += " ORDER BY p.start_date DESC"

        promos = rows(conn, sql, params)

        result = []
        for promo in promos:
            dur_start = promo["start_date"]
            dur_end = promo["end_date"]
            try:
                sd = _dt.strptime(dur_start[:10], "%Y-%m-%d")
                ed = _dt.strptime(dur_end[:10], "%Y-%m-%d")
                dur_days = (ed - sd).days
            except Exception:
                dur_days = 0

            baseline_start = (sd - _td(days=dur_days)).strftime("%Y-%m-%d") if dur_days > 0 else None
            baseline_end = (sd - _td(days=1)).strftime("%Y-%m-%d") if dur_days > 0 else None

            during = row(conn, """
                SELECT COALESCE(SUM(s.total), 0) AS during_total,
                       COALESCE(SUM(si.qty), 0) AS during_qty
                FROM sales s
                JOIN sale_items si ON si.sale_id = s.id
                WHERE date(s.sale_date) BETWEEN ? AND ?
            """, (dur_start[:10], dur_end[:10]))
            during = dict(during) if during else {"during_total": 0, "during_qty": 0}

            baseline = row(conn, """
                SELECT COALESCE(SUM(s.total), 0) AS baseline_total,
                       COALESCE(SUM(si.qty), 0) AS baseline_qty
                FROM sales s
                JOIN sale_items si ON si.sale_id = s.id
                WHERE date(s.sale_date) BETWEEN ? AND ?
            """, (baseline_start, baseline_end)) if baseline_start and baseline_end else {"baseline_total": 0, "baseline_qty": 0}

            products_during = rows(conn, """
                SELECT si.product_id, p.name AS product_name,
                       SUM(si.qty) AS qty, SUM(si.line_total) AS revenue
                FROM sale_items si
                JOIN sales s ON s.id = si.sale_id
                JOIN products p ON p.id = si.product_id
                WHERE date(s.sale_date) BETWEEN ? AND ?
                GROUP BY si.product_id
                ORDER BY revenue DESC
            """, (dur_start[:10], dur_end[:10]))

            p_dict = dict(promo)
            p_dict.update(during)
            p_dict.update(baseline)
            p_dict["products_during"] = [dict(r) for r in products_during]
            result.append(p_dict)

        return jsonify({"promotions": result})
    finally:
        conn.close()


@bp.route("/api/products/<int:pid>/promo-price", methods=["GET"])
def get_promo_price(pid):
    """Get promotional price for a product if any active promotion applies."""
    require_auth()
    conn = get_db()
    try:
        # Get product details
        product = row(conn, "SELECT * FROM products WHERE id = ?", (pid,))
        if not product:
            return jsonify({"error": "product not found"}), 404

        # Get base price
        base_price = float(product["sale_price"] or 0)

        # Check for active promotions
        today_val = now().split(" ")[0]  # Get date part only
        sql = """SELECT * FROM promotions
                 WHERE active = 1
                 AND (start_date IS NULL OR start_date <= ?)
                 AND (end_date IS NULL OR end_date >= ?)"""
        params = [today_val, today_val]

        promotions = rows(conn, sql, params)

        discount = 0
        for promo in promotions:
            apply_to = (promo["apply_to"] or "all").strip().lower()
            discount_type = promo["discount_type"] or "percentage"
            discount_value = float(promo["discount_value"] or 0)

            applies = False

            if apply_to in ("all", "all_products", ""):
                applies = True
            elif apply_to in ("product", "specific_products"):
                product_ids = str(promo["product_ids"] or "")
                if product_ids:
                    try:
                        ids = [int(x.strip()) for x in product_ids.strip("[]()'\" ").split(",") if x.strip()]
                        if pid in ids:
                            applies = True
                    except Exception:
                        pass
            elif apply_to in ("category", "specific_categories"):
                category_ids = str(promo["category_ids"] or "")
                prod_cat_id = product["category_id"] if "category_id" in product.keys() else None
                if category_ids and prod_cat_id is not None:
                    try:
                        ids = [int(x.strip()) for x in category_ids.strip("[]()'\" ").split(",") if x.strip()]
                        if int(prod_cat_id) in ids:
                            applies = True
                    except Exception:
                        pass

            if applies:
                if discount_type == "percentage":
                    discount = max(discount, base_price * (discount_value / 100))
                else:  # fixed
                    discount = max(discount, discount_value)

        final_price = max(0, base_price - discount)
        return jsonify({
            "product_id": pid,
            "base_price": base_price,
            "discount": discount,
            "final_price": final_price,
            "has_promotion": discount > 0
        })
    finally:
        conn.close()


@bp.route("/api/promotions/active-prices", methods=["GET"])
def get_all_promo_prices():
    """Return a map of product_id -> promo price info for all active products with an active promotion."""
    require_auth()
    conn = get_db()
    try:
        today_val = now().split(" ")[0]
        promotions = rows(conn, """
            SELECT * FROM promotions
            WHERE active = 1
            AND (start_date IS NULL OR start_date <= ?)
            AND (end_date IS NULL OR end_date >= ?)
        """, [today_val, today_val])
        if not promotions:
            return jsonify({"prices": {}})

        products = rows(conn, "SELECT id, sale_price, category_id FROM products WHERE active = 1")
        parsed_promos = []
        for promo in promotions:
            apply_to = (promo["apply_to"] or "all").strip().lower()
            discount_type = promo["discount_type"] or "percentage"
            discount_value = float(promo["discount_value"] or 0)
            p_ids = set()
            c_ids = set()
            if apply_to in ("product", "specific_products"):
                raw = str(promo["product_ids"] or "")
                try:
                    p_ids = {int(x.strip()) for x in raw.strip("[]()'\" ").split(",") if x.strip()}
                except Exception:
                    pass
            elif apply_to in ("category", "specific_categories"):
                raw = str(promo["category_ids"] or "")
                try:
                    c_ids = {int(x.strip()) for x in raw.strip("[]()'\" ").split(",") if x.strip()}
                except Exception:
                    pass
            parsed_promos.append((apply_to, discount_type, discount_value, p_ids, c_ids))

        prices = {}
        for prod in products:
            pid = prod["id"]
            base_price = float(prod["sale_price"] or 0)
            cat_id = prod["category_id"]
            discount = 0.0
            for apply_to, discount_type, discount_value, p_ids, c_ids in parsed_promos:
                applies = False
                if apply_to in ("all", "all_products", ""):
                    applies = True
                elif apply_to in ("product", "specific_products") and pid in p_ids:
                    applies = True
                elif apply_to in ("category", "specific_categories") and cat_id is not None and int(cat_id) in c_ids:
                    applies = True
                if applies:
                    if discount_type == "percentage":
                        discount = max(discount, base_price * (discount_value / 100.0))
                    else:
                        discount = max(discount, discount_value)
            if discount > 0:
                prices[str(pid)] = {
                    "product_id": pid,
                    "base_price": base_price,
                    "discount": discount,
                    "final_price": max(0.0, base_price - discount),
                    "has_promotion": True,
                }
        return jsonify({"prices": prices})
    finally:
        conn.close()
