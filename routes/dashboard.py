"""Owner dashboard API — the phone endpoint. Admin sees all branches."""
from flask import Blueprint, jsonify, request
from datetime import datetime, timedelta

from ._common import get_db, rows, q1, today, require_auth, branch_scope

bp = Blueprint("dashboard", __name__)

PROFIT_EXPR = """COALESCE(SUM(si.qty * (si.price - p.purchase_price)), 0)"""


def _scoped(u, col):
    b = branch_scope(u)
    if b is None:
        return "", (), b
    return f" AND {col} = ?", (b,), b


# Supplier due calculation (must be defined before dashboard() uses them)
SUPPLIER_DUE_EXPR = """s.balance
    + COALESCE((SELECT SUM(total - paid) FROM purchases WHERE supplier_id = s.id), 0)
    - COALESCE((SELECT SUM(amount) FROM supplier_payments WHERE supplier_id = s.id), 0)"""
SUPPLIER_DUE_SQL = f"SELECT s.id, s.name, ({SUPPLIER_DUE_EXPR}) AS due FROM suppliers s"
SUPPLIER_DUE_SELECT = f"SELECT ({SUPPLIER_DUE_EXPR}) AS x FROM suppliers s"


@bp.route("/api/dashboard", methods=["GET"])
def dashboard():
    u = require_auth()
    d = today()
    period = request.args.get("period", "today").strip().lower()
    if period not in ("today", "week", "month", "year"):
        period = "today"

    conn = get_db()
    try:
        sf, sp, b = _scoped(u, "s.branch_id")

        def row0(r):
            return r[0] if r else 0

        # Determine date start for the requested financial period
        now_dt = datetime.now()
        if period == "week":
            start_date = (now_dt - timedelta(days=6)).strftime("%Y-%m-%d")
        elif period == "month":
            start_date = (now_dt - timedelta(days=29)).strftime("%Y-%m-%d")
        elif period == "year":
            start_date = f"{now_dt.year}-01-01"
        else:
            start_date = d

        # Period aggregates (financial metrics)
        def period_sales_agg():
            if period == "today":
                sql = (f"SELECT COALESCE(SUM(total),0) AS total, COUNT(*) AS cnt FROM sales s "
                       f"WHERE s.sale_date LIKE ?" + sf)
                res = conn.execute(sql, (f"{d}%",) + sp).fetchone()
            else:
                sql = (f"SELECT COALESCE(SUM(total),0) AS total, COUNT(*) AS cnt FROM sales s "
                       f"WHERE date(s.sale_date) >= date(?) AND date(s.sale_date) <= date(?)" + sf)
                res = conn.execute(sql, (start_date, d) + sp).fetchone()
            if not res:
                return {"total": 0, "cnt": 0}
            return dict(res)

        def period_profit_agg():
            if period == "today":
                sql = (f"SELECT {PROFIT_EXPR} AS profit FROM sales s "
                       f"JOIN sale_items si ON si.sale_id = s.id JOIN products p ON p.id = si.product_id "
                       f"WHERE date(s.sale_date) = date(?)" + sf)
                return row0(conn.execute(sql, (d,) + sp).fetchone())
            else:
                sql = (f"SELECT {PROFIT_EXPR} AS profit FROM sales s "
                       f"JOIN sale_items si ON si.sale_id = s.id JOIN products p ON p.id = si.product_id "
                       f"WHERE date(s.sale_date) >= date(?) AND date(s.sale_date) <= date(?)" + sf)
                return row0(conn.execute(sql, (start_date, d) + sp).fetchone())

        def period_expenses_agg():
            if period == "today":
                sql = "SELECT COALESCE(SUM(amount),0) AS t FROM expenses WHERE date(expense_date) = date(?)"
                params = [d]
            else:
                sql = "SELECT COALESCE(SUM(amount),0) AS t FROM expenses WHERE date(expense_date) >= date(?) AND date(expense_date) <= date(?)"
                params = [start_date, d]
            if b is not None:
                sql += " AND branch_id = ?"
                params.append(b)
            return row0(conn.execute(sql, params).fetchone())

        y = (now_dt - timedelta(days=1)).strftime("%Y-%m-%d")
        y_sql = f"SELECT COALESCE(SUM(total),0) FROM sales s WHERE s.sale_date LIKE ?" + sf
        yesterday = row0(conn.execute(y_sql, (f"{y}%",) + sp).fetchone())

        financial_sales = period_sales_agg()
        if u["role"] in ("admin", "pharmacist"):
            financial_profit = period_profit_agg()
            financial_expenses = period_expenses_agg()
            financial_net_profit = financial_profit - financial_expenses
        else:
            financial_profit = 0.0
            financial_expenses = 0.0
            financial_net_profit = 0.0

        # Chart trend for the selected period
        if period == "today":
            # 24 hours or last 7 days? Showing last 7 days gives context, but let's show today by hour or last 7 days
            trend_sql = (f"SELECT date(s.sale_date) AS day, SUM(s.total) AS total, COUNT(*) AS cnt FROM sales s "
                         f"WHERE date(s.sale_date) >= date('now','-6 days')" + sf +
                         " GROUP BY day ORDER BY day")
            trend_data = [dict(r) for r in rows(conn, trend_sql, sp)]
        elif period == "week":
            trend_sql = (f"SELECT date(s.sale_date) AS day, SUM(s.total) AS total, COUNT(*) AS cnt FROM sales s "
                         f"WHERE date(s.sale_date) >= date(?) AND date(s.sale_date) <= date(?)" + sf +
                         " GROUP BY day ORDER BY day")
            trend_data = [dict(r) for r in rows(conn, trend_sql, (start_date, d) + sp)]
        elif period == "month":
            # Group by 5-day intervals or weeks or each day
            trend_sql = (f"SELECT date(s.sale_date) AS day, SUM(s.total) AS total, COUNT(*) AS cnt FROM sales s "
                         f"WHERE date(s.sale_date) >= date(?) AND date(s.sale_date) <= date(?)" + sf +
                         " GROUP BY day ORDER BY day")
            trend_data = [dict(r) for r in rows(conn, trend_sql, (start_date, d) + sp)]
        else: # year
            # Group by month for year
            trend_sql = (f"SELECT strftime('%Y-%m', s.sale_date) AS day, SUM(s.total) AS total, COUNT(*) AS cnt FROM sales s "
                         f"WHERE date(s.sale_date) >= date(?) AND date(s.sale_date) <= date(?)" + sf +
                         " GROUP BY strftime('%Y-%m', s.sale_date) ORDER BY day")
            trend_data = [dict(r) for r in rows(conn, trend_sql, (start_date, d) + sp)]

        # Top products for the selected period
        top_products = [dict(r) for r in rows(conn,
                 f"SELECT p.name, SUM(si.qty) AS qty, SUM(si.line_total) AS total FROM sale_items si "
                 f"JOIN sales s ON s.id = si.sale_id JOIN products p ON p.id = si.product_id "
                 f"WHERE date(s.sale_date) >= date(?) AND date(s.sale_date) <= date(?)" + sf +
                 " GROUP BY p.id ORDER BY qty DESC LIMIT 5", (start_date, d) + sp)]

        recent = [dict(r) for r in rows(conn,
                 f"SELECT s.id, s.invoice_no, s.total, s.sale_date, s.payment_method FROM sales s "
                 f"WHERE 1=1" + sf + " ORDER BY s.id DESC LIMIT 10", sp)]

        if b is None:
            low_sql = (
                "SELECT * FROM ("
                "  SELECT p.id, p.name, br.id AS branch_id, br.name AS branch_name, "
                "         COALESCE(bpl.min_qty, p.min_qty) AS min_qty, "
                "         COALESCE((SELECT SUM(bt.qty) FROM batches bt "
                "                   WHERE bt.product_id=p.id AND bt.branch_id=br.id "
                "                     AND (bt.expiry_date IS NULL OR bt.expiry_date >= date('now'))), 0) AS qty "
                "  FROM products p "
                "  JOIN branches br ON 1=1 "
                "  LEFT JOIN branch_product_limits bpl ON bpl.product_id=p.id AND bpl.branch_id=br.id "
                "  WHERE p.active=1"
                ") AS _low_q "
                "WHERE min_qty > 0 AND qty <= min_qty ORDER BY qty ASC LIMIT 10"
            )
            exp_sql = ("SELECT bt.id, p.name, bt.expiry_date, bt.qty, br.name AS branch_name FROM batches bt "
                       "JOIN products p ON p.id=bt.product_id LEFT JOIN branches br ON br.id=bt.branch_id "
                       "WHERE bt.qty>0 AND bt.expiry_date IS NOT NULL "
                       "AND bt.expiry_date >= date('now') AND bt.expiry_date <= date('now','+30 days') "
                       "ORDER BY bt.expiry_date LIMIT 10")
            expired_cnt = q1(conn, "SELECT COUNT(*) FROM batches WHERE qty>0 AND expiry_date IS NOT NULL "
                                   "AND expiry_date < date('now')")
            low_params = ()
            exp_params = ()
        else:
            low_sql = (
                "SELECT * FROM ("
                "  SELECT p.id, p.name, br.id AS branch_id, br.name AS branch_name, "
                "         COALESCE(bpl.min_qty, p.min_qty) AS min_qty, "
                "         COALESCE((SELECT SUM(bt.qty) FROM batches bt "
                "                   WHERE bt.product_id=p.id AND bt.branch_id=br.id "
                "                     AND (bt.expiry_date IS NULL OR bt.expiry_date >= date('now'))), 0) AS qty "
                "  FROM products p "
                "  JOIN branches br ON br.id=? "
                "  LEFT JOIN branch_product_limits bpl ON bpl.product_id=p.id AND bpl.branch_id=br.id "
                "  WHERE p.active=1"
                ") AS _low_q "
                "WHERE min_qty > 0 AND qty <= min_qty ORDER BY qty ASC LIMIT 10"
            )
            exp_sql = ("SELECT bt.id, p.name, bt.expiry_date, bt.qty, br.name AS branch_name FROM batches bt "
                       "JOIN products p ON p.id=bt.product_id LEFT JOIN branches br ON br.id=bt.branch_id "
                       "WHERE bt.branch_id=? AND bt.qty>0 AND bt.expiry_date IS NOT NULL "
                       "AND bt.expiry_date >= date('now') AND bt.expiry_date <= date('now','+30 days') "
                       "ORDER BY bt.expiry_date LIMIT 10")
            expired_cnt = q1(conn, "SELECT COUNT(*) FROM batches WHERE branch_id=? AND qty>0 "
                                   "AND expiry_date IS NOT NULL AND expiry_date < date('now')", (b,))
            low_params = (b,)
            exp_params = (b,)

        low = [dict(r) for r in rows(conn, low_sql, low_params)]
        expiring = [dict(r) for r in rows(conn, exp_sql, exp_params)]

        if u["role"] in ("admin", "pharmacist"):
            dues = [dict(r) for r in rows(conn, SUPPLIER_DUE_SQL + " ORDER BY due DESC LIMIT 5")]
            total_due = q1(conn, "SELECT COALESCE(SUM(x),0) FROM (" + SUPPLIER_DUE_SELECT + ") AS _due_subq")
        else:
            dues = []
            total_due = 0.0

        branches = []
        if b is None:
            branches = [dict(r) for r in rows(conn,
                "SELECT br.id, br.name, COALESCE((SELECT SUM(total) FROM sales s "
                "WHERE s.branch_id=br.id AND s.sale_date LIKE ?),0) AS today_total "
                "FROM branches br ORDER BY br.id", (f"{d}%",))]

        # Payment methods breakdown for the selected period
        pm_sql = "SELECT method, SUM(amount) AS total FROM sale_payments sp "
        pm_sql += "JOIN sales s ON s.id = sp.sale_id "
        if period == "today":
            pm_sql += "WHERE s.sale_date LIKE ?"
            pm_params = [f"{d}%"]
        else:
            pm_sql += "WHERE date(s.sale_date) >= date(?) AND date(s.sale_date) <= date(?)"
            pm_params = [start_date, d]

        if b is not None:
            pm_sql += " AND s.branch_id = ?"
            pm_params.append(b)
        pm_sql += " GROUP BY method"
        payment_methods = [dict(r) for r in rows(conn, pm_sql, pm_params)]

        if b is None:
            pending_requests = q1(conn, "SELECT COUNT(*) FROM product_requests WHERE status='pending'") or 0
        else:
            pending_requests = q1(conn, "SELECT COUNT(*) FROM product_requests WHERE branch_id=? AND status='pending'", (b,)) or 0

        return jsonify({
            "date": d,
            "period": period,
            "period_label": {"today": "اليوم", "week": "هذا الأسبوع", "month": "هذا الشهر", "year": "هذه السنة"}.get(period, "اليوم"),
            "today": {
                "sales": financial_sales["total"],
                "invoices": financial_sales["cnt"],
                "profit": financial_profit,
                "expenses": financial_expenses,
                "net_profit": financial_net_profit,
            },
            "financial": {
                "sales": financial_sales["total"],
                "invoices": financial_sales["cnt"],
                "profit": financial_profit,
                "expenses": financial_expenses,
                "net_profit": financial_net_profit,
            },
            "payment_methods": payment_methods,
            "yesterday_sales": yesterday,
            "week": trend_data,
            "trend": trend_data,
            "top_products": top_products,
            "recent_sales": recent,
            "low_stock": low,
            "expiring_soon": expiring,
            "expired_count": expired_cnt,
            "pending_requests_count": pending_requests,
            "supplier_dues": dues,
            "supplier_dues_total": total_due,
            "branches": branches,
        })
    finally:
        conn.close()
