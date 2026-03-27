from __future__ import annotations

from alembic import op


revision = "003_order_import_jobs"
down_revision = "002_document_url_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    statements = [
        "ALTER TABLE import_jobs DROP CONSTRAINT IF EXISTS import_jobs_import_type_check",
        "ALTER TABLE import_jobs ADD CONSTRAINT import_jobs_import_type_check CHECK (import_type IN ('items', 'orders'))",
    ]
    bind = op.get_bind()
    for statement in statements:
        bind.exec_driver_sql(statement)


def downgrade() -> None:
    statements = [
        "ALTER TABLE import_jobs DROP CONSTRAINT IF EXISTS import_jobs_import_type_check",
        "ALTER TABLE import_jobs ADD CONSTRAINT import_jobs_import_type_check CHECK (import_type IN ('items'))",
    ]
    bind = op.get_bind()
    for statement in statements:
        bind.exec_driver_sql(statement)
