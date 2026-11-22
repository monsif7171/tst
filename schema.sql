-- Pharmacy Management System schema (SQLite)
-- Shared masters + per-branch transactions (chain model)

CREATE TABLE IF NOT EXISTS branches (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    phone       TEXT,
    address     TEXT,
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    username    TEXT NOT NULL UNIQUE,
    password    TEXT NOT NULL,          -- bcrypt hash
    full_name   TEXT,
    role        TEXT NOT NULL DEFAULT 'sales',  -- admin | pharmacist | sales
    branch_id   INTEGER,
    active      INTEGER DEFAULT 1,
    warning_msg TEXT,
    created_at  TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (branch_id) REFERENCES branches(id)
);

CREATE TABLE IF NOT EXISTS suppliers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    phone       TEXT,
    email       TEXT,
    address     TEXT,
    balance     REAL DEFAULT 0 CHECK(balance >= 0),
    balance_usd REAL DEFAULT 0 CHECK(balance_usd >= 0),
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS categories (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS products (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    generic_name    TEXT,
    strength        TEXT,
    form            TEXT,
    manufacturer    TEXT,
    category        TEXT,
    category_id     INTEGER,
    barcode         TEXT UNIQUE,
    purchase_price      REAL DEFAULT 0 CHECK(purchase_price >= 0),
    sale_price          REAL DEFAULT 0 CHECK(sale_price >= 0),
    purchase_price_usd  REAL DEFAULT 0 CHECK(purchase_price_usd >= 0),
    sale_price_usd      REAL DEFAULT 0 CHECK(sale_price_usd >= 0),
    min_qty         REAL DEFAULT 0 CHECK(min_qty >= 0),
    unit            TEXT DEFAULT 'piece',
    strip_qty       REAL DEFAULT 1 CHECK(strip_qty > 0),
    carton_qty      REAL DEFAULT 1 CHECK(carton_qty > 0),
    supplier_id     INTEGER,
    is_prescription INTEGER DEFAULT 0,
    active          INTEGER DEFAULT 1,
    FOREIGN KEY (supplier_id) REFERENCES suppliers(id),
    FOREIGN KEY (category_id) REFERENCES categories(id)
);

-- Stock batches: one row per (product, batch, expiry) per branch
CREATE TABLE IF NOT EXISTS batches (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    branch_id   INTEGER NOT NULL,
    product_id  INTEGER NOT NULL,
    batch_no    TEXT,
    expiry_date TEXT,
    qty         REAL DEFAULT 0 CHECK(qty >= 0),
    cost        REAL DEFAULT 0 CHECK(cost >= 0),
    FOREIGN KEY (branch_id)  REFERENCES branches(id),
    FOREIGN KEY (product_id) REFERENCES products(id)
);

-- Branch-specific reorder limits (overrides products.min_qty per branch when set)
CREATE TABLE IF NOT EXISTS branch_product_limits (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    branch_id   INTEGER NOT NULL,
    product_id  INTEGER NOT NULL,
    min_qty     REAL NOT NULL DEFAULT 0 CHECK(min_qty >= 0),
    UNIQUE(branch_id, product_id),
    FOREIGN KEY (branch_id)  REFERENCES branches(id) ON DELETE CASCADE,
    FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS customers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT,
    phone       TEXT UNIQUE,
    loyalty_no  TEXT UNIQUE,
    points      REAL DEFAULT 0,
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS loyalty_ledger (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL,
    sale_id     INTEGER,
    points      REAL NOT NULL, -- positive for earned, negative for redeemed
    type        TEXT NOT NULL, -- earn | redeem_discount | redeem_product | adjust
    note        TEXT,
    created_at  TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE CASCADE,
    FOREIGN KEY (sale_id) REFERENCES sales(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS loyalty_rewards (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id      INTEGER NOT NULL,
    points_cost     REAL NOT NULL CHECK(points_cost > 0),
    max_per_month   INTEGER DEFAULT 1,
    active          INTEGER DEFAULT 1,
    created_at      TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (product_id) REFERENCES products(id)
);

CREATE TABLE IF NOT EXISTS purchases (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    branch_id   INTEGER NOT NULL,
    supplier_id INTEGER,
    invoice_no  TEXT,
    purchase_date TEXT,
    subtotal    REAL DEFAULT 0 CHECK(subtotal >= 0),
    discount    REAL DEFAULT 0 CHECK(discount >= 0),
    extra_cost  REAL DEFAULT 0 CHECK(extra_cost >= 0),
    total       REAL DEFAULT 0 CHECK(total >= 0),
    rate        REAL DEFAULT 1 CHECK(rate > 0),
    total_usd   REAL DEFAULT 0 CHECK(total_usd >= 0),
    paid        REAL DEFAULT 0 CHECK(paid >= 0),
    note        TEXT,
    FOREIGN KEY (branch_id)  REFERENCES branches(id),
    FOREIGN KEY (supplier_id) REFERENCES suppliers(id)
);

CREATE TABLE IF NOT EXISTS purchase_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    purchase_id INTEGER NOT NULL,
    product_id  INTEGER NOT NULL,
    qty         REAL NOT NULL,
    cost        REAL NOT NULL,
    cost_usd    REAL DEFAULT 0 CHECK(cost_usd >= 0),
    batch_no    TEXT,
    expiry_date TEXT,
    FOREIGN KEY (purchase_id) REFERENCES purchases(id) ON DELETE CASCADE,
    FOREIGN KEY (product_id)  REFERENCES products(id)
);

CREATE TABLE IF NOT EXISTS sales (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    branch_id   INTEGER NOT NULL,
    user_id     INTEGER,
    invoice_no  TEXT,
    sale_date   TEXT,
    customer_id INTEGER,
    subtotal    REAL DEFAULT 0 CHECK(subtotal >= 0),
    discount    REAL DEFAULT 0 CHECK(discount >= 0),
    total       REAL DEFAULT 0 CHECK(total >= 0),
    paid        REAL DEFAULT 0 CHECK(paid >= 0),
    payment_method TEXT DEFAULT 'cash',
    note        TEXT,
    FOREIGN KEY (branch_id)  REFERENCES branches(id),
    FOREIGN KEY (user_id)    REFERENCES users(id),
    FOREIGN KEY (customer_id) REFERENCES customers(id)
);

CREATE TABLE IF NOT EXISTS sale_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    sale_id     INTEGER NOT NULL,
    product_id  INTEGER NOT NULL,
    qty         REAL NOT NULL,
    price       REAL NOT NULL,
    line_total  REAL NOT NULL,
    batch_no    TEXT,
    expiry_date TEXT,
    instructions TEXT,
    FOREIGN KEY (sale_id)    REFERENCES sales(id) ON DELETE CASCADE,
    FOREIGN KEY (product_id)  REFERENCES products(id)
);

CREATE TABLE IF NOT EXISTS sale_payments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    sale_id     INTEGER NOT NULL,
    method      TEXT NOT NULL,
    amount      REAL DEFAULT 0,
    FOREIGN KEY (sale_id)    REFERENCES sales(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS expenses (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    branch_id   INTEGER NOT NULL,
    user_id     INTEGER,
    expense_date TEXT,
    category    TEXT,
    amount      REAL DEFAULT 0,
    note        TEXT,
    payment_type TEXT DEFAULT 'day',
    FOREIGN KEY (branch_id) REFERENCES branches(id),
    FOREIGN KEY (user_id)   REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS returns (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    branch_id   INTEGER NOT NULL,
    user_id     INTEGER,
    sale_id     INTEGER,
    type        TEXT,           -- customer | supplier | damage
    product_id  INTEGER,
    qty         REAL DEFAULT 0,
    amount      REAL DEFAULT 0,
    reason      TEXT,
    return_date TEXT,
    FOREIGN KEY (branch_id) REFERENCES branches(id),
    FOREIGN KEY (sale_id)    REFERENCES sales(id),
    FOREIGN KEY (product_id) REFERENCES products(id)
);

CREATE TABLE IF NOT EXISTS inventory_adjustments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    branch_id       INTEGER NOT NULL,
    product_id      INTEGER NOT NULL,
    batch_id        INTEGER,
    qty             REAL NOT NULL, -- positive for addition, negative for reduction
    reason_type     TEXT NOT NULL, -- damage | expiry | return | stock_difference
    reason_note     TEXT,
    adjusted_by     INTEGER NOT NULL,
    adjustment_date TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (branch_id)  REFERENCES branches(id),
    FOREIGN KEY (product_id)  REFERENCES products(id),
    FOREIGN KEY (batch_id)    REFERENCES batches(id),
    FOREIGN KEY (adjusted_by) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS supplier_payments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    branch_id   INTEGER NOT NULL,
    supplier_id INTEGER NOT NULL,
    user_id     INTEGER,
    amount      REAL DEFAULT 0,
    rate        REAL DEFAULT 1 CHECK(rate > 0),
    amount_usd  REAL DEFAULT 0 CHECK(amount_usd >= 0),
    pay_date    TEXT,
    note        TEXT,
    FOREIGN KEY (branch_id) REFERENCES branches(id),
    FOREIGN KEY (supplier_id) REFERENCES suppliers(id)
);

CREATE TABLE IF NOT EXISTS exchange_rate_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    old_rate    REAL,
    new_rate    REAL NOT NULL,
    changed_by  INTEGER,
    created_at  TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (changed_by) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS shifts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    branch_id     INTEGER NOT NULL,
    user_id       INTEGER NOT NULL,
    opening_cash  REAL DEFAULT 0,
    closing_cash  REAL DEFAULT 0,
    expected_cash REAL DEFAULT 0,
    variance      REAL DEFAULT 0,
    status        TEXT DEFAULT 'open', -- open | closed
    opened_at     TEXT,
    closed_at     TEXT,
    note          TEXT,
    FOREIGN KEY (branch_id) REFERENCES branches(id),
    FOREIGN KEY (user_id)   REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS promotions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    discount_type   TEXT NOT NULL, -- percentage | fixed
    discount_value  REAL NOT NULL,
    start_date      TEXT NOT NULL,
    end_date        TEXT NOT NULL,
    apply_to        TEXT NOT NULL, -- all | specific_products | specific_categories
    product_ids     TEXT,          -- list of product IDs if specific
    category_ids    TEXT,          -- list of category IDs if specific
    conditions      TEXT,          -- text explaining who is eligible
    created_by      INTEGER,
    approved_by     INTEGER,       -- only admin can approve
    approved_at     TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    active          INTEGER DEFAULT 0,
    FOREIGN KEY (created_by) REFERENCES users(id),
    FOREIGN KEY (approved_by) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER,
    branch_id   INTEGER,
    action      TEXT NOT NULL,
    table_name  TEXT,
    record_id   INTEGER,
    detail      TEXT,
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS product_requests (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    product_name    TEXT NOT NULL,
    customer_name   TEXT,
    customer_phone  TEXT,
    note            TEXT,
    branch_id       INTEGER,
    user_id         INTEGER,
    status          TEXT DEFAULT 'pending', -- pending | ordered | fulfilled | cancelled
    created_at      TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (branch_id) REFERENCES branches(id),
    FOREIGN KEY (user_id)   REFERENCES users(id)
);

-- Existing indexes
CREATE INDEX IF NOT EXISTS idx_batches_branch_prod ON batches(branch_id, product_id);
CREATE INDEX IF NOT EXISTS idx_batches_expiry ON batches(expiry_date);
CREATE INDEX IF NOT EXISTS idx_sales_branch_date ON sales(branch_id, sale_date);
CREATE INDEX IF NOT EXISTS idx_purchases_branch_date ON purchases(branch_id, purchase_date);
CREATE INDEX IF NOT EXISTS idx_products_barcode ON products(barcode);
CREATE INDEX IF NOT EXISTS idx_products_name ON products(name);

-- Additional indexes for foreign keys and common queries
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
