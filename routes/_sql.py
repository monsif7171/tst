"""Shared SQL expressions to avoid duplication."""
from ._common import q1


# Supplier due calculation (balance + unpaid purchases - payments)
SUPPLIER_DUE_EXPR = """s.balance
    + COALESCE((SELECT SUM(total - paid) FROM purchases WHERE supplier_id = s.id), 0)
    - COALESCE((SELECT SUM(amount) FROM supplier_payments WHERE supplier_id = s.id), 0)"""

SUPPLIER_DUE_SQL = f"SELECT s.id, s.name, ({SUPPLIER_DUE_EXPR}) AS due FROM suppliers s"
SUPPLIER_DUE_SELECT = f"SELECT ({SUPPLIER_DUE_EXPR}) AS x FROM suppliers s"


# Profit calculation: sum of (qty * (sale_price - purchase_price))
PROFIT_EXPR = """COALESCE(SUM(si.qty * (si.price - p.purchase_price)), 0)"""


def get_supplier_dues(conn, branch_id=None, limit=None):
    """Get supplier dues with optional branch filter and limit."""
    sql = SUPPLIER_DUE_SQL
    params = []
    if branch_id is not None:
        sql += " WHERE s.branch_id = ?"
        params.append(branch_id)
    sql += " ORDER BY due DESC"
    if limit:
        sql += " LIMIT ?"
        params.append(limit)
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def get_total_supplier_due(conn):
    """Get total supplier due across all suppliers."""
    return q1(conn, SUPPLIER_DUE_SELECT)


def get_profit_for_sales(conn, branch_id=None, days=None):
    """Get profit from sales with optional branch filter and date range."""
    sql = f"SELECT {PROFIT_EXPR} AS profit FROM sales s JOIN sale_items si ON si.sale_id = s.id JOIN products p ON p.id = si.product_id WHERE 1=1"
    params = []
    if branch_id is not None:
        sql += " AND s.branch_id = ?"
        params.append(branch_id)
    if days is not None:
        sql += " AND date(s.sale_date) >= date('now', ?)"
        params.append(f"-{days} days")
    return q1(conn, sql, tuple(params)) or 0