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
    assert _inventory_qty(conn, item["item_id"], "RESERVED") == 0


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
    assert _inventory_qty(conn, item["item_id"], "STOCK") == 6
    assert _inventory_qty(conn, item["item_id"], "RESERVED") == 4


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
    assert _inventory_qty(conn, item["item_id"], "STOCK") == 3
    assert _inventory_qty(conn, item["item_id"], "RESERVED") == 4


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
