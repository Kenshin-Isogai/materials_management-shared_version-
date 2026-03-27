from __future__ import annotations

from alembic import op


revision = "004_generated_artifacts"
down_revision = "003_order_import_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    statements = [
        "ALTER TABLE import_jobs DROP CONSTRAINT IF EXISTS import_jobs_import_type_check",
        "ALTER TABLE import_jobs ADD CONSTRAINT import_jobs_import_type_check CHECK (import_type IN ('items', 'orders', 'orders_legacy_batch'))",
        """
        CREATE TABLE generated_artifacts (
            artifact_id TEXT PRIMARY KEY,
            artifact_type TEXT NOT NULL,
            filename TEXT NOT NULL,
            storage_path TEXT NOT NULL,
            size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0),
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
            source_job_type TEXT,
            source_job_id TEXT
        )
        """,
        "CREATE INDEX idx_generated_artifacts_type_created ON generated_artifacts (artifact_type, created_at DESC)",
    ]
    bind = op.get_bind()
    for statement in statements:
        bind.exec_driver_sql(statement)


def downgrade() -> None:
    statements = [
        "DROP INDEX IF EXISTS idx_generated_artifacts_type_created",
        "DROP TABLE IF EXISTS generated_artifacts",
        "ALTER TABLE import_jobs DROP CONSTRAINT IF EXISTS import_jobs_import_type_check",
        "ALTER TABLE import_jobs ADD CONSTRAINT import_jobs_import_type_check CHECK (import_type IN ('items', 'orders'))",
    ]
    bind = op.get_bind()
    for statement in statements:
        bind.exec_driver_sql(statement)
