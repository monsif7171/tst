"""Reporting and Financial Analytics API."""
from flask import Blueprint, request, jsonify
from ._common import get_db, rows, row, q1, require_role, branch_scope

bp = Blueprint("reports", __name__)

@bp.route("/api/reports/sales", methods=["GET"])
def sales_report():
    """Sales report with optional date filtering."""
    require_role("admin", "pharmacist")
    start = request.args.get("start")
    end = request.args.get("end")
    conn = get_db()
    try:
        sql = """
            SELECT s.invoice_no, s.sale_date, s.total, s.payment_method,
                   c.name as customer_name, u.full_name as staff_name
            FROM sales s
            LEFT JOIN customers c ON c.id = s.customer_id
            LEFT JOIN users u ON u.id = s.user_id
            WHERE 1=1
        """
        params = []
        if start:
            sql += " AND date(s.sale_date) >= date(?)"
            params.append(start)
        if end:
            sql += " AND date(s.sale_date) <= date(?)"
            params.append(end)
        sql += " ORDER BY s.sale_date DESC"
        return jsonify({"data": [dict(r) for r in rows(conn, sql, params)]})
    finally:
        conn.close()

@bp.route("/api/reports/profit", methods=["GET"])
def profit_report():
    """Daily profit breakdown."""
    require_role("admin", "pharmacist")
    start = request.args.get("start")
    end = request.args.get("end")
    conn = get_db()
    try:
        sql = """
            SELECT date(s.sale_date) as date,
                   SUM(s.total) as total_sales,
                   SUM((SELECT SUM(si.qty * p.purchase_price)
                        FROM sale_items si JOIN products p ON p.id = si.product_id
                        WHERE si.sale_id = s.id)) as total_cost,
                   SUM(s.total) - SUM((SELECT SUM(si.qty * p.purchase_price)
                        FROM sale_items si JOIN products p ON p.id = si.product_id
                        WHERE si.sale_id = s.id)) as profit
            FROM sales s
            WHERE 1=1
        """
        params = []
        if start:
            sql += " AND date(s.sale_date) >= date(?)"
            params.append(start)
        if end:
            sql += " AND date(s.sale_date) <= date(?)"
            params.append(end)
        sql += " GROUP BY date(s.sale_date) ORDER BY date"
        return jsonify({"data": [dict(r) for r in rows(conn, sql, params)]})
    finally:
        conn.close()

@bp.route("/api/reports/stock", methods=["GET"])
def stock_report():
    """Current stock levels for all products."""
    require_role("admin", "pharmacist")
    conn = get_db()
    try:
        sql = """
            SELECT p.name, p.barcode,
                   COALESCE((SELECT SUM(b.qty) FROM batches b WHERE b.product_id = p.id), 0) as stock,
                   p.min_qty, p.unit
            FROM products p
            WHERE p.active = 1
            ORDER BY p.name
        """
        return jsonify({"data": [dict(r) for r in rows(conn, sql)]})
    finally:
        conn.close()

@bp.route("/api/reports/expiry", methods=["GET"])
def expiry_report():
    """Expiring and expired batches."""
    require_role("admin", "pharmacist")
    start = request.args.get("start")
    end = request.args.get("end")
    conn = get_db()
    try:
        sql = """
            SELECT b.batch_no, b.expiry_date, b.qty, p.name as product_name, br.name as branch_name
            FROM batches b
            JOIN products p ON b.product_id = p.id
            JOIN branches br ON b.branch_id = br.id
            WHERE b.qty > 0 AND b.expiry_date IS NOT NULL
        """
        params = []
        if start:
            sql += " AND b.expiry_date >= date(?)"
            params.append(start)
        if end:
            sql += " AND b.expiry_date <= date(?)"
            params.append(end)
        sql += " ORDER BY b.expiry_date"
        return jsonify({"data": [dict(r) for r in rows(conn, sql, params)]})
    finally:
        conn.close()

@bp.route("/api/reports/top", methods=["GET"])
def top_report():
    """Top selling products."""
    require_role("admin", "pharmacist")
    start = request.args.get("start")
    end = request.args.get("end")
    conn = get_db()
    try:
        sql = """
            SELECT p.name, SUM(si.qty) as qty_sold, SUM(si.line_total) as total_revenue
            FROM sale_items si
            JOIN products p ON p.id = si.product_id
            JOIN sales s ON s.id = si.sale_id
            WHERE 1=1
        """
        params = []
        if start:
            sql += " AND date(s.sale_date) >= date(?)"
            params.append(start)
        if end:
            sql += " AND date(s.sale_date) <= date(?)"
            params.append(end)
        sql += " GROUP BY p.id ORDER BY qty_sold DESC LIMIT 20"
        return jsonify({"data": [dict(r) for r in rows(conn, sql, params)]})
    finally:
        conn.close()

@bp.route("/api/reports/supplier", methods=["GET"])
def supplier_report():
    """Supplier overview with dues and purchase history."""
    require_role("admin", "pharmacist")
    conn = get_db()
    try:
        sql = """
            SELECT s.id, s.name, s.phone, s.balance,
                   COALESCE((SELECT COUNT(*) FROM purchases WHERE supplier_id = s.id), 0) as purchase_count,
                   COALESCE((SELECT SUM(total - paid) FROM purchases WHERE supplier_id = s.id), 0) as due
            FROM suppliers s
            ORDER BY s.name
        """
        return jsonify({"data": [dict(r) for r in rows(conn, sql)]})
    finally:
        conn.close()

@bp.route("/api/reports/expenses", methods=["GET"])
def expenses_report():
    """Expense tracking report."""
    require_role("admin", "pharmacist")
    start = request.args.get("start")
    end = request.args.get("end")
    conn = get_db()
    try:
        sql = """
            SELECT e.expense_date, e.category, e.amount, e.note, u.full_name as user_name
            FROM expenses e
            JOIN users u ON u.id = e.user_id
            WHERE 1=1
        """
        params = []
        if start:
            sql += " AND date(e.expense_date) >= date(?)"
            params.append(start)
        if end:
            sql += " AND date(e.expense_date) <= date(?)"
            params.append(end)
        sql += " ORDER BY e.expense_date DESC"
        return jsonify({"data": [dict(r) for r in rows(conn, sql, params)]})
    finally:
        conn.close()


@bp.route("/api/reports/loyalty", methods=["GET"])
def loyalty_report():
    """Loyalty program report: members, points, rewards cost."""
    require_role("admin")
    start = request.args.get("start")
    end = request.args.get("end")
    conn = get_db()
    try:
        # Summary stats
        total_members = q1(conn, "SELECT COUNT(*) FROM customers WHERE phone IS NOT NULL AND phone != ''")

        active_members = 0
        if start or end:
            active_members = q1(conn, """
                SELECT COUNT(DISTINCT customer_id) FROM loyalty_ledger
                WHERE created_at >= date(?) AND created_at <= date(?)
            """, (start or "2000-01-01", end or "2100-01-01"))
        else:
            active_members = q1(conn, "SELECT COUNT(*) FROM customers WHERE points > 0")

        total_points_earned = 0
        if start:
            total_points_earned = q1(conn, "SELECT COALESCE(SUM(points), 0) FROM loyalty_ledger WHERE type = 'earn' AND date(created_at) BETWEEN date(?) AND date(?)", (start, end or "2100-01-01"))
        else:
            total_points_earned = q1(conn, "SELECT COALESCE(SUM(points), 0) FROM loyalty_ledger WHERE type = 'earn'")

        total_points_redeemed = 0
        if start:
            total_points_redeemed = q1(conn, "SELECT COALESCE(SUM(ABS(points)), 0) FROM loyalty_ledger WHERE type IN ('redeem_discount', 'redeem_product') AND date(created_at) BETWEEN date(?) AND date(?)", (start, end or "2100-01-01"))
        else:
            total_points_redeemed = q1(conn, "SELECT COALESCE(SUM(ABS(points)), 0) FROM loyalty_ledger WHERE type IN ('redeem_discount', 'redeem_product')")

        # Get point value from settings
        point_value = float(q1(conn, "SELECT value FROM settings WHERE key = 'loyalty_point_value'") or "0.5")
        total_discount_cost = total_points_redeemed * point_value if total_points_redeemed else 0

        # Top customers by points redeemed
        top_customers = rows(conn, """
            SELECT c.name, c.phone,
                   COALESCE((SELECT SUM(points) FROM loyalty_ledger WHERE customer_id = c.id AND type = 'earn'), 0) as points_earned,
                   COALESCE((SELECT SUM(ABS(points)) FROM loyalty_ledger WHERE customer_id = c.id AND type IN ('redeem_discount', 'redeem_product')), 0) as points_redeemed,
                   c.points as current_balance
            FROM customers c
            WHERE c.points > 0 OR EXISTS (SELECT 1 FROM loyalty_ledger WHERE customer_id = c.id)
            ORDER BY points_redeemed DESC
            LIMIT 10
        """)

        # Monthly breakdown
        monthly = []
        if start:
            monthly = rows(conn, """
                SELECT strftime('%Y-%m', created_at) as month,
                       SUM(CASE WHEN type = 'earn' THEN points ELSE 0 END) as earned,
                       SUM(CASE WHEN type IN ('redeem_discount', 'redeem_product') THEN ABS(points) ELSE 0 END) as redeemed
                FROM loyalty_ledger
                WHERE date(created_at) BETWEEN date(?) AND date(?)
                GROUP BY month ORDER BY month DESC LIMIT 12
            """, (start, end or "2100-01-01"))
        else:
            monthly = rows(conn, """
                SELECT strftime('%Y-%m', created_at) as month,
                       SUM(CASE WHEN type = 'earn' THEN points ELSE 0 END) as earned,
                       SUM(CASE WHEN type IN ('redeem_discount', 'redeem_product') THEN ABS(points) ELSE 0 END) as redeemed
                FROM loyalty_ledger
                GROUP BY month ORDER BY month DESC LIMIT 12
            """)

        # Reward products redemption stats
        reward_stats = rows(conn, """
            SELECT lr.id, p.name as product_name, lr.points_cost,
                   COUNT(ll.id) as times_redeemed,
                   COUNT(ll.id) * lr.points_cost as total_points_spent
            FROM loyalty_rewards lr
            JOIN products p ON p.id = lr.product_id
            LEFT JOIN loyalty_ledger ll ON ll.type = 'redeem_product' AND ll.note LIKE '%reward:' || lr.id || '%'
            WHERE lr.active = 1
            GROUP BY lr.id
            ORDER BY times_redeemed DESC
        """)

        return jsonify({
            "summary": {
                "total_members": total_members or 0,
                "active_members": active_members or 0,
                "total_points_earned": total_points_earned or 0,
                "total_points_redeemed": total_points_redeemed or 0,
                "total_discount_cost": round(total_discount_cost, 2),
                "point_value": point_value
            },
            "top_customers": [dict(c) for c in top_customers],
            "monthly": [dict(m) for m in monthly],
            "reward_stats": [dict(r) for r in reward_stats]
        })
    finally:
        conn.close()


@bp.route("/api/reports/product", methods=["GET"])
def product_report():
    """Specific drug detailed report."""
    require_role("admin", "pharmacist")
    product_id = request.args.get("product_id")
    start = request.args.get("start")
    end = request.args.get("end")
    conn = get_db()
    try:
        # If no product_id supplied, return active products list for dropdown
        if not product_id:
            products_list = rows(conn, """
                SELECT id, name, barcode, generic_name
                FROM products
                WHERE active = 1
                ORDER BY name
            """)
            return jsonify({"products": [dict(p) for p in products_list]})

        product_id = int(product_id)

        # 1. Product Basic Info
        product_info = row(conn, """
            SELECT p.*, s.name as supplier_name, c.name as category_name
            FROM products p
            LEFT JOIN suppliers s ON s.id = p.supplier_id
            LEFT JOIN categories c ON c.id = p.category_id
            WHERE p.id = ?
        """, (product_id,))

        if not product_info:
            return jsonify({"error": "المنتج غير موجود"}), 404

        # 2. Stock Batches
        batches_list = rows(conn, """
            SELECT b.batch_no, b.expiry_date, b.qty, b.cost, br.name as branch_name
            FROM batches b
            LEFT JOIN branches br ON br.id = b.branch_id
            WHERE b.product_id = ?
            ORDER BY b.expiry_date ASC
        """, (product_id,))

        total_stock = sum(b["qty"] for b in batches_list) if batches_list else 0

        # 3. Sales History
        sales_sql = """
            SELECT s.invoice_no, s.sale_date, si.qty, si.price, si.line_total, si.batch_no,
                   c.name as customer_name, u.full_name as staff_name, br.name as branch_name
            FROM sale_items si
            JOIN sales s ON s.id = si.sale_id
            LEFT JOIN customers c ON c.id = s.customer_id
            LEFT JOIN users u ON u.id = s.user_id
            LEFT JOIN branches br ON br.id = s.branch_id
            WHERE si.product_id = ?
        """
        sales_params = [product_id]
        if start:
            sales_sql += " AND date(s.sale_date) >= date(?)"
            sales_params.append(start)
        if end:
            sales_sql += " AND date(s.sale_date) <= date(?)"
            sales_params.append(end)
        sales_sql += " ORDER BY s.sale_date DESC"

        sales_list = rows(conn, sales_sql, sales_params)
        total_qty_sold = sum(s["qty"] for s in sales_list) if sales_list else 0
        total_sales_revenue = sum(s["line_total"] for s in sales_list) if sales_list else 0

        # 4. Purchases History
        purchases_sql = """
            SELECT pu.invoice_no, pu.purchase_date, pi.qty, pi.cost, (pi.qty * pi.cost) as total,
                   pi.batch_no, s.name as supplier_name, br.name as branch_name
            FROM purchase_items pi
            JOIN purchases pu ON pu.id = pi.purchase_id
            LEFT JOIN suppliers s ON s.id = pu.supplier_id
            LEFT JOIN branches br ON br.id = pu.branch_id
            WHERE pi.product_id = ?
        """
        purchases_params = [product_id]
        if start:
            purchases_sql += " AND date(pu.purchase_date) >= date(?)"
            purchases_params.append(start)
        if end:
            purchases_sql += " AND date(pu.purchase_date) <= date(?)"
            purchases_params.append(end)
        purchases_sql += " ORDER BY pu.purchase_date DESC"

        purchases_list = rows(conn, purchases_sql, purchases_params)
        total_qty_purchased = sum(p["qty"] for p in purchases_list) if purchases_list else 0
        total_purchases_cost = sum(p["total"] for p in purchases_list) if purchases_list else 0

        # 5. Inventory Adjustments
        adj_sql = """
            SELECT ia.adjustment_date, ia.qty, ia.reason_type, ia.reason_note,
                   u.full_name as user_name, br.name as branch_name
            FROM inventory_adjustments ia
            LEFT JOIN users u ON u.id = ia.adjusted_by
            LEFT JOIN branches br ON br.id = ia.branch_id
            WHERE ia.product_id = ?
        """
        adj_params = [product_id]
        if start:
            adj_sql += " AND date(ia.adjustment_date) >= date(?)"
            adj_params.append(start)
        if end:
            adj_sql += " AND date(ia.adjustment_date) <= date(?)"
            adj_params.append(end)
        adj_sql += " ORDER BY ia.adjustment_date DESC"

        adjustments_list = rows(conn, adj_sql, adj_params)

        # 6. Returns
        returns_sql = """
            SELECT r.return_date, r.type, r.qty, r.amount, r.reason,
                   u.full_name as user_name, br.name as branch_name
            FROM returns r
            LEFT JOIN users u ON u.id = r.user_id
            LEFT JOIN branches br ON br.id = r.branch_id
            WHERE r.product_id = ?
        """
        returns_params = [product_id]
        if start:
            returns_sql += " AND date(r.return_date) >= date(?)"
            returns_params.append(start)
        if end:
            returns_sql += " AND date(r.return_date) <= date(?)"
            returns_params.append(end)
        returns_sql += " ORDER BY r.return_date DESC"

        returns_list = rows(conn, returns_sql, returns_params)

        cost_price = product_info["purchase_price"] or 0
        total_estimated_cost = total_qty_sold * cost_price
        estimated_profit = total_sales_revenue - total_estimated_cost

        return jsonify({
            "product": dict(product_info),
            "summary": {
                "total_stock": total_stock,
                "total_qty_sold": total_qty_sold,
                "total_sales_revenue": round(total_sales_revenue, 2),
                "total_qty_purchased": total_qty_purchased,
                "total_purchases_cost": round(total_purchases_cost, 2),
                "estimated_profit": round(estimated_profit, 2)
            },
            "batches": [dict(b) for b in batches_list],
            "sales": [dict(s) for s in sales_list],
            "purchases": [dict(p) for p in purchases_list],
            "adjustments": [dict(a) for a in adjustments_list],
            "returns": [dict(r) for r in returns_list]
        })
    finally:
        conn.close()


@bp.route("/api/reports/staff_performance", methods=["GET"])
def staff_performance_report():
    """Employee performance report - Admin only."""
    require_role("admin")
    start = request.args.get("start")
    end = request.args.get("end")
    conn = get_db()
    try:
        users = rows(conn, "SELECT id, username, full_name, role, active, branch_id FROM users ORDER BY full_name")

        staff_data = []
        for u in users:
            uid = u["id"]

            # Sales stats
            sales_where = "user_id = ?"
            sales_params = [uid]
            if start:
                sales_where += " AND date(sale_date) >= date(?)"
                sales_params.append(start)
            if end:
                sales_where += " AND date(sale_date) <= date(?)"
                sales_params.append(end)

            sales_row = row(conn, f"""
                SELECT COUNT(*) as total_invoices,
                       COALESCE(SUM(total), 0) as total_sales,
                       COALESCE(SUM(discount), 0) as total_discounts
                FROM sales
                WHERE {sales_where}
            """, sales_params)

            # Returns stats
            ret_where = "user_id = ?"
            ret_params = [uid]
            if start:
                ret_where += " AND date(return_date) >= date(?)"
                ret_params.append(start)
            if end:
                ret_where += " AND date(return_date) <= date(?)"
                ret_params.append(end)

            returns_row = row(conn, f"""
                SELECT COUNT(*) as returns_count,
                       COALESCE(SUM(amount), 0) as returns_amount
                FROM returns
                WHERE {ret_where}
            """, ret_params)

            # Shift stats
            shift_where = "user_id = ?"
            shift_params = [uid]
            if start:
                shift_where += " AND date(opened_at) >= date(?)"
                shift_params.append(start)
            if end:
                shift_where += " AND date(opened_at) <= date(?)"
                shift_params.append(end)

            shift_row = row(conn, f"""
                SELECT COUNT(*) as total_shifts,
                       COALESCE(SUM(variance), 0) as total_variance
                FROM shifts
                WHERE {shift_where}
            """, shift_params)

            # Branch name
            branch_name = ""
            if u["branch_id"]:
                b_row = row(conn, "SELECT name FROM branches WHERE id = ?", (u["branch_id"],))
                if b_row:
                    branch_name = b_row["name"]

            tot_sales = sales_row["total_sales"] or 0
            ret_amt = returns_row["returns_amount"] or 0
            net_sales = tot_sales - ret_amt

            staff_data.append({
                "id": uid,
                "username": u["username"],
                "full_name": u["full_name"] or u["username"],
                "role": u["role"],
                "active": u["active"],
                "branch_name": branch_name,
                "total_invoices": sales_row["total_invoices"] or 0,
                "total_sales": round(tot_sales, 2),
                "total_discounts": round(sales_row["total_discounts"] or 0, 2),
                "returns_count": returns_row["returns_count"] or 0,
                "returns_amount": round(ret_amt, 2),
                "net_sales": round(net_sales, 2),
                "total_shifts": shift_row["total_shifts"] or 0,
                "total_variance": round(shift_row["total_variance"] or 0, 2)
            })

        # Calculate summary metrics
        overall_sales = sum(s["total_sales"] for s in staff_data)
        overall_invoices = sum(s["total_invoices"] for s in staff_data)
        overall_net = sum(s["net_sales"] for s in staff_data)
        overall_returns = sum(s["returns_amount"] for s in staff_data)

        return jsonify({
            "summary": {
                "overall_sales": round(overall_sales, 2),
                "overall_invoices": overall_invoices,
                "overall_net": round(overall_net, 2),
                "overall_returns": round(overall_returns, 2),
                "staff_count": len(staff_data)
            },
            "staff": staff_data
        })
    finally:
        conn.close()

