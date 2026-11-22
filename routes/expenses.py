"""Operating expenses and daily cash summary."""
from flask import Blueprint, request, jsonify

from ._common import (get_db, rows, q1, now, audit, require_auth, require_role,
                      branch_scope, resolve_branch)
from .validation import ExpenseRequest, validate_payload

bp = Blueprint("expenses", __name__)


@bp.route("/api/expenses", methods=["GET"])
def list_expenses():
    u = require_auth()
    b = branch_scope(u)
    start = request.args.get("start")
    end = request.args.get("end")
    payment_type = request.args.get("payment_type")
    conn = get_db()
    try:
        sql = """SELECT e.*, uf.full_name AS user_name FROM expenses e
                 LEFT JOIN users uf ON uf.id = e.user_id WHERE 1=1"""
        params = []
        if b is not None:
            sql += " AND e.branch_id = ?"
            params.append(b)
        if start:
            sql += " AND date(e.expense_date) >= date(?)"
            params.append(start)
        if end:
            sql += " AND date(e.expense_date) <= date(?)"
            params.append(end)
        if payment_type:
            sql += " AND e.payment_type = ?"
            params.append(payment_type)
        sql += " ORDER BY e.id DESC LIMIT 200"
        return jsonify({"expenses": [dict(r) for r in rows(conn, sql, params)]})
    finally:
        conn.close()


@bp.route("/api/expenses", methods=["POST"])
def create_expense():
    u = require_role("admin", "pharmacist")
    d = request.get_json(force=True)
    val_data, err = validate_payload(ExpenseRequest, d)
    if err:
        return jsonify({"error": err}), 400
    amount = float(val_data["amount"])
    branch_id = resolve_branch(u, val_data)
    conn = get_db()
    try:
        cur = conn.execute(
            "INSERT INTO expenses (branch_id, user_id, expense_date, category, amount, note, payment_type) "
            "VALUES (?,?,?,?,?,?,?)",
            (branch_id, u["id"], now(), val_data.get("category"), amount, val_data.get("note"), val_data.get("payment_type") or "day"),
        )
        audit(conn, u["id"], branch_id, "create_expense", "expenses", cur.lastrowid,
              f"{val_data.get('category')}={amount}")
        conn.commit()
        return jsonify({"ok": True, "id": cur.lastrowid})
    finally:
        conn.close()


@bp.route("/api/expenses/summary", methods=["GET"])
def expenses_summary():
    u = require_auth()
    b = branch_scope(u)
    date = request.args.get("date") or None
    conn = get_db()
    try:
        params = []
        sql = "SELECT category, SUM(amount) AS total FROM expenses WHERE 1=1"
        if b is not None:
            sql += " AND branch_id = ?"
            params.append(b)
        if date:
            sql += " AND date(expense_date) = date(?)"
            params.append(date)
        sql += " GROUP BY category ORDER BY total DESC"
        return jsonify({"by_category": [dict(r) for r in rows(conn, sql, params)]})
    finally:
        conn.close()