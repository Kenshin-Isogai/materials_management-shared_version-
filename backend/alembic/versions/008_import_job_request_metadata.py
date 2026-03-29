from __future__ import annotations

from alembic import op


revision = "008_import_job_request_metadata"
down_revision = "007_remove_legacy_batch"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql(
        "ALTER TABLE import_jobs ADD COLUMN IF NOT EXISTS request_metadata TEXT"
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql(
        "ALTER TABLE import_jobs DROP COLUMN IF EXISTS request_metadata"
    )
