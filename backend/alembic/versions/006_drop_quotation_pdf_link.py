"""drop legacy quotation pdf_link column

Revision ID: 006_drop_quotation_pdf_link
Revises: 005_staged_batch_files
Create Date: 2026-03-27 23:59:00
"""

from __future__ import annotations

from alembic import op


revision = "006_drop_quotation_pdf_link"
down_revision = "005_staged_batch_files"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE quotations DROP COLUMN IF EXISTS pdf_link")


def downgrade() -> None:
    op.execute("ALTER TABLE quotations ADD COLUMN IF NOT EXISTS pdf_link TEXT")
