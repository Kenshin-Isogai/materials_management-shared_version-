from alembic import op


revision = "014_external_sync_foundation"
down_revision = "013_po_number_lock"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    statements = [
        "ALTER TABLE items_master ADD COLUMN IF NOT EXISTS source_system TEXT NOT NULL DEFAULT 'local'",
        "ALTER TABLE items_master ADD COLUMN IF NOT EXISTS external_item_id TEXT",
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_items_master_external_item_id
        ON items_master (external_item_id)
        WHERE external_item_id IS NOT NULL
        """,
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS source_system TEXT NOT NULL DEFAULT 'local'",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS external_order_id TEXT",
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_orders_external_order_id
        ON orders (external_order_id)
        WHERE external_order_id IS NOT NULL
        """,
        """
        CREATE TABLE IF NOT EXISTS external_item_mirrors (
            mirror_id SERIAL PRIMARY KEY,
            source_system TEXT NOT NULL,
            external_item_id TEXT NOT NULL,
            local_item_id INTEGER REFERENCES items_master(item_id) ON DELETE SET NULL,
            mirror_payload JSONB,
            sync_state TEXT NOT NULL DEFAULT 'pending',
            last_webhook_at TEXT,
            last_synced_at TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP::text
        )
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_external_item_mirrors_source_key
        ON external_item_mirrors (source_system, external_item_id)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_external_item_mirrors_local_item
        ON external_item_mirrors (local_item_id)
        """,
        """
        CREATE TABLE IF NOT EXISTS external_order_mirrors (
            mirror_id SERIAL PRIMARY KEY,
            source_system TEXT NOT NULL,
            external_order_id TEXT NOT NULL,
            local_order_id INTEGER REFERENCES orders(order_id) ON DELETE SET NULL,
            mirror_payload JSONB,
            sync_state TEXT NOT NULL DEFAULT 'pending',
            last_webhook_at TEXT,
            last_synced_at TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP::text
        )
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_external_order_mirrors_source_key
        ON external_order_mirrors (source_system, external_order_id)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_external_order_mirrors_local_order
        ON external_order_mirrors (local_order_id)
        """,
        """
        CREATE TABLE IF NOT EXISTS local_order_splits (
            split_id SERIAL PRIMARY KEY,
            split_type TEXT NOT NULL,
            root_order_id INTEGER NOT NULL REFERENCES orders(order_id) ON DELETE CASCADE,
            child_order_id INTEGER NOT NULL UNIQUE REFERENCES orders(order_id) ON DELETE CASCADE,
            split_quantity INTEGER NOT NULL CHECK (split_quantity > 0),
            root_expected_arrival TEXT,
            child_expected_arrival TEXT,
            reconciliation_mode TEXT NOT NULL DEFAULT 'propagate_external_changes',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP::text
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_local_order_splits_root_order
        ON local_order_splits (root_order_id)
        """,
    ]
    for statement in statements:
        bind.exec_driver_sql(statement)


def downgrade() -> None:
    bind = op.get_bind()
    statements = [
        "DROP INDEX IF EXISTS idx_local_order_splits_root_order",
        "DROP TABLE IF EXISTS local_order_splits",
        "DROP INDEX IF EXISTS idx_external_order_mirrors_local_order",
        "DROP INDEX IF EXISTS idx_external_order_mirrors_source_key",
        "DROP TABLE IF EXISTS external_order_mirrors",
        "DROP INDEX IF EXISTS idx_external_item_mirrors_local_item",
        "DROP INDEX IF EXISTS idx_external_item_mirrors_source_key",
        "DROP TABLE IF EXISTS external_item_mirrors",
        "DROP INDEX IF EXISTS idx_orders_external_order_id",
        "ALTER TABLE orders DROP COLUMN IF EXISTS external_order_id",
        "ALTER TABLE orders DROP COLUMN IF EXISTS source_system",
        "DROP INDEX IF EXISTS idx_items_master_external_item_id",
        "ALTER TABLE items_master DROP COLUMN IF EXISTS external_item_id",
        "ALTER TABLE items_master DROP COLUMN IF EXISTS source_system",
    ]
    for statement in statements:
        bind.exec_driver_sql(statement)
