from alembic import op


revision = "016_res_incoming_alloc"
down_revision = "015_split_manual_conflicts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    statements = [
        """
        CREATE TABLE IF NOT EXISTS reservation_incoming_allocations (
            incoming_allocation_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            reservation_id INTEGER NOT NULL REFERENCES reservations (reservation_id) ON DELETE CASCADE,
            item_id INTEGER NOT NULL REFERENCES items_master (item_id),
            order_id INTEGER REFERENCES orders (order_id) ON DELETE SET NULL,
            quantity INTEGER NOT NULL CHECK (quantity > 0),
            status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'RELEASED', 'CONVERTED', 'SHORTAGE')),
            expected_arrival_snapshot DATE,
            target_location TEXT,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
            updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
            released_at TIMESTAMP WITHOUT TIME ZONE,
            note TEXT
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_reservation_incoming_allocations_reservation_id ON reservation_incoming_allocations (reservation_id)",
        "CREATE INDEX IF NOT EXISTS idx_reservation_incoming_allocations_order_status ON reservation_incoming_allocations (order_id, status)",
        "CREATE INDEX IF NOT EXISTS idx_reservation_incoming_allocations_item_status ON reservation_incoming_allocations (item_id, status)",
    ]
    for statement in statements:
        bind.exec_driver_sql(statement)


def downgrade() -> None:
    bind = op.get_bind()
    statements = [
        "DROP INDEX IF EXISTS idx_reservation_incoming_allocations_item_status",
        "DROP INDEX IF EXISTS idx_reservation_incoming_allocations_order_status",
        "DROP INDEX IF EXISTS idx_reservation_incoming_allocations_reservation_id",
        "DROP TABLE IF EXISTS reservation_incoming_allocations",
    ]
    for statement in statements:
        bind.exec_driver_sql(statement)
