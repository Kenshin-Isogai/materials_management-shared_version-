from __future__ import annotations

import sqlite3
from pathlib import Path

from app.db import migrate_db


def test_migrate_backfills_project_id_manual_for_legacy_orders(tmp_path: Path):
    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(
            """
            CREATE TABLE projects (
                project_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                description TEXT,
                status TEXT NOT NULL,
                planned_start TEXT,
                created_at TEXT,
                updated_at TEXT
            );

            CREATE TABLE quotations (
                quotation_id INTEGER PRIMARY KEY AUTOINCREMENT,
                supplier_id INTEGER NOT NULL,
                quotation_number TEXT NOT NULL
            );

            CREATE TABLE orders (
                order_id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id INTEGER NOT NULL,
                quotation_id INTEGER NOT NULL,
                project_id INTEGER,
                order_amount INTEGER NOT NULL,
                ordered_quantity INTEGER,
                ordered_item_number TEXT,
                order_date TEXT NOT NULL,
                expected_arrival TEXT,
                arrival_date TEXT,
                status TEXT
            );

            CREATE TABLE rfq_batches (
                rfq_id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL,
                target_date TEXT,
                note TEXT,
                created_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE rfq_lines (
                line_id INTEGER PRIMARY KEY AUTOINCREMENT,
                rfq_id INTEGER NOT NULL,
                item_id INTEGER NOT NULL,
                requested_quantity INTEGER NOT NULL,
                finalized_quantity INTEGER,
                quoted_supplier_id INTEGER,
                quoted_unit TEXT,
                lead_days INTEGER,
                expected_arrival TEXT,
                linked_order_id INTEGER,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT ''
            );
            """
        )

        conn.execute("INSERT INTO projects(name, status, planned_start, created_at, updated_at) VALUES ('PRJ-MIGRATION', 'PLANNING', '2099-01-01', '2099-01-01', '2099-01-01')")
        project_id = int(conn.execute("SELECT project_id FROM projects").fetchone()[0])
        conn.execute(
            "INSERT INTO quotations(supplier_id, quotation_number) VALUES (1, 'Q-MIGRATION')"
        )
        quotation_id = int(conn.execute("SELECT quotation_id FROM quotations").fetchone()[0])

        # Legacy manually-linked order (no RFQ ownership)
        conn.execute(
            """
            INSERT INTO orders (
                item_id, quotation_id, project_id, order_amount, ordered_quantity,
                ordered_item_number, order_date, expected_arrival, arrival_date, status
            ) VALUES (1, ?, ?, 5, 5, 'ITEM-MIGRATION', '2099-01-01', '2099-01-20', NULL, 'Ordered')
            """,
            (quotation_id, project_id),
        )
        manual_order_id = int(conn.execute("SELECT max(order_id) FROM orders").fetchone()[0])

        # RFQ-owned order should stay non-manual
        conn.execute(
            """
            INSERT INTO orders (
                item_id, quotation_id, project_id, order_amount, ordered_quantity,
                ordered_item_number, order_date, expected_arrival, arrival_date, status
            ) VALUES (1, ?, ?, 3, 3, 'ITEM-MIGRATION', '2099-01-01', '2099-01-15', NULL, 'Ordered')
            """,
            (quotation_id, project_id),
        )
        rfq_order_id = int(conn.execute("SELECT max(order_id) FROM orders").fetchone()[0])

        conn.execute("INSERT INTO rfq_batches(project_id, title, status, target_date, note, created_at, updated_at) VALUES (?, 'RFQ', 'OPEN', '2099-01-05', '', '2099-01-01', '2099-01-01')", (project_id,))
        rfq_id = int(conn.execute("SELECT rfq_id FROM rfq_batches").fetchone()[0])
        conn.execute(
            """
            INSERT INTO rfq_lines(
                rfq_id, item_id, requested_quantity, expected_arrival, linked_order_id, status, created_at, updated_at
            ) VALUES (?, 1, 3, '2099-01-15', ?, 'ORDERED', '2099-01-01', '2099-01-01')
            """,
            (rfq_id, rfq_order_id),
        )

        migrate_db(conn)

        manual_flag = conn.execute(
            "SELECT project_id_manual FROM orders WHERE order_id = ?",
            (manual_order_id,),
        ).fetchone()[0]
        rfq_flag = conn.execute(
            "SELECT project_id_manual FROM orders WHERE order_id = ?",
            (rfq_order_id,),
        ).fetchone()[0]

        assert int(manual_flag) == 1
        assert int(rfq_flag) == 0
    finally:
        conn.close()
