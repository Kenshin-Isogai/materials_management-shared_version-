from __future__ import annotations

import csv
from pathlib import Path

import pytest

from app.errors import AppError
from app import service

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
