from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sqlite3
from typing import Iterator

from .config import ensure_workspace_layout, resolve_db_path
from .utils import DATE_PATTERN, normalize_optional_date

SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS manufacturers (
        manufacturer_id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE CHECK (trim(name) <> '')
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS suppliers (
        supplier_id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE CHECK (trim(name) <> '')
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS items_master (
        item_id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_number TEXT NOT NULL CHECK (trim(item_number) <> ''),
        manufacturer_id INTEGER NOT NULL,
        category TEXT,
        url TEXT,
        description TEXT,
        UNIQUE (manufacturer_id, item_number),
        FOREIGN KEY (manufacturer_id) REFERENCES manufacturers (manufacturer_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS inventory_ledger (
        ledger_id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_id INTEGER NOT NULL,
        location TEXT NOT NULL CHECK (trim(location) <> ''),
        quantity INTEGER NOT NULL CHECK (quantity >= 0),
        last_updated TEXT,
        UNIQUE (item_id, location),
        FOREIGN KEY (item_id) REFERENCES items_master (item_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS quotations (
        quotation_id INTEGER PRIMARY KEY AUTOINCREMENT,
        supplier_id INTEGER NOT NULL,
        quotation_number TEXT NOT NULL CHECK (trim(quotation_number) <> ''),
        issue_date TEXT,
        pdf_link TEXT,
        UNIQUE (supplier_id, quotation_number),
        FOREIGN KEY (supplier_id) REFERENCES suppliers (supplier_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS orders (
        order_id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_id INTEGER NOT NULL,
        quotation_id INTEGER NOT NULL,
        order_amount INTEGER NOT NULL CHECK (order_amount > 0),
        ordered_quantity INTEGER CHECK (ordered_quantity IS NULL OR ordered_quantity > 0),
        ordered_item_number TEXT,
        order_date TEXT NOT NULL,
        expected_arrival TEXT,
        arrival_date TEXT,
        status TEXT NOT NULL DEFAULT 'Ordered' CHECK (status IN ('Ordered', 'Arrived')),
        FOREIGN KEY (item_id) REFERENCES items_master (item_id),
        FOREIGN KEY (quotation_id) REFERENCES quotations (quotation_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS order_lineage_events (
        event_id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_type TEXT NOT NULL CHECK (event_type IN ('ETA_UPDATE', 'ETA_SPLIT', 'ETA_MERGE', 'ARRIVAL_SPLIT')),
        source_order_id INTEGER NOT NULL,
        target_order_id INTEGER,
        quantity INTEGER,
        previous_expected_arrival TEXT,
        new_expected_arrival TEXT,
        note TEXT,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS transaction_log (
        log_id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,
        operation_type TEXT NOT NULL,
        item_id INTEGER NOT NULL,
        quantity INTEGER NOT NULL CHECK (quantity > 0),
        from_location TEXT,
        to_location TEXT,
        note TEXT,
        is_undone INTEGER NOT NULL DEFAULT 0 CHECK (is_undone IN (0, 1)),
        undo_of_log_id INTEGER,
        batch_id TEXT,
        FOREIGN KEY (item_id) REFERENCES items_master (item_id),
        FOREIGN KEY (undo_of_log_id) REFERENCES transaction_log (log_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS projects (
        project_id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE CHECK (trim(name) <> ''),
        description TEXT,
        status TEXT NOT NULL DEFAULT 'PLANNING'
            CHECK (status IN ('PLANNING', 'CONFIRMED', 'ACTIVE', 'COMPLETED', 'CANCELLED')),
        planned_start TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS reservations (
        reservation_id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_id INTEGER NOT NULL,
        quantity INTEGER NOT NULL CHECK (quantity > 0),
        purpose TEXT,
        deadline TEXT,
        created_at TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'ACTIVE'
            CHECK (status IN ('ACTIVE', 'RELEASED', 'CONSUMED')),
        released_at TEXT,
        note TEXT,
        project_id INTEGER,
        FOREIGN KEY (item_id) REFERENCES items_master (item_id),
        FOREIGN KEY (project_id) REFERENCES projects (project_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS reservation_allocations (
        allocation_id INTEGER PRIMARY KEY AUTOINCREMENT,
        reservation_id INTEGER NOT NULL,
        item_id INTEGER NOT NULL,
        location TEXT NOT NULL CHECK (trim(location) <> ''),
        quantity INTEGER NOT NULL CHECK (quantity > 0),
        status TEXT NOT NULL DEFAULT 'ACTIVE'
            CHECK (status IN ('ACTIVE', 'RELEASED', 'CONSUMED')),
        created_at TEXT NOT NULL,
        released_at TEXT,
        note TEXT,
        FOREIGN KEY (reservation_id) REFERENCES reservations (reservation_id) ON DELETE CASCADE,
        FOREIGN KEY (item_id) REFERENCES items_master (item_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS assemblies (
        assembly_id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE CHECK (trim(name) <> ''),
        description TEXT,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS assembly_components (
        assembly_id INTEGER NOT NULL,
        item_id INTEGER NOT NULL,
        quantity INTEGER NOT NULL CHECK (quantity > 0),
        PRIMARY KEY (assembly_id, item_id),
        FOREIGN KEY (assembly_id) REFERENCES assemblies (assembly_id) ON DELETE CASCADE,
        FOREIGN KEY (item_id) REFERENCES items_master (item_id) ON DELETE RESTRICT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS location_assembly_usage (
        usage_id INTEGER PRIMARY KEY AUTOINCREMENT,
        location TEXT NOT NULL CHECK (trim(location) <> ''),
        assembly_id INTEGER NOT NULL,
        quantity INTEGER NOT NULL CHECK (quantity > 0),
        note TEXT,
        updated_at TEXT NOT NULL,
        UNIQUE (location, assembly_id),
        FOREIGN KEY (assembly_id) REFERENCES assemblies (assembly_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS project_requirements (
        requirement_id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        assembly_id INTEGER,
        item_id INTEGER,
        quantity INTEGER NOT NULL CHECK (quantity > 0),
        requirement_type TEXT NOT NULL DEFAULT 'INITIAL'
            CHECK (requirement_type IN ('INITIAL', 'SPARE', 'REPLACEMENT')),
        note TEXT,
        created_at TEXT NOT NULL,
        CHECK (
            (assembly_id IS NOT NULL AND item_id IS NULL)
            OR (assembly_id IS NULL AND item_id IS NOT NULL)
        ),
        FOREIGN KEY (project_id) REFERENCES projects (project_id) ON DELETE CASCADE,
        FOREIGN KEY (assembly_id) REFERENCES assemblies (assembly_id),
        FOREIGN KEY (item_id) REFERENCES items_master (item_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS purchase_candidates (
        candidate_id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_type TEXT NOT NULL CHECK (source_type IN ('BOM', 'PROJECT')),
        project_id INTEGER,
        item_id INTEGER,
        supplier_name TEXT,
        ordered_item_number TEXT,
        canonical_item_number TEXT,
        required_quantity INTEGER NOT NULL CHECK (required_quantity >= 0),
        available_stock INTEGER NOT NULL CHECK (available_stock >= 0),
        shortage_quantity INTEGER NOT NULL CHECK (shortage_quantity >= 0),
        target_date TEXT,
        status TEXT NOT NULL DEFAULT 'OPEN'
            CHECK (status IN ('OPEN', 'ORDERING', 'ORDERED', 'CANCELLED')),
        note TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (project_id) REFERENCES projects (project_id) ON DELETE SET NULL,
        FOREIGN KEY (item_id) REFERENCES items_master (item_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS supplier_item_aliases (
        alias_id INTEGER PRIMARY KEY AUTOINCREMENT,
        supplier_id INTEGER NOT NULL,
        ordered_item_number TEXT NOT NULL CHECK (trim(ordered_item_number) <> ''),
        canonical_item_id INTEGER NOT NULL,
        units_per_order INTEGER NOT NULL CHECK (units_per_order > 0),
        created_at TEXT NOT NULL,
        UNIQUE (supplier_id, ordered_item_number),
        FOREIGN KEY (supplier_id) REFERENCES suppliers (supplier_id),
        FOREIGN KEY (canonical_item_id) REFERENCES items_master (item_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS category_aliases (
        alias_category TEXT PRIMARY KEY
            NOT NULL CHECK (trim(alias_category) <> ''),
        canonical_category TEXT NOT NULL CHECK (trim(canonical_category) <> ''),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        CHECK (alias_category <> canonical_category)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS import_jobs (
        import_job_id INTEGER PRIMARY KEY AUTOINCREMENT,
        import_type TEXT NOT NULL CHECK (import_type IN ('items')),
        source_name TEXT NOT NULL,
        source_content TEXT NOT NULL,
        continue_on_error INTEGER NOT NULL CHECK (continue_on_error IN (0, 1)),
        status TEXT NOT NULL DEFAULT 'ok'
            CHECK (status IN ('ok', 'partial', 'error')),
        processed INTEGER NOT NULL DEFAULT 0,
        created_count INTEGER NOT NULL DEFAULT 0,
        duplicate_count INTEGER NOT NULL DEFAULT 0,
        failed_count INTEGER NOT NULL DEFAULT 0,
        lifecycle_state TEXT NOT NULL DEFAULT 'active'
            CHECK (lifecycle_state IN ('active', 'undone')),
        created_at TEXT NOT NULL,
        undone_at TEXT,
        redo_of_job_id INTEGER,
        last_redo_job_id INTEGER,
        FOREIGN KEY (redo_of_job_id) REFERENCES import_jobs (import_job_id),
        FOREIGN KEY (last_redo_job_id) REFERENCES import_jobs (import_job_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS import_job_effects (
        effect_id INTEGER PRIMARY KEY AUTOINCREMENT,
        import_job_id INTEGER NOT NULL,
        row_number INTEGER NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('created', 'duplicate', 'error')),
        entry_type TEXT CHECK (entry_type IS NULL OR entry_type IN ('item', 'alias')),
        effect_type TEXT NOT NULL,
        item_id INTEGER,
        alias_id INTEGER,
        supplier_id INTEGER,
        item_number TEXT,
        supplier_name TEXT,
        canonical_item_number TEXT,
        units_per_order INTEGER,
        message TEXT,
        code TEXT,
        before_state TEXT,
        after_state TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY (import_job_id) REFERENCES import_jobs (import_job_id) ON DELETE CASCADE
    )
    """,
]

INDEX_STATEMENTS = [
    "CREATE INDEX IF NOT EXISTS idx_transaction_log_batch_id ON transaction_log (batch_id)",
    "CREATE INDEX IF NOT EXISTS idx_transaction_log_undo_of_log_id ON transaction_log (undo_of_log_id)",
    "CREATE INDEX IF NOT EXISTS idx_reservations_item_id ON reservations (item_id)",
    "CREATE INDEX IF NOT EXISTS idx_reservations_status ON reservations (status)",
    "CREATE INDEX IF NOT EXISTS idx_reservations_deadline ON reservations (deadline)",
    "CREATE INDEX IF NOT EXISTS idx_reservations_project_id ON reservations (project_id)",
    "CREATE INDEX IF NOT EXISTS idx_reservation_allocations_reservation_id ON reservation_allocations (reservation_id)",
    "CREATE INDEX IF NOT EXISTS idx_reservation_allocations_item_loc_status ON reservation_allocations (item_id, location, status)",
    "CREATE INDEX IF NOT EXISTS idx_assembly_components_item_id ON assembly_components (item_id)",
    "CREATE INDEX IF NOT EXISTS idx_location_assembly_usage_location ON location_assembly_usage (location)",
    "CREATE INDEX IF NOT EXISTS idx_location_assembly_usage_assembly_id ON location_assembly_usage (assembly_id)",
    "CREATE INDEX IF NOT EXISTS idx_projects_status ON projects (status)",
    "CREATE INDEX IF NOT EXISTS idx_projects_planned_start ON projects (planned_start)",
    "CREATE INDEX IF NOT EXISTS idx_project_requirements_project_id ON project_requirements (project_id)",
    "CREATE INDEX IF NOT EXISTS idx_project_requirements_assembly_id ON project_requirements (assembly_id)",
    "CREATE INDEX IF NOT EXISTS idx_project_requirements_item_id ON project_requirements (item_id)",
    "CREATE INDEX IF NOT EXISTS idx_purchase_candidates_status_target_date ON purchase_candidates (status, target_date)",
    "CREATE INDEX IF NOT EXISTS idx_purchase_candidates_source_type ON purchase_candidates (source_type)",
    "CREATE INDEX IF NOT EXISTS idx_purchase_candidates_project_id ON purchase_candidates (project_id)",
    "CREATE INDEX IF NOT EXISTS idx_purchase_candidates_item_id ON purchase_candidates (item_id)",
    "CREATE INDEX IF NOT EXISTS idx_orders_ordered_item_number ON orders (ordered_item_number)",
    "CREATE INDEX IF NOT EXISTS idx_orders_status_expected_arrival ON orders (status, expected_arrival)",
    "CREATE INDEX IF NOT EXISTS idx_orders_item_status_expected_arrival ON orders (item_id, status, expected_arrival)",
    "CREATE INDEX IF NOT EXISTS idx_order_lineage_events_source ON order_lineage_events (source_order_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_order_lineage_events_target ON order_lineage_events (target_order_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_order_lineage_events_type_created ON order_lineage_events (event_type, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_supplier_item_aliases_canonical_item_id ON supplier_item_aliases (canonical_item_id)",
    "CREATE INDEX IF NOT EXISTS idx_category_aliases_canonical_category ON category_aliases (canonical_category)",
    "CREATE INDEX IF NOT EXISTS idx_category_aliases_updated_at ON category_aliases (updated_at)",
    "CREATE INDEX IF NOT EXISTS idx_import_jobs_type_created_at ON import_jobs (import_type, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_import_jobs_redo_of_job_id ON import_jobs (redo_of_job_id)",
    "CREATE INDEX IF NOT EXISTS idx_import_job_effects_job_row ON import_job_effects (import_job_id, row_number, effect_id)",
]

TRIGGER_STATEMENTS = [
    """
    CREATE TRIGGER IF NOT EXISTS trg_orders_validate_insert
    BEFORE INSERT ON orders
    FOR EACH ROW
    BEGIN
        SELECT CASE
            WHEN NEW.status IS NOT NULL AND NEW.status NOT IN ('Ordered', 'Arrived')
            THEN RAISE(ABORT, 'invalid orders.status')
        END;
        SELECT CASE
            WHEN NEW.order_date IS NULL OR NEW.order_date = '' OR NEW.order_date NOT GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
            THEN RAISE(ABORT, 'invalid orders.order_date')
        END;
        SELECT CASE
            WHEN NEW.expected_arrival IS NOT NULL AND NEW.expected_arrival <> '' AND NEW.expected_arrival NOT GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
            THEN RAISE(ABORT, 'invalid orders.expected_arrival')
        END;
        SELECT CASE
            WHEN NEW.arrival_date IS NOT NULL AND NEW.arrival_date <> '' AND NEW.arrival_date NOT GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
            THEN RAISE(ABORT, 'invalid orders.arrival_date')
        END;
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS trg_orders_validate_update
    BEFORE UPDATE ON orders
    FOR EACH ROW
    BEGIN
        SELECT CASE
            WHEN NEW.status IS NOT NULL AND NEW.status NOT IN ('Ordered', 'Arrived')
            THEN RAISE(ABORT, 'invalid orders.status')
        END;
        SELECT CASE
            WHEN NEW.order_date IS NULL OR NEW.order_date = '' OR NEW.order_date NOT GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
            THEN RAISE(ABORT, 'invalid orders.order_date')
        END;
        SELECT CASE
            WHEN NEW.expected_arrival IS NOT NULL AND NEW.expected_arrival <> '' AND NEW.expected_arrival NOT GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
            THEN RAISE(ABORT, 'invalid orders.expected_arrival')
        END;
        SELECT CASE
            WHEN NEW.arrival_date IS NOT NULL AND NEW.arrival_date <> '' AND NEW.arrival_date NOT GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
            THEN RAISE(ABORT, 'invalid orders.arrival_date')
        END;
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS trg_orders_autofill_after_insert
    AFTER INSERT ON orders
    FOR EACH ROW
    BEGIN
        UPDATE orders
        SET status = COALESCE(NULLIF(status, ''), 'Ordered'),
            ordered_quantity = COALESCE(ordered_quantity, order_amount),
            ordered_item_number = COALESCE(
                NULLIF(ordered_item_number, ''),
                (SELECT item_number FROM items_master WHERE item_id = NEW.item_id)
            )
        WHERE order_id = NEW.order_id;
    END
    """,
]


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    if not _table_exists(conn, table):
        return False
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row["name"] == column for row in rows)


def _ensure_column(conn: sqlite3.Connection, table: str, definition: str) -> None:
    column = definition.split(" ", 1)[0]
    if not _column_exists(conn, table, column):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {definition}")


def _normalize_date_column(conn: sqlite3.Connection, table: str, column: str) -> None:
    if not _column_exists(conn, table, column):
        return
    rows = conn.execute(
        f"SELECT rowid, {column} AS value FROM {table} WHERE {column} IS NOT NULL AND trim({column}) <> ''"
    ).fetchall()
    for row in rows:
        value = row["value"]
        if value is None:
            continue
        if isinstance(value, str) and DATE_PATTERN.match(value.strip()):
            continue
        normalized = None
        try:
            normalized = normalize_optional_date(str(value), f"{table}.{column}")
        except Exception:  # noqa: BLE001
            normalized = None
        conn.execute(
            f"UPDATE {table} SET {column} = ? WHERE rowid = ?",
            (normalized, row["rowid"]),
        )


def _recreate_order_lineage_without_fk(conn: sqlite3.Connection) -> None:
    if not _table_exists(conn, "order_lineage_events"):
        return
    fk_rows = conn.execute("PRAGMA foreign_key_list(order_lineage_events)").fetchall()
    if not fk_rows:
        return
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS order_lineage_events_new (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL CHECK (event_type IN ('ETA_UPDATE', 'ETA_SPLIT', 'ETA_MERGE', 'ARRIVAL_SPLIT')),
            source_order_id INTEGER NOT NULL,
            target_order_id INTEGER,
            quantity INTEGER,
            previous_expected_arrival TEXT,
            new_expected_arrival TEXT,
            note TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        INSERT INTO order_lineage_events_new (
            event_id, event_type, source_order_id, target_order_id, quantity,
            previous_expected_arrival, new_expected_arrival, note, created_at
        )
        SELECT
            event_id, event_type, source_order_id, target_order_id, quantity,
            previous_expected_arrival, new_expected_arrival, note, created_at
        FROM order_lineage_events
        """
    )
    conn.execute("DROP TABLE order_lineage_events")
    conn.execute("ALTER TABLE order_lineage_events_new RENAME TO order_lineage_events")


def _apply_schema(conn: sqlite3.Connection) -> None:
    for statement in SCHEMA_STATEMENTS:
        conn.execute(statement)
    for statement in INDEX_STATEMENTS:
        conn.execute(statement)
    for statement in TRIGGER_STATEMENTS:
        conn.execute(statement)


def migrate_db(conn: sqlite3.Connection) -> None:
    # Keep migration idempotent so startup can run this each time.
    _apply_schema(conn)
    _recreate_order_lineage_without_fk(conn)
    for statement in INDEX_STATEMENTS:
        conn.execute(statement)
    for definition in (
        "ordered_quantity INTEGER",
        "ordered_item_number TEXT",
        "status TEXT",
        "expected_arrival TEXT",
        "arrival_date TEXT",
    ):
        _ensure_column(conn, "orders", definition)

    conn.execute(
        """
        UPDATE orders
        SET status = CASE
            WHEN status IS NULL OR trim(status) = '' THEN 'Ordered'
            WHEN lower(status) = 'arrived' THEN 'Arrived'
            ELSE 'Ordered'
        END
        """
    )
    conn.execute("UPDATE orders SET ordered_quantity = COALESCE(ordered_quantity, order_amount)")
    conn.execute(
        """
        UPDATE orders
        SET ordered_item_number = COALESCE(
            NULLIF(ordered_item_number, ''),
            (SELECT item_number FROM items_master WHERE items_master.item_id = orders.item_id)
        )
        """
    )
    _normalize_date_column(conn, "orders", "order_date")
    _normalize_date_column(conn, "orders", "expected_arrival")
    _normalize_date_column(conn, "orders", "arrival_date")
    _normalize_date_column(conn, "quotations", "issue_date")
    _normalize_date_column(conn, "projects", "planned_start")
    _normalize_date_column(conn, "reservations", "deadline")
    _normalize_date_column(conn, "purchase_candidates", "target_date")

    conn.commit()


def init_db(db_path: str | None = None) -> Path:
    ensure_workspace_layout()
    resolved = resolve_db_path(db_path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    conn = get_connection(str(resolved))
    try:
        migrate_db(conn)
    finally:
        conn.close()
    return resolved


def get_connection(db_path: str | None = None) -> sqlite3.Connection:
    resolved = resolve_db_path(db_path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    # FastAPI may execute dependency setup and endpoint body on different worker threads.
    conn = sqlite3.connect(resolved, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    try:
        conn.execute("BEGIN")
        yield conn
    except Exception:
        conn.rollback()
        raise
    else:
        conn.commit()
