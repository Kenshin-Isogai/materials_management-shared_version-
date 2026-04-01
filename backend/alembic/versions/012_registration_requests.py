from __future__ import annotations

from alembic import op


revision = "012_registration_requests"
down_revision = "011_purchase_order_line_naming_and_nullable_quotation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    statements = [
        """
        CREATE TABLE IF NOT EXISTS registration_requests (
            request_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            email TEXT NOT NULL,
            username TEXT NOT NULL,
            display_name TEXT NOT NULL,
            memo TEXT,
            requested_role TEXT NOT NULL DEFAULT 'viewer',
            identity_provider TEXT,
            external_subject TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            rejection_reason TEXT,
            reviewed_by_user_id INTEGER REFERENCES users (user_id),
            approved_user_id INTEGER REFERENCES users (user_id),
            reviewed_at TIMESTAMP WITHOUT TIME ZONE,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
            updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
            CONSTRAINT registration_requests_status_check CHECK (status IN ('pending', 'approved', 'rejected')),
            CONSTRAINT registration_requests_role_check CHECK (requested_role IN ('admin', 'operator', 'viewer'))
        )
        """,
        (
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_registration_requests_pending_email "
            "ON registration_requests (lower(email)) WHERE status = 'pending'"
        ),
        (
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_registration_requests_pending_username "
            "ON registration_requests (lower(username)) WHERE status = 'pending'"
        ),
        "CREATE INDEX IF NOT EXISTS idx_registration_requests_status_created_at ON registration_requests (status, created_at DESC)",
    ]
    for statement in statements:
        op.execute(statement)


def downgrade() -> None:
    statements = [
        "DROP INDEX IF EXISTS idx_registration_requests_status_created_at",
        "DROP INDEX IF EXISTS idx_registration_requests_pending_username",
        "DROP INDEX IF EXISTS idx_registration_requests_pending_email",
        "DROP TABLE IF EXISTS registration_requests",
    ]
    for statement in statements:
        op.execute(statement)
