from __future__ import annotations

from alembic import op


revision = "007_remove_legacy_order_batch_support"
down_revision = "006_drop_quotation_pdf_link"
branch_labels = None
depends_on = None


def upgrade() -> None:
    statements = [
        "DELETE FROM import_job_effects WHERE import_job_id IN (SELECT import_job_id FROM import_jobs WHERE import_type = 'orders_legacy_batch')",
        "DROP TABLE IF EXISTS legacy_batch_staged_files",
        "DELETE FROM import_jobs WHERE import_type = 'orders_legacy_batch'",
        "ALTER TABLE import_jobs DROP CONSTRAINT IF EXISTS import_jobs_import_type_check",
        "ALTER TABLE import_jobs ADD CONSTRAINT import_jobs_import_type_check CHECK (import_type IN ('items', 'orders'))",
    ]
    bind = op.get_bind()
    for statement in statements:
        bind.exec_driver_sql(statement)


def downgrade() -> None:
    statements = [
        "ALTER TABLE import_jobs DROP CONSTRAINT IF EXISTS import_jobs_import_type_check",
        "ALTER TABLE import_jobs ADD CONSTRAINT import_jobs_import_type_check CHECK (import_type IN ('items', 'orders', 'orders_legacy_batch'))",
        """
        CREATE TABLE IF NOT EXISTS legacy_batch_staged_files (
            staged_file_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            import_job_id INTEGER NOT NULL REFERENCES import_jobs (import_job_id) ON DELETE CASCADE,
            file_role TEXT NOT NULL CHECK (file_role IN ('archive', 'csv', 'pdf')),
            supplier_name TEXT,
            original_path TEXT NOT NULL,
            storage_path TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'staged' CHECK (status IN ('staged', 'processed', 'missing_items', 'error', 'moved')),
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_legacy_batch_staged_files_job_role ON legacy_batch_staged_files (import_job_id, file_role, staged_file_id)",
    ]
    bind = op.get_bind()
    for statement in statements:
        bind.exec_driver_sql(statement)
