from __future__ import annotations

import csv
from io import StringIO
from pathlib import Path
import threading

import pytest

from app.errors import AppError
from app import service
from app.db import get_connection

FUTURE_TARGET_DATE = "2999-12-31"

def _inventory_qty(conn, item_id: int, location: str) -> int:
    row = conn.execute(
        "SELECT quantity FROM inventory_ledger WHERE item_id = ? AND location = ?",
        (item_id, location),
    ).fetchone()
    return int(row["quantity"]) if row else 0

def _create_basic_item(conn, item_number: str = "ITEM-001") -> dict:
    manufacturer = service.create_manufacturer(conn, "TEST-MFG")
    item = service.create_item(
        conn,
        {
            "item_number": item_number,
            "manufacturer_id": manufacturer["manufacturer_id"],
            "category": "Lens",
        },
    )
    return item


def _make_orders_csv_bytes(rows: list[dict[str, str]]) -> bytes:
    output = StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "item_number",
            "quantity",
            "purchase_order_number",
            "quotation_number",
            "issue_date",
            "quotation_document_url",
            "purchase_order_document_url",
            "order_date",
            "expected_arrival",
        ],
    )
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return output.getvalue().encode("utf-8")

def test_move_and_undo_restores_quantities(conn):
    item = _create_basic_item(conn)
    service.adjust_inventory(
        conn,
        item_id=item["item_id"],
        quantity_delta=10,
        location="STOCK",
        note="seed",
    )
    move_log = service.move_inventory(
        conn,
        item_id=item["item_id"],
        quantity=4,
        from_location="STOCK",
        to_location="BENCH_A",
        note="test move",
    )
    undo_result = service.undo_transaction(conn, move_log["log_id"])
    conn.commit()

    assert undo_result["applied_quantity"] == 4
    assert _inventory_qty(conn, item["item_id"], "STOCK") == 10
    assert _inventory_qty(conn, item["item_id"], "BENCH_A") == 0


def test_order_import_job_tracks_undecodable_csv_failures(conn):
    def _raise_decode_error(_content: bytes) -> str:
        raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(service, "_decode_csv_bytes", _raise_decode_error)
    with pytest.raises(UnicodeDecodeError):
        service.import_orders_from_content_with_job(
            conn,
            supplier_name="SupplierBadEncoding",
            content=b"\xff",
            source_name="broken-orders.csv",
        )
    monkeypatch.undo()
    conn.commit()

    jobs, _ = service.list_order_import_jobs(conn)
    assert len(jobs) == 1
    assert jobs[0]["source_name"] == "broken-orders.csv"
    assert jobs[0]["status"] == "error"
    assert jobs[0]["failed_count"] == 1


def test_item_import_job_tracks_undecodable_csv_failures(conn):
    def _raise_decode_error(_content: bytes) -> str:
        raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(service, "_decode_csv_bytes", _raise_decode_error)
    with pytest.raises(UnicodeDecodeError):
        service.import_items_from_content_with_job(
            conn,
            content=b"\xff",
            source_name="broken-items.csv",
        )
    monkeypatch.undo()
    conn.commit()

    jobs, _ = service.list_items_import_jobs(conn)
    assert len(jobs) == 1
    assert jobs[0]["source_name"] == "broken-items.csv"
    assert jobs[0]["status"] == "error"
    assert jobs[0]["failed_count"] == 1


def test_order_import_job_rolls_back_partial_changes_on_unexpected_error(conn, monkeypatch: pytest.MonkeyPatch):
    content = _make_orders_csv_bytes(
        [
            {
                "item_number": "ROLLBACK-ITEM",
                "quantity": "1",
                "quotation_number": "Q-ROLLBACK-001",
                "issue_date": "2026-03-01",
                "quotation_document_url": "https://example.com/q-rollback-001",
                "purchase_order_document_url": "",
                "order_date": "2026-03-02",
                "expected_arrival": "2026-03-10",
            }
        ]
    )

    def _raise_after_side_effect(*args, **kwargs):
        conn.execute("INSERT INTO suppliers (name) VALUES (?)", ("SHOULD-ROLLBACK",))
        raise RuntimeError("boom")

    monkeypatch.setattr(service, "import_orders_from_content", _raise_after_side_effect)

    with pytest.raises(RuntimeError, match="boom"):
        service.import_orders_from_content_with_job(
            conn,
            supplier_name="SupplierRollback",
            content=content,
            source_name="rollback-orders.csv",
        )
    conn.commit()

    jobs, _ = service.list_order_import_jobs(conn)
    assert len(jobs) == 1
    assert jobs[0]["source_name"] == "rollback-orders.csv"
    assert jobs[0]["status"] == "error"
    assert jobs[0]["failed_count"] == 1

    rolled_back = conn.execute(
        "SELECT supplier_id FROM suppliers WHERE name = ?",
        ("SHOULD-ROLLBACK",),
    ).fetchone()
    assert rolled_back is None


def test_update_user_rejects_invalid_role(conn):
    user = service.create_user(
        conn,
        {
            "username": "role-check-user",
            "display_name": "Role Check User",
            "email": "role-check-user@example.test",
            "external_subject": "sub-role-check-user",
            "identity_provider": "test-oidc",
            "hosted_domain": "example.test",
            "role": "operator",
            "is_active": True,
        },
    )

    with pytest.raises(AppError) as exc_info:
        service.update_user(conn, user["user_id"], {"role": "superadmin"})

    assert exc_info.value.code == "INVALID_ROLE"


def test_create_registration_request_rejects_pending_email_and_username(conn):
    request = service.create_registration_request(
        conn,
        data={
            "username": "pending-user",
            "display_name": "Pending User",
            "requested_role": "viewer",
        },
        email="pending@example.test",
        external_subject="sub-pending",
        identity_provider="identity_platform",
    )

    with pytest.raises(AppError) as email_exc:
        service.create_registration_request(
            conn,
            data={
                "username": "other-user",
                "display_name": "Other User",
                "requested_role": "viewer",
            },
            email="pending@example.test",
            external_subject="sub-other",
            identity_provider="identity_platform",
        )
    assert email_exc.value.code == "REGISTRATION_REQUEST_PENDING"
    assert request["status"] == "pending"

    with pytest.raises(AppError) as username_exc:
        service.create_registration_request(
            conn,
            data={
                "username": "pending-user",
                "display_name": "Other User",
                "requested_role": "viewer",
            },
            email="other@example.test",
            external_subject="sub-other-2",
            identity_provider="identity_platform",
        )
    assert username_exc.value.code == "USERNAME_ALREADY_PENDING"


def test_approve_registration_request_creates_user_and_marks_request(conn):
    reviewer = service.create_user(
        conn,
        {
            "username": "review-admin",
            "display_name": "Review Admin",
            "email": "review-admin@example.test",
            "external_subject": "sub-review-admin",
            "identity_provider": "test-oidc",
            "hosted_domain": "example.test",
            "role": "admin",
            "is_active": True,
        },
    )
    request = service.create_registration_request(
        conn,
        data={
            "username": "applicant",
            "display_name": "Applicant",
            "requested_role": "operator",
            "memo": "Please approve",
        },
        email="applicant@example.test",
        external_subject="sub-applicant",
        identity_provider="identity_platform",
    )

    approved = service.approve_registration_request(
        conn,
        request["request_id"],
        reviewer_user_id=reviewer["user_id"],
        data={"role": "operator"},
    )

    assert approved["status"] == "approved"
    assert approved["reviewed_by_user_id"] == reviewer["user_id"]
    assert approved["approved_user_id"] is not None
    created_user = service.get_user(conn, int(approved["approved_user_id"]))
    assert created_user["email"] == "applicant@example.test"
    assert created_user["identity_provider"] == "identity_platform"
    assert created_user["external_subject"] == "sub-applicant"
    assert created_user["role"] == "operator"


def test_reject_registration_request_requires_reason_and_records_review_metadata(conn):
    reviewer = service.create_user(
        conn,
        {
            "username": "reject-admin",
            "display_name": "Reject Admin",
            "email": "reject-admin@example.test",
            "external_subject": "sub-reject-admin",
            "identity_provider": "test-oidc",
            "hosted_domain": "example.test",
            "role": "admin",
            "is_active": True,
        },
    )
    request = service.create_registration_request(
        conn,
        data={
            "username": "reject-me",
            "display_name": "Reject Me",
            "requested_role": "viewer",
        },
        email="reject-me@example.test",
        external_subject="sub-reject-me",
        identity_provider="identity_platform",
    )

    with pytest.raises(AppError) as exc_info:
        service.reject_registration_request(
            conn,
            request["request_id"],
            reviewer_user_id=reviewer["user_id"],
            rejection_reason="",
        )
    assert exc_info.value.code == "INVALID_FIELD"

    rejected = service.reject_registration_request(
        conn,
        request["request_id"],
        reviewer_user_id=reviewer["user_id"],
        rejection_reason="Need more context",
    )
    assert rejected["status"] == "rejected"
    assert rejected["rejection_reason"] == "Need more context"
    assert rejected["reviewed_by_user_id"] == reviewer["user_id"]
    assert rejected["reviewed_at"] is not None


def test_get_registration_status_handles_email_only_identity_lookup(conn):
    service.create_registration_request(
        conn,
        data={
            "username": "email-only",
            "display_name": "Email Only",
            "requested_role": "viewer",
        },
        email="email-only@example.test",
        external_subject=None,
        identity_provider=None,
    )

    status = service.get_registration_status(
        conn,
        email="email-only@example.test",
        external_subject=None,
        identity_provider=None,
        current_user=None,
    )

    assert status["state"] == "pending"
    assert status["request"] is not None
    assert status["request"]["email"] == "email-only@example.test"

def test_reservation_release_roundtrip(conn):
    item = _create_basic_item(conn, item_number="ITEM-RES-001")
    service.adjust_inventory(
        conn,
        item_id=item["item_id"],
        quantity_delta=8,
        location="STOCK",
        note="seed",
    )
    reservation = service.create_reservation(
        conn,
        {
            "item_id": item["item_id"],
            "quantity": 3,
            "purpose": "roundtrip",
        },
    )
    released = service.release_reservation(conn, reservation["reservation_id"])
    conn.commit()

    assert released["status"] == "RELEASED"
    assert _inventory_qty(conn, item["item_id"], "STOCK") == 8
    active_alloc = conn.execute(
        "SELECT COALESCE(SUM(quantity), 0) AS qty FROM reservation_allocations WHERE reservation_id = ? AND status = 'ACTIVE'",
        (reservation["reservation_id"],),
    ).fetchone()
    assert int(active_alloc["qty"]) == 0

def test_reservation_partial_release_keeps_active(conn):
    item = _create_basic_item(conn, item_number="ITEM-RES-PART-REL")
    service.adjust_inventory(
        conn,
        item_id=item["item_id"],
        quantity_delta=10,
        location="STOCK",
        note="seed",
    )
    reservation = service.create_reservation(
        conn,
        {
            "item_id": item["item_id"],
            "quantity": 6,
            "purpose": "partial-release",
        },
    )
    released = service.release_reservation(conn, reservation["reservation_id"], quantity=2)
    conn.commit()

    assert released["status"] == "ACTIVE"
    assert int(released["quantity"]) == 4
    assert _inventory_qty(conn, item["item_id"], "STOCK") == 10
    active_alloc = conn.execute(
        "SELECT COALESCE(SUM(quantity), 0) AS qty FROM reservation_allocations WHERE reservation_id = ? AND status = 'ACTIVE'",
        (reservation["reservation_id"],),
    ).fetchone()
    assert int(active_alloc["qty"]) == 4

def test_reservation_partial_consume_keeps_active(conn):
    item = _create_basic_item(conn, item_number="ITEM-RES-PART-CON")
    service.adjust_inventory(
        conn,
        item_id=item["item_id"],
        quantity_delta=10,
        location="STOCK",
        note="seed",
    )
    reservation = service.create_reservation(
        conn,
        {
            "item_id": item["item_id"],
            "quantity": 7,
            "purpose": "partial-consume",
        },
    )
    consumed = service.consume_reservation(conn, reservation["reservation_id"], quantity=3)
    conn.commit()

    assert consumed["status"] == "ACTIVE"
    assert int(consumed["quantity"]) == 4
    assert _inventory_qty(conn, item["item_id"], "STOCK") == 7
    active_alloc = conn.execute(
        "SELECT COALESCE(SUM(quantity), 0) AS qty FROM reservation_allocations WHERE reservation_id = ? AND status = 'ACTIVE'",
        (reservation["reservation_id"],),
    ).fetchone()
    assert int(active_alloc["qty"]) == 4


def test_reservation_release_undo_restores_active_allocations(conn):
    item = _create_basic_item(conn, item_number="ITEM-RES-UNDO-REL")
    service.adjust_inventory(
        conn,
        item_id=item["item_id"],
        quantity_delta=8,
        location="STOCK",
        note="seed",
    )
    reservation = service.create_reservation(
        conn,
        {
            "item_id": item["item_id"],
            "quantity": 5,
            "purpose": "undo-release",
        },
    )
    service.release_reservation(conn, reservation["reservation_id"], quantity=2)
    release_log = conn.execute(
        """
        SELECT log_id
        FROM transaction_log
        WHERE batch_id LIKE ?
        ORDER BY log_id DESC
        LIMIT 1
        """,
        (f"reservation-release-{reservation['reservation_id']}-%",),
    ).fetchone()

    undo_result = service.undo_transaction(conn, int(release_log["log_id"]))
    restored = service.get_reservation(conn, reservation["reservation_id"])
    conn.commit()

    assert undo_result["applied_quantity"] == 2
    assert restored["status"] == "ACTIVE"
    assert int(restored["quantity"]) == 5
    active_alloc = conn.execute(
        "SELECT COALESCE(SUM(quantity), 0) AS qty FROM reservation_allocations WHERE reservation_id = ? AND status = 'ACTIVE'",
        (reservation["reservation_id"],),
    ).fetchone()
    assert int(active_alloc["qty"]) == 5


def test_reservation_consume_undo_restores_original_location_and_allocation(conn):
    item = _create_basic_item(conn, item_number="ITEM-RES-UNDO-CON")
    service.adjust_inventory(
        conn,
        item_id=item["item_id"],
        quantity_delta=4,
        location="BENCH_A",
        note="seed bench",
    )
    reservation = service.create_reservation(
        conn,
        {
            "item_id": item["item_id"],
            "quantity": 3,
            "purpose": "undo-consume",
        },
    )
    service.consume_reservation(conn, reservation["reservation_id"], quantity=2)
    consume_log = conn.execute(
        """
        SELECT log_id
        FROM transaction_log
        WHERE batch_id LIKE ?
        ORDER BY log_id DESC
        LIMIT 1
        """,
        (f"reservation-consume-{reservation['reservation_id']}-%",),
    ).fetchone()

    undo_result = service.undo_transaction(conn, int(consume_log["log_id"]))
    restored = service.get_reservation(conn, reservation["reservation_id"])
    conn.commit()

    assert undo_result["applied_quantity"] == 2
    assert restored["status"] == "ACTIVE"
    assert int(restored["quantity"]) == 3
    assert _inventory_qty(conn, item["item_id"], "BENCH_A") == 4
    assert _inventory_qty(conn, item["item_id"], "STOCK") == 0
    active_alloc = conn.execute(
        """
        SELECT COALESCE(SUM(quantity), 0) AS qty
        FROM reservation_allocations
        WHERE reservation_id = ? AND status = 'ACTIVE' AND location = 'BENCH_A'
        """,
        (reservation["reservation_id"],),
    ).fetchone()
    assert int(active_alloc["qty"]) == 3


def test_concurrent_reservations_do_not_overallocate(conn, database_url: str):
    item = _create_basic_item(conn, item_number="ITEM-RES-CONCURRENT")
    service.adjust_inventory(
        conn,
        item_id=item["item_id"],
        quantity_delta=5,
        location="STOCK",
        note="seed concurrent reservation",
    )
    conn.commit()

    start = threading.Barrier(3)
    outcomes: list[tuple[str, str | int]] = []
    outcomes_lock = threading.Lock()

    def worker() -> None:
        worker_conn = get_connection(database_url)
        try:
            start.wait(timeout=5)
            try:
                reservation = service.create_reservation(
                    worker_conn,
                    {
                        "item_id": item["item_id"],
                        "quantity": 4,
                        "purpose": "concurrent reservation",
                    },
                )
                worker_conn.commit()
                outcome: tuple[str, str | int] = ("ok", int(reservation["reservation_id"]))
            except AppError as exc:
                worker_conn.rollback()
                outcome = ("error", exc.code)
            with outcomes_lock:
                outcomes.append(outcome)
        finally:
            worker_conn.close()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    start.wait(timeout=5)
    for thread in threads:
        thread.join(timeout=10)
        assert not thread.is_alive()

    assert len(outcomes) == 2
    assert sum(1 for status, _ in outcomes if status == "ok") == 1
    assert sum(1 for status, detail in outcomes if status == "error" and detail == "INSUFFICIENT_STOCK") == 1

    check_conn = get_connection(database_url)
    try:
        reservations = check_conn.execute(
            "SELECT COALESCE(SUM(quantity), 0) AS qty FROM reservations WHERE item_id = ? AND status = 'ACTIVE'",
            (item["item_id"],),
        ).fetchone()
        allocations = check_conn.execute(
            "SELECT COALESCE(SUM(quantity), 0) AS qty FROM reservation_allocations WHERE item_id = ? AND status = 'ACTIVE'",
            (item["item_id"],),
        ).fetchone()
        assert int(reservations["qty"]) == 4
        assert int(allocations["qty"]) == 4
    finally:
        check_conn.close()


def test_concurrent_inventory_adjust_creates_single_row_with_combined_quantity(conn, database_url: str):
    item = _create_basic_item(conn, item_number="ITEM-INV-CONCURRENT")
    conn.commit()

    start = threading.Barrier(3)
    errors: list[str] = []
    errors_lock = threading.Lock()

    def worker() -> None:
        worker_conn = get_connection(database_url)
        try:
            start.wait(timeout=5)
            try:
                service.adjust_inventory(
                    worker_conn,
                    item_id=item["item_id"],
                    quantity_delta=1,
                    location="BENCH_CONCURRENT",
                    note="concurrent adjust",
                )
                worker_conn.commit()
            except Exception as exc:  # noqa: BLE001
                worker_conn.rollback()
                with errors_lock:
                    errors.append(exc.__class__.__name__)
        finally:
            worker_conn.close()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    start.wait(timeout=5)
    for thread in threads:
        thread.join(timeout=10)
        assert not thread.is_alive()

    assert errors == []

    check_conn = get_connection(database_url)
    try:
        row = check_conn.execute(
            """
            SELECT COUNT(*) AS row_count, COALESCE(SUM(quantity), 0) AS total_qty
            FROM inventory_ledger
            WHERE item_id = ? AND location = ?
            """,
            (item["item_id"], "BENCH_CONCURRENT"),
        ).fetchone()
        assert int(row["row_count"]) == 1
        assert int(row["total_qty"]) == 2
    finally:
        check_conn.close()


def test_concurrent_inventory_moves_do_not_overspend_source(conn, database_url: str):
    item = _create_basic_item(conn, item_number="ITEM-MOVE-CONCURRENT")
    service.adjust_inventory(
        conn,
        item_id=item["item_id"],
        quantity_delta=5,
        location="STOCK",
        note="seed concurrent move",
    )
    conn.commit()

    start = threading.Barrier(3)
    outcomes: list[tuple[str, str | int]] = []
    outcomes_lock = threading.Lock()

    def worker() -> None:
        worker_conn = get_connection(database_url)
        try:
            start.wait(timeout=5)
            try:
                moved = service.move_inventory(
                    worker_conn,
                    item_id=item["item_id"],
                    quantity=4,
                    from_location="STOCK",
                    to_location="BENCH_MOVE",
                    note="concurrent move",
                )
                worker_conn.commit()
                outcome: tuple[str, str | int] = ("ok", int(moved["log_id"]))
            except AppError as exc:
                worker_conn.rollback()
                outcome = ("error", exc.code)
            with outcomes_lock:
                outcomes.append(outcome)
        finally:
            worker_conn.close()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    start.wait(timeout=5)
    for thread in threads:
        thread.join(timeout=10)
        assert not thread.is_alive()

    assert len(outcomes) == 2
    assert sum(1 for status, _ in outcomes if status == "ok") == 1
    assert sum(1 for status, detail in outcomes if status == "error" and detail == "INSUFFICIENT_STOCK") == 1

    check_conn = get_connection(database_url)
    try:
        assert _inventory_qty(check_conn, item["item_id"], "STOCK") == 1
        assert _inventory_qty(check_conn, item["item_id"], "BENCH_MOVE") == 4
    finally:
        check_conn.close()


def test_concurrent_order_arrival_is_applied_once(conn, database_url: str):
    item = _create_basic_item(conn, item_number="ITEM-ARRIVE-CONCURRENT")
    import_result = service.import_orders_from_content(
        conn,
        supplier_name="SupplierConcurrentArrival",
        content=(
            "item_number,quantity,quotation_number,issue_date,order_date,expected_arrival,quotation_document_url\n"
            f"{item['item_number']},3,Q-ARRIVE-CONCURRENT-001,2026-04-01,2026-04-01,2026-04-10,https://example.sharepoint.com/sites/procurement/Q-ARRIVE-CONCURRENT-001.pdf\n"
        ).encode("utf-8"),
        source_name="arrival_concurrent.csv",
    )
    order_id = int(import_result["order_ids"][0])
    conn.commit()

    start = threading.Barrier(3)
    outcomes: list[tuple[str, str | int]] = []
    outcomes_lock = threading.Lock()

    def worker() -> None:
        worker_conn = get_connection(database_url)
        try:
            start.wait(timeout=5)
            try:
                result = service.process_order_arrival(worker_conn, order_id=order_id)
                worker_conn.commit()
                outcome: tuple[str, str | int] = ("ok", int(result["arrived_quantity"]))
            except AppError as exc:
                worker_conn.rollback()
                outcome = ("error", exc.code)
            with outcomes_lock:
                outcomes.append(outcome)
        finally:
            worker_conn.close()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    start.wait(timeout=5)
    for thread in threads:
        thread.join(timeout=10)
        assert not thread.is_alive()

    assert len(outcomes) == 2
    assert sum(1 for status, _ in outcomes if status == "ok") == 1
    assert sum(1 for status, detail in outcomes if status == "error" and detail == "ORDER_ALREADY_ARRIVED") == 1

    check_conn = get_connection(database_url)
    try:
        order = service.get_order(check_conn, order_id)
        assert order["status"] == "Arrived"
        assert _inventory_qty(check_conn, item["item_id"], "STOCK") == 3
        arrival_logs = check_conn.execute(
            "SELECT COUNT(*) AS count FROM transaction_log WHERE batch_id = ?",
            (f"arrival-{order_id}",),
        ).fetchone()
        assert int(arrival_logs["count"]) == 1
    finally:
        check_conn.close()


def test_concurrent_reservation_release_only_one_full_release_applies(conn, database_url: str):
    item = _create_basic_item(conn, item_number="ITEM-REL-CONCURRENT")
    service.adjust_inventory(
        conn,
        item_id=item["item_id"],
        quantity_delta=6,
        location="STOCK",
        note="seed concurrent release",
    )
    reservation = service.create_reservation(
        conn,
        {
            "item_id": item["item_id"],
            "quantity": 4,
            "purpose": "concurrent release",
        },
    )
    conn.commit()

    start = threading.Barrier(3)
    outcomes: list[tuple[str, str]] = []
    outcomes_lock = threading.Lock()

    def worker() -> None:
        worker_conn = get_connection(database_url)
        try:
            start.wait(timeout=5)
            try:
                service.release_reservation(worker_conn, reservation["reservation_id"], quantity=4)
                worker_conn.commit()
                outcome = ("ok", "released")
            except AppError as exc:
                worker_conn.rollback()
                outcome = ("error", exc.code)
            with outcomes_lock:
                outcomes.append(outcome)
        finally:
            worker_conn.close()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    start.wait(timeout=5)
    for thread in threads:
        thread.join(timeout=10)
        assert not thread.is_alive()

    assert len(outcomes) == 2
    assert sum(1 for status, _ in outcomes if status == "ok") == 1
    assert sum(1 for status, detail in outcomes if status == "error" and detail == "RESERVATION_NOT_ACTIVE") == 1

    check_conn = get_connection(database_url)
    try:
        restored = service.get_reservation(check_conn, reservation["reservation_id"])
        assert restored["status"] == "RELEASED"
        active_alloc = check_conn.execute(
            """
            SELECT COALESCE(SUM(quantity), 0) AS qty
            FROM reservation_allocations
            WHERE reservation_id = ? AND status = 'ACTIVE'
            """,
            (reservation["reservation_id"],),
        ).fetchone()
        assert int(active_alloc["qty"]) == 0
    finally:
        check_conn.close()


def test_concurrent_reservation_consume_only_one_full_consume_applies(conn, database_url: str):
    item = _create_basic_item(conn, item_number="ITEM-CONSUME-CONCURRENT")
    service.adjust_inventory(
        conn,
        item_id=item["item_id"],
        quantity_delta=6,
        location="STOCK",
        note="seed concurrent consume",
    )
    reservation = service.create_reservation(
        conn,
        {
            "item_id": item["item_id"],
            "quantity": 4,
            "purpose": "concurrent consume",
        },
    )
    conn.commit()

    start = threading.Barrier(3)
    outcomes: list[tuple[str, str]] = []
    outcomes_lock = threading.Lock()

    def worker() -> None:
        worker_conn = get_connection(database_url)
        try:
            start.wait(timeout=5)
            try:
                service.consume_reservation(worker_conn, reservation["reservation_id"], quantity=4)
                worker_conn.commit()
                outcome = ("ok", "consumed")
            except AppError as exc:
                worker_conn.rollback()
                outcome = ("error", exc.code)
            with outcomes_lock:
                outcomes.append(outcome)
        finally:
            worker_conn.close()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    start.wait(timeout=5)
    for thread in threads:
        thread.join(timeout=10)
        assert not thread.is_alive()

    assert len(outcomes) == 2
    assert sum(1 for status, _ in outcomes if status == "ok") == 1
    assert sum(1 for status, detail in outcomes if status == "error" and detail == "RESERVATION_NOT_ACTIVE") == 1

    check_conn = get_connection(database_url)
    try:
        consumed = service.get_reservation(check_conn, reservation["reservation_id"])
        assert consumed["status"] == "CONSUMED"
        assert _inventory_qty(check_conn, item["item_id"], "STOCK") == 2
    finally:
        check_conn.close()


def test_concurrent_undo_only_one_compensation_applies(conn, database_url: str):
    item = _create_basic_item(conn, item_number="ITEM-UNDO-CONCURRENT")
    service.adjust_inventory(
        conn,
        item_id=item["item_id"],
        quantity_delta=6,
        location="STOCK",
        note="seed undo concurrent",
    )
    move_log = service.move_inventory(
        conn,
        item_id=item["item_id"],
        quantity=4,
        from_location="STOCK",
        to_location="BENCH_UNDO",
        note="undo concurrency target",
    )
    conn.commit()

    start = threading.Barrier(3)
    outcomes: list[tuple[str, str | int]] = []
    outcomes_lock = threading.Lock()

    def worker() -> None:
        worker_conn = get_connection(database_url)
        try:
            start.wait(timeout=5)
            try:
                result = service.undo_transaction(worker_conn, move_log["log_id"])
                worker_conn.commit()
                outcome: tuple[str, str | int] = ("ok", int(result["applied_quantity"]))
            except AppError as exc:
                worker_conn.rollback()
                outcome = ("error", exc.code)
            with outcomes_lock:
                outcomes.append(outcome)
        finally:
            worker_conn.close()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    start.wait(timeout=5)
    for thread in threads:
        thread.join(timeout=10)
        assert not thread.is_alive()

    assert len(outcomes) == 2
    assert sum(1 for status, _ in outcomes if status == "ok") == 1
    assert sum(1 for status, detail in outcomes if status == "error" and detail == "ALREADY_UNDONE") == 1

    check_conn = get_connection(database_url)
    try:
        assert _inventory_qty(check_conn, item["item_id"], "STOCK") == 6
        assert _inventory_qty(check_conn, item["item_id"], "BENCH_UNDO") == 0
        undo_rows = check_conn.execute(
            "SELECT COUNT(*) AS count FROM transaction_log WHERE undo_of_log_id = ?",
            (move_log["log_id"],),
        ).fetchone()
        assert int(undo_rows["count"]) == 1
    finally:
        check_conn.close()


def test_operational_integrity_summary_detects_reservation_allocation_mismatch(conn):
    item = _create_basic_item(conn, item_number="ITEM-INTEGRITY-SUMMARY")
    service.adjust_inventory(
        conn,
        item_id=item["item_id"],
        quantity_delta=5,
        location="STOCK",
        note="seed integrity summary",
    )
    reservation = service.create_reservation(
        conn,
        {
            "item_id": item["item_id"],
            "quantity": 4,
            "purpose": "integrity summary",
        },
    )
    conn.execute(
        "UPDATE reservation_allocations SET quantity = 2 WHERE reservation_id = ? AND status = 'ACTIVE'",
        (reservation["reservation_id"],),
    )

    summary = service.get_operational_integrity_summary(conn)

    assert summary["ok"] is False
    assert summary["checks"]["active_reservation_quantity_mismatches"] == 1
    assert summary["checks"]["duplicate_undo_logs"] == 0

def test_reservation_partial_quantity_cannot_exceed_remaining(conn):
    item = _create_basic_item(conn, item_number="ITEM-RES-PART-ERR")
    service.adjust_inventory(
        conn,
        item_id=item["item_id"],
        quantity_delta=5,
        location="STOCK",
        note="seed",
    )
    reservation = service.create_reservation(
        conn,
        {
            "item_id": item["item_id"],
            "quantity": 2,
            "purpose": "partial-error",
        },
    )

    with pytest.raises(AppError) as exc_info:
        service.release_reservation(conn, reservation["reservation_id"], quantity=3)

    assert exc_info.value.code == "INVALID_RESERVATION_QUANTITY"

def test_release_reservation_fails_when_active_allocations_missing(conn):
    item = _create_basic_item(conn, item_number="ITEM-RES-INCONS-REL")
    service.adjust_inventory(
        conn,
        item_id=item["item_id"],
        quantity_delta=5,
        location="STOCK",
        note="seed",
    )
    reservation = service.create_reservation(
        conn,
        {
            "item_id": item["item_id"],
            "quantity": 4,
            "purpose": "allocation-mismatch-release",
        },
    )
    conn.execute(
        "UPDATE reservation_allocations SET status = 'RELEASED', released_at = ? WHERE reservation_id = ?",
        (service.now_jst_iso(), reservation["reservation_id"]),
    )

    with pytest.raises(AppError) as exc_info:
        service.release_reservation(conn, reservation["reservation_id"], quantity=2)

    assert exc_info.value.code == "RESERVATION_ALLOCATION_INCONSISTENT"

def test_consume_reservation_fails_when_active_allocations_missing(conn):
    item = _create_basic_item(conn, item_number="ITEM-RES-INCONS-CON")
    service.adjust_inventory(
        conn,
        item_id=item["item_id"],
        quantity_delta=6,
        location="STOCK",
        note="seed",
    )
    reservation = service.create_reservation(
        conn,
        {
            "item_id": item["item_id"],
            "quantity": 5,
            "purpose": "allocation-mismatch-consume",
        },
    )
    conn.execute(
        "UPDATE reservation_allocations SET status = 'CONSUMED', released_at = ? WHERE reservation_id = ?",
        (service.now_jst_iso(), reservation["reservation_id"]),
    )

    with pytest.raises(AppError) as exc_info:
        service.consume_reservation(conn, reservation["reservation_id"], quantity=3)

    assert exc_info.value.code == "RESERVATION_ALLOCATION_INCONSISTENT"

def test_arrival_undo_is_limited_by_stock_when_other_locations_have_inventory(conn):
    item = _create_basic_item(conn, item_number="ITEM-UNDO-ARRIVAL-STOCK")
    arrival_log = service.adjust_inventory(
        conn,
        item_id=item["item_id"],
        quantity_delta=10,
        location="STOCK",
        note="arrival baseline",
    )
    service.move_inventory(
        conn,
        item_id=item["item_id"],
        quantity=8,
        from_location="STOCK",
        to_location="BENCH_A",
        note="move away from stock",
    )

    undo_result = service.undo_transaction(conn, arrival_log["log_id"])
    conn.commit()

    assert undo_result["applied_quantity"] == 2
    assert _inventory_qty(conn, item["item_id"], "STOCK") == 0
    assert _inventory_qty(conn, item["item_id"], "BENCH_A") == 8

def test_item_flow_ignores_allocation_only_reserve_logs(conn):
    item = _create_basic_item(conn, item_number="ITEM-FLOW-RESERVE")
    service.adjust_inventory(
        conn,
        item_id=item["item_id"],
        quantity_delta=10,
        location="STOCK",
        note="seed",
    )
    reservation = service.create_reservation(
        conn,
        {
            "item_id": item["item_id"],
            "quantity": 4,
            "purpose": "flow check",
        },
    )
    service.release_reservation(conn, reservation["reservation_id"])

    timeline = service.get_item_flow_timeline(conn, item["item_id"])
    transaction_events = [
        event for event in timeline["events"] if event["source_type"] == "transaction"
    ]

    assert [event["delta"] for event in transaction_events] == [10]

def test_upsert_supplier_item_alias_by_name_creates_supplier_when_missing(conn):
    manufacturer = service.create_manufacturer(conn, "MFG-SERVICE-ALIAS")
    item = service.create_item(
        conn,
        {
            "item_number": "SERVICE-ALIAS-CANONICAL-001",
            "manufacturer_id": manufacturer["manufacturer_id"],
            "category": "Lens",
        },
    )

    result = service.upsert_supplier_item_alias_by_name(
        conn,
        supplier_name="ServiceAliasSupplier",
        ordered_item_number="SERVICE-ALIAS-ORDERED-001",
        canonical_item_number=item["item_number"],
        units_per_order=3,
    )

    assert result["supplier_name"] == "ServiceAliasSupplier"
    assert result["ordered_item_number"] == "SERVICE-ALIAS-ORDERED-001"
    assert result["canonical_item_number"] == item["item_number"]
    assert result["units_per_order"] == 3

    suppliers = service.list_suppliers(conn)
    assert any(row["name"] == "ServiceAliasSupplier" for row in suppliers)

def test_import_orders_missing_items_csv_includes_manufacturer_column(conn, tmp_path: Path):
    supplier = service.create_supplier(conn, "SupplierA")
    rows = [
        {
            "item_number": "UNKNOWN-NEW-001",
            "quantity": "1",
            "quotation_number": "Q-MISS-001",
            "issue_date": "2026-03-02",
            "order_date": "2026-03-02",
            "expected_arrival": "",
            "quotation_document_url": "https://example.sharepoint.com/sites/procurement/placeholder.pdf",
        }
    ]

    result = service.import_orders_from_rows(
        conn,
        supplier_id=int(supplier["supplier_id"]),
        rows=rows,
        source_name="Q-MISS-001.csv",
        missing_output_dir=tmp_path,
    )

    assert result["status"] == "missing_items"
    with Path(result["missing_csv_path"]).open("r", encoding="utf-8", newline="") as fp:
        reader = csv.DictReader(fp)
        headers = list(reader.fieldnames or [])
        row = next(reader)
    assert "manufacturer_name" in headers
    assert row["manufacturer_name"] == ""

def test_import_orders_resolves_alias_with_case_insensitive_supplier_name(conn):
    supplier = service.create_supplier(conn, "SupplierAlias")
    manufacturer = service.create_manufacturer(conn, "MFG-ALIAS")
    item = service.create_item(
        conn,
        {
            "item_number": "ALIAS-CANONICAL-001",
            "manufacturer_id": manufacturer["manufacturer_id"],
            "category": "Lens",
        },
    )
    service.upsert_supplier_item_alias(
        conn,
        supplier_id=int(supplier["supplier_id"]),
        ordered_item_number="SUP-ALIAS-001",
        canonical_item_number=item["item_number"],
        units_per_order=3,
    )

    result = service.import_orders_from_rows(
        conn,
        supplier_name="supplieralias",
        rows=[
            {
                "item_number": "SUP-ALIAS-001",
                "quantity": "2",
                "quotation_number": "Q-ALIAS-001",
                "issue_date": "2026-03-02",
                "order_date": "2026-03-02",
                "expected_arrival": "",
                "quotation_document_url": "https://example.sharepoint.com/sites/procurement/placeholder.pdf",
            }
        ],
    )

    assert result["status"] == "ok"
    order = service.get_order(conn, int(result["order_ids"][0]))
    assert int(order["item_id"]) == int(item["item_id"])
    assert int(order["ordered_quantity"]) == 2
    assert int(order["order_amount"]) == 6

def test_upsert_supplier_item_alias_by_name_uses_case_insensitive_supplier_lookup(conn):
    supplier = service.create_supplier(conn, "SupplierCase")
    manufacturer = service.create_manufacturer(conn, "MFG-CASE")
    service.create_item(
        conn,
        {
            "item_number": "CASE-CANONICAL-001",
            "manufacturer_id": manufacturer["manufacturer_id"],
            "category": "Mirror",
        },
    )

    result = service.upsert_supplier_item_alias_by_name(
        conn,
        supplier_name="suppliercase",
        ordered_item_number="CASE-ALIAS-001",
        canonical_item_number="CASE-CANONICAL-001",
        units_per_order=2,
    )

    assert result["ordered_item_number"] == "CASE-ALIAS-001"
    aliases = service.list_supplier_item_aliases(conn, int(supplier["supplier_id"]))
    assert len(aliases) == 1
    assert aliases[0]["ordered_item_number"] == "CASE-ALIAS-001"

def test_upsert_supplier_item_alias_by_name_propagates_item_not_found(conn):
    with pytest.raises(AppError) as exc_info:
        service.upsert_supplier_item_alias_by_name(
            conn,
            supplier_name="SupplierFail",
            ordered_item_number="ALIAS-FAIL-001",
            canonical_item_number="DOES-NOT-EXIST",
            units_per_order=1,
        )

    assert exc_info.value.code == "ITEM_NOT_FOUND"
    assert exc_info.value.status_code == 404

def test_import_orders_resolves_alias_with_dash_variant_item_number(conn):
    supplier = service.create_supplier(conn, "SupplierDash")
    manufacturer = service.create_manufacturer(conn, "MFG-DASH")
    item = service.create_item(
        conn,
        {
            "item_number": "B1-E02",
            "manufacturer_id": manufacturer["manufacturer_id"],
            "category": "Lens",
        },
    )
    service.upsert_supplier_item_alias(
        conn,
        supplier_id=int(supplier["supplier_id"]),
        ordered_item_number="B1-E02-10",
        canonical_item_number="B1-E02",
        units_per_order=10,
    )

    result = service.import_orders_from_rows(
        conn,
        supplier_name="SupplierDash",
        rows=[
            {
                "item_number": "B1−E02−10",
                "quantity": "2",
                "quotation_number": "Q-DASH-001",
                "issue_date": "2026-03-02",
                "order_date": "2026-03-02",
                "expected_arrival": "",
                "quotation_document_url": "https://example.sharepoint.com/sites/procurement/placeholder.pdf",
            }
        ],
    )

    assert result["status"] == "ok"
    order = service.get_order(conn, int(result["order_ids"][0]))
    assert int(order["item_id"]) == int(item["item_id"])
    assert int(order["ordered_quantity"]) == 2
    assert int(order["order_amount"]) == 20


def test_import_orders_reuses_purchase_order_without_document_url(conn):
    supplier = service.create_supplier(conn, "SupplierNoPoUrlReuse")
    item = _create_basic_item(conn, item_number="ITEM-NO-PO-URL-REUSE")

    result = service.import_orders_from_rows(
        conn,
        supplier_id=int(supplier["supplier_id"]),
        rows=[
            {
                "item_number": item["item_number"],
                "quantity": "2",
                "purchase_order_number": "PO-NO-PO-URL-REUSE-001",
                "quotation_number": "Q-NO-PO-URL-001",
                "issue_date": "2026-03-02",
                "quotation_document_url": "https://example.sharepoint.com/sites/procurement/Q-NO-PO-URL-001.pdf",
                "purchase_order_document_url": "",
                "order_date": "2026-03-02",
                "expected_arrival": "2026-03-12",
            },
            {
                "item_number": item["item_number"],
                "quantity": "3",
                "purchase_order_number": "PO-NO-PO-URL-REUSE-001",
                "quotation_number": "Q-NO-PO-URL-002",
                "issue_date": "2026-03-03",
                "quotation_document_url": "https://example.sharepoint.com/sites/procurement/Q-NO-PO-URL-002.pdf",
                "purchase_order_document_url": "",
                "order_date": "2026-03-03",
                "expected_arrival": "2026-03-13",
            },
        ],
        source_name="reuse_purchase_order_without_url.csv",
    )

    assert result["status"] == "ok"
    first_order = service.get_order(conn, int(result["order_ids"][0]))
    second_order = service.get_order(conn, int(result["order_ids"][1]))
    assert int(first_order["purchase_order_id"]) == int(second_order["purchase_order_id"])

    purchase_order_count = conn.execute(
        "SELECT COUNT(*) AS c FROM purchase_orders WHERE supplier_id = ?",
        (int(supplier["supplier_id"]),),
    ).fetchone()
    assert int(purchase_order_count["c"]) == 1


def test_update_and_delete_quotation_use_db_as_source_of_truth(conn, tmp_path: Path, monkeypatch):
    item = _create_basic_item(conn, item_number="SYNC-ITEM-001")
    roots = service.build_roots(
        unregistered_root=tmp_path / "quotations" / "unregistered",
        registered_root=tmp_path / "quotations" / "registered",
    )
    service.ensure_roots(roots)

    csv_path = roots.registered_csv_root / "SupplierSync" / "Q-SYNC-001.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(
            fp,
            fieldnames=[
                "supplier",
                "item_number",
                "quantity",
                "quotation_number",
                "issue_date",
                "order_date",
                "expected_arrival",
                "quotation_document_url",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "supplier": "SupplierSync",
                "item_number": item["item_number"],
                "quantity": "3",
                "quotation_number": "Q-SYNC-001",
                "issue_date": "2026-03-01",
                "order_date": "2026-03-01",
                "expected_arrival": "2026-03-10",
                "quotation_document_url": "https://example.sharepoint.com/sites/procurement/Q-SYNC-001.pdf",
            }
        )

    import_result = service.import_orders_from_csv_path(
        conn,
        supplier_name="SupplierSync",
        csv_path=csv_path,
    )
    assert import_result["status"] == "ok"
    order_id = int(import_result["order_ids"][0])

    order = service.get_order(conn, order_id)
    updated = service.update_quotation(
        conn,
        int(order["quotation_id"]),
        {
            "issue_date": "2026-03-05",
            "quotation_document_url": "https://example.sharepoint.com/sites/procurement/Q-SYNC-001",
        },
    )
    assert updated["issue_date"] == "2026-03-05"
    assert updated["quotation_document_url"] == "https://example.sharepoint.com/sites/procurement/Q-SYNC-001"

    monkeypatch.setattr(
        service,
        "build_roots",
        lambda **_: (_ for _ in ()).throw(AssertionError("build_roots should not be used during quotation edits")),
    )
    with csv_path.open("r", encoding="utf-8", newline="") as fp:
        rows = list(csv.DictReader(fp))
    assert rows[0]["issue_date"] == "2026-03-01"
    assert rows[0]["quotation_document_url"] == "https://example.sharepoint.com/sites/procurement/Q-SYNC-001.pdf"

    delete_result = service.delete_quotation(conn, int(order["quotation_id"]))
    assert delete_result["deleted"] is True
    assert delete_result["csv_sync"]["enabled"] is False
    assert conn.execute("SELECT COUNT(*) AS c FROM orders").fetchone()["c"] == 0
    assert conn.execute("SELECT COUNT(*) AS c FROM quotations").fetchone()["c"] == 0

    with csv_path.open("r", encoding="utf-8", newline="") as fp:
        remaining_rows = list(csv.DictReader(fp))
    assert len(remaining_rows) == 1

def test_update_and_delete_order_leave_archived_csv_unchanged(conn, tmp_path: Path, monkeypatch):
    item = _create_basic_item(conn, item_number="SYNC-DUP-001")
    roots = service.build_roots(
        unregistered_root=tmp_path / "quotations" / "unregistered",
        registered_root=tmp_path / "quotations" / "registered",
    )
    service.ensure_roots(roots)

    csv_path = roots.registered_csv_root / "SupplierDup" / "Q-DUP-001.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(
            fp,
            fieldnames=[
                "supplier",
                "item_number",
                "quantity",
                "quotation_number",
                "issue_date",
                "order_date",
                "expected_arrival",
                "quotation_document_url",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "supplier": "SupplierDup",
                "item_number": item["item_number"],
                "quantity": "3",
                "quotation_number": "Q-DUP-001",
                "issue_date": "2026-04-01",
                "order_date": "2026-04-01",
                "expected_arrival": "2026-04-10",
                "quotation_document_url": "https://example.sharepoint.com/sites/procurement/Q-DUP-001.pdf",
            }
        )
        writer.writerow(
            {
                "supplier": "SupplierDup",
                "item_number": item["item_number"],
                "quantity": "5",
                "quotation_number": "Q-DUP-001",
                "issue_date": "2026-04-01",
                "order_date": "2026-04-01",
                "expected_arrival": "2026-04-11",
                "quotation_document_url": "https://example.sharepoint.com/sites/procurement/Q-DUP-001.pdf",
            }
        )

    import_result = service.import_orders_from_csv_path(
        conn,
        supplier_name="SupplierDup",
        csv_path=csv_path,
    )
    assert import_result["status"] == "ok"
    first_order_id = int(import_result["order_ids"][0])
    second_order_id = int(import_result["order_ids"][1])

    monkeypatch.setattr(
        service,
        "build_roots",
        lambda **_: (_ for _ in ()).throw(AssertionError("build_roots should not be used during order edits")),
    )
    service.update_order(conn, first_order_id, {"expected_arrival": "2026-04-20"})

    with csv_path.open("r", encoding="utf-8", newline="") as fp:
        rows_after_update = list(csv.DictReader(fp))
    assert rows_after_update[0]["expected_arrival"] == "2026-04-10"
    assert rows_after_update[1]["expected_arrival"] == "2026-04-11"

    delete_result = service.delete_order(conn, second_order_id)
    assert delete_result["csv_sync"]["enabled"] is False

    with csv_path.open("r", encoding="utf-8", newline="") as fp:
        rows_after_delete = list(csv.DictReader(fp))
    assert len(rows_after_delete) == 2
    assert rows_after_delete[0]["quantity"] == "3"
    assert rows_after_delete[1]["quantity"] == "5"

def test_update_order_can_split_partial_eta_without_archive_sync(conn, tmp_path: Path, monkeypatch):
    item = _create_basic_item(conn, item_number="SYNC-SPLIT-001")
    roots = service.build_roots(
        unregistered_root=tmp_path / "quotations" / "unregistered",
        registered_root=tmp_path / "quotations" / "registered",
    )
    service.ensure_roots(roots)

    csv_path = roots.registered_csv_root / "SupplierSplit" / "Q-SPLIT-001.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(
            fp,
            fieldnames=[
                "supplier",
                "item_number",
                "quantity",
                "quotation_number",
                "issue_date",
                "order_date",
                "expected_arrival",
                "quotation_document_url",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "supplier": "SupplierSplit",
                "item_number": item["item_number"],
                "quantity": "50",
                "quotation_number": "Q-SPLIT-001",
                "issue_date": "2026-04-01",
                "order_date": "2026-04-01",
                "expected_arrival": "2026-04-10",
                "quotation_document_url": "https://example.sharepoint.com/sites/procurement/Q-SPLIT-001.pdf",
            }
        )

    import_result = service.import_orders_from_csv_path(
        conn,
        supplier_name="SupplierSplit",
        csv_path=csv_path,
    )
    assert import_result["status"] == "ok"
    order_id = int(import_result["order_ids"][0])

    monkeypatch.setattr(
        service,
        "build_roots",
        lambda **_: (_ for _ in ()).throw(AssertionError("build_roots should not be used during order split")),
    )
    result = service.update_order(
        conn,
        order_id,
        {
            "expected_arrival": "2026-04-25",
            "split_quantity": 30,
        },
    )

    assert result["order_id"] == order_id
    assert result["updated_order"]["order_amount"] == 20
    assert result["updated_order"]["expected_arrival"] == "2026-04-10"
    assert result["created_order"]["order_amount"] == 30
    assert result["created_order"]["expected_arrival"] == "2026-04-25"
    assert result["created_order"]["is_split_child"] is True
    assert result["created_order"]["split_root_order_id"] == order_id
    split_row = conn.execute(
        """
        SELECT split_type, root_order_id, child_order_id, split_quantity, reconciliation_mode,
               is_manual_override, manual_override_fields
        FROM local_order_splits
        WHERE child_order_id = ?
        """,
        (int(result["split_order_id"]),),
    ).fetchone()
    assert split_row is not None
    assert split_row["split_type"] == "ETA_SPLIT"
    assert int(split_row["root_order_id"]) == order_id
    assert int(split_row["child_order_id"]) == int(result["split_order_id"])
    assert int(split_row["split_quantity"]) == 30
    assert split_row["reconciliation_mode"] == "propagate_external_changes"
    assert bool(split_row["is_manual_override"]) is True
    assert "expected_arrival" in str(split_row["manual_override_fields"])
    assert "quantity" in str(split_row["manual_override_fields"])
    assert result["created_order"]["split_manual_override_fields"] == ["expected_arrival", "quantity"]

    with csv_path.open("r", encoding="utf-8", newline="") as fp:
        rows_after_update = list(csv.DictReader(fp))
    assert len(rows_after_update) == 1
    assert rows_after_update[0]["quantity"] == "50"
    assert rows_after_update[0]["expected_arrival"] == "2026-04-10"


def test_update_order_marks_split_child_eta_edit_as_manual_override(conn):
    item = _create_basic_item(conn, item_number="SPLIT-MANUAL-ETA-001")
    imported = service.import_orders_from_rows(
        conn,
        supplier_name="SplitManualEtaSupplier",
        rows=[
            {
                "item_number": item["item_number"],
                "quantity": "10",
                "quotation_number": "Q-SPLIT-MANUAL-ETA-001",
                "issue_date": "2026-04-01",
                "order_date": "2026-04-01",
                "expected_arrival": "2026-04-10",
                "quotation_document_url": "https://example.sharepoint.com/sites/procurement/placeholder.pdf",
            }
        ],
        source_name="split_manual_eta.csv",
    )
    order_id = int(imported["order_ids"][0])
    split = service.update_order(
        conn,
        order_id,
        {
            "expected_arrival": "2026-04-20",
            "split_quantity": 4,
        },
    )
    child_order_id = int(split["split_order_id"])

    updated_child = service.update_order(
        conn,
        child_order_id,
        {
            "expected_arrival": "2026-04-22",
        },
    )
    assert updated_child["expected_arrival"] == "2026-04-22"

    split_row = conn.execute(
        """
        SELECT is_manual_override, manual_override_fields, last_manual_override_at
        FROM local_order_splits
        WHERE child_order_id = ?
        """,
        (child_order_id,),
    ).fetchone()
    assert split_row is not None
    assert bool(split_row["is_manual_override"]) is True
    assert "expected_arrival" in str(split_row["manual_override_fields"])
    assert split_row["last_manual_override_at"] is not None
    assert updated_child["split_manual_override_fields"] == ["expected_arrival", "quantity"]


def test_item_ownership_guard_raises_when_source_system_metadata_missing():
    with pytest.raises(AppError) as exc_info:
        service._assert_item_is_locally_managed({"item_id": 101})

    assert exc_info.value.code == "ITEM_SOURCE_SYSTEM_MISSING"
    assert exc_info.value.status_code == 500


def test_order_ownership_guard_raises_when_source_system_metadata_missing():
    with pytest.raises(AppError) as exc_info:
        service._assert_order_is_locally_managed({"order_id": 202})

    assert exc_info.value.code == "ORDER_SOURCE_SYSTEM_MISSING"
    assert exc_info.value.status_code == 500


def test_record_external_order_mirror_conflict_upserts_conflict_state(conn):
    item = _create_basic_item(conn, item_number="EXT-CONFLICT-ITEM-001")
    imported = service.import_orders_from_rows(
        conn,
        supplier_name="ExternalConflictSupplier",
        rows=[
            {
                "item_number": item["item_number"],
                "quantity": "5",
                "quotation_number": "Q-EXT-CONFLICT-001",
                "issue_date": "2026-04-01",
                "order_date": "2026-04-01",
                "expected_arrival": "2026-04-15",
                "quotation_document_url": "https://example.sharepoint.com/sites/procurement/placeholder.pdf",
            }
        ],
        source_name="external_conflict.csv",
    )
    order_id = int(imported["order_ids"][0])

    first = service.record_external_order_mirror_conflict(
        conn,
        source_system="purchasing",
        external_order_id="EXT-ORDER-001",
        local_order_id=order_id,
        conflict_code="ORDER_QUANTITY_CONFLICT",
        conflict_message="External quantity decrease could not be absorbed by local splits",
    )
    assert first["sync_state"] == "conflict"
    assert first["conflict_code"] == "ORDER_QUANTITY_CONFLICT"
    assert int(first["local_order_id"]) == order_id

    second = service.record_external_order_mirror_conflict(
        conn,
        source_system="purchasing",
        external_order_id="EXT-ORDER-001",
        conflict_code="ORDER_CANCEL_CONFLICT",
        conflict_message="External cancellation conflicts with local arrived quantity",
    )
    assert second["sync_state"] == "conflict"
    assert second["conflict_code"] == "ORDER_CANCEL_CONFLICT"
    assert second["conflict_message"] == "External cancellation conflicts with local arrived quantity"
    assert int(second["local_order_id"]) == order_id
    assert second["conflict_detected_at"] is not None


def test_update_order_rejects_manual_project_reassignment_for_ordered_rfq_link(conn):
    item = _create_basic_item(conn, item_number="ITEM-RFQ-ORDER-GUARD")
    owner_project = service.create_project(
        conn,
        {
            "name": "PROJ-RFQ-ORDER-GUARD-OWNER",
            "status": "PLANNING",
            "planned_start": FUTURE_TARGET_DATE,
            "requirements": [{"item_id": item["item_id"], "assembly_id": None, "quantity": 5}],
        },
    )
    other_project = service.create_project(
        conn,
        {
            "name": "PROJ-RFQ-ORDER-GUARD-OTHER",
            "status": "PLANNING",
            "planned_start": FUTURE_TARGET_DATE,
            "requirements": [{"item_id": item["item_id"], "assembly_id": None, "quantity": 1}],
        },
    )
    rfq = service.create_project_rfq_batch_from_analysis(
        conn,
        owner_project["project_id"],
        target_date=FUTURE_TARGET_DATE,
    )
    line_id = int(rfq["lines"][0]["line_id"])

    imported = service.import_orders_from_rows(
        conn,
        supplier_name="RFQ-ORDER-GUARD-SUP",
        rows=[
            {
                "item_number": item["item_number"],
                "quantity": "5",
                "quotation_number": "Q-RFQ-ORDER-GUARD-001",
                "issue_date": "2026-03-01",
                "order_date": "2026-03-02",
                "expected_arrival": FUTURE_TARGET_DATE,
                "quotation_document_url": "https://example.sharepoint.com/sites/procurement/placeholder.pdf",
            }
        ],
        source_name="rfq_order_guard.csv",
    )
    order_id = int(imported["order_ids"][0])

    service.update_rfq_line(
        conn,
        line_id,
        {
            "linked_purchase_order_line_id": order_id,
            "status": "ORDERED",
        },
    )

    unchanged = service.update_order(conn, order_id, {"project_id": owner_project["project_id"]})
    assert int(unchanged["project_id"]) == owner_project["project_id"]

    with pytest.raises(AppError) as other_exc:
        service.update_order(conn, order_id, {"project_id": other_project["project_id"]})
    assert other_exc.value.code == "ORDER_PROJECT_MANAGED_BY_RFQ"

    with pytest.raises(AppError) as clear_exc:
        service.update_order(conn, order_id, {"project_id": None})
    assert clear_exc.value.code == "ORDER_PROJECT_MANAGED_BY_RFQ"
    assert int(service.get_order(conn, order_id)["project_id"]) == owner_project["project_id"]


def test_merge_open_orders_records_lineage_without_archive_sync(conn, tmp_path: Path, monkeypatch):
    item = _create_basic_item(conn, item_number="SYNC-MERGE-001")
    roots = service.build_roots(
        unregistered_root=tmp_path / "quotations" / "unregistered",
        registered_root=tmp_path / "quotations" / "registered",
    )
    service.ensure_roots(roots)

    csv_path = roots.registered_csv_root / "SupplierMerge" / "Q-MERGE-001.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(
            fp,
            fieldnames=[
                "supplier",
                "item_number",
                "quantity",
                "quotation_number",
                "issue_date",
                "order_date",
                "expected_arrival",
                "quotation_document_url",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "supplier": "SupplierMerge",
                "item_number": item["item_number"],
                "quantity": "20",
                "quotation_number": "Q-MERGE-001",
                "issue_date": "2026-05-01",
                "order_date": "2026-05-01",
                "expected_arrival": "2026-05-20",
                "quotation_document_url": "https://example.sharepoint.com/sites/procurement/Q-MERGE-001.pdf",
            }
        )
        writer.writerow(
            {
                "supplier": "SupplierMerge",
                "item_number": item["item_number"],
                "quantity": "30",
                "quotation_number": "Q-MERGE-001",
                "issue_date": "2026-05-01",
                "order_date": "2026-05-01",
                "expected_arrival": "2026-05-25",
                "quotation_document_url": "https://example.sharepoint.com/sites/procurement/Q-MERGE-001.pdf",
            }
        )

    import_result = service.import_orders_from_csv_path(
        conn,
        supplier_name="SupplierMerge",
        csv_path=csv_path,
    )
    assert import_result["status"] == "ok"
    first_order_id = int(import_result["order_ids"][0])
    second_order_id = int(import_result["order_ids"][1])

    monkeypatch.setattr(
        service,
        "build_roots",
        lambda **_: (_ for _ in ()).throw(AssertionError("build_roots should not be used during order merge")),
    )
    merged = service.merge_open_orders(
        conn,
        source_purchase_order_line_id=first_order_id,
        target_purchase_order_line_id=second_order_id,
        expected_arrival="2026-05-30",
    )
    assert merged["merged"] is True
    assert merged["target_order"]["order_amount"] == 50
    assert merged["target_order"]["expected_arrival"] == "2026-05-30"

    lineage = service.list_order_lineage_events(conn, order_id=second_order_id)
    assert any(
        event["event_type"] == "ETA_MERGE"
        and int(event["source_purchase_order_line_id"]) == first_order_id
        and int(event["target_purchase_order_line_id"]) == second_order_id
        for event in lineage
    )

    with csv_path.open("r", encoding="utf-8", newline="") as fp:
        rows_after = list(csv.DictReader(fp))
    assert len(rows_after) == 2
    assert rows_after[0]["quantity"] == "20"
    assert rows_after[1]["quantity"] == "30"




def test_merge_open_orders_nonfirst_sibling_keeps_archived_csv_unchanged(conn, tmp_path: Path, monkeypatch):
    item = _create_basic_item(conn, item_number="SYNC-MERGE-ORDER-001")
    roots = service.build_roots(
        unregistered_root=tmp_path / "quotations" / "unregistered",
        registered_root=tmp_path / "quotations" / "registered",
    )
    service.ensure_roots(roots)

    csv_path = roots.registered_csv_root / "SupplierMergeOrder" / "Q-MERGE-ORDER-001.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(
            fp,
            fieldnames=[
                "supplier",
                "item_number",
                "quantity",
                "quotation_number",
                "issue_date",
                "order_date",
                "expected_arrival",
                "quotation_document_url",
            ],
        )
        writer.writeheader()
        writer.writerow({"supplier": "SupplierMergeOrder", "item_number": item["item_number"], "quantity": "10", "quotation_number": "Q-MERGE-ORDER-001", "issue_date": "2026-06-01", "order_date": "2026-06-01", "expected_arrival": "2026-06-10", "quotation_document_url": "https://example.sharepoint.com/sites/procurement/Q-MERGE-ORDER-001.pdf"})
        writer.writerow({"supplier": "SupplierMergeOrder", "item_number": item["item_number"], "quantity": "20", "quotation_number": "Q-MERGE-ORDER-001", "issue_date": "2026-06-01", "order_date": "2026-06-01", "expected_arrival": "2026-06-20", "quotation_document_url": "https://example.sharepoint.com/sites/procurement/Q-MERGE-ORDER-001.pdf"})
        writer.writerow({"supplier": "SupplierMergeOrder", "item_number": item["item_number"], "quantity": "30", "quotation_number": "Q-MERGE-ORDER-001", "issue_date": "2026-06-01", "order_date": "2026-06-01", "expected_arrival": "2026-06-30", "quotation_document_url": "https://example.sharepoint.com/sites/procurement/Q-MERGE-ORDER-001.pdf"})

    import_result = service.import_orders_from_csv_path(conn, supplier_name="SupplierMergeOrder", csv_path=csv_path)
    assert import_result["status"] == "ok"
    first_order_id, second_order_id, third_order_id = [int(v) for v in import_result["order_ids"]]

    monkeypatch.setattr(
        service,
        "build_roots",
        lambda **_: (_ for _ in ()).throw(AssertionError("build_roots should not be used during order merge")),
    )
    merged = service.merge_open_orders(
        conn,
        source_purchase_order_line_id=second_order_id,
        target_purchase_order_line_id=third_order_id,
        expected_arrival="2026-07-05",
    )
    assert merged["merged"] is True

    with csv_path.open("r", encoding="utf-8", newline="") as fp:
        rows_after = list(csv.DictReader(fp))

    assert len(rows_after) == 3
    assert rows_after[0]["quantity"] == "10"
    assert rows_after[0]["expected_arrival"] == "2026-06-10"
    assert rows_after[1]["quantity"] == "20"
    assert rows_after[1]["expected_arrival"] == "2026-06-20"
    assert rows_after[2]["quantity"] == "30"
    assert rows_after[2]["expected_arrival"] == "2026-06-30"
    assert conn.execute("SELECT COUNT(*) AS c FROM orders WHERE order_id = ?", (second_order_id,)).fetchone()["c"] == 0
    assert conn.execute("SELECT COUNT(*) AS c FROM orders WHERE order_id = ?", (first_order_id,)).fetchone()["c"] == 1
    assert conn.execute("SELECT COUNT(*) AS c FROM orders WHERE order_id = ?", (third_order_id,)).fetchone()["c"] == 1


def test_merge_open_orders_rejects_different_purchase_orders(conn):
    item = _create_basic_item(conn, item_number="SYNC-MERGE-PO-MISMATCH-001")
    imported = service.import_orders_from_rows(
        conn,
        supplier_name="SupplierMergePurchaseOrderMismatch",
        rows=[
            {
                "item_number": item["item_number"],
                "quantity": "10",
                "purchase_order_number": "PO-MERGE-PO-MISMATCH-001",
                "quotation_number": "Q-MERGE-PO-MISMATCH-001",
                "issue_date": "2026-06-01",
                "order_date": "2026-06-01",
                "expected_arrival": "2026-06-10",
                "quotation_document_url": "https://example.sharepoint.com/sites/procurement/Q-MERGE-PO-MISMATCH-001.pdf",
                "purchase_order_document_url": "https://example.sharepoint.com/sites/procurement/PO-MERGE-PO-MISMATCH-001.pdf",
            },
            {
                "item_number": item["item_number"],
                "quantity": "20",
                "purchase_order_number": "PO-MERGE-PO-MISMATCH-002",
                "quotation_number": "Q-MERGE-PO-MISMATCH-001",
                "issue_date": "2026-06-01",
                "order_date": "2026-06-01",
                "expected_arrival": "2026-06-20",
                "quotation_document_url": "https://example.sharepoint.com/sites/procurement/Q-MERGE-PO-MISMATCH-001.pdf",
                "purchase_order_document_url": "https://example.sharepoint.com/sites/procurement/PO-MERGE-PO-MISMATCH-002.pdf",
            },
        ],
        source_name="merge_purchase_order_mismatch.csv",
    )
    first_order_id, second_order_id = [int(v) for v in imported["order_ids"]]

    with pytest.raises(AppError) as exc_info:
        service.merge_open_orders(
            conn,
            source_purchase_order_line_id=first_order_id,
            target_purchase_order_line_id=second_order_id,
        )

    assert exc_info.value.code == "ORDER_MERGE_SCOPE_MISMATCH"
    assert "purchase_order_id" in exc_info.value.message


def test_split_order_keeps_archived_csv_unchanged(conn, tmp_path: Path, monkeypatch):
    item = _create_basic_item(conn, item_number="SYNC-SPLIT-ORDER-001")
    roots = service.build_roots(
        unregistered_root=tmp_path / "quotations" / "unregistered",
        registered_root=tmp_path / "quotations" / "registered",
    )
    service.ensure_roots(roots)

    csv_path = roots.registered_csv_root / "SupplierSplitOrder" / "Q-SPLIT-ORDER-001.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(
            fp,
            fieldnames=[
                "supplier",
                "item_number",
                "quantity",
                "quotation_number",
                "issue_date",
                "order_date",
                "expected_arrival",
                "quotation_document_url",
            ],
        )
        writer.writeheader()
        writer.writerow({"supplier": "SupplierSplitOrder", "item_number": item["item_number"], "quantity": "10", "quotation_number": "Q-SPLIT-ORDER-001", "issue_date": "2026-08-01", "order_date": "2026-08-01", "expected_arrival": "2026-08-10", "quotation_document_url": "https://example.sharepoint.com/sites/procurement/Q-SPLIT-ORDER-001.pdf"})
        writer.writerow({"supplier": "SupplierSplitOrder", "item_number": item["item_number"], "quantity": "10", "quotation_number": "Q-SPLIT-ORDER-001", "issue_date": "2026-08-01", "order_date": "2026-08-01", "expected_arrival": "2026-08-20", "quotation_document_url": "https://example.sharepoint.com/sites/procurement/Q-SPLIT-ORDER-001.pdf"})
        writer.writerow({"supplier": "SupplierSplitOrder", "item_number": item["item_number"], "quantity": "10", "quotation_number": "Q-SPLIT-ORDER-001", "issue_date": "2026-08-01", "order_date": "2026-08-01", "expected_arrival": "2026-08-30", "quotation_document_url": "https://example.sharepoint.com/sites/procurement/Q-SPLIT-ORDER-001.pdf"})

    import_result = service.import_orders_from_csv_path(conn, supplier_name="SupplierSplitOrder", csv_path=csv_path)
    assert import_result["status"] == "ok"
    _, second_order_id, _ = [int(v) for v in import_result["order_ids"]]

    monkeypatch.setattr(
        service,
        "build_roots",
        lambda **_: (_ for _ in ()).throw(AssertionError("build_roots should not be used during order split")),
    )
    service.update_order(
        conn,
        second_order_id,
        {
            "expected_arrival": "2026-09-05",
            "split_quantity": 4,
        },
    )

    with csv_path.open("r", encoding="utf-8", newline="") as fp:
        rows_after = list(csv.DictReader(fp))

    assert len(rows_after) == 3
    assert rows_after[0]["quantity"] == "10"
    assert rows_after[0]["expected_arrival"] == "2026-08-10"
    assert rows_after[1]["quantity"] == "10"
    assert rows_after[1]["expected_arrival"] == "2026-08-20"
    assert rows_after[2]["quantity"] == "10"
    assert rows_after[2]["expected_arrival"] == "2026-08-30"

def test_delete_quotation_rejects_if_any_linked_order_arrived(conn):
    item = _create_basic_item(conn, item_number="ARRIVE-GUARD-001")
    csv_content = "\n".join(
        [
            "item_number,quantity,quotation_number,issue_date,order_date,expected_arrival,quotation_document_url",
            f"{item['item_number']},2,Q-ARRIVE-001,2026-04-01,2026-04-01,2026-04-10,https://example.sharepoint.com/sites/procurement/Q-ARRIVE-001.pdf",
        ]
    )
    import_result = service.import_orders_from_content(
        conn,
        supplier_name="SupplierArriveGuard",
        content=csv_content.encode("utf-8"),
        source_name="arrived_guard.csv",
    )
    assert import_result["status"] == "ok"
    order_id = int(import_result["order_ids"][0])
    order = service.get_order(conn, order_id)
    conn.execute("UPDATE orders SET status = 'Arrived' WHERE order_id = ?", (order_id,))

    with pytest.raises(service.AppError, match="cannot be deleted") as excinfo:
        service.delete_quotation(conn, int(order["quotation_id"]))

    assert excinfo.value.code == "QUOTATION_HAS_ARRIVED_ORDERS"
    assert conn.execute("SELECT COUNT(*) AS c FROM quotations").fetchone()["c"] == 1
    assert conn.execute("SELECT COUNT(*) AS c FROM orders").fetchone()["c"] == 1

def test_import_inventory_movements_from_rows(conn):
    item = _create_basic_item(conn, item_number="ITEM-MOVE-CSV")
    service.adjust_inventory(conn, item_id=item["item_id"], quantity_delta=10, location="STOCK")

    result = service.import_inventory_movements_from_rows(
        conn,
        rows=[
            {
                "operation_type": "MOVE",
                "item_id": str(item["item_id"]),
                "quantity": "3",
                "from_location": "STOCK",
                "to_location": "BENCH_A",
                "note": "csv move",
            },
            {
                "operation_type": "CONSUME",
                "item_id": str(item["item_id"]),
                "quantity": "2",
                "from_location": "STOCK",
            },
        ],
    )
    conn.commit()

    assert len(result["operations"]) == 2
    assert _inventory_qty(conn, item["item_id"], "STOCK") == 5
    assert _inventory_qty(conn, item["item_id"], "BENCH_A") == 3

def test_import_inventory_movements_from_rows_rejects_non_numeric_fields(conn):
    item = _create_basic_item(conn, item_number="ITEM-MOVE-CSV-INVALID")

    with pytest.raises(service.AppError) as excinfo_qty:
        service.import_inventory_movements_from_rows(
            conn,
            rows=[
                {
                    "operation_type": "MOVE",
                    "item_id": str(item["item_id"]),
                    "quantity": "abc",
                    "from_location": "STOCK",
                    "to_location": "BENCH_A",
                }
            ],
        )

    assert excinfo_qty.value.status_code == 422
    assert excinfo_qty.value.code == "INVALID_QUANTITY"

    with pytest.raises(service.AppError) as excinfo_item:
        service.import_inventory_movements_from_rows(
            conn,
            rows=[
                {
                    "operation_type": "MOVE",
                    "item_id": "abc",
                    "quantity": "1",
                    "from_location": "STOCK",
                    "to_location": "BENCH_A",
                }
            ],
        )

    assert excinfo_item.value.status_code == 422
    assert excinfo_item.value.code == "INVALID_ITEM"

def test_import_reservations_from_rows_rejects_non_numeric_fields(conn):
    item = _create_basic_item(conn, item_number="ITEM-RES-CSV-INVALID")
    service.adjust_inventory(conn, item_id=item["item_id"], quantity_delta=20, location="STOCK")
    assembly = service.create_assembly(
        conn,
        {
            "name": "RES-CSV-ASM-INVALID",
            "components": [{"item_id": item["item_id"], "quantity": 2}],
        },
    )

    with pytest.raises(service.AppError) as excinfo_qty:
        service.import_reservations_from_rows(conn, rows=[{"item_id": str(item["item_id"]), "quantity": "abc"}])
    assert excinfo_qty.value.status_code == 422
    assert excinfo_qty.value.code == "INVALID_QUANTITY"

    with pytest.raises(service.AppError) as excinfo_project:
        service.import_reservations_from_rows(
            conn,
            rows=[{"item_id": str(item["item_id"]), "quantity": "1", "project_id": "abc"}],
        )
    assert excinfo_project.value.status_code == 422
    assert excinfo_project.value.code == "INVALID_PROJECT"

    with pytest.raises(service.AppError) as excinfo_item:
        service.import_reservations_from_rows(conn, rows=[{"item_id": "abc", "quantity": "1"}])
    assert excinfo_item.value.status_code == 422
    assert excinfo_item.value.code == "INVALID_ITEM"

    with pytest.raises(service.AppError) as excinfo_asm_qty:
        service.import_reservations_from_rows(
            conn,
            rows=[{"assembly": assembly["name"], "quantity": "1", "assembly_quantity": "abc"}],
        )
    assert excinfo_asm_qty.value.status_code == 422
    assert excinfo_asm_qty.value.code == "INVALID_QUANTITY"


def test_import_reservations_from_rows_with_assembly(conn):
    item = _create_basic_item(conn, item_number="ITEM-RES-CSV-A")
    service.adjust_inventory(conn, item_id=item["item_id"], quantity_delta=20, location="STOCK")
    assembly = service.create_assembly(
        conn,
        {
            "name": "RES-CSV-ASM",
            "components": [{"item_id": item["item_id"], "quantity": 2}],
        },
    )

    created = service.import_reservations_from_rows(
        conn,
        rows=[
            {
                "assembly": assembly["name"],
                "assembly_quantity": "3",
                "quantity": "2",
                "purpose": "csv assembly reserve",
            }
        ],
    )
    conn.commit()

    assert len(created) == 1
    assert int(created[0]["quantity"]) == 12
    assert created[0]["status"] == "ACTIVE"


def test_import_reservations_from_rows_assembly_override_wins_over_raw_item_id(conn):
    item = _create_basic_item(conn, item_number="ITEM-RES-CSV-OVERRIDE")
    service.adjust_inventory(conn, item_id=item["item_id"], quantity_delta=20, location="STOCK")
    assembly = service.create_assembly(
        conn,
        {
            "name": "RES-CSV-ASM-OVERRIDE",
            "components": [{"item_id": item["item_id"], "quantity": 2}],
        },
    )

    created = service.import_reservations_from_rows(
        conn,
        rows=[
            {
                "item_id": "999999",
                "quantity": "3",
                "assembly_quantity": "2",
                "purpose": "override to assembly",
            }
        ],
        row_overrides={"2": {"assembly_id": assembly["assembly_id"]}},
    )
    conn.commit()

    assert len(created) == 1
    assert created[0]["item_id"] == item["item_id"]
    assert int(created[0]["quantity"]) == 12
    assert created[0]["purpose"] == "override to assembly"


def test_analyze_bom_rows_target_date_includes_pending_arrivals(conn):
    item = _create_basic_item(conn, item_number="ITEM-BOM-DATE")
    service.adjust_inventory(conn, item_id=item["item_id"], quantity_delta=2, location="STOCK")
    service.import_orders_from_rows(
        conn,
        supplier_name="BOM-DATE-SUP",
        rows=[
            {
                "item_number": item["item_number"],
                "quantity": "5",
                "quotation_number": "QBOM-DATE-001",
                "issue_date": "2026-03-01",
                "order_date": "2026-03-02",
                "expected_arrival": "2026-03-20",
                "quotation_document_url": "https://example.sharepoint.com/sites/procurement/placeholder.pdf",
            }
        ],
        source_name="bom_date.csv",
    )

    without_date = service.analyze_bom_rows(
        conn,
        rows=[
            {
                "supplier": "BOM-DATE-SUP",
                "item_number": item["item_number"],
                "required_quantity": 6,
            }
        ],
    )
    with_date = service.analyze_bom_rows(
        conn,
        rows=[
            {
                "supplier": "BOM-DATE-SUP",
                "item_number": item["item_number"],
                "required_quantity": 6,
            }
        ],
        target_date=FUTURE_TARGET_DATE,
    )

    assert without_date["target_date"] is None
    assert int(without_date["rows"][0]["available_stock"]) == 2
    assert int(without_date["rows"][0]["shortage"]) == 4
    assert with_date["target_date"] == FUTURE_TARGET_DATE
    assert int(with_date["rows"][0]["available_stock"]) == 7
    assert int(with_date["rows"][0]["shortage"]) == 0


def test_analyze_bom_rows_rejects_past_target_date(conn):
    item = _create_basic_item(conn, item_number="ITEM-BOM-PAST-DATE")

    with pytest.raises(AppError) as exc_info:
        service.analyze_bom_rows(
            conn,
            rows=[
                {
                    "supplier": "BOM-PAST-SUP",
                    "item_number": item["item_number"],
                    "required_quantity": 1,
                }
            ],
            target_date="2000-01-01",
        )

    assert exc_info.value.code == "INVALID_TARGET_DATE"


def test_project_gap_analysis_target_date_includes_pending_arrivals(conn):
    item = _create_basic_item(conn, item_number="ITEM-PROJ-GAP-DATE")
    service.adjust_inventory(conn, item_id=item["item_id"], quantity_delta=2, location="STOCK")
    project = service.create_project(
        conn,
        {
            "name": "PROJ-GAP-DATE-001",
            "status": "PLANNING",
            "requirements": [
                {
                    "item_id": item["item_id"],
                    "assembly_id": None,
                    "quantity": 6,
                }
            ],
        },
    )
    service.import_orders_from_rows(
        conn,
        supplier_name="PROJ-GAP-SUP",
        rows=[
            {
                "item_number": item["item_number"],
                "quantity": "5",
                "quotation_number": "QPROJ-GAP-001",
                "issue_date": "2026-03-01",
                "order_date": "2026-03-02",
                "expected_arrival": "2026-03-20",
                "quotation_document_url": "https://example.sharepoint.com/sites/procurement/placeholder.pdf",
            }
        ],
        source_name="project_gap.csv",
    )

    without_date = service.project_gap_analysis(conn, project["project_id"])
    with_date = service.project_gap_analysis(
        conn,
        project["project_id"],
        target_date=FUTURE_TARGET_DATE,
    )

    assert without_date["target_date"] == service.today_jst()
    assert int(without_date["rows"][0]["available_stock"]) == 2
    assert int(without_date["rows"][0]["shortage"]) == 4
    assert with_date["target_date"] == FUTURE_TARGET_DATE
    assert int(with_date["rows"][0]["available_stock"]) == 7
    assert int(with_date["rows"][0]["shortage"]) == 0


def test_project_gap_analysis_rejects_past_target_date(conn):
    item = _create_basic_item(conn, item_number="ITEM-PROJ-GAP-PAST")
    project = service.create_project(
        conn,
        {
            "name": "PROJ-GAP-PAST-001",
            "requirements": [
                {
                    "item_id": item["item_id"],
                    "assembly_id": None,
                    "quantity": 1,
                }
            ],
        },
    )

    with pytest.raises(AppError) as exc_info:
        service.project_gap_analysis(
            conn,
            project["project_id"],
            target_date="2000-01-01",
        )

    assert exc_info.value.code == "INVALID_TARGET_DATE"


def test_project_planning_analysis_keeps_started_committed_projects_in_pipeline(conn):
    item = _create_basic_item(conn, item_number="ITEM-PLAN-STARTED-COMMITTED")
    committed = service.create_project(
        conn,
        {
            "name": "PROJ-STARTED-COMMITTED-001",
            "status": "ACTIVE",
            "planned_start": "2000-01-01",
            "requirements": [
                {
                    "item_id": item["item_id"],
                    "assembly_id": None,
                    "quantity": 5,
                }
            ],
        },
    )
    selected = service.create_project(
        conn,
        {
            "name": "PROJ-STARTED-PREVIEW-001",
            "status": "PLANNING",
            "planned_start": FUTURE_TARGET_DATE,
            "requirements": [
                {
                    "item_id": item["item_id"],
                    "assembly_id": None,
                    "quantity": 5,
                }
            ],
        },
    )
    service.import_orders_from_rows(
        conn,
        supplier_name="PLAN-STARTED-SUP",
        rows=[
            {
                "item_number": item["item_number"],
                "quantity": "5",
                "quotation_number": "Q-PLAN-STARTED-001",
                "issue_date": "2026-03-01",
                "order_date": "2026-03-02",
                "expected_arrival": FUTURE_TARGET_DATE,
                "quotation_document_url": "https://example.sharepoint.com/sites/procurement/placeholder.pdf",
            }
        ],
        source_name="planning_started_orders.csv",
    )

    analysis = service.project_planning_analysis(conn, selected["project_id"])

    assert [int(row["project_id"]) for row in analysis["pipeline"]] == [
        committed["project_id"],
        selected["project_id"],
    ]
    assert analysis["pipeline"][0]["planned_start"] == "2000-01-01"
    assert int(analysis["rows"][0]["covered_on_time_quantity"]) == 0
    assert int(analysis["rows"][0]["shortage_at_start"]) == 5


def test_project_planning_analysis_allows_started_committed_project_dates(conn):
    item = _create_basic_item(conn, item_number="ITEM-PLAN-INFLIGHT")
    project = service.create_project(
        conn,
        {
            "name": "PROJ-INFLIGHT-001",
            "status": "CONFIRMED",
            "planned_start": "2000-01-01",
            "requirements": [
                {
                    "item_id": item["item_id"],
                    "assembly_id": None,
                    "quantity": 1,
                }
            ],
        },
    )

    analysis = service.project_planning_analysis(conn, project["project_id"])

    assert analysis["target_date"] == "2000-01-01"
    assert analysis["summary"]["planned_start"] == "2000-01-01"
    assert int(analysis["rows"][0]["shortage_at_start"]) == 1


def test_project_gap_analysis_returns_effective_planning_date_without_explicit_target(conn):
    item = _create_basic_item(conn, item_number="ITEM-PROJ-GAP-EFFECTIVE-DATE")
    project = service.create_project(
        conn,
        {
            "name": "PROJ-GAP-EFFECTIVE-DATE-001",
            "status": "CONFIRMED",
            "requirements": [
                {
                    "item_id": item["item_id"],
                    "assembly_id": None,
                    "quantity": 1,
                }
            ],
        },
    )

    analysis = service.project_gap_analysis(conn, project["project_id"])

    assert analysis["target_date"] == service.today_jst()
    assert analysis["project"]["planned_start"] == service.today_jst()
    assert analysis["summary"]["planned_start"] == service.today_jst()
    assert int(analysis["rows"][0]["shortage"]) == 1


def test_project_planning_analysis_includes_source_breakdown_and_cumulative_generic_metrics(conn):
    item = _create_basic_item(conn, item_number="ITEM-PLAN-SOURCES")
    service.adjust_inventory(conn, item_id=item["item_id"], quantity_delta=2, location="STOCK")
    service.create_project(
        conn,
        {
            "name": "PROJ-PLAN-SOURCES-EARLIER",
            "status": "CONFIRMED",
            "planned_start": "2999-05-01",
            "requirements": [
                {
                    "item_id": item["item_id"],
                    "assembly_id": None,
                    "quantity": 1,
                }
            ],
        },
    )
    project = service.create_project(
        conn,
        {
            "name": "PROJ-PLAN-SOURCES-SELECTED",
            "status": "PLANNING",
            "planned_start": FUTURE_TARGET_DATE,
            "requirements": [
                {
                    "item_id": item["item_id"],
                    "assembly_id": None,
                    "quantity": 6,
                }
            ],
        },
    )
    service.import_orders_from_rows(
        conn,
        supplier_name="PLAN-SOURCES-SUP",
        rows=[
            {
                "item_number": item["item_number"],
                "quantity": "2",
                "quotation_number": "Q-PLAN-SOURCES-001",
                "issue_date": "2026-03-01",
                "order_date": "2026-03-02",
                "expected_arrival": FUTURE_TARGET_DATE,
                "quotation_document_url": "https://example.sharepoint.com/sites/procurement/placeholder.pdf",
            },
            {
                "item_number": item["item_number"],
                "quantity": "1",
                "quotation_number": "Q-PLAN-SOURCES-002",
                "issue_date": "2026-03-01",
                "order_date": "2026-03-03",
                "expected_arrival": "3000-01-15",
                "quotation_document_url": "https://example.sharepoint.com/sites/procurement/placeholder.pdf",
            },
        ],
        source_name="planning_sources.csv",
    )
    rfq = service.create_project_rfq_batch_from_analysis(
        conn,
        project["project_id"],
        target_date=FUTURE_TARGET_DATE,
    )
    line_id = int(rfq["lines"][0]["line_id"])
    service.update_rfq_line(
        conn,
        line_id,
        {
            "finalized_quantity": 1,
            "expected_arrival": FUTURE_TARGET_DATE,
            "status": "QUOTED",
        },
    )

    analysis = service.project_planning_analysis(
        conn,
        project["project_id"],
        target_date=FUTURE_TARGET_DATE,
    )

    row = analysis["rows"][0]
    source_types = {str(source["source_type"]) for source in row["supply_sources_by_start"]}

    assert int(analysis["summary"]["cumulative_generic_consumed_before_total"]) == 1
    assert int(analysis["summary"]["generic_committed_total"]) == 4
    assert int(row["covered_on_time_quantity"]) == 4
    assert int(row["shortage_at_start"]) == 2
    assert int(row["recovered_after_start_quantity"]) == 1
    assert int(row["remaining_shortage_quantity"]) == 1
    assert source_types == {"stock", "generic_order", "quoted_rfq"}
    assert sum(int(source["quantity"]) for source in row["supply_sources_by_start"]) == 4
    assert [str(source["source_type"]) for source in row["recovery_sources_after_start"]] == [
        "generic_order"
    ]


def test_get_item_planning_context_includes_committed_and_preview_project_rows(conn):
    item = _create_basic_item(conn, item_number="ITEM-PLAN-CONTEXT")
    service.adjust_inventory(conn, item_id=item["item_id"], quantity_delta=3, location="STOCK")
    committed = service.create_project(
        conn,
        {
            "name": "PROJ-PLAN-CONTEXT-COMMITTED",
            "status": "CONFIRMED",
            "planned_start": "2999-05-01",
            "requirements": [{"item_id": item["item_id"], "assembly_id": None, "quantity": 2}],
        },
    )
    preview = service.create_project(
        conn,
        {
            "name": "PROJ-PLAN-CONTEXT-PREVIEW",
            "status": "PLANNING",
            "planned_start": FUTURE_TARGET_DATE,
            "requirements": [{"item_id": item["item_id"], "assembly_id": None, "quantity": 4}],
        },
    )
    service.import_orders_from_rows(
        conn,
        supplier_name="PLAN-CONTEXT-SUP",
        rows=[
            {
                "item_number": item["item_number"],
                "quantity": "1",
                "quotation_number": "Q-PLAN-CONTEXT-001",
                "issue_date": "2026-03-01",
                "order_date": "2026-03-02",
                "expected_arrival": FUTURE_TARGET_DATE,
                "quotation_document_url": "https://example.sharepoint.com/sites/procurement/placeholder.pdf",
            }
        ],
        source_name="planning_context.csv",
    )

    context = service.get_item_planning_context(
        conn,
        item["item_id"],
        preview_project_id=preview["project_id"],
        target_date=FUTURE_TARGET_DATE,
    )

    assert context["item_number"] == item["item_number"]
    assert context["target_date"] == FUTURE_TARGET_DATE
    assert [int(row["project_id"]) for row in context["projects"]] == [
        committed["project_id"],
        preview["project_id"],
    ]
    assert context["projects"][1]["is_planning_preview"] is True
    assert int(context["projects"][1]["required_quantity"]) == 4
    assert isinstance(context["projects"][1]["supply_sources_by_start"], list)


def test_create_project_rfq_batch_auto_confirms_and_persists_start_date(conn):
    item = _create_basic_item(conn, item_number="ITEM-RFQ-AUTO-CONFIRM")
    project = service.create_project(
        conn,
        {
            "name": "PROJ-RFQ-AUTO-CONFIRM-001",
            "requirements": [
                {
                    "item_id": item["item_id"],
                    "assembly_id": None,
                    "quantity": 3,
                }
            ],
        },
    )

    rfq = service.create_project_rfq_batch_from_analysis(conn, project["project_id"])
    updated_project = service.get_project(conn, project["project_id"])
    pipeline = service.list_planning_pipeline(conn)

    assert updated_project["status"] == "CONFIRMED"
    assert updated_project["planned_start"] == service.today_jst()
    assert rfq["target_date"] == service.today_jst()
    assert any(int(row["project_id"]) == project["project_id"] for row in pipeline)


def test_update_rfq_line_only_dedicates_ordered_links_and_clears_replaced_orders(conn):
    item = _create_basic_item(conn, item_number="ITEM-RFQ-ORDER-SYNC")
    project = service.create_project(
        conn,
        {
            "name": "PROJ-RFQ-ORDER-SYNC-001",
            "status": "PLANNING",
            "planned_start": FUTURE_TARGET_DATE,
            "requirements": [
                {
                    "item_id": item["item_id"],
                    "assembly_id": None,
                    "quantity": 5,
                }
            ],
        },
    )
    rfq = service.create_project_rfq_batch_from_analysis(
        conn,
        project["project_id"],
        target_date=FUTURE_TARGET_DATE,
    )
    line_id = int(rfq["lines"][0]["line_id"])

    service.import_orders_from_rows(
        conn,
        supplier_name="RFQ-ORDER-SYNC-SUP",
        rows=[
            {
                "item_number": item["item_number"],
                "quantity": "5",
                "quotation_number": "Q-RFQ-ORDER-SYNC-001",
                "issue_date": "2026-03-01",
                "order_date": "2026-03-02",
                "expected_arrival": FUTURE_TARGET_DATE,
                "quotation_document_url": "https://example.sharepoint.com/sites/procurement/placeholder.pdf",
            },
            {
                "item_number": item["item_number"],
                "quantity": "5",
                "quotation_number": "Q-RFQ-ORDER-SYNC-002",
                "issue_date": "2026-03-01",
                "order_date": "2026-03-03",
                "expected_arrival": FUTURE_TARGET_DATE,
                "quotation_document_url": "https://example.sharepoint.com/sites/procurement/placeholder.pdf",
            },
        ],
        source_name="rfq_order_sync.csv",
    )
    order_rows = conn.execute(
        "SELECT order_id FROM orders ORDER BY order_id ASC"
    ).fetchall()
    first_order_id = int(order_rows[0]["order_id"])
    second_order_id = int(order_rows[1]["order_id"])

    quoted = service.update_rfq_line(
        conn,
        line_id,
        {
            "expected_arrival": FUTURE_TARGET_DATE,
            "status": "QUOTED",
            "linked_purchase_order_line_id": first_order_id,
        },
    )
    assert quoted["line"]["status"] == "QUOTED"
    assert quoted["line"]["linked_purchase_order_line_id"] is None
    assert service.get_order(conn, first_order_id)["project_id"] is None

    ordered = service.update_rfq_line(
        conn,
        line_id,
        {
            "linked_purchase_order_line_id": first_order_id,
            "status": "ORDERED",
        },
    )
    assert ordered["line"]["status"] == "ORDERED"
    assert int(ordered["line"]["linked_purchase_order_line_id"]) == first_order_id
    assert int(service.get_order(conn, first_order_id)["project_id"]) == project["project_id"]

    replaced = service.update_rfq_line(
        conn,
        line_id,
        {
            "linked_purchase_order_line_id": second_order_id,
            "status": "ORDERED",
        },
    )
    assert int(replaced["line"]["linked_purchase_order_line_id"]) == second_order_id
    assert service.get_order(conn, first_order_id)["project_id"] is None
    assert int(service.get_order(conn, second_order_id)["project_id"]) == project["project_id"]

    cleared = service.update_rfq_line(
        conn,
        line_id,
        {
            "linked_purchase_order_line_id": second_order_id,
            "status": "QUOTED",
        },
    )
    assert cleared["line"]["status"] == "QUOTED"
    assert cleared["line"]["linked_purchase_order_line_id"] is None
    assert service.get_order(conn, second_order_id)["project_id"] is None


def test_split_order_leaves_rfq_managed_project_assignment_on_original_order_only(
    conn, tmp_path: Path, monkeypatch
):
    item = _create_basic_item(conn, item_number="ITEM-RFQ-SPLIT-ONLY-ORIGINAL")
    project = service.create_project(
        conn,
        {
            "name": "PROJ-RFQ-SPLIT-ONLY-ORIGINAL-001",
            "status": "PLANNING",
            "planned_start": FUTURE_TARGET_DATE,
            "requirements": [{"item_id": item["item_id"], "assembly_id": None, "quantity": 5}],
        },
    )
    rfq = service.create_project_rfq_batch_from_analysis(
        conn,
        project["project_id"],
        target_date=FUTURE_TARGET_DATE,
    )
    line_id = int(rfq["lines"][0]["line_id"])

    roots = service.build_roots(
        unregistered_root=tmp_path / "quotations" / "unregistered",
        registered_root=tmp_path / "quotations" / "registered",
    )
    service.ensure_roots(roots)
    monkeypatch.setattr(service, "build_roots", lambda **_: roots)

    csv_path = roots.registered_csv_root / "SupplierRfqSplit" / "Q-RFQ-SPLIT-001.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(
            fp,
            fieldnames=[
                "supplier",
                "item_number",
                "quantity",
                "quotation_number",
                "issue_date",
                "order_date",
                "expected_arrival",
                "quotation_document_url",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "supplier": "SupplierRfqSplit",
                "item_number": item["item_number"],
                "quantity": "5",
                "quotation_number": "Q-RFQ-SPLIT-001",
                "issue_date": "2026-03-01",
                "order_date": "2026-03-02",
                "expected_arrival": FUTURE_TARGET_DATE,
                "quotation_document_url": "https://example.sharepoint.com/sites/procurement/placeholder.pdf",
            }
        )

    imported = service.import_orders_from_csv_path(
        conn,
        supplier_name="SupplierRfqSplit",
        csv_path=csv_path,
    )
    order_id = int(imported["order_ids"][0])
    service.update_rfq_line(
        conn,
        line_id,
        {
            "linked_purchase_order_line_id": order_id,
            "status": "ORDERED",
        },
    )

    split = service.update_order(
        conn,
        order_id,
        {
            "expected_arrival": "2999-06-10",
            "split_quantity": 2,
        },
    )

    assert int(split["updated_order"]["project_id"]) == project["project_id"]
    assert split["created_order"]["project_id"] is None
    assert service.get_order(conn, int(split["split_order_id"]))["project_id"] is None


def test_create_project_rfq_batch_uses_selected_target_date(conn):
    item = _create_basic_item(conn, item_number="ITEM-RFQ-TARGET-DATE")
    project = service.create_project(
        conn,
        {
            "name": "PROJ-RFQ-TARGET-DATE-001",
            "status": "PLANNING",
            "planned_start": "2999-01-01",
            "requirements": [
                {
                    "item_id": item["item_id"],
                    "assembly_id": None,
                    "quantity": 5,
                }
            ],
        },
    )
    service.import_orders_from_rows(
        conn,
        supplier_name="RFQ-TARGET-DATE-SUP",
        rows=[
            {
                "item_number": item["item_number"],
                "quantity": "3",
                "quotation_number": "Q-RFQ-TARGET-DATE-001",
                "issue_date": "2026-03-01",
                "order_date": "2026-03-02",
                "expected_arrival": "2999-03-01",
                "quotation_document_url": "https://example.sharepoint.com/sites/procurement/placeholder.pdf",
            }
        ],
        source_name="rfq_target_date.csv",
    )

    rfq = service.create_project_rfq_batch_from_analysis(
        conn,
        project["project_id"],
        target_date="2999-06-01",
    )
    updated_project = service.get_project(conn, project["project_id"])

    assert rfq["target_date"] == "2999-06-01"
    assert int(rfq["lines"][0]["requested_quantity"]) == 2
    assert updated_project["status"] == "CONFIRMED"
    assert updated_project["planned_start"] == "2999-06-01"


def test_purchase_candidates_create_list_and_update(conn):
    item = _create_basic_item(conn, item_number="ITEM-PURCHASE-CAND")
    service.adjust_inventory(conn, item_id=item["item_id"], quantity_delta=2, location="STOCK")
    project = service.create_project(
        conn,
        {
            "name": "PROJ-PURCHASE-CAND-001",
            "status": "PLANNING",
            "requirements": [
                {
                    "item_id": item["item_id"],
                    "assembly_id": None,
                    "quantity": 6,
                }
            ],
        },
    )

    from_project = service.create_purchase_candidates_from_project_gap(conn, project["project_id"])
    assert from_project["created_count"] == 1
    created_project_candidate = from_project["created"][0]
    assert created_project_candidate["source_type"] == "PROJECT"
    assert int(created_project_candidate["shortage_quantity"]) == 4
    assert created_project_candidate["status"] == "OPEN"

    from_bom = service.create_purchase_candidates_from_bom(
        conn,
        rows=[
            {
                "supplier": "PURCHASE-CAND-SUP",
                "item_number": item["item_number"],
                "required_quantity": 5,
            },
            {
                "supplier": "PURCHASE-CAND-SUP",
                "item_number": "UNKNOWN-CAND-001",
                "required_quantity": 3,
            },
        ],
    )
    assert from_bom["created_count"] == 2

    open_rows, _ = service.list_purchase_candidates(conn, status="OPEN", page=1, per_page=50)
    assert len(open_rows) >= 3

    updated = service.update_purchase_candidate(
        conn,
        int(created_project_candidate["candidate_id"]),
        {"status": "ORDERING", "note": "RFQ in progress"},
    )
    assert updated["status"] == "ORDERING"
    assert updated["note"] == "RFQ in progress"


def test_project_gap_and_purchase_candidates_expand_assembly_requirements(conn):
    component = _create_basic_item(conn, item_number="ITEM-PROJ-ASM-COMP")
    assembly = service.create_assembly(
        conn,
        {
            "name": "PROJ-ASM-REQ-001",
            "components": [{"item_id": component["item_id"], "quantity": 3}],
        },
    )
    project = service.create_project(
        conn,
        {
            "name": "PROJ-ASM-REQ-001",
            "status": "PLANNING",
            "requirements": [
                {
                    "item_id": None,
                    "assembly_id": assembly["assembly_id"],
                    "quantity": 2,
                }
            ],
        },
    )

    gap = service.project_gap_analysis(conn, project["project_id"])
    gap_row = next(row for row in gap["rows"] if int(row["item_id"]) == component["item_id"])
    assert int(gap_row["required_quantity"]) == 6
    assert int(gap_row["shortage"]) == 6

    created = service.create_purchase_candidates_from_project_gap(conn, project["project_id"])
    assert created["created_count"] == 1
    assert int(created["created"][0]["item_id"]) == component["item_id"]
    assert int(created["created"][0]["shortage_quantity"]) == 6


def test_delete_item_blocked_when_referenced_by_purchase_candidate(conn):
    item = _create_basic_item(conn, item_number="ITEM-PURCHASE-CAND-DELETE")
    created = service.create_purchase_candidates_from_bom(
        conn,
        rows=[
            {
                "supplier": "PURCHASE-CAND-DELETE-SUP",
                "item_number": item["item_number"],
                "required_quantity": 1,
            },
            {
                "supplier": "PURCHASE-CAND-DELETE-SUP",
                "item_number": "MISSING-PURCHASE-CAND-DELETE",
                "required_quantity": 1,
            },
        ],
        target_date=FUTURE_TARGET_DATE,
    )
    purchase_row = next(
        (
            row
            for row in created["created"]
            if row.get("item_id") is not None and int(row["item_id"]) == int(item["item_id"])
        ),
        None,
    )
    assert purchase_row is not None

    with pytest.raises(AppError) as exc_info:
        service.delete_item(conn, item["item_id"])

    assert exc_info.value.code == "ITEM_REFERENCED"
    assert "purchase_candidates" in exc_info.value.message


def test_partial_arrival_sibling_inherits_project_id(conn):
    """P1: Arrival-split sibling must carry the original order's project_id so that
    the remaining open quantity stays visible in project planning supply."""
    item = _create_basic_item(conn, item_number="ITEM-ARRIVAL-SPLIT-PROJECT")
    project = service.create_project(
        conn,
        {
            "name": "PROJ-ARRIVAL-SPLIT-001",
            "status": "PLANNING",
            "planned_start": FUTURE_TARGET_DATE,
            "requirements": [{"item_id": item["item_id"], "assembly_id": None, "quantity": 10}],
        },
    )
    imported = service.import_orders_from_rows(
        conn,
        supplier_name="ARRIVAL-SPLIT-SUP",
        rows=[
            {
                "item_number": item["item_number"],
                "quantity": "10",
                "quotation_number": "Q-ARRIVAL-SPLIT-001",
                "issue_date": "2026-03-01",
                "order_date": "2026-03-02",
                "expected_arrival": FUTURE_TARGET_DATE,
                "quotation_document_url": "https://example.sharepoint.com/sites/procurement/placeholder.pdf",
            }
        ],
        source_name="arrival_split.csv",
    )
    order_id = int(imported["order_ids"][0])
    service.update_order(conn, order_id, {"project_id": project["project_id"]})

    result = service.process_order_arrival(conn, order_id=order_id, quantity=4)
    sibling_id = result["split_order_id"]
    assert sibling_id is not None

    sibling = service.get_order(conn, sibling_id)
    assert int(sibling["project_id"]) == project["project_id"], (
        "Arrival-split sibling must inherit project_id from the original order"
    )
    assert int(sibling["order_amount"]) == 6
    assert sibling["is_split_child"] is True
    assert int(sibling["split_root_order_id"]) == order_id
    split_row = conn.execute(
        """
        SELECT split_type, root_order_id, child_order_id, split_quantity
        FROM local_order_splits
        WHERE child_order_id = ?
        """,
        (sibling_id,),
    ).fetchone()
    assert split_row is not None
    assert split_row["split_type"] == "ARRIVAL_SPLIT"
    assert int(split_row["root_order_id"]) == order_id
    assert int(split_row["child_order_id"]) == sibling_id
    assert int(split_row["split_quantity"]) == 6


def test_manual_project_id_preserved_when_rfq_link_removed(conn):
    """P2: A project_id set via PUT /orders/{id} must not be cleared by
    _sync_order_project_assignment_from_rfq when the RFQ link is removed."""
    item = _create_basic_item(conn, item_number="ITEM-MANUAL-PROJECT-RFQ")
    project = service.create_project(
        conn,
        {
            "name": "PROJ-MANUAL-PROJECT-RFQ-001",
            "status": "PLANNING",
            "planned_start": FUTURE_TARGET_DATE,
            "requirements": [{"item_id": item["item_id"], "assembly_id": None, "quantity": 5}],
        },
    )
    rfq = service.create_project_rfq_batch_from_analysis(
        conn,
        project["project_id"],
        target_date=FUTURE_TARGET_DATE,
    )
    line_id = int(rfq["lines"][0]["line_id"])

    imported = service.import_orders_from_rows(
        conn,
        supplier_name="MANUAL-PROJECT-RFQ-SUP",
        rows=[
            {
                "item_number": item["item_number"],
                "quantity": "5",
                "quotation_number": "Q-MANUAL-PROJECT-RFQ-001",
                "issue_date": "2026-03-01",
                "order_date": "2026-03-02",
                "expected_arrival": FUTURE_TARGET_DATE,
                "quotation_document_url": "https://example.sharepoint.com/sites/procurement/placeholder.pdf",
            }
        ],
        source_name="manual_project_rfq.csv",
    )
    order_id = int(imported["order_ids"][0])

    # Manually assign the project to the order BEFORE linking to the RFQ
    service.update_order(conn, order_id, {"project_id": project["project_id"]})
    assert int(service.get_order(conn, order_id)["project_id"]) == project["project_id"]

    # Link the order to the RFQ (same project — allowed)
    service.update_rfq_line(conn, line_id, {"linked_purchase_order_line_id": order_id, "status": "ORDERED"})
    assert int(service.get_order(conn, order_id)["project_id"]) == project["project_id"]

    # Remove the RFQ link — manual project_id must survive
    service.update_rfq_line(
        conn,
        line_id,
        {"linked_purchase_order_line_id": order_id, "status": "QUOTED", "expected_arrival": FUTURE_TARGET_DATE},
    )
    assert int(service.get_order(conn, order_id)["project_id"]) == project["project_id"], (
        "Manually-assigned project_id must not be cleared when the RFQ link is removed"
    )


def test_confirm_project_allocation_can_preview_and_execute(conn):
    stock_item = _create_basic_item(conn, item_number="ALLOC-STOCK-ITEM")
    order_manufacturer = service.create_manufacturer(conn, "TEST-MFG-ALLOC-ORDER")
    order_item = service.create_item(
        conn,
        {
            "item_number": "ALLOC-ORDER-ITEM",
            "manufacturer_id": order_manufacturer["manufacturer_id"],
            "category": "Lens",
        },
    )
    service.adjust_inventory(
        conn,
        item_id=stock_item["item_id"],
        quantity_delta=3,
        location="STOCK",
        note="seed stock allocation item",
    )
    project = service.create_project(
        conn,
        {
            "name": "ALLOC-CONFIRM-PROJECT",
            "status": "CONFIRMED",
            "planned_start": FUTURE_TARGET_DATE,
            "requirements": [
                {"item_id": stock_item["item_id"], "assembly_id": None, "quantity": 3},
                {"item_id": order_item["item_id"], "assembly_id": None, "quantity": 4},
            ],
        },
    )
    imported = service.import_orders_from_rows(
        conn,
        supplier_name="ALLOC-SUPPLIER",
        rows=[
            {
                "item_number": order_item["item_number"],
                "quantity": "6",
                "quotation_number": "Q-ALLOC-001",
                "issue_date": "2026-03-01",
                "order_date": "2026-03-02",
                "expected_arrival": FUTURE_TARGET_DATE,
                "quotation_document_url": "https://example.sharepoint.com/sites/procurement/placeholder.pdf",
            }
        ],
        source_name="confirm_allocation.csv",
    )
    order_id = int(imported["order_ids"][0])

    preview = service.confirm_project_allocation(
        conn,
        project["project_id"],
        target_date=FUTURE_TARGET_DATE,
        dry_run=True,
    )

    assert preview["dry_run"] is True
    assert len(preview["reservations_created"]) == 1
    assert preview["reservations_created"][0]["reservation_id"] is None
    assert preview["reservations_created"][0]["item_id"] == stock_item["item_id"]
    assert preview["reservations_created"][0]["quantity"] == 3
    assert len(preview["orders_split"]) == 1
    assert preview["orders_split"][0]["original_order_id"] == order_id
    assert preview["orders_split"][0]["assigned_quantity"] == 4
    assert preview["orders_split"][0]["remaining_quantity"] == 2

    executed = service.confirm_project_allocation(
        conn,
        project["project_id"],
        target_date=FUTURE_TARGET_DATE,
        dry_run=False,
        expected_snapshot_signature=preview["snapshot_signature"],
    )
    conn.commit()

    assert executed["dry_run"] is False
    assert len(executed["reservations_created"]) == 1
    created_reservation_id = int(executed["reservations_created"][0]["reservation_id"])
    reservation = service.get_reservation(conn, created_reservation_id)
    assert int(reservation["project_id"]) == project["project_id"]
    assert int(reservation["quantity"]) == 3

    updated_original = service.get_order(conn, order_id)
    created_order_id = int(executed["orders_split"][0]["new_order_id"])
    created_order = service.get_order(conn, created_order_id)
    assert updated_original["project_id"] is None
    assert int(updated_original["order_amount"]) == 2
    assert int(created_order["project_id"]) == project["project_id"]
    assert int(created_order["project_id_manual"]) == 1
    assert int(created_order["order_amount"]) == 4


def test_confirm_project_allocation_rejects_stale_snapshot(conn):
    item = _create_basic_item(conn, item_number="ALLOC-STALE-ITEM")
    service.adjust_inventory(
        conn,
        item_id=item["item_id"],
        quantity_delta=2,
        location="STOCK",
        note="seed stale allocation item",
    )
    project = service.create_project(
        conn,
        {
            "name": "ALLOC-STALE-PROJECT",
            "status": "PLANNING",
            "planned_start": FUTURE_TARGET_DATE,
            "requirements": [{"item_id": item["item_id"], "assembly_id": None, "quantity": 2}],
        },
    )

    preview = service.confirm_project_allocation(
        conn,
        project["project_id"],
        target_date=FUTURE_TARGET_DATE,
        dry_run=True,
    )

    service.adjust_inventory(
        conn,
        item_id=item["item_id"],
        quantity_delta=-1,
        location="STOCK",
        note="mutate snapshot after preview",
    )

    with pytest.raises(AppError) as exc:
        service.confirm_project_allocation(
            conn,
            project["project_id"],
            target_date=FUTURE_TARGET_DATE,
            dry_run=False,
            expected_snapshot_signature=preview["snapshot_signature"],
        )

    assert exc.value.code == "PLANNING_SNAPSHOT_CHANGED"


def test_confirm_project_allocation_rejects_persist_for_planning_project(conn):
    item = _create_basic_item(conn, item_number="ALLOC-DRAFT-ITEM")
    service.adjust_inventory(
        conn,
        item_id=item["item_id"],
        quantity_delta=2,
        location="STOCK",
        note="seed draft allocation item",
    )
    project = service.create_project(
        conn,
        {
            "name": "ALLOC-DRAFT-PROJECT",
            "status": "PLANNING",
            "planned_start": FUTURE_TARGET_DATE,
            "requirements": [{"item_id": item["item_id"], "assembly_id": None, "quantity": 2}],
        },
    )

    preview = service.confirm_project_allocation(
        conn,
        project["project_id"],
        target_date=FUTURE_TARGET_DATE,
        dry_run=True,
    )
    assert preview["dry_run"] is True
    assert preview["snapshot_signature"]

    with pytest.raises(AppError) as exc:
        service.confirm_project_allocation(
            conn,
            project["project_id"],
            target_date=FUTURE_TARGET_DATE,
            dry_run=False,
            expected_snapshot_signature=preview["snapshot_signature"],
        )

    assert exc.value.code == "PROJECT_CONFIRMATION_REQUIRED"


def test_import_orders_deduplicates_missing_rows_for_same_item(conn, tmp_path: Path):
    """When the same unregistered item_number appears on multiple CSV rows
    (e.g. different expected_arrival dates), there should be only one
    missing row per (supplier, item_number) pair."""
    supplier = service.create_supplier(conn, "SupplierDedup")
    rows = [
        {
            "item_number": "DEDUP-ITEM-001",
            "quantity": "2",
            "quotation_number": "Q-DEDUP-001",
            "issue_date": "2026-03-01",
            "order_date": "2026-03-09",
            "expected_arrival": "2026-03-10",
            "quotation_document_url": "https://example.sharepoint.com/sites/procurement/placeholder.pdf",
        },
        {
            "item_number": "DEDUP-ITEM-001",
            "quantity": "3",
            "quotation_number": "Q-DEDUP-001",
            "issue_date": "2026-03-01",
            "order_date": "2026-03-09",
            "expected_arrival": "2026-03-18",
            "quotation_document_url": "https://example.sharepoint.com/sites/procurement/placeholder.pdf",
        },
        {
            "item_number": "DEDUP-ITEM-001",
            "quantity": "1",
            "quotation_number": "Q-DEDUP-001",
            "issue_date": "2026-03-01",
            "order_date": "2026-03-09",
            "expected_arrival": "2026-04-20",
            "quotation_document_url": "https://example.sharepoint.com/sites/procurement/placeholder.pdf",
        },
    ]

    result = service.import_orders_from_rows(
        conn,
        supplier_id=int(supplier["supplier_id"]),
        rows=rows,
        source_name="Q-DEDUP-001.csv",
        missing_output_dir=tmp_path,
    )

    assert result["status"] == "missing_items"
    assert result["missing_count"] == 1, (
        f"Expected 1 deduplicated missing row, got {result['missing_count']}"
    )
    assert len(result["rows"]) == 1
    assert result["rows"][0]["item_number"] == "DEDUP-ITEM-001"


def test_inventory_snapshot_net_available_returns_residual_stock(conn):
    item = _create_basic_item(conn, item_number="ITEM-SNAPSHOT-NET")
    project = service.create_project(
        conn,
        {
            "name": "SNAPSHOT-NET-PROJECT",
            "status": "CONFIRMED",
            "planned_start": FUTURE_TARGET_DATE,
            "requirements": [],
        },
    )
    service.adjust_inventory(
        conn,
        item_id=item["item_id"],
        quantity_delta=10,
        location="STOCK",
        note="seed snapshot stock",
    )
    service.create_reservation(
        conn,
        {
            "item_id": item["item_id"],
            "quantity": 4,
            "purpose": "occupy stock",
            "deadline": FUTURE_TARGET_DATE,
            "project_id": project["project_id"],
        },
    )
    service.import_orders_from_content(
        conn,
        content=(
            "item_number,quantity,quotation_number,issue_date,order_date,expected_arrival,quotation_document_url\n"
            f"{item['item_number']},3,Q-SNAPSHOT-NET-001,2026-03-01,2026-03-02,{FUTURE_TARGET_DATE},https://example.sharepoint.com/sites/procurement/Q-SNAPSHOT-NET-001.pdf\n"
        ).encode("utf-8"),
        supplier_name="SNAPSHOT-SUPPLIER",
        source_name="snapshot_net_available.csv",
    )
    conn.commit()

    snapshot = service.get_inventory_snapshot(
        conn,
        target_date=FUTURE_TARGET_DATE,
        mode="future",
        basis="net_available",
    )

    assert snapshot["basis"] == "net_available"
    assert snapshot["mode"] == "future"
    matching_rows = [row for row in snapshot["rows"] if int(row["item_id"]) == item["item_id"]]
    assert len(matching_rows) == 1
    assert matching_rows[0]["location"] == "STOCK"
    assert int(matching_rows[0]["quantity"]) == 9
    assert int(matching_rows[0]["allocated_quantity"]) == 4
    assert int(matching_rows[0]["active_reservation_count"]) == 1
    assert matching_rows[0]["allocated_project_names"] == ["SNAPSHOT-NET-PROJECT"]


def test_inventory_snapshot_net_available_rejects_past_mode(conn):
    with pytest.raises(AppError) as exc_info:
        service.get_inventory_snapshot(
            conn,
            target_date="2020-01-01",
            mode="past",
            basis="net_available",
        )

    assert exc_info.value.code == "SNAPSHOT_BASIS_MODE_UNSUPPORTED"
