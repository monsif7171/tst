"""Products, batches, stock levels, expiry alerts, Excel/CSV import."""
import csv
import datetime
import io
import os
import re
import sqlite3
import random
import time

from flask import Blueprint, request, jsonify, send_file
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment

from ._common import (get_db, row, rows, q1, now, today, audit, require_auth,
                      require_role, branch_scope, resolve_branch)
from .validation import ProductRequest, BatchRequest, validate_payload
from .drug_service import lookup_drug_by_barcode, search_drugs_online

bp = Blueprint("products", __name__)

HEADER_ALIASES = {
    "name": ("name", "الاسم", "اسم الدواء", "اسم المنتج", "الصنف", "اسم الصنف", "الدواء", "product", "product_name", "item", "item_name"),
    "generic_name": ("generic_name", "المادة الفعالة", "الاسم العلمي", "العلمي", "generic", "active_ingredient"),
    "strength": ("strength", "التركيز", "dosage", "تركيز"),
    "form": ("form", "الشكل الدوائي", "الشكل", "dosage_form"),
    "manufacturer": ("manufacturer", "الشركة", "الشركة المصنعة", "المصنع", "company"),
    "category": ("category", "التصنيف", "الفئة", "تصنيف", "القسم", "فئة", "group"),
    "barcode": ("barcode", "الباركود", "باركود", "كود", "code", "upc", "ean"),
    "purchase_price": ("purchase_price", "سعر الشراء", "سعر التكلفة", "التكلفة", "cost", "cost_price", "purchase price"),
    "sale_price": ("sale_price", "سعر البيع", "سعر المستهلك", "السعر", "price", "sale price"),
    "purchase_price_usd": ("purchase_price_usd", "سعر الشراء بالدولار", "تكلفة الدولار", "cost_usd", "purchase price usd"),
    "sale_price_usd": ("sale_price_usd", "سعر البيع بالدولار", "سعر الدولار", "سعر المستهلك بالدولار", "price_usd", "sale price usd"),
    "min_qty": ("min_qty", "الحد الأدنى", "الحد الادنى", "حد الطلب", "min", "min_limit"),
    "unit": ("unit", "الوحدة", "وحدة"),
    "strip_qty": ("strip_qty", "عدد الحبات بالشريط", "حبات بالشريط", "شريط"),
    "carton_qty": ("carton_qty", "عدد الاشرطة بالكرتونة", "أشرطة بالكرتونة", "كرتونة"),
    "supplier_id": ("supplier_id", "المورد", "supplier"),
    "qty": ("qty", "الكمية", "كمية", "المخزون", "الرصيد", "رصيد", "الكمية الحالية", "الرصيد الابتدائي", "quantity", "stock", "count"),
    "expiry_date": ("expiry_date", "تاريخ الصلاحية", "تاريخ الانتهاء", "الصلاحية", "الانتهاء", "expiry", "exp_date"),
    "batch_no": ("batch_no", "رقم التشغيلة", "رقم الدفعة", "الدفعة", "تشغيلة", "batch", "lot"),
}


def _clean_barcode(val):
    if val is None:
        return None
    if isinstance(val, float):
        val = int(val)
    s = str(val).strip()
    if not s or s.lower() in ("nan", "none", "null"):
        return None
    if s.endswith(".0") and s[:-2].isdigit():
        s = s[:-2]
    return s


def _clean_date(val):
    if not val:
        return None
    if isinstance(val, (datetime.date, datetime.datetime)):
        return val.strftime("%Y-%m-%d")
    s = str(val).strip()
    if not s or s.lower() in ("nan", "none", "null"):
        return None
    m1 = re.match(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", s)
    if m1:
        y, m, d = m1.groups()
        return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"
    m2 = re.match(r"^(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})", s)
    if m2:
        d, m, y = m2.groups()
        return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"
    return s[:10]


def _resolve_category(conn, cat_name):
    if not cat_name:
        return None, None
    cat_name = str(cat_name).strip()
    if not cat_name:
        return None, None
    c = row(conn, "SELECT id, name FROM categories WHERE LOWER(name) = LOWER(?)", (cat_name,))
    if c:
        return c["id"], c["name"]
    try:
        cur = conn.execute("INSERT INTO categories (name) VALUES (?)", (cat_name,))
        return cur.lastrowid, cat_name
    except sqlite3.IntegrityError:
        c = row(conn, "SELECT id, name FROM categories WHERE LOWER(name) = LOWER(?)", (cat_name,))
        return (c["id"], c["name"]) if c else (None, cat_name)



@bp.route("/api/products/generate-barcode", methods=["GET"])
def generate_unique_barcode():
    u = require_auth()
    conn = get_db()
    try:
        while True:
            code = str(random.randint(100000000000, 999999999999))
            exists = q1(conn, "SELECT id FROM products WHERE barcode = ?", (code,))
            if not exists:
                return jsonify({"barcode": code})
    finally:
        conn.close()


@bp.route("/api/products/lookup-external", methods=["GET"])
def lookup_external_product():
    """Lookup product in external public drug database (OpenFDA) by barcode or name."""
    require_auth()
    barcode = request.args.get("barcode", "").strip()
    name = request.args.get("name", "").strip()

    if not barcode and not name:
        return jsonify({"found": False, "message": "يرجى تحديد الباركود أو اسم الدواء للبحث"}), 400

    conn = get_db()
    try:
        existing = None
        if barcode:
            existing = row(conn, "SELECT id, name, sale_price, purchase_price, generic_name, strength, form, barcode FROM products WHERE barcode = ? AND active = 1", (barcode,))

        drug = None
        if barcode:
            drug = lookup_drug_by_barcode(barcode, conn=conn)

        if not drug and name:
            results = search_drugs_online(name, limit=1, conn=conn)
            if results:
                drug = results[0]
                if barcode and not drug.get("barcode"):
                    drug["barcode"] = barcode

        if drug:
            if drug.get("category"):
                cat_row = row(conn, "SELECT id, name FROM categories WHERE LOWER(name) = LOWER(?)", (drug["category"],))
                if cat_row:
                    drug["category_id"] = cat_row["id"]
                    drug["category"] = cat_row["name"]

            return jsonify({
                "found": True,
                "already_exists_locally": bool(existing),
                "existing_product": dict(existing) if existing else None,
                "product": drug
            })

        return jsonify({
            "found": False,
            "already_exists_locally": bool(existing),
            "existing_product": dict(existing) if existing else None,
            "message": "لم يتم العثور على الدواء في المستودع العام"
        })
    finally:
        conn.close()


@bp.route("/api/products/search-external", methods=["GET"])
def search_external_products():
    """Search external public drug database (OpenFDA) by name or active ingredient for autocomplete/catalog."""
    require_auth()
    q = request.args.get("q", "").strip()
    limit = request.args.get("limit", 10, type=int)

    if not q or len(q) < 2:
        return jsonify({"results": []})

    conn = get_db()
    try:
        results = search_drugs_online(q, limit=limit, conn=conn)
        return jsonify({"results": results})
    finally:
        conn.close()


@bp.route("/api/products/quick-import-external", methods=["POST"])
def quick_import_external_product():
    """Quickly import a product from external search directly into the local database."""
    u = require_role("admin", "pharmacist")
    data = request.get_json(force=True) or {}

    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "اسم الدواء مطلوب"}), 400

    barcode = (data.get("barcode") or "").strip() or None
    conn = get_db()
    try:
        if barcode:
            exists = row(conn, "SELECT id, name FROM products WHERE barcode = ? AND active = 1", (barcode,))
            if exists:
                return jsonify({"error": f"الباركود مستخدم بالفعل مع دواء ({exists['name']})", "existing_id": exists["id"]}), 409

        cat_name = data.get("category")
        cat_id = data.get("category_id")
        if not cat_id and cat_name:
            cat_id, cat_name = _resolve_category(conn, cat_name)
        elif cat_id:
            c = row(conn, "SELECT name FROM categories WHERE id = ?", (cat_id,))
            cat_name = c["name"] if c else None

        rate_val = q1(conn, "SELECT value FROM settings WHERE key = 'usd_exchange_rate'")
        rate = float(rate_val) if rate_val and float(rate_val) > 0 else 1.0

        try:
            pur_price = float(data.get("purchase_price") or 0)
        except (ValueError, TypeError):
            pur_price = 0.0

        try:
            sale_price = float(data.get("sale_price") or 0)
        except (ValueError, TypeError):
            sale_price = 0.0

        try:
            pur_price_usd = float(data.get("purchase_price_usd") or 0)
        except (ValueError, TypeError):
            pur_price_usd = 0.0

        try:
            sale_price_usd = float(data.get("sale_price_usd") or 0)
        except (ValueError, TypeError):
            sale_price_usd = 0.0

        if pur_price > 0 and pur_price_usd == 0 and rate > 0:
            pur_price_usd = round(pur_price / rate, 2)
        elif pur_price_usd > 0 and pur_price == 0:
            pur_price = round(pur_price_usd * rate, 2)

        if sale_price > 0 and sale_price_usd == 0 and rate > 0:
            sale_price_usd = round(sale_price / rate, 2)
        elif sale_price_usd > 0 and sale_price == 0:
            sale_price = round(sale_price_usd * rate)

        try:
            min_qty = float(data.get("min_qty") or 5)
        except (ValueError, TypeError):
            min_qty = 5.0

        try:
            strip_qty = float(data.get("strip_qty") or 1)
        except (ValueError, TypeError):
            strip_qty = 1.0

        try:
            carton_qty = float(data.get("carton_qty") or 1)
        except (ValueError, TypeError):
            carton_qty = 1.0

        cur = conn.execute(
            """INSERT INTO products (
                name, generic_name, strength, form, manufacturer,
                category, category_id, barcode, purchase_price, sale_price,
                purchase_price_usd, sale_price_usd, min_qty, unit, strip_qty, carton_qty,
                supplier_id, is_prescription, active
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
            (
                name,
                data.get("generic_name") or None,
                data.get("strength") or None,
                data.get("form") or None,
                data.get("manufacturer") or None,
                cat_name or None,
                cat_id or None,
                barcode,
                pur_price,
                sale_price,
                pur_price_usd,
                sale_price_usd,
                min_qty,
                data.get("unit") or "علبة",
                strip_qty,
                carton_qty,
                data.get("supplier_id") or None,
                1 if data.get("is_prescription") else 0
            )
        )
        pid = cur.lastrowid
        user_branch = u.get("branch_id") if hasattr(u, "get") else u["branch_id"]
        audit(conn, u["id"], user_branch, "import_external_product", "products", pid, f"name={name}, barcode={barcode}")
        conn.commit()

        os.makedirs("data/barcodes", exist_ok=True)
        if barcode:
            try:
                from barcode import get as bc_get
                bc_get('code128', str(barcode)).save(f"data/barcodes/{pid}")
            except Exception:
                pass

        prod = row(conn, "SELECT * FROM products WHERE id = ?", (pid,))
        return jsonify({"ok": True, "product": dict(prod)})
    finally:
        conn.close()



def _save_branch_limits(conn, pid: int, branch_limits):
    """Save or clear per-branch min_qty overrides for a product."""
    if not isinstance(branch_limits, dict):
        return
    for k, val in branch_limits.items():
        try:
            bid = int(k)
        except (ValueError, TypeError):
            continue
        if val is None or str(val).strip() == "":
            conn.execute(
                "DELETE FROM branch_product_limits WHERE branch_id = ? AND product_id = ?",
                (bid, pid),
            )
        else:
            try:
                mval = float(val)
            except (ValueError, TypeError):
                continue
            if mval < 0:
                continue
            existing = row(
                conn,
                "SELECT id FROM branch_product_limits WHERE branch_id = ? AND product_id = ?",
                (bid, pid),
            )
            if existing:
                conn.execute(
                    "UPDATE branch_product_limits SET min_qty = ? WHERE id = ?",
                    (mval, existing["id"]),
                )
            else:
                conn.execute(
                    "INSERT INTO branch_product_limits (branch_id, product_id, min_qty) VALUES (?,?,?)",
                    (bid, pid, mval),
                )


@bp.route("/api/products", methods=["GET"])
def list_products():
    u = require_auth()
    b = branch_scope(u)
    req_b = request.args.get("branch_id", type=int)
    effective_b = b if b is not None else req_b
    search = (request.args.get("search") or "").strip()
    category = request.args.get("category")
    conn = get_db()
    try:
        if effective_b is None:
            sql = """SELECT p.*,
                     p.min_qty AS default_min_qty,
                     COALESCE(c.name, p.category, '') AS category,
                     COALESCE((SELECT SUM(qty) FROM batches WHERE product_id=p.id AND (expiry_date IS NULL OR expiry_date >= date('now'))),0) AS stock,
                     COALESCE((SELECT SUM(qty) FROM batches WHERE product_id=p.id),0) AS total_stock_with_expired
                     FROM products p LEFT JOIN categories c ON c.id = p.category_id
                     WHERE p.active = 1"""
            params = []
        else:
            sql = """SELECT p.*,
                     p.min_qty AS default_min_qty,
                     COALESCE((SELECT min_qty FROM branch_product_limits WHERE product_id=p.id AND branch_id=?), p.min_qty) AS min_qty,
                     (SELECT min_qty FROM branch_product_limits WHERE product_id=p.id AND branch_id=?) AS custom_branch_min_qty,
                     COALESCE(c.name, p.category, '') AS category,
                     COALESCE((SELECT SUM(qty) FROM batches WHERE product_id=p.id AND branch_id=? AND (expiry_date IS NULL OR expiry_date >= date('now'))),0) AS stock,
                     COALESCE((SELECT SUM(qty) FROM batches WHERE product_id=p.id AND branch_id=?),0) AS total_stock_with_expired
                     FROM products p LEFT JOIN categories c ON c.id = p.category_id
                     WHERE p.active = 1"""
            params = [effective_b, effective_b, effective_b, effective_b]
        if search:
            like = f"%{search}%"
            sql += " AND (p.name LIKE ? OR p.barcode LIKE ? OR p.generic_name LIKE ?)"
            params += [like, like, like]
        if category:
            sql += " AND (p.category = ? OR c.name = ?)"
            params += [category, category]
        sql += " ORDER BY p.name"
        return jsonify({"products": [dict(r) for r in rows(conn, sql, params)]})
    finally:
        conn.close()


@bp.route("/api/products/<int:pid>", methods=["GET"])
def get_product(pid):
    u = require_auth()
    b = branch_scope(u)
    conn = get_db()
    try:
        if b is None:
            p = row(conn, """SELECT p.*, p.min_qty AS default_min_qty, COALESCE(c.name, p.category, '') AS category,
                             COALESCE((SELECT SUM(qty) FROM batches WHERE product_id=p.id),0) AS stock
                             FROM products p LEFT JOIN categories c ON c.id = p.category_id WHERE p.id = ?""", (pid,))
        else:
            p = row(conn, """SELECT p.*, p.min_qty AS default_min_qty,
                             COALESCE((SELECT min_qty FROM branch_product_limits WHERE product_id=p.id AND branch_id=?), p.min_qty) AS min_qty,
                             COALESCE(c.name, p.category, '') AS category,
                             COALESCE((SELECT SUM(qty) FROM batches WHERE product_id=p.id AND branch_id=?),0) AS stock
                             FROM products p LEFT JOIN categories c ON c.id = p.category_id WHERE p.id = ?""", (b, b, pid))
        if not p:
            return jsonify({"error": "not found"}), 404
        out = dict(p)
        br_rows = rows(conn, """
            SELECT br.id AS branch_id, br.name AS branch_name,
                   bpl.min_qty AS custom_min_qty,
                   COALESCE(bpl.min_qty, ?) AS effective_min_qty,
                   COALESCE((SELECT SUM(bt.qty) FROM batches bt
                             WHERE bt.product_id = ? AND bt.branch_id = br.id
                               AND (bt.expiry_date IS NULL OR bt.expiry_date >= date('now'))), 0) AS stock
            FROM branches br
            LEFT JOIN branch_product_limits bpl ON bpl.branch_id = br.id AND bpl.product_id = ?
            ORDER BY br.id
        """, (out.get("default_min_qty", out.get("min_qty", 0)), pid, pid))
        out["branch_limits"] = [dict(r) for r in br_rows]
        return jsonify(out)
    finally:
        conn.close()


@bp.route("/api/products/<int:pid>/branches-lookup", methods=["GET"])
def product_branches_lookup(pid):
    """Cross-branch stock lookup + same generic_name alternatives for POS and inventory."""
    u = require_auth()
    curr_b = u["branch_id"]
    conn = get_db()
    try:
        p = row(conn, "SELECT * FROM products WHERE id = ?", (pid,))
        if not p:
            return jsonify({"error": "not found"}), 404
        p_dict = dict(p)

        br_rows = rows(conn, """
            SELECT br.id AS branch_id, br.name AS branch_name, br.phone, br.address,
                   bpl.min_qty AS custom_min_qty,
                   COALESCE(bpl.min_qty, ?) AS min_qty,
                   COALESCE((SELECT SUM(bt.qty) FROM batches bt
                             WHERE bt.product_id = ? AND bt.branch_id = br.id
                               AND (bt.expiry_date IS NULL OR bt.expiry_date >= date('now'))), 0) AS stock,
                   COALESCE((SELECT SUM(bt.qty) FROM batches bt
                             WHERE bt.product_id = ? AND bt.branch_id = br.id
                               AND bt.expiry_date IS NOT NULL AND bt.expiry_date < date('now')), 0) AS expired_stock
            FROM branches br
            LEFT JOIN branch_product_limits bpl ON bpl.branch_id = br.id AND bpl.product_id = ?
            ORDER BY br.id
        """, (p_dict.get("min_qty") or 0, pid, pid, pid))

        branches_list = []
        for r in br_rows:
            d_br = dict(r)
            d_br["is_current"] = bool(curr_b is not None and d_br["branch_id"] == curr_b)
            branches_list.append(d_br)

        alternatives = []
        gen = (p_dict.get("generic_name") or "").strip()
        if gen:
            alt_rows = rows(conn, """
                SELECT id, name, generic_name, strength, form, sale_price, unit, is_prescription
                FROM products
                WHERE active = 1 AND id != ? AND LOWER(TRIM(generic_name)) = LOWER(TRIM(?))
                ORDER BY name
            """, (pid, gen))
            for ar in alt_rows:
                ad = dict(ar)
                alt_pid = ad["id"]
                alt_brs = rows(conn, """
                    SELECT br.id AS branch_id, br.name AS branch_name, br.phone,
                           COALESCE((SELECT SUM(bt.qty) FROM batches bt
                                     WHERE bt.product_id = ? AND bt.branch_id = br.id
                                       AND (bt.expiry_date IS NULL OR bt.expiry_date >= date('now'))), 0) AS stock
                    FROM branches br
                    ORDER BY br.id
                """, (alt_pid,))
                alt_branches = []
                curr_stock = 0.0
                other_stock = 0.0
                for abr in alt_brs:
                    abd = dict(abr)
                    is_curr = bool(curr_b is not None and abd["branch_id"] == curr_b)
                    abd["is_current"] = is_curr
                    st = float(abd["stock"] or 0)
                    if curr_b is not None:
                        if is_curr:
                            curr_stock += st
                        else:
                            other_stock += st
                    else:
                        curr_stock += st
                    if st > 0:
                        alt_branches.append(abd)
                ad["current_stock"] = curr_stock
                ad["other_branches_stock"] = other_stock
                ad["branches_with_stock"] = alt_branches
                alternatives.append(ad)

        return jsonify({
            "product": p_dict,
            "current_branch_id": curr_b,
            "branches": branches_list,
            "alternatives": alternatives,
        })
    finally:
        conn.close()


@bp.route("/api/products/<int:pid>/branch-limits", methods=["PUT"])
def update_product_branch_limits(pid):
    """Update per-branch reorder limits (min_qty) for a product."""
    u = require_role("admin", "pharmacist")
    d = request.get_json(force=True)
    conn = get_db()
    try:
        p = row(conn, "SELECT id, name, min_qty FROM products WHERE id = ?", (pid,))
        if not p:
            return jsonify({"error": "not found"}), 404
        if u["role"] == "admin":
            if "default_min_qty" in d and d["default_min_qty"] is not None:
                conn.execute("UPDATE products SET min_qty = ? WHERE id = ?", (float(d["default_min_qty"] or 0), pid))
            _save_branch_limits(conn, pid, d.get("branch_limits") or {})
        else:
            if u["branch_id"]:
                _save_branch_limits(conn, pid, {str(u["branch_id"]): d.get("min_qty")})
        audit(conn, u["id"], u["branch_id"], "update_branch_limits", "products", pid, p["name"])
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


@bp.route("/api/products/<int:pid>/barcode", methods=["GET"])
def get_barcode(pid):
    u = require_auth()
    b = branch_scope(u)
    conn = get_db()
    try:
        if b is None:
            p = row(conn, "SELECT barcode, name, sale_price FROM products WHERE id = ?", (pid,))
        else:
            p = row(conn, "SELECT barcode, name, sale_price FROM products WHERE id = ? AND active = 1", (pid,))
        if not p or not p["barcode"]:
            return jsonify({"error": "no barcode"}), 404
        p_dict = dict(p)
        barcode_val = p_dict["barcode"]
        img_path = f"data/barcodes/{pid}.svg"
        if not os.path.exists(img_path):
            os.makedirs("data/barcodes", exist_ok=True)
            try:
                from barcode import get as bc_get
                bc_get('code128', barcode_val).save(f"data/barcodes/{pid}")
            except Exception as e:
                print(f"Barcode generation warning: {e}")
        return jsonify({
            "barcode": barcode_val,
            "name": p_dict.get("name", ""),
            "sale_price": p_dict.get("sale_price", 0),
            "image_url": f"/data/barcodes/{pid}.svg"
        })
    finally:
        conn.close()


@bp.route("/api/products", methods=["POST"])
def create_product():
    u = require_role("admin", "pharmacist")
    d = request.get_json(force=True) or {}
    val_data, err = validate_payload(ProductRequest, d)
    if err:
        return jsonify({"error": err}), 400
    name = val_data["name"]
    strip_qty = float(val_data.get("strip_qty") or 1)
    carton_qty = float(val_data.get("carton_qty") or 1)
    purchase_price = float(val_data.get("purchase_price") or 0)
    sale_price = float(val_data.get("sale_price") or 0)
    purchase_price_usd = float(val_data.get("purchase_price_usd") or 0)
    sale_price_usd = float(val_data.get("sale_price_usd") or 0)
    min_qty = float(val_data.get("min_qty") or 0)

    conn = get_db()
    try:
        rate_val = q1(conn, "SELECT value FROM settings WHERE key = 'usd_exchange_rate'")
        rate = float(rate_val) if rate_val and float(rate_val) > 0 else 1.0

        if sale_price_usd > 0 and sale_price == 0:
            sale_price = round(sale_price_usd * rate)
        elif sale_price > 0 and sale_price_usd == 0:
            sale_price_usd = round(sale_price / rate, 2)

        if purchase_price_usd > 0 and purchase_price == 0:
            purchase_price = round(purchase_price_usd * rate, 2)
        elif purchase_price > 0 and purchase_price_usd == 0:
            purchase_price_usd = round(purchase_price / rate, 2)

        cat_id = val_data.get("category_id")
        try:
            cat_id = int(cat_id) if cat_id else None
        except (ValueError, TypeError):
            cat_id = None

        cat_name = (val_data.get("category") or "").strip()
        if cat_id and not cat_name:
            cat_name = q1(conn, "SELECT name FROM categories WHERE id = ?", (cat_id,)) or ""
        elif cat_name and not cat_id:
            cat_id = q1(conn, "SELECT id FROM categories WHERE name = ?", (cat_name,))

        barcode_val = val_data.get("barcode")
        if not barcode_val:
            barcode_val = str(random.randint(100000000000, 999999999999))

        cur = conn.execute(
            "INSERT INTO products (name, generic_name, strength, form, manufacturer, category, category_id, "
            "barcode, purchase_price, sale_price, purchase_price_usd, sale_price_usd, min_qty, unit, strip_qty, carton_qty, supplier_id, is_prescription) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (name, val_data.get("generic_name"), val_data.get("strength"), val_data.get("form"),
             val_data.get("manufacturer"), cat_name, cat_id, barcode_val,
             purchase_price, sale_price, purchase_price_usd, sale_price_usd, min_qty, val_data.get("unit") or "piece",
             strip_qty, carton_qty, val_data.get("supplier_id"), int(val_data.get("is_prescription", 0))),
        )
        pid = cur.lastrowid
        if val_data.get("branch_limits"):
            _save_branch_limits(conn, pid, val_data.get("branch_limits"))
        audit(conn, u["id"], u["branch_id"], "create_product", "products", pid, name)
        conn.commit()
        os.makedirs("data/barcodes", exist_ok=True)
        try:
            from barcode import get as bc_get
            bc_get('code128', barcode_val).save(f"data/barcodes/{pid}")
        except Exception as e:
            print(f"Barcode generation warning: {e}")
        return jsonify({"ok": True, "id": pid, "barcode": barcode_val})
    except sqlite3.IntegrityError:
        return jsonify({"error": "barcode already exists"}), 409
    finally:
        conn.close()


@bp.route("/api/products/<int:pid>", methods=["PUT"])
def update_product(pid):
    u = require_role("admin", "pharmacist")
    d = request.get_json(force=True) or {}
    val_data, err = validate_payload(ProductRequest, d)
    if err:
        return jsonify({"error": err}), 400
    strip_qty = float(val_data.get("strip_qty") or 1)
    carton_qty = float(val_data.get("carton_qty") or 1)
    purchase_price = float(val_data.get("purchase_price") or 0)
    sale_price = float(val_data.get("sale_price") or 0)
    purchase_price_usd = float(val_data.get("purchase_price_usd") or 0)
    sale_price_usd = float(val_data.get("sale_price_usd") or 0)
    min_qty = float(val_data.get("min_qty") or 0)

    conn = get_db()
    try:
        rate_val = q1(conn, "SELECT value FROM settings WHERE key = 'usd_exchange_rate'")
        rate = float(rate_val) if rate_val and float(rate_val) > 0 else 1.0

        if sale_price_usd > 0 and sale_price == 0:
            sale_price = round(sale_price_usd * rate)
        elif sale_price > 0 and sale_price_usd == 0:
            sale_price_usd = round(sale_price / rate, 2)

        if purchase_price_usd > 0 and purchase_price == 0:
            purchase_price = round(purchase_price_usd * rate, 2)
        elif purchase_price > 0 and purchase_price_usd == 0:
            purchase_price_usd = round(purchase_price / rate, 2)

        cat_id = val_data.get("category_id")
        try:
            cat_id = int(cat_id) if cat_id else None
        except (ValueError, TypeError):
            cat_id = None

        cat_name = (val_data.get("category") or "").strip()
        if cat_id and not cat_name:
            cat_name = q1(conn, "SELECT name FROM categories WHERE id = ?", (cat_id,)) or ""
        elif cat_name and not cat_id:
            cat_id = q1(conn, "SELECT id FROM categories WHERE name = ?", (cat_name,))

        if u["role"] != "admin" and u["branch_id"]:
            old_default_min = q1(conn, "SELECT min_qty FROM products WHERE id = ?", (pid,)) or 0
            _save_branch_limits(conn, pid, {str(u["branch_id"]): min_qty})
            min_qty = old_default_min

        conn.execute(
            "UPDATE products SET name=?, generic_name=?, strength=?, form=?, manufacturer=?, "
            "category=?, category_id=?, barcode=?, purchase_price=?, sale_price=?, purchase_price_usd=?, sale_price_usd=?, min_qty=?, unit=?, "
            "strip_qty=?, carton_qty=?, supplier_id=?, is_prescription=? WHERE id=?",
            (val_data.get("name"), val_data.get("generic_name"), val_data.get("strength"), val_data.get("form"),
             val_data.get("manufacturer"), cat_name, cat_id, (val_data.get("barcode") or None),
             purchase_price, sale_price, purchase_price_usd, sale_price_usd, min_qty, val_data.get("unit") or "piece",
             strip_qty, carton_qty, val_data.get("supplier_id"), int(val_data.get("is_prescription", 0)), pid),
        )
        if u["role"] == "admin" and val_data.get("branch_limits") is not None:
            _save_branch_limits(conn, pid, val_data.get("branch_limits"))
        audit(conn, u["id"], u["branch_id"], "update_product", "products", pid, val_data.get("name"))
        conn.commit()
        if val_data.get("barcode"):
            os.makedirs("data/barcodes", exist_ok=True)
            try:
                from barcode import get as bc_get
                bc_get('code128', val_data["barcode"]).save(f"data/barcodes/{pid}")
            except Exception as e:
                print(f"Barcode generation warning: {e}")
        return jsonify({"ok": True})
    except sqlite3.IntegrityError:
        return jsonify({"error": "barcode already exists"}), 409
    finally:
        conn.close()


@bp.route("/api/products/<int:pid>", methods=["DELETE"])
def delete_product(pid):
    u = require_role("admin")
    conn = get_db()
    try:
        conn.execute("UPDATE products SET active = 0 WHERE id = ?", (pid,))
        audit(conn, u["id"], u["branch_id"], "delete_product", "products", pid)
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


@bp.route("/api/products/template", methods=["GET"])
def products_template():
    """Download an Excel or CSV template for product imports with sample rows."""
    require_role("admin", "pharmacist")
    fmt = (request.args.get("format") or "xlsx").lower()

    headers = [
        "اسم الدواء *", "المادة الفعالة", "التركيز", "الشكل الدوائي",
        "التصنيف", "الشركة المصنعة", "الباركود", "سعر الشراء", "سعر البيع",
        "الكمية الحالية", "تاريخ الصلاحية", "رقم التشغيلة", "الحد الأدنى",
        "الوحدة", "حبات بالشريط", "أشرطة بالكرتونة"
    ]
    sample_rows = [
        ["بنادول إكسترا", "باراسيتامول + كافيين", "500 ملغ", "أقراص", "مسكنات", "GSK", "628100100123", 12.50, 16.00, 50, "2027-12-31", "BN101", 10, "علبة", 24, 1],
        ["أوجمنتين 1 جم", "أموكسيسيلين + كلافولانات", "1000 ملغ", "أقراص", "مضادات حيوية", "GSK", "628100100124", 38.00, 48.50, 30, "2026-11-30", "BN102", 5, "علبة", 14, 1],
        ["أوميبرازول 20", "أوميبرازول", "20 ملغ", "كبسولات", "أدوية المعدة", "AstraZeneca", "628100100125", 22.00, 29.00, 40, "2027-06-30", "BN103", 8, "علبة", 14, 1],
    ]

    if fmt == "csv":
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(headers)
        for r in sample_rows:
            writer.writerow(r)
        csv_bytes = io.BytesIO(out.getvalue().encode("utf-8-sig"))
        return send_file(csv_bytes, as_attachment=True, download_name="medicine_import_template.csv", mimetype="text/csv; charset=utf-8")

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "نموذج استيراد الأدوية"
    ws.views.sheetView[0].rightToLeft = True

    ws.append(headers)
    header_fill = PatternFill(start_color="0F766E", end_color="0F766E", fill_type="solid")
    header_font = Font(name="Segoe UI", size=11, bold=True, color="FFFFFF")
    center_align = Alignment(horizontal="center", vertical="center", wrap_text=True)
    right_align = Alignment(horizontal="right", vertical="center")

    for col_num in range(1, len(headers) + 1):
        c = ws.cell(row=1, column=col_num)
        c.fill = header_fill
        c.font = header_font
        c.alignment = center_align

    for r in sample_rows:
        ws.append(r)

    for row_idx in range(2, ws.max_row + 1):
        for col_idx in range(1, len(headers) + 1):
            cell = ws.cell(row=row_idx, column=col_idx)
            if col_idx in (7, 11, 12, 14):
                cell.alignment = center_align
            elif col_idx in (8, 9):
                cell.number_format = "#,##0.00"
                cell.alignment = right_align
            elif col_idx in (10, 13, 15, 16):
                cell.number_format = "#,##0"
                cell.alignment = right_align
            else:
                cell.alignment = right_align

    for col in ws.columns:
        max_len = max(len(str(cell.value or "")) for cell in col)
        col_letter = col[0].column_letter
        ws.column_dimensions[col_letter].width = max(max_len + 4, 14)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name="medicine_import_template.xlsx", mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@bp.route("/api/products/export", methods=["GET"])
def export_products():
    """Export catalog of products to Excel or CSV."""
    u = require_role("admin", "pharmacist")
    b = branch_scope(u)
    req_b = request.args.get("branch_id", type=int)
    effective_b = b if b is not None else req_b
    search = (request.args.get("search") or "").strip()
    category = request.args.get("category")
    fmt = (request.args.get("format") or "xlsx").lower()

    conn = get_db()
    try:
        if effective_b is None:
            sql = """SELECT p.*,
                     COALESCE(c.name, p.category, '') AS category_name,
                     COALESCE((SELECT SUM(qty) FROM batches WHERE product_id=p.id AND (expiry_date IS NULL OR expiry_date >= date('now'))),0) AS current_stock
                     FROM products p LEFT JOIN categories c ON c.id = p.category_id
                     WHERE p.active = 1"""
            params = []
        else:
            sql = """SELECT p.*,
                     COALESCE(c.name, p.category, '') AS category_name,
                     COALESCE((SELECT SUM(qty) FROM batches WHERE product_id=p.id AND branch_id=? AND (expiry_date IS NULL OR expiry_date >= date('now'))),0) AS current_stock
                     FROM products p LEFT JOIN categories c ON c.id = p.category_id
                     WHERE p.active = 1"""
            params = [effective_b]
        if search:
            like = f"%{search}%"
            sql += " AND (p.name LIKE ? OR p.barcode LIKE ? OR p.generic_name LIKE ?)"
            params += [like, like, like]
        if category:
            sql += " AND (p.category = ? OR c.name = ?)"
            params += [category, category]
        sql += " ORDER BY p.name ASC"
        prods = [dict(r) for r in rows(conn, sql, params)]
    finally:
        conn.close()

    headers = [
        "رقم الدواء", "اسم الدواء", "المادة الفعالة", "التركيز", "الشكل الدوائي",
        "التصنيف", "الشركة المصنعة", "الباركود", "سعر الشراء", "سعر البيع",
        "سعر الشراء ($)", "سعر البيع ($)",
        "الرصيد المتوفر", "الحد الأدنى", "الوحدة", "حبات بالشريط", "أشرطة بالكرتونة", "يتطلب وصفة"
    ]

    if fmt == "csv":
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(headers)
        for p in prods:
            writer.writerow([
                p.get("id"), p.get("name"), p.get("generic_name") or "", p.get("strength") or "", p.get("form") or "",
                p.get("category_name") or p.get("category") or "", p.get("manufacturer") or "", p.get("barcode") or "",
                f"{float(p.get('purchase_price') or 0):.2f}", f"{float(p.get('sale_price') or 0):.2f}",
                f"{float(p.get('purchase_price_usd') or 0):.2f}", f"{float(p.get('sale_price_usd') or 0):.2f}",
                p.get("current_stock") or 0, p.get("min_qty") or 0, p.get("unit") or "قطعة",
                p.get("strip_qty") or 1, p.get("carton_qty") or 1,
                "نعم" if p.get("is_prescription") else "لا"
            ])
        csv_bytes = io.BytesIO(out.getvalue().encode("utf-8-sig"))
        filename = f"products_export_{today()}.csv"
        return send_file(csv_bytes, as_attachment=True, download_name=filename, mimetype="text/csv; charset=utf-8")

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "قائمة الأدوية"
    ws.views.sheetView[0].rightToLeft = True

    ws.append(headers)
    header_fill = PatternFill(start_color="0F766E", end_color="0F766E", fill_type="solid")
    header_font = Font(name="Segoe UI", size=11, bold=True, color="FFFFFF")
    center_align = Alignment(horizontal="center", vertical="center")
    right_align = Alignment(horizontal="right", vertical="center")

    for col_num in range(1, len(headers) + 1):
        c = ws.cell(row=1, column=col_num)
        c.fill = header_fill
        c.font = header_font
        c.alignment = center_align

    for p in prods:
        ws.append([
            p.get("id"), p.get("name"), p.get("generic_name") or "", p.get("strength") or "", p.get("form") or "",
            p.get("category_name") or p.get("category") or "", p.get("manufacturer") or "", str(p.get("barcode") or ""),
            float(p.get("purchase_price") or 0), float(p.get("sale_price") or 0),
            float(p.get("purchase_price_usd") or 0), float(p.get("sale_price_usd") or 0),
            float(p.get("current_stock") or 0), float(p.get("min_qty") or 0), p.get("unit") or "قطعة",
            float(p.get("strip_qty") or 1), float(p.get("carton_qty") or 1),
            "نعم" if p.get("is_prescription") else "لا"
        ])

    for row_idx in range(2, ws.max_row + 1):
        for col_idx in range(1, len(headers) + 1):
            cell = ws.cell(row=row_idx, column=col_idx)
            if col_idx in (1, 8, 15, 18):
                cell.alignment = center_align
            elif col_idx in (9, 10, 11, 12):
                cell.number_format = "#,##0.00"
                cell.alignment = right_align
            elif col_idx in (13, 14, 16, 17):
                cell.number_format = "#,##0"
                cell.alignment = right_align
            else:
                cell.alignment = right_align

    for col in ws.columns:
        max_len = max(len(str(cell.value or "")) for cell in col)
        col_letter = col[0].column_letter
        ws.column_dimensions[col_letter].width = max(max_len + 3, 12)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    filename = f"products_export_{today()}.xlsx"
    return send_file(buf, as_attachment=True, download_name=filename, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@bp.route("/api/products/import", methods=["POST"])
def import_products():
    """Import products from Excel (.xlsx/.xlsm) or CSV with intelligent upsert and batch creation."""
    u = require_role("admin", "pharmacist")
    if "file" not in request.files:
        return jsonify({"error": "no file"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "empty file"}), 400
    raw = f.read()

    data = []
    if f.filename.lower().endswith((".xlsx", ".xlsm")):
        try:
            wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
            ws = wb.active
            data = list(ws.iter_rows(values_only=True))
        except Exception as e:
            return jsonify({"error": f"فشل قراءة ملف Excel: {str(e)}"}), 400
    else:
        decoded = None
        for enc in ("utf-8-sig", "utf-8", "cp1256", "latin1"):
            try:
                decoded = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        if decoded is None:
            return jsonify({"error": "صيغة الملف غير مدعومة، يرجى استخدام .xlsx أو .csv بترميز UTF-8"}), 400
        try:
            data = list(csv.reader(io.StringIO(decoded)))
        except Exception as e:
            return jsonify({"error": f"فشل قراءة ملف CSV: {str(e)}"}), 400

    if not data or len(data) < 2:
        return jsonify({"error": "الملف فارغ أو لا يحتوي على صفوف بيانات"}), 400

    clean_header = [re.sub(r'[*()\[\]]', '', str(c or "")).strip().lower() for c in data[0]]
    idx = {}
    for canon, aliases in HEADER_ALIASES.items():
        for a in aliases:
            a_norm = a.strip().lower()
            matched = False
            for i, h in enumerate(clean_header):
                if h == a_norm:
                    idx[canon] = i
                    matched = True
                    break
            if not matched:
                for i, h in enumerate(clean_header):
                    if a_norm in h and len(a_norm) >= 3:
                        idx[canon] = i
                        matched = True
                        break
            if matched:
                break

    if "name" not in idx:
        return jsonify({"error": "الملف غير صالح: يجب أن يحتوي على عمود باسم (اسم الدواء) أو (name)"}), 400

    conn = get_db()
    imported = updated = skipped = 0
    errors = []
    branch_id = (u.get("branch_id") if hasattr(u, "get") else u["branch_id"]) or 1

    rate_val = q1(conn, "SELECT value FROM settings WHERE key = 'usd_exchange_rate'")
    rate = float(rate_val) if rate_val and float(rate_val) > 0 else 1.0

    try:
        for row_num, r in enumerate(data[1:], start=2):
            if not r or all(c is None or str(c).strip() == "" for c in r):
                continue

            def col(name, default=None):
                i = idx.get(name)
                return r[i] if i is not None and i < len(r) and r[i] not in (None, "") else default

            name = str(col("name") or "").strip()
            if not name:
                skipped += 1
                errors.append(f"صف {row_num}: اسم الدواء فارغ")
                continue

            barcode = _clean_barcode(col("barcode"))
            cat_name = col("category")
            cat_id = None
            if cat_name:
                cat_id, cat_name = _resolve_category(conn, cat_name)

            try:
                purchase_price = float(col("purchase_price", 0) or 0)
                sale_price = float(col("sale_price", 0) or 0)
                purchase_price_usd = float(col("purchase_price_usd", 0) or 0)
                sale_price_usd = float(col("sale_price_usd", 0) or 0)
                min_qty = float(col("min_qty", 0) or 0)
                unit = str(col("unit", "piece") or "piece").strip()
                strip_qty = float(col("strip_qty", 1) or 1)
                carton_qty = float(col("carton_qty", 1) or 1)
                supplier_id = col("supplier_id")
                qty = float(col("qty", 0) or 0)

                if sale_price_usd > 0 and sale_price == 0:
                    sale_price = round(sale_price_usd * rate)
                elif sale_price > 0 and sale_price_usd == 0:
                    sale_price_usd = round(sale_price / rate, 2)

                if purchase_price_usd > 0 and purchase_price == 0:
                    purchase_price = round(purchase_price_usd * rate, 2)
                elif purchase_price > 0 and purchase_price_usd == 0:
                    purchase_price_usd = round(purchase_price / rate, 2)
            except (ValueError, TypeError):
                skipped += 1
                errors.append(f"صف {row_num} ({name}): خطأ في القيم الرقمية")
                continue

            # Check if product exists by barcode or exact name
            existing = None
            if barcode:
                existing = row(conn, "SELECT id, name, barcode FROM products WHERE barcode = ?", (barcode,))
            if not existing:
                existing = row(conn, "SELECT id, name, barcode FROM products WHERE LOWER(name) = LOWER(?)", (name,))

            try:
                if existing:
                    pid = existing["id"]
                    conn.execute("""
                        UPDATE products SET
                            purchase_price = CASE WHEN ? > 0 THEN ? ELSE purchase_price END,
                            sale_price = CASE WHEN ? > 0 THEN ? ELSE sale_price END,
                            purchase_price_usd = CASE WHEN ? > 0 THEN ? ELSE purchase_price_usd END,
                            sale_price_usd = CASE WHEN ? > 0 THEN ? ELSE sale_price_usd END,
                            generic_name = COALESCE(?, generic_name),
                            strength = COALESCE(?, strength),
                            form = COALESCE(?, form),
                            manufacturer = COALESCE(?, manufacturer),
                            category_id = COALESCE(?, category_id),
                            category = COALESCE(?, category),
                            min_qty = CASE WHEN ? > 0 THEN ? ELSE min_qty END,
                            unit = COALESCE(?, unit)
                        WHERE id = ?
                    """, (purchase_price, purchase_price, sale_price, sale_price,
                          purchase_price_usd, purchase_price_usd, sale_price_usd, sale_price_usd,
                          col("generic_name"), col("strength"), col("form"), col("manufacturer"),
                          cat_id, cat_name, min_qty, min_qty, unit, pid))
                    updated += 1
                else:
                    if not barcode:
                        while True:
                            candidate = str(random.randint(100000000000, 999999999999))
                            if not q1(conn, "SELECT id FROM products WHERE barcode = ?", (candidate,)):
                                barcode = candidate
                                break
                    cur = conn.execute("""
                        INSERT INTO products (
                            name, generic_name, strength, form, manufacturer, category, category_id,
                            barcode, purchase_price, sale_price, purchase_price_usd, sale_price_usd,
                            min_qty, unit, strip_qty, carton_qty, supplier_id, is_prescription, active
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,1)
                    """, (name, col("generic_name"), col("strength"), col("form"), col("manufacturer"),
                          cat_name, cat_id, barcode, purchase_price, sale_price,
                          purchase_price_usd, sale_price_usd, min_qty, unit,
                          strip_qty, carton_qty, supplier_id))
                    pid = cur.lastrowid
                    imported += 1

                # If initial quantity is given, create an inventory batch
                if qty > 0:
                    batch_no = str(col("batch_no") or "").strip() or f"IMP-{pid}-{int(time.time()) % 100000}"
                    expiry_date = _clean_date(col("expiry_date"))
                    cost = purchase_price if purchase_price > 0 else 0
                    conn.execute("""
                        INSERT INTO batches (branch_id, product_id, batch_no, expiry_date, qty, cost)
                        VALUES (?,?,?,?,?,?)
                    """, (branch_id, pid, batch_no, expiry_date, qty, cost))

                if barcode:
                    os.makedirs("data/barcodes", exist_ok=True)
                    try:
                        from barcode import get as bc_get
                        bc_get('code128', barcode).save(f"data/barcodes/{pid}")
                    except Exception:
                        pass

            except sqlite3.IntegrityError as e:
                skipped += 1
                errors.append(f"صف {row_num} ({name}): تعارض في البيانات ({e})")
            except Exception as e:
                skipped += 1
                errors.append(f"صف {row_num} ({name}): {str(e)}")

        audit(conn, u["id"], u["branch_id"], "import_products", "products", None,
              f"imported={imported} updated={updated} skipped={skipped}")
        conn.commit()
        return jsonify({
            "ok": True,
            "imported": imported,
            "updated": updated,
            "skipped": skipped,
            "errors": errors[:10]
        })
    finally:
        conn.close()


@bp.route("/api/products/<int:pid>/best-batch", methods=["GET"])
def best_batch(pid):
    u = require_auth()
    b = branch_scope(u)
    conn = get_db()
    try:
        if b is None:
            r = row(conn, """SELECT batch_no, expiry_date FROM batches
                             WHERE product_id = ? AND qty > 0 AND (expiry_date IS NULL OR expiry_date >= date('now'))
                             ORDER BY expiry_date IS NULL, expiry_date ASC, id ASC LIMIT 1""", (pid,))
        else:
            r = row(conn, """SELECT batch_no, expiry_date FROM batches
                             WHERE product_id = ? AND branch_id = ? AND qty > 0 AND (expiry_date IS NULL OR expiry_date >= date('now'))
                             ORDER BY expiry_date IS NULL, expiry_date ASC, id ASC LIMIT 1""", (pid, b))
        if not r:
            return jsonify({"batch_no": None, "expiry_date": None})
        return jsonify(dict(r))
    finally:
        conn.close()


@bp.route("/api/batches", methods=["GET"])
def list_batches():
    """List all batches with optional product filter."""
    u = require_auth()
    b = branch_scope(u)
    pid = request.args.get("product_id", type=int)
    conn = get_db()
    try:
        sql = """SELECT bt.*, p.name AS product_name FROM batches bt
                 JOIN products p ON p.id = bt.product_id WHERE 1=1"""
        params = []
        if b is not None:
            sql += " AND bt.branch_id = ?"
            params.append(b)
        if pid:
            sql += " AND bt.product_id = ?"
            params.append(pid)
        sql += " ORDER BY bt.expiry_date IS NULL, bt.expiry_date"
        return jsonify({"batches": [dict(r) for r in rows(conn, sql, params)]})
    finally:
        conn.close()


@bp.route("/api/batches", methods=["POST"])
def add_batch():
    u = require_role("admin")
    d = request.get_json(force=True) or {}
    val_data, err = validate_payload(BatchRequest, d)
    if err:
        return jsonify({"error": err}), 400
    branch_id = resolve_branch(u, val_data)
    conn = get_db()
    try:
        cur = conn.execute(
            "INSERT INTO batches (branch_id, product_id, batch_no, expiry_date, qty, cost) VALUES (?,?,?,?,?,?)",
            (branch_id, val_data["product_id"], val_data.get("batch_no"), val_data.get("expiry_date"),
             float(val_data.get("qty") or 0), float(val_data.get("cost") or 0)),
        )
        audit(conn, u["id"], branch_id, "add_batch", "batches", cur.lastrowid,
              f"product={val_data['product_id']} qty={val_data.get('qty')}")
        conn.commit()
        return jsonify({"ok": True, "id": cur.lastrowid})
    finally:
        conn.close()


@bp.route("/api/stock/low", methods=["GET"])
def low_stock():
    u = require_auth()
    b = branch_scope(u)
    req_b = request.args.get("branch_id", type=int)
    effective_b = b if b is not None else req_b
    conn = get_db()
    try:
        if effective_b is None:
            sql = """SELECT * FROM (
                         SELECT p.id, p.name, p.barcode, p.unit,
                                br.id AS branch_id, br.name AS branch_name,
                                COALESCE(bpl.min_qty, p.min_qty) AS min_qty,
                                COALESCE((SELECT SUM(bt.qty) FROM batches bt
                                          WHERE bt.product_id=p.id AND bt.branch_id=br.id
                                            AND (bt.expiry_date IS NULL OR bt.expiry_date >= date('now'))), 0) AS qty
                         FROM products p
                         JOIN branches br ON 1=1
                         LEFT JOIN branch_product_limits bpl ON bpl.product_id=p.id AND bpl.branch_id=br.id
                         WHERE p.active=1
                     ) AS _low_q
                     WHERE min_qty > 0 AND qty <= min_qty
                     ORDER BY qty ASC"""
            params = ()
        else:
            sql = """SELECT * FROM (
                         SELECT p.id, p.name, p.barcode, p.unit,
                                br.id AS branch_id, br.name AS branch_name,
                                COALESCE(bpl.min_qty, p.min_qty) AS min_qty,
                                COALESCE((SELECT SUM(bt.qty) FROM batches bt
                                          WHERE bt.product_id=p.id AND bt.branch_id=br.id
                                            AND (bt.expiry_date IS NULL OR bt.expiry_date >= date('now'))), 0) AS qty
                         FROM products p
                         JOIN branches br ON br.id = ?
                         LEFT JOIN branch_product_limits bpl ON bpl.product_id=p.id AND bpl.branch_id=br.id
                         WHERE p.active=1
                     ) AS _low_q
                     WHERE min_qty > 0 AND qty <= min_qty
                     ORDER BY qty ASC"""
            params = (effective_b,)
        return jsonify({"items": [dict(r) for r in rows(conn, sql, params)]})
    finally:
        conn.close()


@bp.route("/api/expiry", methods=["GET"])
def expiry_alerts():
    u = require_auth()
    b = branch_scope(u)
    req_b = request.args.get("branch_id", type=int)
    effective_b = b if b is not None else req_b
    days = request.args.get("days", 30, type=int)
    conn = get_db()
    try:
        sql = """SELECT bt.*, p.name AS product_name, br.name AS branch_name FROM batches bt
                 JOIN products p ON p.id = bt.product_id
                 LEFT JOIN branches br ON br.id = bt.branch_id
                 WHERE bt.qty > 0 AND bt.expiry_date IS NOT NULL
                   AND bt.expiry_date >= date('now') AND bt.expiry_date <= date('now', ?)"""
        params = [f"+{days} days"]
        if effective_b is not None:
            sql += " AND bt.branch_id = ?"
            params.append(effective_b)
        sql += " ORDER BY bt.expiry_date"
        return jsonify({"items": [dict(r) for r in rows(conn, sql, params)]})
    finally:
        conn.close()


@bp.route("/api/expiry/expired", methods=["GET"])
def expired_batches():
    u = require_auth()
    b = branch_scope(u)
    req_b = request.args.get("branch_id", type=int)
    effective_b = b if b is not None else req_b
    conn = get_db()
    try:
        sql = """SELECT bt.*, p.name AS product_name, br.name AS branch_name FROM batches bt
                 JOIN products p ON p.id = bt.product_id
                 LEFT JOIN branches br ON br.id = bt.branch_id
                 WHERE bt.qty > 0 AND bt.expiry_date IS NOT NULL AND bt.expiry_date < date('now')"""
        params = []
        if effective_b is not None:
            sql += " AND bt.branch_id = ?"
            params.append(effective_b)
        sql += " ORDER BY bt.expiry_date"
        return jsonify({"items": [dict(r) for r in rows(conn, sql, params)]})
    finally:
        conn.close()


@bp.route("/api/categories", methods=["GET"])
def list_categories():
    require_auth()
    conn = get_db()
    try:
        return jsonify({"categories": [dict(r) for r in rows(conn, "SELECT * FROM categories ORDER BY name")]})
    finally:
        conn.close()


@bp.route("/api/categories/<int:cid>", methods=["GET"])
def get_category(cid):
    require_auth()
    conn = get_db()
    try:
        c = row(conn, "SELECT * FROM categories WHERE id = ?", (cid,))
        if not c:
            return jsonify({"error": "category not found"}), 404
        return jsonify(dict(c))
    finally:
        conn.close()


@bp.route("/api/categories/<int:cid>", methods=["DELETE"])
def delete_category(cid):
    u = require_role("admin")
    conn = get_db()
    try:
        # Remove category_id from products (set to NULL but keep category name)
        conn.execute("UPDATE products SET category_id = NULL WHERE category_id = ?", (cid,))
        conn.execute("DELETE FROM categories WHERE id = ?", (cid,))
        audit(conn, u["id"], u["branch_id"], "delete_category", "categories", cid)
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


@bp.route("/api/categories/<int:cid>", methods=["PUT"])
def update_category(cid):
    u = require_role("admin", "pharmacist")
    d = request.get_json(force=True)
    if not (d.get("name") or "").strip():
        return jsonify({"error": "name required"}), 400
    conn = get_db()
    try:
        conn.execute("UPDATE categories SET name = ? WHERE id = ?", (d["name"].strip(), cid))
        audit(conn, u["id"], u["branch_id"], "update_category", "categories", cid, d["name"])
        conn.commit()
        return jsonify({"ok": True})
    except sqlite3.IntegrityError:
        return jsonify({"error": "category name already exists"}), 409
    finally:
        conn.close()


@bp.route("/api/categories", methods=["POST"])
def create_category():
    u = require_role("admin", "pharmacist")
    d = request.get_json(force=True)
    if not (d.get("name") or "").strip():
        return jsonify({"error": "name required"}), 400
    conn = get_db()
    try:
        cur = conn.execute("INSERT INTO categories (name) VALUES (?)", (d["name"].strip(),))
        audit(conn, u["id"], u["branch_id"], "create_category", "categories", cur.lastrowid, d["name"])
        conn.commit()
        return jsonify({"ok": True, "id": cur.lastrowid})
    except sqlite3.IntegrityError:
        return jsonify({"error": "category name already exists"}), 409
    finally:
        conn.close()