from __future__ import annotations

from alembic import op


revision = "002_document_url_fields"
down_revision = "001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    statements = [
        "ALTER TABLE quotations ADD COLUMN quotation_document_url TEXT",
        "ALTER TABLE orders ADD COLUMN purchase_order_document_url TEXT",
    ]
    bind = op.get_bind()
    for statement in statements:
        bind.exec_driver_sql(statement)


def downgrade() -> None:
    statements = [
        "ALTER TABLE orders DROP COLUMN IF EXISTS purchase_order_document_url",
        "ALTER TABLE quotations DROP COLUMN IF EXISTS quotation_document_url",
    ]
    bind = op.get_bind()
    for statement in statements:
        bind.exec_driver_sql(statement)
