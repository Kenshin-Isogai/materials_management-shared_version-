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

    assert users_row is not None
    assert oidc_email_row is not None
    assert order_audit_row is not None
