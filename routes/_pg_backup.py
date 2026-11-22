"""Local backup / restore for PostgreSQL (Supabase) and cross-format (.db <-> .json.gz).

Supports:
- Dumping PostgreSQL (Supabase) to a compressed `.json.gz` file in `BACKUP_DIR`
- Loading either a `.json.gz` snapshot OR a `.db` / `.db.prerestore` SQLite database file
- Restoring any loaded snapshot into PostgreSQL (Supabase) atomically in a single transaction
- Restoring a `.json.gz` snapshot into a local SQLite database
"""
import base64
import datetime as _dt
import decimal
import gzip
import json
import sqlite3

FORMAT = "pharmsys-pg-backup"
FORMAT_VERSION = 1
EXT = ".json.gz"


def _raw_conn(connect_timeout=10):
    import psycopg2
    from config import DATABASE_URL
    from ._common import close_db
    # Critical: close Flask's request-scoped g.db first so it does not hold an
    # AccessShareLock on `users` (from require_role) that would block TRUNCATE!
    close_db()
    db_url = DATABASE_URL or ""
    if db_url.startswith("postgres://"):
        db_url = "postgresql://" + db_url[len("postgres://"):]
    return psycopg2.connect(db_url, connect_timeout=connect_timeout)


def _encode(v):
    if isinstance(v, decimal.Decimal):
        return str(v)
    if isinstance(v, (_dt.datetime, _dt.date, _dt.time)):
        return v.isoformat()
    if isinstance(v, _dt.timedelta):
        return f"{v.total_seconds()} seconds"
    if isinstance(v, (bytes, bytearray, memoryview)):
        return {"$b64": base64.b64encode(bytes(v)).decode("ascii")}
    raise TypeError(f"Unsupported type in backup: {type(v).__name__}")


def _decode(v):
    if isinstance(v, dict) and set(v) == {"$b64"}:
        return base64.b64decode(v["$b64"])
    if isinstance(v, decimal.Decimal):
        return float(v)
    if isinstance(v, (_dt.datetime, _dt.date, _dt.time)):
        return v.isoformat()
    if isinstance(v, _dt.timedelta):
        return f"{v.total_seconds()} seconds"
    return v


def _tables_and_columns(cur):
    """Fetch all base tables and their columns in a single round-trip."""
    cur.execute("""
        SELECT c.table_name, c.column_name
        FROM information_schema.columns c
        JOIN information_schema.tables t
          ON t.table_schema = c.table_schema AND t.table_name = c.table_name
        WHERE c.table_schema = 'public' AND t.table_type = 'BASE TABLE'
        ORDER BY c.table_name, c.ordinal_position
    """)
    tbl_cols = {}
    for t, col in cur.fetchall():
        tbl_cols.setdefault(t, []).append(col)
    return tbl_cols


def _fk_order(cur, tables):
    """Order tables so that referenced (parent) tables come before children."""
    cur.execute("""
        SELECT c.conrelid::regclass::text, c.confrelid::regclass::text
        FROM pg_constraint c
        JOIN pg_namespace n ON n.oid = c.connamespace
        WHERE c.contype = 'f' AND n.nspname = 'public'
    """)
    deps = {t: set() for t in tables}
    for child, parent in cur.fetchall():
        child, parent = child.strip('"'), parent.strip('"')
        if child in deps and parent in deps and child != parent:
            deps[child].add(parent)
    ordered, done = [], set()
    while len(ordered) < len(tables):
        ready = [t for t in tables if t not in done and deps[t] <= done]
        if not ready:  # cycle - append the rest as-is
            ready = [t for t in tables if t not in done]
        for t in ready:
            ordered.append(t)
            done.add(t)
    return ordered


def dump_to_payload():
    """Return a full in-memory snapshot dict of the PostgreSQL database."""
    from psycopg2 import sql
    conn = _raw_conn()
    try:
        conn.set_session(isolation_level="REPEATABLE READ", readonly=True)
        cur = conn.cursor()
        tbl_cols = _tables_and_columns(cur)
        data, counts = {}, {}
        for t, cols in tbl_cols.items():
            cur.execute(sql.SQL("SELECT * FROM {}").format(sql.Identifier(t)))
            col_names = [d[0] for d in cur.description] if cur.description else cols
            rws = [list(r) for r in cur.fetchall()]
            data[t] = {"columns": col_names, "rows": rws}
            counts[t] = len(rws)
        conn.rollback()
    finally:
        conn.close()
    return {
        "format": FORMAT,
        "version": FORMAT_VERSION,
        "created_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "tables": data,
    }, counts


def dump_to_file(path):
    """Write a full snapshot of the PostgreSQL database to ``path``."""
    payload, counts = dump_to_payload()
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, default=_encode)
    return counts


def _is_sqlite_file(path):
    try:
        with open(path, "rb") as fh:
            return fh.read(16) == b"SQLite format 3\x00"
    except OSError:
        return False


def _load_sqlite_file(path):
    """Read a SQLite .db backup file into the common payload dict."""
    if not _is_sqlite_file(path):
        raise ValueError("الملف ليس قاعدة بيانات SQLite صالحة")
    conn = sqlite3.connect(path)
    try:
        tables_res = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        data = {}
        for (t,) in tables_res:
            cur = conn.execute(f'SELECT * FROM "{t}"')
            cols = [d[0] for d in cur.description]
            rws = [list(r) for r in cur.fetchall()]
            data[t] = {"columns": cols, "rows": rws}
        if not data:
            raise ValueError("ملف SQLite لا يحتوي على جداول")
        return {
            "format": FORMAT,
            "version": FORMAT_VERSION,
            "tables": data,
        }
    finally:
        conn.close()


def load_file(path):
    """Read and validate a backup file (.json.gz or SQLite .db)."""
    if _is_sqlite_file(path):
        return _load_sqlite_file(path)
    try:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, ValueError) as e:
        raise ValueError("ملف النسخة الاحتياطية تالف أو غير صالح") from e
    if not isinstance(payload, dict) or payload.get("format") != FORMAT:
        raise ValueError("الملف ليس نسخة احتياطية من نظام الصيدلية")
    if payload.get("version", 0) > FORMAT_VERSION:
        raise ValueError("النسخة الاحتياطية من إصدار أحدث من النظام")
    if not isinstance(payload.get("tables"), dict):
        raise ValueError("ملف النسخة الاحتياطية لا يحتوي على جداول")
    return payload


def restore_from_payload(payload):
    """Replace all PostgreSQL data with the backup contents, atomically."""
    from psycopg2 import sql
    from psycopg2.extras import execute_values
    conn = _raw_conn()
    try:
        cur = conn.cursor()
        cur.execute("SET LOCAL lock_timeout = '15s'; SET LOCAL statement_timeout = '120s';")
        cur.execute("ALTER TABLE customers DROP CONSTRAINT IF EXISTS customers_phone_key;")
        tbl_cols = _tables_and_columns(cur)
        live_tables = list(tbl_cols.keys())
        backup = payload["tables"]
        targets = [t for t in live_tables if t in backup]
        if not targets:
            raise ValueError("لا توجد جداول مطابقة في النسخة الاحتياطية")

        cur.execute(sql.SQL("TRUNCATE {} RESTART IDENTITY CASCADE").format(
            sql.SQL(", ").join(sql.Identifier(t) for t in live_tables)))

        counts = {}
        for t in _fk_order(cur, targets):
            live_cols = set(tbl_cols.get(t, ()))
            cols = backup[t].get("columns") or []
            keep = [i for i, c in enumerate(cols) if c in live_cols]  # tolerate schema drift
            rws = backup[t].get("rows") or []
            if keep and rws:
                execute_values(
                    cur,
                    sql.SQL("INSERT INTO {} ({}) VALUES %s").format(
                        sql.Identifier(t),
                        sql.SQL(", ").join(sql.Identifier(cols[i]) for i in keep),
                    ).as_string(conn),
                    [[_decode(r[i]) for i in keep] for r in rws],
                    page_size=500,
                )
            counts[t] = len(rws)

        # Re-sync serial / identity sequences in a single query
        cur.execute("""
            SELECT table_name, column_name FROM information_schema.columns
            WHERE table_schema = 'public'
              AND (column_default LIKE 'nextval(%' OR is_identity = 'YES')
        """)
        seq_parts = []
        for t, c in cur.fetchall():
            if t not in live_tables:
                continue
            seq_parts.append(
                sql.SQL(
                    "setval(pg_get_serial_sequence({t_lit}, {c_lit}), "
                    "COALESCE((SELECT MAX({c}) FROM {t}), 1), "
                    "(SELECT MAX({c}) IS NOT NULL FROM {t}))"
                ).format(
                    t_lit=sql.Literal(f'public."{t}"'),
                    c_lit=sql.Literal(c),
                    c=sql.Identifier(c),
                    t=sql.Identifier(t),
                )
            )
        if seq_parts:
            cur.execute(sql.SQL("SELECT ") + sql.SQL(", ").join(seq_parts))
        conn.commit()
        return counts
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def restore_payload_to_sqlite(payload, db_path):
    """Replace all data in a local SQLite database with the backup payload."""
    from ._common import close_db
    close_db()
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = OFF")
        live_tables = [
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        ]
        backup = payload["tables"]
        targets = [t for t in live_tables if t in backup]
        if not targets:
            raise ValueError("لا توجد جداول مطابقة في النسخة الاحتياطية")
        for t in live_tables:
            conn.execute(f'DELETE FROM "{t}"')
        for t in targets:
            live_cols = {r[1] for r in conn.execute(f'PRAGMA table_info("{t}")').fetchall()}
            cols = backup[t].get("columns") or []
            keep = [i for i, c in enumerate(cols) if c in live_cols]
            rws = backup[t].get("rows") or []
            if keep and rws:
                col_list = ", ".join(f'"{cols[i]}"' for i in keep)
                placeholders = ", ".join("?" for _ in keep)
                conn.executemany(
                    f'INSERT INTO "{t}" ({col_list}) VALUES ({placeholders})',
                    [[_decode(r[i]) for i in keep] for r in rws],
                )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
