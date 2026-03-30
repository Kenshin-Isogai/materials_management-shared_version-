from __future__ import annotations


def test_init_db_creates_users_and_orders_schema(conn):
    users_row = conn.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'users' AND column_name = 'username'
        """
    ).fetchone()
    oidc_email_row = conn.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'users' AND column_name = 'email'
        """
    ).fetchone()
    order_audit_row = conn.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'orders' AND column_name = 'created_by'
        """
    ).fetchone()
    purchase_order_header_row = conn.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'purchase_orders' AND column_name = 'purchase_order_document_url'
        """
    ).fetchone()
    order_purchase_order_fk_row = conn.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'orders' AND column_name = 'purchase_order_id'
        """
    ).fetchone()

    assert users_row is not None
    assert oidc_email_row is not None
    assert order_audit_row is not None
    assert purchase_order_header_row is not None
    assert order_purchase_order_fk_row is not None
