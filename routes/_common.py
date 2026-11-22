"""Shared helpers for all blueprints."""
import os
import re
import sqlite3
import logging
from datetime import datetime
from flask import session, abort, g
from bcrypt import hashpw, gensalt
from config import (BASE_DIR, STATIC_DIR, SECRET_KEY, DB_PATH, SCHEMA_PATH,
                    SCHEMA_POSTGRES_PATH, BACKUP_DIR, _safe_path,
                    DATABASE_URL, IS_POSTGRES)

#Tables that do NOT have an auto-incrementing 'id' column
_NO_ID_TABLES = {"settings", "sales_seq", "purchases_seq"}


class _PgRow(dict):
    """Row object compatible with sqlite3.Row (supports both key and index access)."""
    def __init__(self, columns, values):
        super().__init__(zip(columns, values))
        self._values = tuple(values)

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        return super().__getitem__(key)


def _sqlite_row_factory(cursor, row_values):
    """Row factory for sqlite3 to provide full dict methods (.get, keys, items) while maintaining index and key access."""
    cols = [col[0] for col in cursor.description]
    return _PgRow(cols, row_values)


def _translate_sql_for_pg(sql: str, params=()):
    """Translate SQLite SQL dialect to PostgreSQL dialect automatically."""
    s = sql.strip()
    new_params = list(params) if params else []

    # 1. Handle PRAGMA table_info(table)
    m_pragma = re.match(r"PRAGMA\s+table_info\(\s*(\w+)\s*\)", s, re.I)
    if m_pragma:
        tbl = m_pragma.group(1)
        return (
            "SELECT ordinal_position AS cid, column_name AS name "
            "FROM information_schema.columns WHERE table_name = %s",
            [tbl]
        )

    # 2. Handle INSERT OR IGNORE INTO categories
    if re.search(r"INSERT\s+OR\s+IGNORE\s+INTO", s, re.I):
        s = re.sub(r"INSERT\s+OR\s+IGNORE\s+INTO", "INSERT INTO", s, flags=re.I)
        if "ON CONFLICT" not in s.upper():
            s = s.rstrip(";") + " ON CONFLICT DO NOTHING"

    # 3. Date & Time functions
    # date('now', '-6 days') / date('now', '+30 days')
    s = re.sub(
        r"date\(\s*'now'\s*,\s*'([+-]?\d+\s+\w+)'\s*\)",
        r"to_char(CURRENT_DATE + CAST('\1' AS INTERVAL), 'YYYY-MM-DD')",
        s,
        flags=re.I
    )
    # date('now', ?)
    s = re.sub(
        r"date\(\s*'now'\s*,\s*\?\s*\)",
        r"to_char(CURRENT_DATE + CAST(? AS INTERVAL), 'YYYY-MM-DD')",
        s,
        flags=re.I
    )
    # datetime('now')
    s = re.sub(
        r"datetime\(\s*'now'\s*\)",
        r"to_char(CURRENT_TIMESTAMP, 'YYYY-MM-DD HH24:MI:SS')",
        s,
        flags=re.I
    )
    # date('now')
    s = re.sub(
        r"date\(\s*'now'\s*\)",
        r"to_char(CURRENT_DATE, 'YYYY-MM-DD')",
        s,
        flags=re.I
    )
    # strftime('%Y-%m', col) -> substr(CAST(col AS TEXT), 1, 7)
    s = re.sub(
        r"strftime\(\s*'%Y-%m'\s*,\s*([^)]+)\)",
        r"substr(CAST(\1 AS TEXT), 1, 7)",
        s,
        flags=re.I
    )
    # date(col) -> substr(CAST(col AS TEXT), 1, 10)
    s = re.sub(
        r"\bdate\(\s*([^)]+)\s*\)",
        r"substr(CAST(\1 AS TEXT), 1, 10)",
        s,
        flags=re.I
    )

    # 4. Scalar MAX(0, expr) -> GREATEST(0, expr)
    s = re.sub(r"\bMAX\(\s*0\s*,", "GREATEST(0,", s, flags=re.I)

    # 5. Subqueries without alias in FROM (...)
    s = re.sub(r"FROM\s*\(\s*(SELECT\b(?:(?!\bAS\s+\w+\s*$)[\s\S])*)\)\s*$", r"FROM (\1) AS _subq", s, flags=re.I)

    # 6. Fix HAVING alias in low_stock queries for strict PostgreSQL GROUP BY / HAVING
    if "HAVING qty <= p.min_qty" in s:
        m_coal = re.search(r"(COALESCE\(\(SELECT SUM\(qty\) FROM batches WHERE [^)]+\)\s*,\s*0\))\s+AS\s+qty", s, re.I)
        if m_coal:
            s = s.replace("HAVING qty <= p.min_qty", f"HAVING {m_coal.group(1)} <= p.min_qty")

    # 7. Fix strict GROUP BY in PostgreSQL where p.name or lr.id is selected
    s = re.sub(r"GROUP BY\s+p\.id\b(?!\s*,\s*p\.name)", "GROUP BY p.id, p.name", s, flags=re.I)
    s = re.sub(r"GROUP BY\s+si\.product_id\b(?!\s*,\s*p\.name)", "GROUP BY si.product_id, p.name", s, flags=re.I)
    s = re.sub(r"GROUP BY\s+lr\.id\b(?!\s*,\s*p\.name)", "GROUP BY lr.id, p.name, lr.points_cost", s, flags=re.I)

    # 7.5. PostgreSQL requires numeric argument for ROUND with precision: ROUND(double, int) -> ROUND(CAST(double AS NUMERIC), int)
    s = re.sub(r"\bROUND\(\s*(?!CAST\b)([^,]+?)\s*,\s*(\d+)\s*\)", r"ROUND(CAST(\1 AS NUMERIC), \2)", s, flags=re.I)

    # 8. Escape literal % before replacing ? with %s
    s = s.replace("%", "%%")
    s = s.replace("?", "%s")

    # 9. Auto-append RETURNING id for INSERT statements to populate cur.lastrowid
    m_ins = re.match(r"^\s*INSERT\s+INTO\s+(\w+)", s, re.I)
    has_returning = False
    if m_ins:
        tbl_name = m_ins.group(1).lower()
        if tbl_name not in _NO_ID_TABLES and "RETURNING " not in s.upper() and "ON CONFLICT DO NOTHING" not in s.upper():
            s = s.rstrip().rstrip(";") + " RETURNING id"
            has_returning = True

    return s, new_params, has_returning


class _PgCursorWrapper:
    """Wraps psycopg2 cursor to behave like sqlite3.Cursor."""
    def __init__(self, raw_cur, lastrowid=None):
        self._cur = raw_cur
        self.lastrowid = lastrowid

    @property
    def rowcount(self):
        return self._cur.rowcount

    def fetchone(self):
        r = self._cur.fetchone()
        if r is None:
            return None
        cols = [d[0] for d in self._cur.description]
        return _PgRow(cols, r)

    def fetchall(self):
        rs = self._cur.fetchall()
        if not rs or not self._cur.description:
            return []
        cols = [d[0] for d in self._cur.description]
        return [_PgRow(cols, r) for r in rs]


class _PgConnectionWrapper:
    """Wraps psycopg2 connection to behave like sqlite3.Connection."""
    def __init__(self, raw_conn):
        self._conn = raw_conn

    def execute(self, sql: str, params=()):
        pg_sql, pg_params, added_returning = _translate_sql_for_pg(sql, params)[:3] if len(_translate_sql_for_pg(sql, params)) == 3 else (*_translate_sql_for_pg(sql, params), False)
        cur = self._conn.cursor()
        try:
            cur.execute(pg_sql, tuple(pg_params))
        except Exception as e:
            self._conn.rollback()
            import psycopg2
            if isinstance(e, psycopg2.IntegrityError):
                raise sqlite3.IntegrityError(str(e)) from e
            raise
        last_id = None
        if added_returning and cur.description:
            r = cur.fetchone()
            if r:
                last_id = r[0]
        return _PgCursorWrapper(cur, lastrowid=last_id)

    def executescript(self, script: str):
        cur = self._conn.cursor()
        cur.execute(script)
        self._conn.commit()

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        try:
            self._conn.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Hybrid Online (Supabase) / Offline (Local SQLite) Failover & Sync State
# ---------------------------------------------------------------------------
import json as _json
import time as _time

_SYNC_STATE_FILE = os.path.join(os.path.dirname(DB_PATH), ".sync_state.json")
_SYNC_STATE_CACHE = None
_LAST_PROBE = {"ts": 0.0, "ok": False}
_MUTATING_SQL_RE = re.compile(r"^\s*(?:INSERT|UPDATE|DELETE|REPLACE)\b", re.I)


def get_sync_state() -> dict:
    global _SYNC_STATE_CACHE
    if _SYNC_STATE_CACHE is not None:
        return dict(_SYNC_STATE_CACHE)
    default_state = {"offline_mode": False, "dirty": False, "last_sync": None}
    try:
        if os.path.exists(_SYNC_STATE_FILE):
            with open(_SYNC_STATE_FILE, "r", encoding="utf-8") as fh:
                loaded = _json.load(fh)
                if isinstance(loaded, dict):
                    default_state.update(loaded)
    except Exception:
        pass
    _SYNC_STATE_CACHE = default_state
    return dict(_SYNC_STATE_CACHE)


def set_sync_state(*, offline_mode=None, dirty=None, last_sync=None) -> dict:
    global _SYNC_STATE_CACHE
    st = get_sync_state()
    if offline_mode is not None:
        st["offline_mode"] = bool(offline_mode)
    if dirty is not None:
        st["dirty"] = bool(dirty)
    if last_sync is not None:
        st["last_sync"] = last_sync
    _SYNC_STATE_CACHE = st
    try:
        os.makedirs(os.path.dirname(_SYNC_STATE_FILE), exist_ok=True)
        with open(_SYNC_STATE_FILE, "w", encoding="utf-8") as fh:
            _json.dump(st, fh, ensure_ascii=False)
    except Exception:
        pass
    return dict(st)


def probe_supabase(timeout: int = 3, force: bool = False) -> bool:
    """Quickly test if the remote Supabase PostgreSQL server is reachable."""
    if not IS_POSTGRES:
        return False
    now_ts = _time.time()
    if not force and (now_ts - _LAST_PROBE["ts"]) < 5.0:
        return _LAST_PROBE["ok"]
    try:
        import psycopg2
        db_url = DATABASE_URL
        if db_url.startswith("postgres://"):
            db_url = "postgresql://" + db_url[len("postgres://"):]
        c = psycopg2.connect(db_url, connect_timeout=timeout)
        c.close()
        _LAST_PROBE["ts"] = now_ts
        _LAST_PROBE["ok"] = True
        return True
    except Exception:
        _LAST_PROBE["ts"] = now_ts
        _LAST_PROBE["ok"] = False
        return False


class _SqliteOfflineWrapper:
    """Wraps sqlite3.Connection during offline fallback and marks state dirty on writes."""
    def __init__(self, conn: sqlite3.Connection, track_dirty: bool = True):
        self._conn = conn
        self._track_dirty = track_dirty

    def execute(self, sql: str, params=()):
        cur = self._conn.execute(sql, params)
        if self._track_dirty and _MUTATING_SQL_RE.match(sql or ""):
            st = get_sync_state()
            if not st.get("dirty"):
                set_sync_state(dirty=True)
        return cur

    def executemany(self, sql: str, seq_of_params):
        cur = self._conn.executemany(sql, seq_of_params)
        if self._track_dirty and _MUTATING_SQL_RE.match(sql or ""):
            set_sync_state(dirty=True)
        return cur

    def executescript(self, script: str):
        return self._conn.executescript(script)

    def commit(self):
        return self._conn.commit()

    def rollback(self):
        return self._conn.rollback()

    def close(self):
        return self._conn.close()

    def __getattr__(self, name):
        return getattr(self._conn, name)


def _ensure_local_sqlite_schema():
    """Ensure local SQLite database file exists and has all required tables/columns."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = _sqlite_row_factory
    try:
        if os.path.exists(SCHEMA_PATH):
            with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
                conn.executescript(f.read())
        prod_cols = [c[1] for c in conn.execute("PRAGMA table_info(products)").fetchall()]
        if "category" not in prod_cols:
            conn.execute("ALTER TABLE products ADD COLUMN category TEXT")
        if "category_id" not in prod_cols:
            conn.execute("ALTER TABLE products ADD COLUMN category_id INTEGER")
        if "purchase_price_usd" not in prod_cols:
            conn.execute("ALTER TABLE products ADD COLUMN purchase_price_usd REAL DEFAULT 0")
        if "sale_price_usd" not in prod_cols:
            conn.execute("ALTER TABLE products ADD COLUMN sale_price_usd REAL DEFAULT 0")

        sup_cols = [c[1] for c in conn.execute("PRAGMA table_info(suppliers)").fetchall()]
        if "balance_usd" not in sup_cols:
            conn.execute("ALTER TABLE suppliers ADD COLUMN balance_usd REAL DEFAULT 0")

        purch_cols = [c[1] for c in conn.execute("PRAGMA table_info(purchases)").fetchall()]
        if "rate" not in purch_cols:
            conn.execute("ALTER TABLE purchases ADD COLUMN rate REAL DEFAULT 1")
        if "total_usd" not in purch_cols:
            conn.execute("ALTER TABLE purchases ADD COLUMN total_usd REAL DEFAULT 0")

        pi_cols = [c[1] for c in conn.execute("PRAGMA table_info(purchase_items)").fetchall()]
        if "cost_usd" not in pi_cols:
            conn.execute("ALTER TABLE purchase_items ADD COLUMN cost_usd REAL DEFAULT 0")

        sp_cols = [c[1] for c in conn.execute("PRAGMA table_info(supplier_payments)").fetchall()]
        if "rate" not in sp_cols:
            conn.execute("ALTER TABLE supplier_payments ADD COLUMN rate REAL DEFAULT 1")
        if "amount_usd" not in sp_cols:
            conn.execute("ALTER TABLE supplier_payments ADD COLUMN amount_usd REAL DEFAULT 0")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS exchange_rate_history (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                old_rate    REAL,
                new_rate    REAL NOT NULL,
                changed_by  INTEGER,
                created_at  TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (changed_by) REFERENCES users(id)
            )
        """)

        shift_cols = [c[1] for c in conn.execute("PRAGMA table_info(shifts)").fetchall()]
        if "closing_cash" not in shift_cols:
            conn.execute("ALTER TABLE shifts ADD COLUMN closing_cash REAL DEFAULT 0")
            if "actual_cash" in shift_cols:
                conn.execute("UPDATE shifts SET closing_cash = actual_cash WHERE closing_cash = 0 OR closing_cash IS NULL")

        expense_cols = [c[1] for c in conn.execute("PRAGMA table_info(expenses)").fetchall()]
        if "payment_type" not in expense_cols:
            conn.execute("ALTER TABLE expenses ADD COLUMN payment_type TEXT DEFAULT 'day'")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS product_requests (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                product_name    TEXT NOT NULL,
                customer_name   TEXT,
                customer_phone  TEXT,
                note            TEXT,
                branch_id       INTEGER,
                user_id         INTEGER,
                status          TEXT DEFAULT 'pending',
                created_at      TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (branch_id) REFERENCES branches(id),
                FOREIGN KEY (user_id)   REFERENCES users(id)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS loyalty_rewards (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id      INTEGER NOT NULL,
                points_cost     REAL NOT NULL CHECK(points_cost > 0),
                max_per_month   INTEGER DEFAULT 1,
                active          INTEGER DEFAULT 1,
                created_at      TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (product_id) REFERENCES products(id)
            )
        """)

        ledger_cols = [c[1] for c in conn.execute("PRAGMA table_info(loyalty_ledger)").fetchall()]
        if "note" not in ledger_cols:
            conn.execute("ALTER TABLE loyalty_ledger ADD COLUMN note TEXT")

        si_cols = [c[1] for c in conn.execute("PRAGMA table_info(sale_items)").fetchall()]
        if "instructions" not in si_cols:
            conn.execute("ALTER TABLE sale_items ADD COLUMN instructions TEXT")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS branch_product_limits (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                branch_id   INTEGER NOT NULL,
                product_id  INTEGER NOT NULL,
                min_qty     REAL NOT NULL DEFAULT 0 CHECK(min_qty >= 0),
                UNIQUE(branch_id, product_id),
                FOREIGN KEY (branch_id)  REFERENCES branches(id) ON DELETE CASCADE,
                FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_branch_prod_limits ON branch_product_limits(branch_id, product_id)")

        conn.commit()
    finally:
        conn.close()


def _open_local_sqlite(track_dirty: bool = False):
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = _sqlite_row_factory
    conn.execute("PRAGMA foreign_keys = ON")
    if track_dirty:
        return _SqliteOfflineWrapper(conn, track_dirty=True)
    return conn


def _connect_db():
    """Create a new database connection (PostgreSQL if online, automatic fallback to local SQLite if offline)."""
    if IS_POSTGRES:
        st = get_sync_state()
        if st.get("offline_mode"):
            return _open_local_sqlite(track_dirty=True)
        try:
            import psycopg2
            db_url = DATABASE_URL
            if db_url.startswith("postgres://"):
                db_url = "postgresql://" + db_url[len("postgres://"):]
            raw_conn = psycopg2.connect(db_url, connect_timeout=4)
            _LAST_PROBE["ts"] = _time.time()
            _LAST_PROBE["ok"] = True
            return _PgConnectionWrapper(raw_conn)
        except Exception as exc:
            logging.getLogger("pharmacy.db").warning(
                f"Supabase connection failed ({exc}); falling back to local SQLite offline mode."
            )
            _LAST_PROBE["ts"] = _time.time()
            _LAST_PROBE["ok"] = False
            set_sync_state(offline_mode=True)
            _ensure_local_sqlite_schema()
            return _open_local_sqlite(track_dirty=True)
    return _open_local_sqlite(track_dirty=False)


def get_db():
    """Get database connection. Uses Flask's g if in app context, otherwise creates direct connection."""
    try:
        from flask import g
        conn = getattr(g, "db", None)
        if conn is not None:
            is_closed = False
            if hasattr(conn, "closed"):
                is_closed = bool(conn.closed)
            elif hasattr(conn, "_conn") and hasattr(conn._conn, "closed"):
                is_closed = bool(conn._conn.closed)
            if not is_closed:
                try:
                    conn.execute("SELECT 1")
                except Exception:
                    is_closed = True
            if is_closed:
                g.db = None
                conn = None
        if conn is None:
            g.db = _connect_db()
        return g.db
    except RuntimeError:
        return _connect_db()



def close_db(e=None):
    """Close database connection at end of request."""
    try:
        from flask import g
        db = g.pop("db", None)
        if db is not None:
            db.close()
    except RuntimeError:
        pass  # Outside app context


def row(conn, sql, params=()):
    return conn.execute(sql, params).fetchone()


def rows(conn, sql, params=()):
    return conn.execute(sql, params).fetchall()


def q1(conn, sql, params=()):
    r = conn.execute(sql, params).fetchone()
    return r[0] if r else None


def init_db():
    os.makedirs(BACKUP_DIR, exist_ok=True)
    _ensure_local_sqlite_schema()
    conn = get_db()
    try:
        using_pg = isinstance(conn, _PgConnectionWrapper)
        schema_file = SCHEMA_POSTGRES_PATH if using_pg else SCHEMA_PATH
        if os.path.exists(schema_file):
            with open(schema_file, "r", encoding="utf-8") as f:
                conn.executescript(f.read())
        if not q1(conn, "SELECT COUNT(*) FROM branches"):
            conn.execute("INSERT INTO branches (name) VALUES ('الفرع الرئيسي')")
        if not q1(conn, "SELECT COUNT(*) FROM categories"):
            default_categories = [
                "العناية بالبشرة والتجميل",
                "المكملات الغذائية والفيتامينات",
                "العناية الشخصية والنظافة",
                "المستلزمات والأجهزة الطبية",
                "الأدوية العامة",
                "أخرى"
            ]
            for cat in default_categories:
                conn.execute("INSERT OR IGNORE INTO categories (name) VALUES (?)", (cat,))
        conn.execute("INSERT OR IGNORE INTO categories (name) VALUES ('أخرى')")
        if not q1(conn, "SELECT COUNT(*) FROM users"):
            admin_pwd_hash = hashpw("admin123".encode('utf-8'), gensalt()).decode('utf-8')
            conn.execute(
                "INSERT INTO users (username, password, full_name, role) VALUES (?,?,?,?)",
                ("admin", admin_pwd_hash, "مدير النظام", "admin"),
            )

        if using_pg:
            conn.execute("ALTER TABLE sale_items ADD COLUMN IF NOT EXISTS instructions TEXT")
            conn.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS purchase_price_usd DOUBLE PRECISION DEFAULT 0")
            conn.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS sale_price_usd DOUBLE PRECISION DEFAULT 0")
            conn.execute("ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS balance_usd DOUBLE PRECISION DEFAULT 0")
            conn.execute("ALTER TABLE purchases ADD COLUMN IF NOT EXISTS rate DOUBLE PRECISION DEFAULT 1")
            conn.execute("ALTER TABLE purchases ADD COLUMN IF NOT EXISTS total_usd DOUBLE PRECISION DEFAULT 0")
            conn.execute("ALTER TABLE purchase_items ADD COLUMN IF NOT EXISTS cost_usd DOUBLE PRECISION DEFAULT 0")
            conn.execute("ALTER TABLE supplier_payments ADD COLUMN IF NOT EXISTS rate DOUBLE PRECISION DEFAULT 1")
            conn.execute("ALTER TABLE supplier_payments ADD COLUMN IF NOT EXISTS amount_usd DOUBLE PRECISION DEFAULT 0")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS exchange_rate_history (
                    id          SERIAL PRIMARY KEY,
                    old_rate    DOUBLE PRECISION,
                    new_rate    DOUBLE PRECISION NOT NULL,
                    changed_by  INTEGER REFERENCES users(id),
                    created_at  TEXT DEFAULT to_char( CURRENT_TIMESTAMP, 'YYYY-MM-DD HH24:MI:SS' )
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS branch_product_limits (
                    id          SERIAL PRIMARY KEY,
                    branch_id   INTEGER NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
                    product_id  INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
                    min_qty     DOUBLE PRECISION NOT NULL DEFAULT 0 CHECK(min_qty >= 0),
                    UNIQUE(branch_id, product_id)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_branch_prod_limits ON branch_product_limits(branch_id, product_id)")
        conn.commit()
    finally:
        conn.close()

    # Mirror Supabase to local SQLite on startup when online and no unsynced local changes exist
    if IS_POSTGRES:
        st = get_sync_state()
        if not st.get("offline_mode") and not st.get("dirty"):
            try:
                from . import _pg_backup
                payload, _ = _pg_backup.dump_to_payload()
                _pg_backup.restore_payload_to_sqlite(payload, DB_PATH)
                set_sync_state(offline_mode=False, dirty=False, last_sync=now())
            except Exception as e:
                logging.getLogger("pharmacy.db").warning(f"Initial local replica sync skipped: {e}")


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today():
    return datetime.now().strftime("%Y-%m-%d")


def audit(conn, user, branch, action, table=None, record_id=None, detail=None):
    conn.execute(
        "INSERT INTO audit_log (user_id, branch_id, action, table_name, record_id, detail, created_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (user, branch, action, table, record_id, detail, now()),
    )
    try:
        logging.getLogger("pharmacy.audit").info(
            f"user={user} branch={branch} action={action} table={table} id={record_id} detail={detail}"
        )
    except Exception:
        pass


def current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    conn = get_db()
    r = row(conn, "SELECT * FROM users WHERE id = ?", (uid,))
    return dict(r) if r else None


def require_auth():
    u = current_user()
    if not u:
        abort(401, description="Authentication required")
    return u


def require_role(*roles):
    u = require_auth()
    if u["role"] not in roles:
        abort(403, description="Insufficient permissions")
    return u


def branch_scope(user):
    """Admin sees all branches; staff see only their own."""
    if user["role"] == "admin":
        return None
    return user["branch_id"]


def resolve_branch(user, payload=None):
    """Branch for a write: explicit for admin, own for staff, seeded default fallback."""
    conn = get_db()
    b = None
    if user["role"] == "admin" and payload and payload.get("branch_id"):
        try:
            b = int(payload.get("branch_id"))
        except (ValueError, TypeError):
            b = None
    if b is None:
        b = user["branch_id"] or (payload or {}).get("branch_id")
        if b is not None:
            try:
                b = int(b)
            except (ValueError, TypeError):
                b = None
    if b is None:
        b = q1(conn, "SELECT MIN(id) FROM branches")
    return b


def next_invoice(conn, table, branch_id, prefix):
    """Generate next invoice number atomically using a sequence table."""
    # Use a per-table sequence to avoid race conditions
    seq_table = f"{table}_seq"
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {seq_table} (
            branch_id INTEGER NOT NULL,
            seq INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (branch_id)
        )
    """)
    cur = conn.execute(
        f"INSERT INTO {seq_table} (branch_id, seq) VALUES (?, 1) "
        f"ON CONFLICT(branch_id) DO UPDATE SET seq = {seq_table}.seq + 1 RETURNING seq",
        (branch_id,)
    )
    row = cur.fetchone()
    n = row[0] if row else 1
    return f"{prefix}-{branch_id}-{n:06d}"
