from alembic import op


revision = "011_po_line_naming_nullable_q"
down_revision = "010_purchase_orders_header"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    statements = [
        "ALTER TABLE orders ALTER COLUMN quotation_id DROP NOT NULL",
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = 'order_lineage_events'
                  AND column_name = 'source_order_id'
            ) THEN
                ALTER TABLE order_lineage_events RENAME COLUMN source_order_id TO source_purchase_order_line_id;
            END IF;
        END$$
        """,
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = 'order_lineage_events'
                  AND column_name = 'target_order_id'
            ) THEN
                ALTER TABLE order_lineage_events RENAME COLUMN target_order_id TO target_purchase_order_line_id;
            END IF;
        END$$
        """,
        "DROP INDEX IF EXISTS idx_order_lineage_events_source",
        "DROP INDEX IF EXISTS idx_order_lineage_events_target",
        "CREATE INDEX idx_order_lineage_events_source ON order_lineage_events (source_purchase_order_line_id, created_at)",
        "CREATE INDEX idx_order_lineage_events_target ON order_lineage_events (target_purchase_order_line_id, created_at)",
    ]
    for statement in statements:
        bind.exec_driver_sql(statement)


def downgrade() -> None:
    bind = op.get_bind()
    statements = [
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM orders WHERE quotation_id IS NULL) THEN
                RAISE EXCEPTION 'Cannot downgrade while orders.quotation_id contains NULL values';
            END IF;
        END$$
        """,
        "DROP INDEX IF EXISTS idx_order_lineage_events_source",
        "DROP INDEX IF EXISTS idx_order_lineage_events_target",
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = 'order_lineage_events'
                  AND column_name = 'source_purchase_order_line_id'
            ) THEN
                ALTER TABLE order_lineage_events RENAME COLUMN source_purchase_order_line_id TO source_order_id;
            END IF;
        END$$
        """,
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = 'order_lineage_events'
                  AND column_name = 'target_purchase_order_line_id'
            ) THEN
                ALTER TABLE order_lineage_events RENAME COLUMN target_purchase_order_line_id TO target_order_id;
            END IF;
        END$$
        """,
        "CREATE INDEX idx_order_lineage_events_source ON order_lineage_events (source_order_id, created_at)",
        "CREATE INDEX idx_order_lineage_events_target ON order_lineage_events (target_order_id, created_at)",
        "ALTER TABLE orders ALTER COLUMN quotation_id SET NOT NULL",
    ]
    for statement in statements:
        bind.exec_driver_sql(statement)
