-- Pharmacy Management System Schema for Supabase (PostgreSQL)
-- Run this in Supabase SQL Editor (https://supabase.com/dashboard/project/_/sql)

CREATE TABLE IF NOT EXISTS branches (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    phone       TEXT,
    address     TEXT,
    created_at  TEXT DEFAULT to_char( CURRENT_TIMESTAMP, 'YYYY-MM-DD HH24:MI:SS' )
);

CREATE TABLE IF NOT EXISTS users (
    id          SERIAL PRIMARY KEY,
    username    TEXT NOT NULL UNIQUE,
    password    TEXT NOT NULL,
    full_name   TEXT,
    role        TEXT NOT NULL DEFAULT 'sales',
    branch_id   INTEGER REFERENCES branches(id),
    active      INTEGER DEFAULT 1,
    warning_msg TEXT,
    created_at  TEXT DEFAULT to_char( CURRENT_TIMESTAMP, 'YYYY-MM-DD HH24:MI:SS' )
);

CREATE TABLE IF NOT EXISTS suppliers (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    phone       TEXT,
    email       TEXT,
    address     TEXT,
    balance     DOUBLE PRECISION DEFAULT 0 CHECK(balance >= 0),
    balance_usd DOUBLE PRECISION DEFAULT 0 CHECK(balance_usd >= 0),
    created_at  TEXT DEFAULT to_char( CURRENT_TIMESTAMP, 'YYYY-MM-DD HH24:MI:SS' )
);

CREATE TABLE IF NOT EXISTS categories (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS products (
    id              SERIAL PRIMARY KEY,
    name            TEXT NOT NULL,
    generic_name    TEXT,
    strength        TEXT,
    form            TEXT,
    manufacturer    TEXT,
    category        TEXT,
    category_id     INTEGER REFERENCES categories(id),
    barcode         TEXT UNIQUE,
    purchase_price      DOUBLE PRECISION DEFAULT 0 CHECK(purchase_price >= 0),
    sale_price          DOUBLE PRECISION DEFAULT 0 CHECK(sale_price >= 0),
    purchase_price_usd  DOUBLE PRECISION DEFAULT 0 CHECK(purchase_price_usd >= 0),
    sale_price_usd      DOUBLE PRECISION DEFAULT 0 CHECK(sale_price_usd >= 0),
    min_qty         DOUBLE PRECISION DEFAULT 0 CHECK(min_qty >= 0),
    unit            TEXT DEFAULT 'piece',
    strip_qty       DOUBLE PRECISION DEFAULT 1 CHECK(strip_qty > 0),
    carton_qty      DOUBLE PRECISION DEFAULT 1 CHECK(carton_qty > 0),
    supplier_id     INTEGER REFERENCES suppliers(id),
    is_prescription INTEGER DEFAULT 0,
    active          INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS batches (
    id          SERIAL PRIMARY KEY,
    branch_id   INTEGER NOT NULL REFERENCES branches(id),
    product_id  INTEGER NOT NULL REFERENCES products(id),
    batch_no    TEXT,
    expiry_date TEXT,
    qty         DOUBLE PRECISION DEFAULT 0 CHECK(qty >= 0),
    cost        DOUBLE PRECISION DEFAULT 0 CHECK(cost >= 0)
);

CREATE TABLE IF NOT EXISTS branch_product_limits (
    id          SERIAL PRIMARY KEY,
    branch_id   INTEGER NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    product_id  INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    min_qty     DOUBLE PRECISION NOT NULL DEFAULT 0 CHECK(min_qty >= 0),
    UNIQUE(branch_id, product_id)
);

CREATE TABLE IF NOT EXISTS customers (
    id          SERIAL PRIMARY KEY,
    name        TEXT,
    phone       TEXT,
    loyalty_no  TEXT UNIQUE,
    points      DOUBLE PRECISION DEFAULT 0,
    created_at  TEXT DEFAULT to_char( CURRENT_TIMESTAMP, 'YYYY-MM-DD HH24:MI:SS' )
);

CREATE TABLE IF NOT EXISTS sales (
    id              SERIAL PRIMARY KEY,
    branch_id       INTEGER NOT NULL REFERENCES branches(id),
    user_id         INTEGER REFERENCES users(id),
    invoice_no      TEXT,
    sale_date       TEXT,
    customer_id     INTEGER REFERENCES customers(id),
    subtotal        DOUBLE PRECISION DEFAULT 0 CHECK(subtotal >= 0),
    discount        DOUBLE PRECISION DEFAULT 0 CHECK(discount >= 0),
    total           DOUBLE PRECISION DEFAULT 0 CHECK(total >= 0),
    paid            DOUBLE PRECISION DEFAULT 0 CHECK(paid >= 0),
    payment_method  TEXT DEFAULT 'cash',
    note            TEXT
);

CREATE TABLE IF NOT EXISTS sale_items (
    id          SERIAL PRIMARY KEY,
    sale_id     INTEGER NOT NULL REFERENCES sales(id) ON DELETE CASCADE,
    product_id  INTEGER NOT NULL REFERENCES products(id),
    qty         DOUBLE PRECISION NOT NULL,
    price       DOUBLE PRECISION NOT NULL,
    line_total  DOUBLE PRECISION NOT NULL,
    batch_no    TEXT,
    expiry_date TEXT,
    instructions TEXT
);

CREATE TABLE IF NOT EXISTS sale_payments (
    id          SERIAL PRIMARY KEY,
    sale_id     INTEGER NOT NULL REFERENCES sales(id) ON DELETE CASCADE,
    method      TEXT NOT NULL,
    amount      DOUBLE PRECISION DEFAULT 0
);

CREATE TABLE IF NOT EXISTS loyalty_ledger (
    id          SERIAL PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    sale_id     INTEGER REFERENCES sales(id) ON DELETE CASCADE,
    points      DOUBLE PRECISION NOT NULL,
    type        TEXT NOT NULL,
    note        TEXT,
    created_at  TEXT DEFAULT to_char( CURRENT_TIMESTAMP, 'YYYY-MM-DD HH24:MI:SS' )
);

CREATE TABLE IF NOT EXISTS loyalty_rewards (
    id              SERIAL PRIMARY KEY,
    product_id      INTEGER NOT NULL REFERENCES products(id),
    points_cost     DOUBLE PRECISION NOT NULL CHECK(points_cost > 0),
    max_per_month   INTEGER DEFAULT 1,
    active          INTEGER DEFAULT 1,
    created_at      TEXT DEFAULT to_char( CURRENT_TIMESTAMP, 'YYYY-MM-DD HH24:MI:SS' )
);

CREATE TABLE IF NOT EXISTS purchases (
    id            SERIAL PRIMARY KEY,
    branch_id     INTEGER NOT NULL REFERENCES branches(id),
    supplier_id   INTEGER REFERENCES suppliers(id),
    invoice_no    TEXT,
    purchase_date TEXT,
    subtotal      DOUBLE PRECISION DEFAULT 0 CHECK(subtotal >= 0),
    discount      DOUBLE PRECISION DEFAULT 0 CHECK(discount >= 0),
    extra_cost    DOUBLE PRECISION DEFAULT 0 CHECK(extra_cost >= 0),
    total         DOUBLE PRECISION DEFAULT 0 CHECK(total >= 0),
    rate          DOUBLE PRECISION DEFAULT 1 CHECK(rate > 0),
    total_usd     DOUBLE PRECISION DEFAULT 0 CHECK(total_usd >= 0),
    paid          DOUBLE PRECISION DEFAULT 0 CHECK(paid >= 0),
    note          TEXT
);

CREATE TABLE IF NOT EXISTS purchase_items (
    id          SERIAL PRIMARY KEY,
    purchase_id INTEGER NOT NULL REFERENCES purchases(id) ON DELETE CASCADE,
    product_id  INTEGER NOT NULL REFERENCES products(id),
    qty         DOUBLE PRECISION NOT NULL,
    cost        DOUBLE PRECISION NOT NULL,
    cost_usd    DOUBLE PRECISION DEFAULT 0 CHECK(cost_usd >= 0),
    batch_no    TEXT,
    expiry_date TEXT
);

CREATE TABLE IF NOT EXISTS expenses (
    id           SERIAL PRIMARY KEY,
    branch_id    INTEGER NOT NULL REFERENCES branches(id),
    user_id      INTEGER REFERENCES users(id),
    expense_date TEXT,
    category     TEXT,
    amount       DOUBLE PRECISION DEFAULT 0,
    note         TEXT,
    payment_type TEXT DEFAULT 'day'
);

CREATE TABLE IF NOT EXISTS returns (
    id          SERIAL PRIMARY KEY,
    branch_id   INTEGER NOT NULL REFERENCES branches(id),
    user_id     INTEGER,
    sale_id     INTEGER REFERENCES sales(id),
    type        TEXT,
    product_id  INTEGER REFERENCES products(id),
    qty         DOUBLE PRECISION DEFAULT 0,
    amount      DOUBLE PRECISION DEFAULT 0,
    reason      TEXT,
    return_date TEXT
);

CREATE TABLE IF NOT EXISTS inventory_adjustments (
    id              SERIAL PRIMARY KEY,
    branch_id       INTEGER NOT NULL REFERENCES branches(id),
    product_id      INTEGER NOT NULL REFERENCES products(id),
    batch_id        INTEGER REFERENCES batches(id),
    qty             DOUBLE PRECISION NOT NULL,
    reason_type     TEXT NOT NULL,
    reason_note     TEXT,
    adjusted_by     INTEGER NOT NULL REFERENCES users(id),
    adjustment_date TEXT DEFAULT to_char( CURRENT_TIMESTAMP, 'YYYY-MM-DD HH24:MI:SS' )
);

CREATE TABLE IF NOT EXISTS supplier_payments (
    id          SERIAL PRIMARY KEY,
    branch_id   INTEGER NOT NULL REFERENCES branches(id),
    supplier_id INTEGER NOT NULL REFERENCES suppliers(id),
    user_id     INTEGER,
    amount      DOUBLE PRECISION DEFAULT 0,
    rate        DOUBLE PRECISION DEFAULT 1 CHECK(rate > 0),
    amount_usd  DOUBLE PRECISION DEFAULT 0 CHECK(amount_usd >= 0),
    pay_date    TEXT,
    note        TEXT
);

CREATE TABLE IF NOT EXISTS exchange_rate_history (
    id          SERIAL PRIMARY KEY,
    old_rate    DOUBLE PRECISION,
    new_rate    DOUBLE PRECISION NOT NULL,
    changed_by  INTEGER REFERENCES users(id),
    created_at  TEXT DEFAULT to_char( CURRENT_TIMESTAMP, 'YYYY-MM-DD HH24:MI:SS' )
);

CREATE TABLE IF NOT EXISTS shifts (
    id            SERIAL PRIMARY KEY,
    branch_id     INTEGER NOT NULL REFERENCES branches(id),
    user_id       INTEGER NOT NULL REFERENCES users(id),
    opening_cash  DOUBLE PRECISION DEFAULT 0,
    closing_cash  DOUBLE PRECISION DEFAULT 0,
    expected_cash DOUBLE PRECISION DEFAULT 0,
    variance      DOUBLE PRECISION DEFAULT 0,
    status        TEXT DEFAULT 'open',
    opened_at     TEXT,
    closed_at     TEXT,
    note          TEXT
);

CREATE TABLE IF NOT EXISTS promotions (
    id              SERIAL PRIMARY KEY,
    name            TEXT NOT NULL,
    discount_type   TEXT NOT NULL,
    discount_value  DOUBLE PRECISION NOT NULL,
    start_date      TEXT NOT NULL,
    end_date        TEXT NOT NULL,
    apply_to        TEXT NOT NULL,
    product_ids     TEXT,
    category_ids    TEXT,
    conditions      TEXT,
    created_by      INTEGER REFERENCES users(id),
    approved_by     INTEGER REFERENCES users(id),
    approved_at     TEXT,
    created_at      TEXT DEFAULT to_char( CURRENT_TIMESTAMP, 'YYYY-MM-DD HH24:MI:SS' ),
    active          INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS audit_log (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER,
    branch_id   INTEGER,
    action      TEXT NOT NULL,
    table_name  TEXT,
    record_id   INTEGER,
    detail      TEXT,
    created_at  TEXT DEFAULT to_char( CURRENT_TIMESTAMP, 'YYYY-MM-DD HH24:MI:SS' )
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS product_requests (
    id              SERIAL PRIMARY KEY,
    product_name    TEXT NOT NULL,
    customer_name   TEXT,
    customer_phone  TEXT,
    note            TEXT,
    branch_id       INTEGER REFERENCES branches(id),
    user_id         INTEGER REFERENCES users(id),
    status          TEXT DEFAULT 'pending',
    created_at      TEXT DEFAULT to_char( CURRENT_TIMESTAMP, 'YYYY-MM-DD HH24:MI:SS' )
);

CREATE TABLE IF NOT EXISTS sales_seq (
    branch_id INTEGER PRIMARY KEY,
    seq       INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS purchases_seq (
    branch_id INTEGER PRIMARY KEY,
    seq       INTEGER NOT NULL DEFAULT 0
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_batches_branch_prod ON batches(branch_id, product_id);
CREATE INDEX IF NOT EXISTS idx_batches_expiry ON batches(expiry_date);
CREATE INDEX IF NOT EXISTS idx_sales_branch_date ON sales(branch_id, sale_date);
CREATE INDEX IF NOT EXISTS idx_purchases_branch_date ON purchases(branch_id, purchase_date);
CREATE INDEX IF NOT EXISTS idx_products_barcode ON products(barcode);
CREATE INDEX IF NOT EXISTS idx_products_name ON products(name);
CREATE INDEX IF NOT EXISTS idx_sales_user_id ON sales(user_id);
CREATE INDEX IF NOT EXISTS idx_sales_customer_id ON sales(customer_id);
CREATE INDEX IF NOT EXISTS idx_purchases_supplier_id ON purchases(supplier_id);
CREATE INDEX IF NOT EXISTS idx_expenses_branch_id ON expenses(branch_id);
CREATE INDEX IF NOT EXISTS idx_expenses_user_id ON expenses(user_id);
CREATE INDEX IF NOT EXISTS idx_returns_sale_id ON returns(sale_id);
CREATE INDEX IF NOT EXISTS idx_shifts_user_id ON shifts(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_user_id ON audit_log(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_branch_id ON audit_log(branch_id);
CREATE INDEX IF NOT EXISTS idx_branch_prod_limits ON branch_product_limits(branch_id, product_id);
