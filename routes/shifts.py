"""Shifts & Cash API: open and close cashier shifts with cash reconciliation."""
from flask import Blueprint, request, jsonify
from ._common import get_db, row, rows, q1, now, audit, require_auth, require_role, resolve_branch
from .validation import ShiftOpenRequest, ShiftCloseRequest, validate_payload

bp = Blueprint("shifts", __name__)

@bp.route("/api/shifts/open", methods=["POST"])
def open_shift():
    u = require_auth()
    d = request.get_json(force=True) or {}
    val_data, err = validate_payload(ShiftOpenRequest, d)
    if err:
        return jsonify({"error": err}), 400
    branch_id = resolve_branch(u, val_data)
    conn = get_db()
    try:
        active = row(conn, "SELECT * FROM shifts WHERE user_id = ? AND status = 'open'", (u["id"],))
        if active:
            return jsonify({"error": "shift already open", "shift": dict(active)}), 400
        opening_cash = float(d.get("opening_cash") or 0)
        cur = conn.execute(
            "INSERT INTO shifts (branch_id, user_id, opening_cash, status, opened_at) VALUES (?,?,?, 'open', ?)",
            (branch_id, u["id"], opening_cash, now())
        )
        conn.commit()
        return jsonify({"ok": True, "shift_id": cur.lastrowid})
    finally:
        conn.close()

@bp.route("/api/shifts/current", methods=["GET"])
def current_shift():
    u = require_auth()
    conn = get_db()
    try:
        s = row(conn, "SELECT * FROM shifts WHERE user_id = ? AND status = 'open'", (u["id"],))
        if not s:
            return jsonify({"shift": None})
        opening = float(s["opening_cash"])
        opened_at = s["opened_at"]
        branch_id = s["branch_id"]
        
        # Calculate cash received (including split payments if recorded)
        cash_sales = q1(conn, """
            SELECT COALESCE(SUM(amount), 0) FROM (
                SELECT sp.amount FROM sale_payments sp
                JOIN sales s ON s.id = sp.sale_id
                WHERE s.branch_id = ? AND s.user_id = ? AND sp.method = 'cash' AND s.sale_date >= ?
                UNION ALL
                SELECT s.total AS amount FROM sales s
                WHERE s.branch_id = ? AND s.user_id = ? AND s.payment_method = 'cash' AND s.sale_date >= ?
                AND NOT EXISTS (SELECT 1 FROM sale_payments WHERE sale_id = s.id)
            ) AS _cash_subq
        """, (branch_id, u["id"], opened_at, branch_id, u["id"], opened_at)) or 0

        # Customer cash refunds
        cash_returns = q1(conn, """
            SELECT COALESCE(SUM(amount), 0) FROM returns
            WHERE branch_id = ? AND user_id = ? AND type = 'customer' AND return_date >= ?
        """, (branch_id, u["id"], opened_at)) or 0

        expenses = q1(conn, "SELECT COALESCE(SUM(amount),0) FROM expenses WHERE branch_id = ? AND user_id = ? AND expense_date >= ?", (branch_id, u["id"], opened_at)) or 0
        expected = opening + float(cash_sales) - float(cash_returns) - float(expenses)
        res = dict(s)
        res["expected_cash"] = expected
        res["cash_sales"] = cash_sales
        res["cash_returns"] = cash_returns
        res["expenses"] = expenses
        return jsonify({"shift": res})
    finally:
        conn.close()

@bp.route("/api/shifts/close", methods=["POST"])
def close_shift():
    u = require_auth()
    d = request.get_json(force=True) or {}
    val_data, err = validate_payload(ShiftCloseRequest, d)
    if err:
        return jsonify({"error": err}), 400
    closing_cash = float(val_data.get("closing_cash") or 0)
    conn = get_db()
    try:
        s = row(conn, "SELECT * FROM shifts WHERE user_id = ? AND status = 'open'", (u["id"],))
        if not s:
            return jsonify({"error": "no open shift found"}), 400
        opening = float(s["opening_cash"])
        opened_at = s["opened_at"]
        branch_id = s["branch_id"]
        
        cash_sales = q1(conn, """
            SELECT COALESCE(SUM(amount), 0) FROM (
                SELECT sp.amount FROM sale_payments sp
                JOIN sales s ON s.id = sp.sale_id
                WHERE s.branch_id = ? AND s.user_id = ? AND sp.method = 'cash' AND s.sale_date >= ?
                UNION ALL
                SELECT s.total AS amount FROM sales s
                WHERE s.branch_id = ? AND s.user_id = ? AND s.payment_method = 'cash' AND s.sale_date >= ?
                AND NOT EXISTS (SELECT 1 FROM sale_payments WHERE sale_id = s.id)
            ) AS _cash_subq
        """, (branch_id, u["id"], opened_at, branch_id, u["id"], opened_at)) or 0

        cash_returns = q1(conn, """
            SELECT COALESCE(SUM(amount), 0) FROM returns
            WHERE branch_id = ? AND user_id = ? AND type = 'customer' AND return_date >= ?
        """, (branch_id, u["id"], opened_at)) or 0

        expenses = q1(conn, "SELECT COALESCE(SUM(amount),0) FROM expenses WHERE branch_id = ? AND user_id = ? AND expense_date >= ?", (branch_id, u["id"], opened_at)) or 0
        expected = opening + float(cash_sales) - float(cash_returns) - float(expenses)
        variance = closing_cash - expected

        shift_cols = [c[1] for c in conn.execute("PRAGMA table_info(shifts)").fetchall()]
        sets = ["expected_cash = ?", "variance = ?", "status = 'closed'", "closed_at = ?", "note = ?"]
        params = [expected, variance, now(), d.get("note")]
        if "closing_cash" in shift_cols:
            sets.insert(0, "closing_cash = ?")
            params.insert(0, closing_cash)
        if "actual_cash" in shift_cols:
            sets.insert(0, "actual_cash = ?")
            params.insert(0, closing_cash)
        params.append(s["id"])

        conn.execute(f"UPDATE shifts SET {', '.join(sets)} WHERE id = ?", params)
        conn.commit()
        return jsonify({"ok": True, "expected": expected, "variance": variance})
    finally:
        conn.close()
