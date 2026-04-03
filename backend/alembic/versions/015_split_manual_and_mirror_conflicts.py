from alembic import op


revision = "015_split_manual_conflicts"
down_revision = "014_external_sync_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    statements = [
        "ALTER TABLE local_order_splits ADD COLUMN IF NOT EXISTS is_manual_override BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE local_order_splits ADD COLUMN IF NOT EXISTS manual_override_fields TEXT",
        "ALTER TABLE local_order_splits ADD COLUMN IF NOT EXISTS last_manual_override_at TEXT",
        "ALTER TABLE external_item_mirrors ADD COLUMN IF NOT EXISTS conflict_code TEXT",
        "ALTER TABLE external_item_mirrors ADD COLUMN IF NOT EXISTS conflict_message TEXT",
        "ALTER TABLE external_item_mirrors ADD COLUMN IF NOT EXISTS conflict_detected_at TEXT",
        "ALTER TABLE external_order_mirrors ADD COLUMN IF NOT EXISTS conflict_code TEXT",
        "ALTER TABLE external_order_mirrors ADD COLUMN IF NOT EXISTS conflict_message TEXT",
        "ALTER TABLE external_order_mirrors ADD COLUMN IF NOT EXISTS conflict_detected_at TEXT",
        "CREATE INDEX IF NOT EXISTS idx_external_item_mirrors_sync_state ON external_item_mirrors (sync_state)",
        "CREATE INDEX IF NOT EXISTS idx_external_order_mirrors_sync_state ON external_order_mirrors (sync_state)",
    ]
    for statement in statements:
        bind.exec_driver_sql(statement)


def downgrade() -> None:
    bind = op.get_bind()
    statements = [
        "DROP INDEX IF EXISTS idx_external_order_mirrors_sync_state",
        "DROP INDEX IF EXISTS idx_external_item_mirrors_sync_state",
        "ALTER TABLE external_order_mirrors DROP COLUMN IF EXISTS conflict_detected_at",
        "ALTER TABLE external_order_mirrors DROP COLUMN IF EXISTS conflict_message",
        "ALTER TABLE external_order_mirrors DROP COLUMN IF EXISTS conflict_code",
        "ALTER TABLE external_item_mirrors DROP COLUMN IF EXISTS conflict_detected_at",
        "ALTER TABLE external_item_mirrors DROP COLUMN IF EXISTS conflict_message",
        "ALTER TABLE external_item_mirrors DROP COLUMN IF EXISTS conflict_code",
        "ALTER TABLE local_order_splits DROP COLUMN IF EXISTS last_manual_override_at",
        "ALTER TABLE local_order_splits DROP COLUMN IF EXISTS manual_override_fields",
        "ALTER TABLE local_order_splits DROP COLUMN IF EXISTS is_manual_override",
    ]
    for statement in statements:
        bind.exec_driver_sql(statement)
