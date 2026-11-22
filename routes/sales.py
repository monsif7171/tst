"""Sales / POS: create, list, detail, cancel, customer return.
Expired batches are never dispensed (FEFO among valid batches only)."""
from flask import Blueprint, request, jsonify

from ._common import (get_db, row, rows, q1, now, audit, require_auth, require_role,
                      branch_scope, resolve_branch, next_invoice)

bp = Blueprint("sales", __name__)

# Updated stock consumption to prevent sale of expired items while supporting items without expiry
VALID_STOCK = ("SELECT * FROM batches WHERE branch_id = ? AND product_id = ? AND qty > 0 "
               "AND (expiry_date IS NULL OR expiry_date >= date('now')) "
               "ORDER BY expiry_date IS NULL, expiry_date ASC, id ASC")

def _consume_stock(conn, branch_id, product_id, qty):
    """Consume stock using FEFO and strictly reject expired items."""
    # First, verify if any non-expired stock exists
    bs = rows(conn, VALID_STOCK, (branch_id, product_id))

    # Check for expired but existing stock to raise specific alerts if needed
    expired_count = q1(conn, "SELECT SUM(qty) FROM batches WHERE branch_id = ? AND product_id = ? AND qty > 0 AND expiry_date < date('now')", (branch_id, product_id)) or 0
    if expired_count > 0:
        # We could log this or trigger a notification
        pass

    remaining = float(qty)
    batch_info = []
    for b in bs:
        if remaining <= 0:
            break
        take = min(float(b["qty"]), remaining)
        conn.execute("UPDATE batches SET qty = qty - ? WHERE id = ?", (take, b["id"]))
        batch_info.append({
            "batch_no": b["batch_no"],
            "expiry_date": b["expiry_date"],
            "qty": take
        })
        remaining -= take

    if remaining > 0:
        return "insufficient_stock", None
    return None, batch_info


def _restock(conn, branch_id, product_id, qty, batch_no=None, expiry_date=None):
    """Restock with batch tracking. If batch_no/expiry provided, use that batch; otherwise find matching batch."""
    if batch_no and expiry_date:
        bid = q1(conn, "SELECT id FROM batches WHERE branch_id = ? AND product_id = ? AND batch_no = ? AND expiry_date = ?",
                 (branch_id, product_id, batch_no, expiry_date))
        if bid:
            conn.execute("UPDATE batches SET qty = qty + ? WHERE id = ?", (qty, bid))
            return
    # Fallback: find newest batch for this product at this branch
    bid = q1(conn, "SELECT id FROM batches WHERE branch_id = ? AND product_id = ? "
                   "ORDER BY expiry_date IS NULL, expiry_date DESC, id DESC LIMIT 1",
             (branch_id, product_id))
    if bid:
        conn.execute("UPDATE batches SET qty = qty + ? WHERE id = ?", (qty, bid))
    else:
        conn.execute("INSERT INTO batches (branch_id, product_id, batch_no, expiry_date, qty, cost) "
                     "VALUES (?,?,?,?,?,0)", (branch_id, product_id, batch_no or "RETURN", expiry_date, qty))


@bp.route("/api/sales", methods=["POST"])
def create_sale():
    u = require_role("admin", "pharmacist", "sales")
    d = request.get_json(force=True)
    items = d.get("items") or []
    if not items:
        return jsonify({"error": "no items"}), 400
    branch_id = resolve_branch(u, d)
    conn = get_db()
    try:
        subtotal = 0.0
        validated_items = []
        for it in items:
            if not isinstance(it, dict) or not it.get("product_id"):
                return jsonify({"error": "بيانات الصنف غير صالحة"}), 400
            try:
                pid = int(it["product_id"])
                qty = float(it.get("qty") or 0)
            except (ValueError, TypeError):
                return jsonify({"error": "معرف المنتج أو الكمية غير صالحة"}), 400

            if qty <= 0:
                return jsonify({"error": f"الكمية للمنتج {pid} يجب أن تكون أكبر من الصفر"}), 400

            p = row(conn, "SELECT * FROM products WHERE id = ?", (pid,))
            if not p or not p["active"]:
                return jsonify({"error": f"product {pid} not found"}), 404

            catalog_price = float(p["sale_price"] or 0)
            client_price = it.get("price")
            if client_price is not None:
                try:
                    price = float(client_price)
                except (ValueError, TypeError):
                    price = catalog_price
            else:
                price = catalog_price

            if price < 0:
                return jsonify({"error": f"سعر المنتج {p['name']} لا يمكن أن يكون سالباً"}), 400

            # If client price is below catalog price, check if user has privilege or active promo applies
            if price < catalog_price and u["role"] not in ("admin", "pharmacist"):
                today_val = now().split(" ")[0]
                promo = row(conn, """
                    SELECT * FROM promotions
                    WHERE active = 1
                      AND (start_date IS NULL OR start_date <= ?)
                      AND (end_date IS NULL OR end_date >= ?)
                      AND (apply_to IN ('all', 'all_products', '')
                           OR (apply_to IN ('product', 'specific_products') AND product_ids LIKE ?)
                           OR (apply_to IN ('category', 'specific_categories') AND category_ids LIKE ?))
                    ORDER BY discount_value DESC LIMIT 1
                """, (today_val, today_val, f"%{pid}%", f"%{p['category_id']}%" if p.get('category_id') else "___none___"))

                promo_price = catalog_price
                if promo:
                    disc_type = promo["discount_type"] or "percentage"
                    disc_val = float(promo["discount_value"] or 0)
                    if disc_type == "percentage":
                        promo_price = max(0.0, catalog_price * (1.0 - (disc_val / 100.0)))
                    else:
                        promo_price = max(0.0, catalog_price - disc_val)

                if round(price, 2) < round(promo_price, 2):
                    price = promo_price

            line_total = price * qty
            subtotal += line_total
            validated_items.append({
                "product_id": pid,
                "qty": qty,
                "price": price,
                "line_total": line_total,
                "instructions": (str(it.get("instructions") or "").strip()[:500]) or None,
                "is_prescription": bool(p["is_prescription"]),
            })

        try:
            discount = float(d.get("discount") or 0)
        except (ValueError, TypeError):
            discount = 0.0
        if discount < 0:
            return jsonify({"error": "قيمة الخصم لا يمكن أن تكون سالبة"}), 400
        discount = min(discount, subtotal)
        total = max(0.0, subtotal - discount)

        try:
            paid = float(d.get("paid") or total)
        except (ValueError, TypeError):
            paid = total
        if paid < 0:
            return jsonify({"error": "المبلغ المدفوع لا يمكن أن يكون سالباً"}), 400

        # Validate points redemption before writing sale
        customer_id = d.get("customer_id")
        try:
            points_redeemed = float(d.get("points_redeemed") or 0)
        except (ValueError, TypeError):
            points_redeemed = 0.0

        if points_redeemed < 0:
            return jsonify({"error": "النقاط المستبدلة لا يمكن أن تكون سالبة"}), 400

        if points_redeemed > 0:
            if not customer_id:
                return jsonify({"error": "لا يمكن استبدال نقاط بدون تحديد عميل"}), 400
            cust = row(conn, "SELECT id, points FROM customers WHERE id = ?", (customer_id,))
            if not cust:
                return jsonify({"error": "العميل غير موجود"}), 404
            available_pts = float(cust["points"] or 0)
            if available_pts < points_redeemed:
                return jsonify({"error": f"رصيد نقاط العميل ({available_pts}) لا يكفي لاستبدال {points_redeemed} نقطة"}), 400

        invoice = next_invoice(conn, "sales", branch_id, "INV")
        cur = conn.execute(
            "INSERT INTO sales (branch_id, user_id, invoice_no, sale_date, customer_id, subtotal, "
            "discount, total, paid, payment_method, note) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (branch_id, u["id"], invoice, now(), customer_id, subtotal, discount,
             total, paid, d.get("payment_method") or "cash", d.get("note")),
        )
        sale_id = cur.lastrowid
        for vi in validated_items:
            err, batch_info = _consume_stock(conn, branch_id, vi["product_id"], vi["qty"])
            if err:
                conn.rollback()
                return jsonify({"error": err, "product_id": vi["product_id"]}), 400
            batch_no = batch_info[0]["batch_no"] if batch_info else None
            expiry_date = batch_info[0]["expiry_date"] if batch_info else None
            conn.execute(
                "INSERT INTO sale_items (sale_id, product_id, qty, price, line_total, batch_no, expiry_date, instructions) VALUES (?,?,?,?,?,?,?,?)",
                (sale_id, vi["product_id"], vi["qty"], vi["price"], vi["line_total"], batch_no, expiry_date, vi["instructions"]),
            )
        # Save payment methods
        payments = d.get("payment_methods", [])
        if not payments:
             payments = [{"method": d.get("payment_method", "cash"), "amount": paid}]

        for pmt in payments:
            conn.execute("INSERT INTO sale_payments (sale_id, method, amount) VALUES (?,?,?)",
                         (sale_id, pmt["method"], float(pmt["amount"])))

        # Loyalty points: use configurable earn rate, exclude prescription if configured
        earned_points = 0.0
        if customer_id and total > 0:
            from .loyalty import get_loyalty_settings
            ls = get_loyalty_settings(conn)
            try:
                earn_rate = float(ls.get("loyalty_earn_rate") or 10)
            except (ValueError, TypeError):
                earn_rate = 10.0
            if earn_rate <= 0:
                earn_rate = 10.0
            exclude_rx = ls.get("loyalty_exclude_prescription") == "1"

            eligible_total = total
            if exclude_rx:
                rx_total = sum(vi["line_total"] for vi in validated_items if vi["is_prescription"])
                eligible_total = max(0, total - rx_total)

            if eligible_total > 0:
                earned_points = round(eligible_total / earn_rate, 2)
                conn.execute("UPDATE customers SET points = points + ? WHERE id = ?", (earned_points, customer_id))
                conn.execute("INSERT INTO loyalty_ledger (customer_id, sale_id, points, type, note) VALUES (?,?,?,?,?)",
                             (customer_id, sale_id, earned_points, "earn", f"كسب من فاتورة {invoice}"))

        # Deduct redeemed points if customer used points as discount
        if customer_id and points_redeemed > 0:
            conn.execute("UPDATE customers SET points = MAX(0, points - ?) WHERE id = ?", (points_redeemed, customer_id))
            conn.execute("INSERT INTO loyalty_ledger (customer_id, sale_id, points, type, note) VALUES (?,?,?,?,?)",
                         (customer_id, sale_id, -points_redeemed, "redeem_discount", f"خصم نقاط على فاتورة {invoice}"))

        audit(conn, u["id"], branch_id, "create_sale", "sales", sale_id, f"{invoice} total={total}")
        conn.commit()
        return jsonify({"ok": True, "sale_id": sale_id, "invoice_no": invoice, "total": total,
                        "paid": paid, "change": max(0.0, paid - total),
                        "points_earned": earned_points, "points_redeemed": points_redeemed})
    finally:
        conn.close()


@bp.route("/api/sales", methods=["GET"])
def list_sales():
    u = require_auth()
    b = branch_scope(u)
    limit = request.args.get("limit", 50, type=int)
    date = request.args.get("date")
    conn = get_db()
    try:
        sql = """SELECT s.*, uf.full_name AS user_name, c.name AS customer_name
                 FROM sales s LEFT JOIN users uf ON uf.id = s.user_id
                 LEFT JOIN customers c ON c.id = s.customer_id WHERE 1=1"""
        params = []
        if b is not None:
            sql += " AND s.branch_id = ?"
            params.append(b)
        if date:
            sql += " AND s.sale_date LIKE ?"
            params.append(f"{date}%")
        sql += " ORDER BY s.id DESC LIMIT ?"
        params.append(limit)
        return jsonify({"sales": [dict(r) for r in rows(conn, sql, params)]})
    finally:
        conn.close()


@bp.route("/api/sales/invoice/<invoice_no>", methods=["GET"])
def get_sale_by_invoice(invoice_no):
    u = require_auth()
    conn = get_db()
    try:
        s = row(conn, "SELECT * FROM sales WHERE invoice_no = ?", (invoice_no,))
        if not s:
            return jsonify({"error": "not found"}), 404
        if u["role"] != "admin" and s["branch_id"] != u["branch_id"]:
            return jsonify({"error": "forbidden"}), 403

        # Get items
        items = rows(conn, """SELECT si.*, p.name, p.barcode FROM sale_items si
                              JOIN products p ON p.id = si.product_id WHERE si.sale_id = ?""", (s["id"],))

        # Get already returned items to calculate available quantity
        returns = rows(conn, "SELECT product_id, SUM(qty) as returned_qty FROM returns WHERE sale_id = ? GROUP BY product_id", (s["id"],))
        returned_map = {r["product_id"]: r["returned_qty"] for r in returns}

        out = dict(s)
        out["items"] = []
        for i in items:
            item = dict(i)
            item["returned_qty"] = returned_map.get(item["product_id"], 0)
            item["available_qty"] = float(item["qty"]) - float(item["returned_qty"])
            out["items"].append(item)

        out["customer_name"] = q1(conn, "SELECT name FROM customers WHERE id = ?", (s["customer_id"],)) if s["customer_id"] else None

        return jsonify(out)
    finally:
        conn.close()


@bp.route("/api/sales/<int:sid>", methods=["GET"])
def get_sale(sid):
    u = require_auth()
    conn = get_db()
    try:
        s = row(conn, "SELECT * FROM sales WHERE id = ?", (sid,))
        if not s:
            return jsonify({"error": "not found"}), 404
        if u["role"] != "admin" and s["branch_id"] != u["branch_id"]:
            return jsonify({"error": "forbidden"}), 403
        items = rows(conn, """SELECT si.*, p.name, p.barcode FROM sale_items si
                              JOIN products p ON p.id = si.product_id WHERE si.sale_id = ?""", (sid,))
        out = dict(s)
        out["items"] = [dict(i) for i in items]
        out["payments"] = [dict(p) for p in rows(conn, "SELECT method, amount FROM sale_payments WHERE sale_id = ?", (sid,))]
        return jsonify(out)
    finally:
        conn.close()


@bp.route("/api/sales/<int:sid>/cancel", methods=["POST"])
def cancel_sale(sid):
    u = require_role("admin", "pharmacist")
    conn = get_db()
    try:
        s = row(conn, "SELECT * FROM sales WHERE id = ?", (sid,))
        if not s:
            return jsonify({"error": "not found"}), 404
        if u["role"] != "admin" and s["branch_id"] != u["branch_id"]:
            return jsonify({"error": "forbidden"}), 403
        if q1(conn, "SELECT COUNT(*) FROM returns WHERE sale_id = ?", (sid,)):
            return jsonify({"error": "sale has returns, cancel blocked"}), 400

        # Restock items back to batches with original batch info
        for it in rows(conn, "SELECT * FROM sale_items WHERE sale_id = ?", (sid,)):
            _restock(conn, s["branch_id"], it["product_id"], float(it["qty"]), it["batch_no"], it["expiry_date"])

        # Revert loyalty points earned if any
        ledger_points = rows(conn, "SELECT id, customer_id, points FROM loyalty_ledger WHERE sale_id = ? AND type = 'earn'", (sid,))
        for lp in ledger_points:
            conn.execute("UPDATE customers SET points = MAX(0, points - ?) WHERE id = ?", (lp["points"], lp["customer_id"]))
        conn.execute("DELETE FROM loyalty_ledger WHERE sale_id = ?", (sid,))

        # Delete dependent rows and the sale record
        conn.execute("DELETE FROM sale_payments WHERE sale_id = ?", (sid,))
        conn.execute("DELETE FROM sale_items WHERE sale_id = ?", (sid,))
        conn.execute("DELETE FROM sales WHERE id = ?", (sid,))

        audit(conn, u["id"], s["branch_id"], "cancel_sale", "sales", sid, s["invoice_no"])
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


@bp.route("/api/sales/<int:sid>/return", methods=["POST"])
def return_item(sid):
    u = require_role("admin", "pharmacist", "sales")
    d = request.get_json(force=True)
    pid = d.get("product_id")
    qty = float(d.get("qty") or 0)
    if qty <= 0 or not pid:
        return jsonify({"error": "product_id and qty required"}), 400
    conn = get_db()
    try:
        s = row(conn, "SELECT * FROM sales WHERE id = ?", (sid,))
        if not s:
            return jsonify({"error": "not found"}), 404
        if u["role"] != "admin" and s["branch_id"] != u["branch_id"]:
            return jsonify({"error": "forbidden"}), 403
        si = row(conn, "SELECT * FROM sale_items WHERE sale_id = ? AND product_id = ?", (sid, pid))
        if not si:
            return jsonify({"error": "item not in sale"}), 400

        # Prevent returning more than available remaining quantity
        prev_returned = q1(conn, "SELECT COALESCE(SUM(qty), 0) FROM returns WHERE sale_id = ? AND product_id = ? AND type = 'customer'", (sid, pid)) or 0
        available_to_return = max(0.0, float(si["qty"]) - float(prev_returned))
        if available_to_return <= 0:
            return jsonify({"error": "item has already been fully returned"}), 400
        qty = min(qty, available_to_return)

        # Pass batch info from sale_item for accurate restocking
        _restock(conn, s["branch_id"], pid, qty, si["batch_no"], si["expiry_date"])
        amount = qty * float(si["price"])
        conn.execute(
            "INSERT INTO returns (branch_id, user_id, sale_id, type, product_id, qty, amount, reason, return_date) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (s["branch_id"], u["id"], sid, "customer", pid, qty, amount, d.get("reason"), now()),
        )

        # Adjust customer loyalty points if applicable
        if s["customer_id"] and float(s["total"] or 0) > 0:
            from .loyalty import get_loyalty_settings
            ls = get_loyalty_settings(conn)
            try:
                earn_rate = float(ls.get("loyalty_earn_rate") or 10)
            except (ValueError, TypeError):
                earn_rate = 10.0
            if earn_rate <= 0:
                earn_rate = 10.0
            points_to_deduct = round(amount / earn_rate, 2)
            conn.execute("UPDATE customers SET points = MAX(0, points - ?) WHERE id = ?", (points_to_deduct, s["customer_id"]))
            conn.execute("INSERT INTO loyalty_ledger (customer_id, sale_id, points, type, note) VALUES (?,?,?,?,?)",
                         (s["customer_id"], sid, -points_to_deduct, "adjust", "خصم نقاط بسبب مرتجع"))

        audit(conn, u["id"], s["branch_id"], "return_sale", "returns", None,
              f"sale={sid} product={pid} qty={qty}")
        conn.commit()
        return jsonify({"ok": True, "refund": amount})
    finally:
        conn.close()