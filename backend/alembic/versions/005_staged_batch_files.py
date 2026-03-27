from __future__ import annotations

from alembic import op


revision = "005_staged_batch_files"
down_revision = "004_generated_artifacts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    statements = [
        """
        CREATE TABLE legacy_batch_staged_files (
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
        "CREATE INDEX idx_legacy_batch_staged_files_job_role ON legacy_batch_staged_files (import_job_id, file_role, staged_file_id)",
    ]
    bind = op.get_bind()
    for statement in statements:
        bind.exec_driver_sql(statement)


def downgrade() -> None:
    statements = [
        "DROP INDEX IF EXISTS idx_legacy_batch_staged_files_job_role",
        "DROP TABLE IF EXISTS legacy_batch_staged_files",
    ]
    bind = op.get_bind()
    for statement in statements:
        bind.exec_driver_sql(statement)
