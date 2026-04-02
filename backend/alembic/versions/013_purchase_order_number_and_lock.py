from alembic import op


revision = "013_po_number_lock"
down_revision = "012_registration_requests"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    statements = [
        "ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS purchase_order_number TEXT",
        "ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS import_locked BOOLEAN NOT NULL DEFAULT TRUE",
        """
        ALTER TABLE purchase_orders
        ADD CONSTRAINT purchase_orders_purchase_order_number_nonblank
        CHECK (purchase_order_number IS NULL OR btrim(purchase_order_number) <> '')
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_purchase_orders_supplier_number
        ON purchase_orders (supplier_id, purchase_order_number)
        WHERE purchase_order_number IS NOT NULL
        """,
        "CREATE INDEX IF NOT EXISTS idx_purchase_orders_import_locked ON purchase_orders (supplier_id, import_locked)",
    ]
    for statement in statements:
        bind.exec_driver_sql(statement)
    bind.exec_driver_sql(
        """
        UPDATE purchase_orders
        SET import_locked = FALSE
        WHERE purchase_order_number IS NULL
        """
    )
    bind.exec_driver_sql(
        """
        UPDATE purchase_orders
        SET purchase_order_number = 'LEGACY-PO-' || purchase_order_id::text
        WHERE purchase_order_number IS NULL
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    statements = [
        "DROP INDEX IF EXISTS idx_purchase_orders_import_locked",
        "DROP INDEX IF EXISTS idx_purchase_orders_supplier_number",
        "ALTER TABLE purchase_orders DROP CONSTRAINT IF EXISTS purchase_orders_purchase_order_number_nonblank",
        "ALTER TABLE purchase_orders DROP COLUMN IF EXISTS import_locked",
        "ALTER TABLE purchase_orders DROP COLUMN IF EXISTS purchase_order_number",
    ]
    for statement in statements:
        bind.exec_driver_sql(statement)
