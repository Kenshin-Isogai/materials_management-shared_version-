from __future__ import annotations

import csv
from pathlib import Path

import pytest

from app.errors import AppError
from app import service

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

def test_import_unregistered_orders_moves_csv_and_pdf(conn, tmp_path: Path):
    item = _create_basic_item(conn, item_number="U-ITEM-001")

    unregistered_root = tmp_path / "quotations" / "unregistered"
    registered_root = tmp_path / "quotations" / "registered"
    supplier_csv_dir = unregistered_root / "csv_files" / "SupplierA"
    supplier_pdf_dir = unregistered_root / "pdf_files" / "SupplierA"
    supplier_csv_dir.mkdir(parents=True, exist_ok=True)
    supplier_pdf_dir.mkdir(parents=True, exist_ok=True)

    pdf_path = supplier_pdf_dir / "Q-001.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%test\n")

    csv_path = supplier_csv_dir / "Q-001.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(
            fp,
            fieldnames=[
                "item_number",
                "quantity",
                "quotation_number",
                "issue_date",
                "order_date",
                "expected_arrival",
                "pdf_link",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "item_number": item["item_number"],
                "quantity": "2",
                "quotation_number": "Q-001",
                "issue_date": "2026-02-20",
                "order_date": "2026-02-21",
                "expected_arrival": "2026-02-28",
                "pdf_link": "Q-001.pdf",
            }
        )

    result = service.import_unregistered_order_csvs(
        conn,
        unregistered_root=unregistered_root,
        registered_root=registered_root,
    )
    conn.commit()

    assert result["status"] == "ok"
    assert result["succeeded"] == 1
    assert not csv_path.exists()
    assert not pdf_path.exists()
    assert (registered_root / "csv_files" / "SupplierA" / "Q-001.csv").exists()
    assert (registered_root / "pdf_files" / "SupplierA" / "Q-001.pdf").exists()

    row = conn.execute(
        """
        SELECT q.pdf_link
        FROM quotations q
        JOIN suppliers s ON s.supplier_id = q.supplier_id
        WHERE s.name = ? AND q.quotation_number = ?
        """,
        ("SupplierA", "Q-001"),
    ).fetchone()
    assert row is not None
    assert str(row["pdf_link"]).endswith("Q-001.pdf")

def test_import_unregistered_orders_missing_items_keeps_source_files(conn, tmp_path: Path):
    unregistered_root = tmp_path / "quotations" / "unregistered"
    registered_root = tmp_path / "quotations" / "registered"
    supplier_csv_dir = unregistered_root / "csv_files" / "SupplierMissing"
    supplier_pdf_dir = unregistered_root / "pdf_files" / "SupplierMissing"
    supplier_csv_dir.mkdir(parents=True, exist_ok=True)
    supplier_pdf_dir.mkdir(parents=True, exist_ok=True)

    pdf_path = supplier_pdf_dir / "Q-MISS-001.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%missing\n")

    csv_path = supplier_csv_dir / "Q-MISS-001.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(
            fp,
            fieldnames=[
                "item_number",
                "quantity",
                "quotation_number",
                "issue_date",
                "order_date",
                "expected_arrival",
                "pdf_link",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "item_number": "MISSING-ITEM-001",
                "quantity": "2",
                "quotation_number": "Q-MISS-001",
                "issue_date": "2026-02-20",
                "order_date": "2026-02-21",
                "expected_arrival": "2026-02-28",
                "pdf_link": "Q-MISS-001.pdf",
            }
        )

    result = service.import_unregistered_order_csvs(
        conn,
        unregistered_root=unregistered_root,
        registered_root=registered_root,
    )
    conn.commit()

    assert result["status"] == "ok"
    assert result["succeeded"] == 0
    assert result["missing_items"] == 1
    assert csv_path.exists()
    assert pdf_path.exists()
    assert not (registered_root / "csv_files" / "SupplierMissing" / "Q-MISS-001.csv").exists()
    assert not (registered_root / "pdf_files" / "SupplierMissing" / "Q-MISS-001.pdf").exists()

    register_path = result.get("missing_items_register_csv")
    assert register_path is not None
    register_file = Path(register_path)
    assert register_file.exists()
    assert register_file.parent == (unregistered_root / "missing_item_registers")

    with register_file.open("r", encoding="utf-8", newline="") as fp:
        reader = csv.DictReader(fp)
        rows = list(reader)

    assert len(rows) == 1
    assert rows[0]["source_supplier"] == "SupplierMissing"
    assert rows[0]["source_csv"].endswith("Q-MISS-001.csv")
    assert rows[0]["item_number"] == "MISSING-ITEM-001"

def test_import_unregistered_orders_rolls_back_pdf_move_on_csv_move_failure(
    conn,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    item = _create_basic_item(conn, item_number="U-ITEM-FAIL-001")

    unregistered_root = tmp_path / "quotations" / "unregistered"
    registered_root = tmp_path / "quotations" / "registered"
    supplier_csv_dir = unregistered_root / "csv_files" / "SupplierFail"
    supplier_pdf_dir = unregistered_root / "pdf_files" / "SupplierFail"
    supplier_csv_dir.mkdir(parents=True, exist_ok=True)
    supplier_pdf_dir.mkdir(parents=True, exist_ok=True)

    pdf_path = supplier_pdf_dir / "Q-FAIL.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%rollback\n")

    csv_path = supplier_csv_dir / "Q-FAIL.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(
            fp,
            fieldnames=[
                "item_number",
                "quantity",
                "quotation_number",
                "issue_date",
                "order_date",
                "expected_arrival",
                "pdf_link",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "item_number": item["item_number"],
                "quantity": "2",
                "quotation_number": "Q-FAIL",
                "issue_date": "2026-02-20",
                "order_date": "2026-02-21",
                "expected_arrival": "2026-02-28",
                "pdf_link": "Q-FAIL.pdf",
            }
        )

    original_move = service.shutil.move

    def _fail_csv_move(src: str, dst: str) -> str:
        if Path(src).name == "Q-FAIL.csv":
            raise OSError("simulated csv move failure")
        return original_move(src, dst)

    monkeypatch.setattr(service.shutil, "move", _fail_csv_move)

    result = service.import_unregistered_order_csvs(
        conn,
        unregistered_root=unregistered_root,
        registered_root=registered_root,
    )

    assert result["status"] == "error"
    assert result["failed"] == 1
    assert result["files"][0]["status"] == "error"

    # Source files remain in unregistered when the per-file move phase fails.
    assert csv_path.exists()
    assert pdf_path.exists()
    assert not (registered_root / "csv_files" / "SupplierFail" / "Q-FAIL.csv").exists()
    assert not (registered_root / "pdf_files" / "SupplierFail" / "Q-FAIL.pdf").exists()

    row = conn.execute("SELECT COUNT(*) AS c FROM orders").fetchone()
    assert row is not None
    assert int(row["c"]) == 0

def test_migrate_quotations_layout_dry_run_apply_and_idempotent(conn, tmp_path: Path):
    unregistered_root = tmp_path / "quotations" / "unregistered"
    registered_root = tmp_path / "quotations" / "registered"
    legacy_supplier_dir = unregistered_root / "SupplierLegacy"
    legacy_supplier_dir.mkdir(parents=True, exist_ok=True)

    legacy_pdf = legacy_supplier_dir / "Q-100.pdf"
    legacy_pdf.write_bytes(b"%PDF-1.4\n%legacy\n")

    legacy_csv = legacy_supplier_dir / "Q-100.csv"
    with legacy_csv.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(
            fp,
            fieldnames=[
                "item_number",
                "quantity",
                "quotation_number",
                "issue_date",
                "order_date",
                "expected_arrival",
                "pdf_link",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "item_number": "LEG-ITEM-001",
                "quantity": "1",
                "quotation_number": "Q-100",
                "issue_date": "2026-02-20",
                "order_date": "2026-02-21",
                "expected_arrival": "2026-03-01",
                "pdf_link": "quatations/unregistred/pdf_files/SupplierLegacy/Q-100.pdf",
            }
        )

    supplier = service.create_supplier(conn, "SupplierLegacy")
    conn.execute(
        """
        INSERT INTO quotations (supplier_id, quotation_number, issue_date, pdf_link)
        VALUES (?, ?, ?, ?)
        """,
        (
            supplier["supplier_id"],
            "Q-100",
            "2026-02-20",
            "quatations/unregistred/pdf_files/SupplierLegacy/Q-100.pdf",
        ),
    )
    conn.commit()

    preview = service.migrate_quotations_layout(
        conn,
        unregistered_root=unregistered_root,
        registered_root=registered_root,
        apply=False,
    )
    assert preview["mode"] == "dry_run"
    assert preview["planned_moves"] >= 2
    assert preview["moved"] == 0
    assert legacy_csv.exists()
    assert legacy_pdf.exists()

    applied = service.migrate_quotations_layout(
        conn,
        unregistered_root=unregistered_root,
        registered_root=registered_root,
        apply=True,
    )
    conn.commit()
    assert applied["mode"] == "apply"
    assert applied["moved"] >= 2
    assert not legacy_csv.exists()
    assert not legacy_pdf.exists()
    migrated_csv = unregistered_root / "csv_files" / "SupplierLegacy" / "Q-100.csv"
    migrated_pdf = unregistered_root / "pdf_files" / "SupplierLegacy" / "Q-100.pdf"
    assert migrated_csv.exists()
    assert migrated_pdf.exists()

    with migrated_csv.open("r", encoding="utf-8-sig", newline="") as fp:
        reader = csv.DictReader(fp)
        first = next(reader)
    assert first is not None
    assert "quatations" not in str(first["pdf_link"])
    assert str(first["pdf_link"]).endswith("Q-100.pdf")

    row = conn.execute(
        "SELECT pdf_link FROM quotations WHERE quotation_number = ?",
        ("Q-100",),
    ).fetchone()
    assert row is not None
    assert "quatations" not in str(row["pdf_link"])
    assert str(row["pdf_link"]).endswith("Q-100.pdf")

    rerun = service.migrate_quotations_layout(
        conn,
        unregistered_root=unregistered_root,
        registered_root=registered_root,
        apply=True,
    )
    assert rerun["moved"] == 0
    assert rerun["planned_csv_rewrites"] == 0
    assert rerun["planned_db_rewrites"] == 0

def test_register_missing_requires_details_for_new_item(conn):
    with pytest.raises(AppError) as exc_info:
        service.register_missing_items_from_rows(
            conn,
            [
                {
                    "supplier": "SupplierA",
                    "item_number": "UNRESOLVED-001",
                    "resolution_type": "new_item",
                    "category": "",
                    "url": "",
                    "description": "",
                }
            ],
        )

    assert exc_info.value.code == "MISSING_ITEM_UNRESOLVED"

def test_register_missing_new_item_uses_manufacturer_from_csv(conn):
    result = service.register_missing_items_from_rows(
        conn,
        [
            {
                "supplier": "SupplierA",
                "item_number": "MFG-SPEC-001",
                "manufacturer_name": "MFG-SPEC",
                "resolution_type": "new_item",
                "category": "Lens",
                "url": "",
                "description": "",
            }
        ],
    )

    assert result["created_items"] == 1
    row = conn.execute(
        """
        SELECT i.item_number, m.name AS manufacturer_name
        FROM items_master i
        JOIN manufacturers m ON m.manufacturer_id = i.manufacturer_id
        WHERE i.item_number = ?
        """,
        ("MFG-SPEC-001",),
    ).fetchone()
    assert row is not None
    assert row["manufacturer_name"] == "MFG-SPEC"

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
            "pdf_link": "",
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
                "pdf_link": "",
            }
        ],
    )

    assert result["status"] == "ok"
    order = service.get_order(conn, int(result["order_ids"][0]))
    assert int(order["item_id"]) == int(item["item_id"])
    assert int(order["ordered_quantity"]) == 2
    assert int(order["order_amount"]) == 6

def test_register_missing_items_alias_uses_case_insensitive_supplier_lookup(conn):
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

    result = service.register_missing_items_from_rows(
        conn,
        [
            {
                "supplier": "suppliercase",
                "item_number": "CASE-ALIAS-001",
                "resolution_type": "alias",
                "canonical_item_number": "CASE-CANONICAL-001",
                "units_per_order": "2",
            }
        ],
    )

    assert result["created_aliases"] == 1
    aliases = service.list_supplier_item_aliases(conn, int(supplier["supplier_id"]))
    assert len(aliases) == 1
    assert aliases[0]["ordered_item_number"] == "CASE-ALIAS-001"

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
                "pdf_link": "",
            }
        ],
    )

    assert result["status"] == "ok"
    order = service.get_order(conn, int(result["order_ids"][0]))
    assert int(order["item_id"]) == int(item["item_id"])
    assert int(order["ordered_quantity"]) == 2
    assert int(order["order_amount"]) == 20

def test_register_unregistered_missing_items_reads_consolidated_register_folder(conn, tmp_path: Path):
    unregistered_root = tmp_path / "quotations" / "unregistered"
    registered_root = tmp_path / "quotations" / "registered"
    register_dir = unregistered_root / "missing_item_registers"
    register_dir.mkdir(parents=True, exist_ok=True)

    register_csv = register_dir / "batch_missing_items_registration_20260302_120000.csv"
    with register_csv.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(
            fp,
            fieldnames=[
                "source_csv",
                "source_supplier",
                "item_number",
                "supplier",
                "resolution_type",
                "category",
                "url",
                "description",
                "canonical_item_number",
                "units_per_order",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "source_csv": "quotations/unregistered/csv_files/SupplierBatch/QB-001.csv",
                "source_supplier": "SupplierBatch",
                "item_number": "BATCH-NEW-001",
                "supplier": "SupplierBatch",
                "resolution_type": "new_item",
                "category": "Lens",
                "url": "",
                "description": "",
                "canonical_item_number": "",
                "units_per_order": "",
            }
        )

    result = service.register_unregistered_missing_items_csvs(
        conn,
        unregistered_root=unregistered_root,
        registered_root=registered_root,
    )
    conn.commit()

    assert result["status"] == "ok"
    assert result["succeeded"] == 1
    assert not register_csv.exists()
    moved = registered_root / "csv_files" / "UNKNOWN" / register_csv.name
    assert moved.exists()

    row = conn.execute(
        """
        SELECT i.item_number
        FROM items_master i
        JOIN manufacturers m ON m.manufacturer_id = i.manufacturer_id
        WHERE i.item_number = ? AND m.name = ?
        """,
        ("BATCH-NEW-001", "UNKNOWN"),
    ).fetchone()
    assert row is not None

def test_import_unregistered_orders_missing_items_same_csv_name_different_suppliers_preserves_rows(conn, tmp_path: Path):
    unregistered_root = tmp_path / "quotations" / "unregistered"
    registered_root = tmp_path / "quotations" / "registered"

    for supplier in ("SupplierA", "SupplierB"):
        supplier_csv_dir = unregistered_root / "csv_files" / supplier
        supplier_csv_dir.mkdir(parents=True, exist_ok=True)
        csv_path = supplier_csv_dir / "Q-001.csv"
        with csv_path.open("w", encoding="utf-8", newline="") as fp:
            writer = csv.DictWriter(
                fp,
                fieldnames=[
                    "item_number",
                    "quantity",
                    "quotation_number",
                    "issue_date",
                    "order_date",
                    "expected_arrival",
                    "pdf_link",
                ],
            )
            writer.writeheader()
            writer.writerow(
                {
                    "item_number": f"MISSING-{supplier}",
                    "quantity": "1",
                    "quotation_number": f"Q-{supplier}",
                    "issue_date": "2026-02-20",
                    "order_date": "2026-02-21",
                    "expected_arrival": "2026-02-28",
                    "pdf_link": "",
                }
            )

    captured_paths: list[str] = []
    original_writer = service._write_batch_missing_items_register

    def _capture_missing_paths(missing_reports, *, output_dir):
        captured_paths.extend(str(report.get("missing_csv_path", "")) for report in missing_reports)
        return original_writer(missing_reports, output_dir=output_dir)

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(service, "_write_batch_missing_items_register", _capture_missing_paths)
    try:
        result = service.import_unregistered_order_csvs(
            conn,
            unregistered_root=unregistered_root,
            registered_root=registered_root,
        )
    finally:
        monkeypatch.undo()

    assert result["status"] == "ok"
    assert result["missing_items"] == 2
    register_path = result.get("missing_items_register_csv")
    assert register_path is not None

    with Path(register_path).open("r", encoding="utf-8", newline="") as fp:
        rows = list(csv.DictReader(fp))

    assert len(rows) == 2
    assert {row["source_supplier"] for row in rows} == {"SupplierA", "SupplierB"}
    assert any("SupplierA__Q-001_missing_items_registration.csv" in path for path in captured_paths)
    assert any("SupplierB__Q-001_missing_items_registration.csv" in path for path in captured_paths)

def test_import_unregistered_orders_missing_items_batch_register_deduplicates_by_supplier_manufacturer_and_item_number(
    conn,
    tmp_path: Path,
):
    unregistered_root = tmp_path / "quotations" / "unregistered"
    registered_root = tmp_path / "quotations" / "registered"

    for supplier in ("SupplierA", "SupplierB"):
        supplier_csv_dir = unregistered_root / "csv_files" / supplier
        supplier_csv_dir.mkdir(parents=True, exist_ok=True)
        csv_path = supplier_csv_dir / f"{supplier}.csv"
        with csv_path.open("w", encoding="utf-8", newline="") as fp:
            writer = csv.DictWriter(
                fp,
                fieldnames=[
                    "item_number",
                    "quantity",
                    "quotation_number",
                    "issue_date",
                    "order_date",
                    "expected_arrival",
                    "pdf_link",
                ],
            )
            writer.writeheader()
            writer.writerow(
                {
                    "item_number": "DUP-001",
                    "quantity": "1",
                    "quotation_number": f"Q-{supplier}",
                    "issue_date": "2026-02-20",
                    "order_date": "2026-02-21",
                    "expected_arrival": "2026-02-28",
                    "pdf_link": "",
                }
            )

    result = service.import_unregistered_order_csvs(
        conn,
        unregistered_root=unregistered_root,
        registered_root=registered_root,
    )

    register_path = result.get("missing_items_register_csv")
    assert register_path is not None

    with Path(register_path).open("r", encoding="utf-8", newline="") as fp:
        rows = list(csv.DictReader(fp))

    assert result["missing_items"] == 2
    assert len(rows) == 2
    assert {row["source_supplier"] for row in rows} == {"SupplierA", "SupplierB"}
    assert {row["item_number"] for row in rows} == {"DUP-001"}
    assert {row["manufacturer_name"] for row in rows} == {""}

def test_import_unregistered_orders_keeps_per_file_missing_csv_when_batch_register_write_fails(
    conn,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    unregistered_root = tmp_path / "quotations" / "unregistered"
    registered_root = tmp_path / "quotations" / "registered"
    supplier_csv_dir = unregistered_root / "csv_files" / "SupplierFail"
    supplier_csv_dir.mkdir(parents=True, exist_ok=True)

    csv_path = supplier_csv_dir / "Q-FAIL-MISSING.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(
            fp,
            fieldnames=[
                "item_number",
                "quantity",
                "quotation_number",
                "issue_date",
                "order_date",
                "expected_arrival",
                "pdf_link",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "item_number": "MISSING-FAIL-001",
                "quantity": "1",
                "quotation_number": "Q-FAIL-MISSING",
                "issue_date": "2026-02-20",
                "order_date": "2026-02-21",
                "expected_arrival": "2026-02-28",
                "pdf_link": "",
            }
        )

    def _raise_write(*args, **kwargs):
        raise OSError("simulated batch write failure")

    monkeypatch.setattr(service, "_write_batch_missing_items_register", _raise_write)

    with pytest.raises(OSError, match="simulated batch write failure"):
        service.import_unregistered_order_csvs(
            conn,
            unregistered_root=unregistered_root,
            registered_root=registered_root,
        )

    temp_register = unregistered_root / "missing_item_registers" / "SupplierFail__Q-FAIL-MISSING_missing_items_registration.csv"
    assert temp_register.exists()

def test_update_and_delete_quotation_syncs_csv_and_db(conn, tmp_path: Path, monkeypatch):
    item = _create_basic_item(conn, item_number="SYNC-ITEM-001")
    roots = service.build_roots(
        unregistered_root=tmp_path / "quotations" / "unregistered",
        registered_root=tmp_path / "quotations" / "registered",
    )
    service.ensure_roots(roots)
    monkeypatch.setattr(service, "build_roots", lambda **_: roots)

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
                "pdf_link",
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
                "pdf_link": "",
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
            "pdf_link": "quotations/registered/pdf_files/SupplierSync/Q-SYNC-001.pdf",
        },
    )
    assert updated["issue_date"] == "2026-03-05"
    assert updated["pdf_link"] == "quotations/registered/pdf_files/SupplierSync/Q-SYNC-001.pdf"

    with csv_path.open("r", encoding="utf-8", newline="") as fp:
        rows = list(csv.DictReader(fp))
    assert rows[0]["issue_date"] == "2026-03-05"
    assert rows[0]["pdf_link"] == "quotations/registered/pdf_files/SupplierSync/Q-SYNC-001.pdf"

    delete_result = service.delete_quotation(conn, int(order["quotation_id"]))
    assert delete_result["deleted"] is True
    assert conn.execute("SELECT COUNT(*) AS c FROM orders").fetchone()["c"] == 0
    assert conn.execute("SELECT COUNT(*) AS c FROM quotations").fetchone()["c"] == 0

    with csv_path.open("r", encoding="utf-8", newline="") as fp:
        remaining_rows = list(csv.DictReader(fp))
    assert remaining_rows == []

def test_update_and_delete_order_with_duplicate_item_rows_only_touches_target_order(conn, tmp_path: Path, monkeypatch):
    item = _create_basic_item(conn, item_number="SYNC-DUP-001")
    roots = service.build_roots(
        unregistered_root=tmp_path / "quotations" / "unregistered",
        registered_root=tmp_path / "quotations" / "registered",
    )
    service.ensure_roots(roots)
    monkeypatch.setattr(service, "build_roots", lambda **_: roots)

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
                "pdf_link",
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
                "pdf_link": "",
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
                "pdf_link": "",
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

    service.update_order(conn, first_order_id, {"expected_arrival": "2026-04-20"})

    with csv_path.open("r", encoding="utf-8", newline="") as fp:
        rows_after_update = list(csv.DictReader(fp))
    assert rows_after_update[0]["expected_arrival"] == "2026-04-20"
    assert rows_after_update[1]["expected_arrival"] == "2026-04-11"

    service.delete_order(conn, second_order_id)

    with csv_path.open("r", encoding="utf-8", newline="") as fp:
        rows_after_delete = list(csv.DictReader(fp))
    assert len(rows_after_delete) == 1
    assert rows_after_delete[0]["quantity"] == "3"

def test_update_order_can_split_partial_eta_with_csv_sync(conn, tmp_path: Path, monkeypatch):
    item = _create_basic_item(conn, item_number="SYNC-SPLIT-001")
    roots = service.build_roots(
        unregistered_root=tmp_path / "quotations" / "unregistered",
        registered_root=tmp_path / "quotations" / "registered",
    )
    service.ensure_roots(roots)
    monkeypatch.setattr(service, "build_roots", lambda **_: roots)

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
                "pdf_link",
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
                "pdf_link": "",
            }
        )

    import_result = service.import_orders_from_csv_path(
        conn,
        supplier_name="SupplierSplit",
        csv_path=csv_path,
    )
    assert import_result["status"] == "ok"
    order_id = int(import_result["order_ids"][0])

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

    with csv_path.open("r", encoding="utf-8", newline="") as fp:
        rows_after_update = list(csv.DictReader(fp))
    assert len(rows_after_update) == 2
    assert rows_after_update[0]["quantity"] == "20"
    assert rows_after_update[0]["expected_arrival"] == "2026-04-10"
    assert rows_after_update[1]["quantity"] == "30"
    assert rows_after_update[1]["expected_arrival"] == "2026-04-25"


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
                "pdf_link": "",
            }
        ],
        source_name="rfq_order_guard.csv",
    )
    order_id = int(imported["order_ids"][0])

    service.update_rfq_line(
        conn,
        line_id,
        {
            "linked_order_id": order_id,
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


def test_merge_open_orders_records_lineage_and_syncs_csv(conn, tmp_path: Path, monkeypatch):
    item = _create_basic_item(conn, item_number="SYNC-MERGE-001")
    roots = service.build_roots(
        unregistered_root=tmp_path / "quotations" / "unregistered",
        registered_root=tmp_path / "quotations" / "registered",
    )
    service.ensure_roots(roots)
    monkeypatch.setattr(service, "build_roots", lambda **_: roots)

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
                "pdf_link",
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
                "pdf_link": "",
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
                "pdf_link": "",
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

    merged = service.merge_open_orders(
        conn,
        source_order_id=first_order_id,
        target_order_id=second_order_id,
        expected_arrival="2026-05-30",
    )
    assert merged["merged"] is True
    assert merged["target_order"]["order_amount"] == 50
    assert merged["target_order"]["expected_arrival"] == "2026-05-30"

    lineage = service.list_order_lineage_events(conn, order_id=second_order_id)
    assert any(
        event["event_type"] == "ETA_MERGE"
        and int(event["source_order_id"]) == first_order_id
        and int(event["target_order_id"]) == second_order_id
        for event in lineage
    )

    with csv_path.open("r", encoding="utf-8", newline="") as fp:
        rows_after = list(csv.DictReader(fp))
    assert len(rows_after) == 1
    assert rows_after[0]["quantity"] == "50"
    assert rows_after[0]["expected_arrival"] == "2026-05-30"




def test_merge_open_orders_removes_correct_source_row_for_nonfirst_sibling(conn, tmp_path: Path, monkeypatch):
    item = _create_basic_item(conn, item_number="SYNC-MERGE-ORDER-001")
    roots = service.build_roots(
        unregistered_root=tmp_path / "quotations" / "unregistered",
        registered_root=tmp_path / "quotations" / "registered",
    )
    service.ensure_roots(roots)
    monkeypatch.setattr(service, "build_roots", lambda **_: roots)

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
                "pdf_link",
            ],
        )
        writer.writeheader()
        writer.writerow({"supplier": "SupplierMergeOrder", "item_number": item["item_number"], "quantity": "10", "quotation_number": "Q-MERGE-ORDER-001", "issue_date": "2026-06-01", "order_date": "2026-06-01", "expected_arrival": "2026-06-10", "pdf_link": ""})
        writer.writerow({"supplier": "SupplierMergeOrder", "item_number": item["item_number"], "quantity": "20", "quotation_number": "Q-MERGE-ORDER-001", "issue_date": "2026-06-01", "order_date": "2026-06-01", "expected_arrival": "2026-06-20", "pdf_link": ""})
        writer.writerow({"supplier": "SupplierMergeOrder", "item_number": item["item_number"], "quantity": "30", "quotation_number": "Q-MERGE-ORDER-001", "issue_date": "2026-06-01", "order_date": "2026-06-01", "expected_arrival": "2026-06-30", "pdf_link": ""})

    import_result = service.import_orders_from_csv_path(conn, supplier_name="SupplierMergeOrder", csv_path=csv_path)
    assert import_result["status"] == "ok"
    first_order_id, second_order_id, third_order_id = [int(v) for v in import_result["order_ids"]]

    merged = service.merge_open_orders(
        conn,
        source_order_id=second_order_id,
        target_order_id=third_order_id,
        expected_arrival="2026-07-05",
    )
    assert merged["merged"] is True

    with csv_path.open("r", encoding="utf-8", newline="") as fp:
        rows_after = list(csv.DictReader(fp))

    assert len(rows_after) == 2
    assert rows_after[0]["quantity"] == "10"
    assert rows_after[0]["expected_arrival"] == "2026-06-10"
    assert rows_after[1]["quantity"] == "50"
    assert rows_after[1]["expected_arrival"] == "2026-07-05"
    assert conn.execute("SELECT COUNT(*) AS c FROM orders WHERE order_id = ?", (second_order_id,)).fetchone()["c"] == 0
    assert conn.execute("SELECT COUNT(*) AS c FROM orders WHERE order_id = ?", (first_order_id,)).fetchone()["c"] == 1
    assert conn.execute("SELECT COUNT(*) AS c FROM orders WHERE order_id = ?", (third_order_id,)).fetchone()["c"] == 1


def test_split_order_appends_new_csv_row_after_sibling_block(conn, tmp_path: Path, monkeypatch):
    item = _create_basic_item(conn, item_number="SYNC-SPLIT-ORDER-001")
    roots = service.build_roots(
        unregistered_root=tmp_path / "quotations" / "unregistered",
        registered_root=tmp_path / "quotations" / "registered",
    )
    service.ensure_roots(roots)
    monkeypatch.setattr(service, "build_roots", lambda **_: roots)

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
                "pdf_link",
            ],
        )
        writer.writeheader()
        writer.writerow({"supplier": "SupplierSplitOrder", "item_number": item["item_number"], "quantity": "10", "quotation_number": "Q-SPLIT-ORDER-001", "issue_date": "2026-08-01", "order_date": "2026-08-01", "expected_arrival": "2026-08-10", "pdf_link": ""})
        writer.writerow({"supplier": "SupplierSplitOrder", "item_number": item["item_number"], "quantity": "10", "quotation_number": "Q-SPLIT-ORDER-001", "issue_date": "2026-08-01", "order_date": "2026-08-01", "expected_arrival": "2026-08-20", "pdf_link": ""})
        writer.writerow({"supplier": "SupplierSplitOrder", "item_number": item["item_number"], "quantity": "10", "quotation_number": "Q-SPLIT-ORDER-001", "issue_date": "2026-08-01", "order_date": "2026-08-01", "expected_arrival": "2026-08-30", "pdf_link": ""})

    import_result = service.import_orders_from_csv_path(conn, supplier_name="SupplierSplitOrder", csv_path=csv_path)
    assert import_result["status"] == "ok"
    _, second_order_id, _ = [int(v) for v in import_result["order_ids"]]

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

    assert len(rows_after) == 4
    assert rows_after[0]["quantity"] == "10"
    assert rows_after[0]["expected_arrival"] == "2026-08-10"
    assert rows_after[1]["quantity"] == "6"
    assert rows_after[1]["expected_arrival"] == "2026-08-20"
    assert rows_after[2]["quantity"] == "10"
    assert rows_after[2]["expected_arrival"] == "2026-08-30"
    assert rows_after[3]["quantity"] == "4"
    assert rows_after[3]["expected_arrival"] == "2026-09-05"

def test_delete_quotation_rejects_if_any_linked_order_arrived(conn):
    item = _create_basic_item(conn, item_number="ARRIVE-GUARD-001")
    csv_content = "\n".join(
        [
            "item_number,quantity,quotation_number,issue_date,order_date,expected_arrival,pdf_link",
            f"{item['item_number']},2,Q-ARRIVE-001,2026-04-01,2026-04-01,2026-04-10,",
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
                "pdf_link": "",
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
                "pdf_link": "",
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
                "pdf_link": "",
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
                "pdf_link": "",
            },
            {
                "item_number": item["item_number"],
                "quantity": "1",
                "quotation_number": "Q-PLAN-SOURCES-002",
                "issue_date": "2026-03-01",
                "order_date": "2026-03-03",
                "expected_arrival": "3000-01-15",
                "pdf_link": "",
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
                "pdf_link": "",
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
                "pdf_link": "",
            },
            {
                "item_number": item["item_number"],
                "quantity": "5",
                "quotation_number": "Q-RFQ-ORDER-SYNC-002",
                "issue_date": "2026-03-01",
                "order_date": "2026-03-03",
                "expected_arrival": FUTURE_TARGET_DATE,
                "pdf_link": "",
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
            "linked_order_id": first_order_id,
        },
    )
    assert quoted["line"]["status"] == "QUOTED"
    assert quoted["line"]["linked_order_id"] is None
    assert service.get_order(conn, first_order_id)["project_id"] is None

    ordered = service.update_rfq_line(
        conn,
        line_id,
        {
            "linked_order_id": first_order_id,
            "status": "ORDERED",
        },
    )
    assert ordered["line"]["status"] == "ORDERED"
    assert int(ordered["line"]["linked_order_id"]) == first_order_id
    assert int(service.get_order(conn, first_order_id)["project_id"]) == project["project_id"]

    replaced = service.update_rfq_line(
        conn,
        line_id,
        {
            "linked_order_id": second_order_id,
            "status": "ORDERED",
        },
    )
    assert int(replaced["line"]["linked_order_id"]) == second_order_id
    assert service.get_order(conn, first_order_id)["project_id"] is None
    assert int(service.get_order(conn, second_order_id)["project_id"]) == project["project_id"]

    cleared = service.update_rfq_line(
        conn,
        line_id,
        {
            "linked_order_id": second_order_id,
            "status": "QUOTED",
        },
    )
    assert cleared["line"]["status"] == "QUOTED"
    assert cleared["line"]["linked_order_id"] is None
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
                "pdf_link",
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
                "pdf_link": "",
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
            "linked_order_id": order_id,
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
                "pdf_link": "",
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
                "pdf_link": "",
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
                "pdf_link": "",
            }
        ],
        source_name="manual_project_rfq.csv",
    )
    order_id = int(imported["order_ids"][0])

    # Manually assign the project to the order BEFORE linking to the RFQ
    service.update_order(conn, order_id, {"project_id": project["project_id"]})
    assert int(service.get_order(conn, order_id)["project_id"]) == project["project_id"]

    # Link the order to the RFQ (same project — allowed)
    service.update_rfq_line(conn, line_id, {"linked_order_id": order_id, "status": "ORDERED"})
    assert int(service.get_order(conn, order_id)["project_id"]) == project["project_id"]

    # Remove the RFQ link — manual project_id must survive
    service.update_rfq_line(
        conn,
        line_id,
        {"linked_order_id": order_id, "status": "QUOTED", "expected_arrival": FUTURE_TARGET_DATE},
    )
    assert int(service.get_order(conn, order_id)["project_id"]) == project["project_id"], (
        "Manually-assigned project_id must not be cleared when the RFQ link is removed"
    )
