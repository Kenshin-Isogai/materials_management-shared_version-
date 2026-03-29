from __future__ import annotations

from alembic import op


revision = "009_oidc_user_identity"
down_revision = "008_import_job_request_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    statements = [
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS email TEXT",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS external_subject TEXT",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS identity_provider TEXT",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS hosted_domain TEXT",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_ci ON users (lower(email)) WHERE email IS NOT NULL",
        (
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_external_identity "
            "ON users (identity_provider, external_subject) "
            "WHERE identity_provider IS NOT NULL AND external_subject IS NOT NULL"
        ),
    ]
    for statement in statements:
        op.execute(statement)


def downgrade() -> None:
    statements = [
        "DROP INDEX IF EXISTS idx_users_external_identity",
        "DROP INDEX IF EXISTS idx_users_email_ci",
        "ALTER TABLE users DROP COLUMN IF EXISTS hosted_domain",
        "ALTER TABLE users DROP COLUMN IF EXISTS identity_provider",
        "ALTER TABLE users DROP COLUMN IF EXISTS external_subject",
        "ALTER TABLE users DROP COLUMN IF EXISTS email",
    ]
    for statement in statements:
        op.execute(statement)
