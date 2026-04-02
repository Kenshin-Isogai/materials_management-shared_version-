from __future__ import annotations

import importlib.util
from pathlib import Path

from app.db import get_connection, init_db
from .conftest import _reset_database


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
    purchase_order_number_row = conn.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'purchase_orders' AND column_name = 'purchase_order_number'
        """
    ).fetchone()
    purchase_order_lock_row = conn.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'purchase_orders' AND column_name = 'import_locked'
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
    assert purchase_order_number_row is not None
    assert purchase_order_lock_row is not None
    assert order_purchase_order_fk_row is not None


def test_init_db_uses_explicit_database_url_even_when_env_differs(database_url: str, monkeypatch):
    _reset_database(database_url)
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://invalid:invalid@127.0.0.1:59999/invalid")

    init_db(database_url)
    conn = get_connection(database_url)
    try:
        users_row = conn.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'users' AND column_name = 'username'
            """
        ).fetchone()
    finally:
        conn.close()

    assert users_row is not None


def test_purchase_order_number_migration_backfills_legacy_headers(conn):
    conn.execute("DROP TABLE IF EXISTS orders CASCADE")
    conn.execute("DROP TABLE IF EXISTS purchase_orders CASCADE")
    conn.execute(
        """
        CREATE TABLE purchase_orders (
            purchase_order_id SERIAL PRIMARY KEY,
            supplier_id INTEGER NOT NULL REFERENCES suppliers(supplier_id),
            purchase_order_document_url TEXT
        )
        """
    )
    supplier_id = int(
        conn.execute(
            "INSERT INTO suppliers (name) VALUES (?) RETURNING supplier_id",
            ("LegacyPurchaseOrderSupplier",),
        ).fetchone()["supplier_id"]
    )
    conn.execute(
        """
        INSERT INTO purchase_orders (supplier_id, purchase_order_document_url)
        VALUES (?, ?), (?, ?)
        """,
        (
            supplier_id,
            "https://example.sharepoint.com/sites/procurement/legacy-one",
            supplier_id,
            "https://example.sharepoint.com/sites/procurement/legacy-two",
        ),
    )

    migration_path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "013_purchase_order_number_and_lock.py"
    )
    spec = importlib.util.spec_from_file_location("po_number_lock_migration", migration_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    class _OpProxy:
        def __init__(self, bind):
            self._bind = bind

        def get_bind(self):
            return self._bind

    module.op = _OpProxy(conn._connection)
    module.upgrade()
    conn.commit()

    rows = conn.execute(
        """
        SELECT purchase_order_id, purchase_order_number, import_locked
        FROM purchase_orders
        WHERE supplier_id = ?
        ORDER BY purchase_order_id
        """,
        (supplier_id,),
    ).fetchall()

    assert [str(row["purchase_order_number"]) for row in rows] == [
        f"LEGACY-PO-{int(rows[0]['purchase_order_id'])}",
        f"LEGACY-PO-{int(rows[1]['purchase_order_id'])}",
    ]
    assert [bool(row["import_locked"]) for row in rows] == [False, False]
