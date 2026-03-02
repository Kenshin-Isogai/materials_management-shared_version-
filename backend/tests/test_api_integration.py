from __future__ import annotations

import csv
from io import StringIO
from pathlib import Path


def test_health_endpoint(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["data"]["healthy"] is True


def test_auth_capabilities_endpoint_defaults_and_header(client):
    response = client.get("/api/auth/capabilities")
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["auth_mode"] == "none"
    assert payload["auth_enforced"] is False
    assert payload["planned_roles"] == ["admin", "operator", "viewer"]
    assert payload["effective_role"] == "operator"

    header_response = client.get("/api/auth/capabilities", headers={"X-User-Role": "Viewer"})
    assert header_response.status_code == 200
    header_payload = header_response.json()["data"]
    assert header_payload["effective_role"] == "viewer"


def test_inventory_reservation_and_dashboard_flow(client):
    manufacturer = client.post("/api/manufacturers", json={"name": "API-MFG"}).json()["data"]
    item = client.post(
        "/api/items",
        json={
            "item_number": "API-ITEM-001",
            "manufacturer_id": manufacturer["manufacturer_id"],
            "category": "Mirror",
        },
    ).json()["data"]

    adjust = client.post(
        "/api/inventory/adjust",
        json={
            "item_id": item["item_id"],
            "quantity_delta": 10,
            "location": "STOCK",
            "note": "seed",
        },
    )
    assert adjust.status_code == 200
    assert adjust.json()["status"] == "ok"

    reserve = client.post(
        "/api/reservations",
        json={
            "item_id": item["item_id"],
            "quantity": 4,
            "purpose": "API test",
        },
    )
    assert reserve.status_code == 200
    assert reserve.json()["data"]["status"] == "ACTIVE"

    inventory = client.get(f"/api/inventory?item_id={item['item_id']}&per_page=50")
    assert inventory.status_code == 200
    rows = inventory.json()["data"]
    quantities = {row["location"]: row["quantity"] for row in rows}
    assert quantities["STOCK"] == 6
    assert quantities["RESERVED"] == 4

    dashboard = client.get("/api/dashboard/summary")
    assert dashboard.status_code == 200
    payload = dashboard.json()
    assert payload["status"] == "ok"
    assert "overdue_orders" in payload["data"]
    assert "recent_activity" in payload["data"]


def test_reservation_partial_release_and_consume_endpoints(client):
    manufacturer = client.post("/api/manufacturers", json={"name": "API-RES-PART-MFG"}).json()["data"]
    item = client.post(
        "/api/items",
        json={
            "item_number": "API-RES-PART-001",
            "manufacturer_id": manufacturer["manufacturer_id"],
            "category": "Lens",
        },
    ).json()["data"]

    seed = client.post(
        "/api/inventory/adjust",
        json={
            "item_id": item["item_id"],
            "quantity_delta": 12,
            "location": "STOCK",
            "note": "seed",
        },
    )
    assert seed.status_code == 200

    reservation = client.post(
        "/api/reservations",
        json={
            "item_id": item["item_id"],
            "quantity": 8,
            "purpose": "partial API test",
        },
    )
    assert reservation.status_code == 200
    reservation_id = reservation.json()["data"]["reservation_id"]

    partial_release = client.post(
        f"/api/reservations/{reservation_id}/release",
        json={"quantity": 3},
    )
    assert partial_release.status_code == 200
    released_data = partial_release.json()["data"]
    assert released_data["status"] == "ACTIVE"
    assert released_data["quantity"] == 5

    partial_consume = client.post(
        f"/api/reservations/{reservation_id}/consume",
        json={"quantity": 2},
    )
    assert partial_consume.status_code == 200
    consumed_data = partial_consume.json()["data"]
    assert consumed_data["status"] == "ACTIVE"
    assert consumed_data["quantity"] == 3

    inventory = client.get(f"/api/inventory?item_id={item['item_id']}&per_page=50")
    assert inventory.status_code == 200
    rows = inventory.json()["data"]
    quantities = {row["location"]: row["quantity"] for row in rows}
    assert quantities["STOCK"] == 7
    assert quantities["RESERVED"] == 3

    over_release = client.post(
        f"/api/reservations/{reservation_id}/release",
        json={"quantity": 10},
    )
    assert over_release.status_code == 422
    over_payload = over_release.json()
    assert over_payload["status"] == "error"
    assert over_payload["error"]["code"] == "INVALID_RESERVATION_QUANTITY"


def test_unregistered_order_import_endpoint(client, tmp_path: Path):
    client.post("/api/manufacturers", json={"name": "API-UNREG-MFG"})
    client.post(
        "/api/items",
        json={
            "item_number": "API-UNREG-ITEM",
            "manufacturer_name": "API-UNREG-MFG",
            "category": "Lens",
        },
    )

    unregistered_root = tmp_path / "quotations" / "unregistered"
    registered_root = tmp_path / "quotations" / "registered"
    supplier_csv_dir = unregistered_root / "csv_files" / "SupplierEndpoint"
    supplier_pdf_dir = unregistered_root / "pdf_files" / "SupplierEndpoint"
    supplier_csv_dir.mkdir(parents=True, exist_ok=True)
    supplier_pdf_dir.mkdir(parents=True, exist_ok=True)

    pdf_path = supplier_pdf_dir / "QE-001.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 endpoint test")

    csv_path = supplier_csv_dir / "QE-001.csv"
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
                "item_number": "API-UNREG-ITEM",
                "quantity": "5",
                "quotation_number": "QE-001",
                "issue_date": "2026-02-20",
                "order_date": "2026-02-21",
                "expected_arrival": "2026-03-01",
                "pdf_link": "QE-001.pdf",
            }
        )

    response = client.post(
        "/api/orders/import-unregistered",
        json={
            "unregistered_root": str(unregistered_root),
            "registered_root": str(registered_root),
            "continue_on_error": False,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["data"]["succeeded"] == 1
    assert not csv_path.exists()
    assert (registered_root / "csv_files" / "SupplierEndpoint" / "QE-001.csv").exists()
    assert (registered_root / "pdf_files" / "SupplierEndpoint" / "QE-001.pdf").exists()


def test_unregistered_order_import_endpoint_accepts_unregistered_pdf_path(client, tmp_path: Path):
    client.post("/api/manufacturers", json={"name": "API-UNREG-PATH-MFG"})
    client.post(
        "/api/items",
        json={
            "item_number": "API-UNREG-PATH-ITEM",
            "manufacturer_name": "API-UNREG-PATH-MFG",
            "category": "Lens",
        },
    )

    unregistered_root = tmp_path / "quotations" / "unregistered"
    registered_root = tmp_path / "quotations" / "registered"
    supplier_csv_dir = unregistered_root / "csv_files" / "SupplierPath"
    supplier_pdf_dir = unregistered_root / "pdf_files" / "SupplierPath"
    supplier_csv_dir.mkdir(parents=True, exist_ok=True)
    supplier_pdf_dir.mkdir(parents=True, exist_ok=True)

    pdf_path = supplier_pdf_dir / "QP-001.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 endpoint path test")

    csv_path = supplier_csv_dir / "QP-001.csv"
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
                "item_number": "API-UNREG-PATH-ITEM",
                "quantity": "2",
                "quotation_number": "QP-001",
                "issue_date": "2026-02-20",
                "order_date": "2026-02-21",
                "expected_arrival": "2026-03-01",
                "pdf_link": "quotations/unregistered/pdf_files/SupplierPath/QP-001.pdf",
            }
        )

    response = client.post(
        "/api/orders/import-unregistered",
        json={
            "unregistered_root": str(unregistered_root),
            "registered_root": str(registered_root),
            "continue_on_error": False,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["data"]["succeeded"] == 1
    assert not csv_path.exists()
    assert (registered_root / "csv_files" / "SupplierPath" / "QP-001.csv").exists()
    assert (registered_root / "pdf_files" / "SupplierPath" / "QP-001.pdf").exists()


def test_order_import_returns_missing_item_details(client):
    output = StringIO()
    writer = csv.DictWriter(
        output,
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
            "quotation_number": "QM-001",
            "issue_date": "2026-02-21",
            "order_date": "2026-02-22",
            "expected_arrival": "2026-03-01",
            "pdf_link": "QM-001.pdf",
        }
    )
    response = client.post(
        "/api/orders/import",
        files={"file": ("orders.csv", output.getvalue().encode("utf-8"), "text/csv")},
        data={"supplier_name": "SupplierMissing", "default_order_date": "2026-02-22"},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "missing_items"
    assert data["missing_count"] == 1
    assert data["rows"][0]["row"] == 2
    assert data["rows"][0]["supplier"] == "SupplierMissing"
    assert data["rows"][0]["item_number"] == "MISSING-ITEM-001"


def test_order_import_autonormalizes_pdf_link_filename(client):
    client.post("/api/manufacturers", json={"name": "API-MANUAL-MFG"})
    client.post(
        "/api/items",
        json={
            "item_number": "API-MANUAL-ITEM",
            "manufacturer_name": "API-MANUAL-MFG",
            "category": "Lens",
        },
    )

    output = StringIO()
    writer = csv.DictWriter(
        output,
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
            "item_number": "API-MANUAL-ITEM",
            "quantity": "2",
            "quotation_number": "Q-MANUAL-001",
            "issue_date": "2026-02-21",
            "order_date": "2026-02-22",
            "expected_arrival": "2026-03-01",
            "pdf_link": "Q-MANUAL-001.pdf",
        }
    )
    response = client.post(
        "/api/orders/import",
        files={"file": ("orders.csv", output.getvalue().encode("utf-8"), "text/csv")},
        data={"supplier_name": "SupplierManual"},
    )
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "ok"

    listing = client.get("/api/quotations?supplier=SupplierManual&per_page=50")
    assert listing.status_code == 200
    rows = listing.json()["data"]
    assert len(rows) == 1
    assert (
        rows[0]["pdf_link"]
        == "quotations/registered/pdf_files/SupplierManual/Q-MANUAL-001.pdf"
    )


def test_order_import_rejects_unregistered_pdf_link_path(client):
    client.post("/api/manufacturers", json={"name": "API-MANUAL-VALID-MFG"})
    client.post(
        "/api/items",
        json={
            "item_number": "API-MANUAL-VALID-ITEM",
            "manufacturer_name": "API-MANUAL-VALID-MFG",
            "category": "Lens",
        },
    )

    output = StringIO()
    writer = csv.DictWriter(
        output,
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
            "item_number": "API-MANUAL-VALID-ITEM",
            "quantity": "1",
            "quotation_number": "Q-MANUAL-002",
            "issue_date": "2026-02-21",
            "order_date": "2026-02-22",
            "expected_arrival": "2026-03-01",
            "pdf_link": "quotations/unregistered/pdf_files/SupplierManual/Q-MANUAL-002.pdf",
        }
    )
    response = client.post(
        "/api/orders/import",
        files={"file": ("orders.csv", output.getvalue().encode("utf-8"), "text/csv")},
        data={"supplier_name": "SupplierManual"},
    )
    assert response.status_code == 422
    payload = response.json()
    assert payload["status"] == "error"
    assert payload["error"]["code"] == "INVALID_CSV"
    assert "quotations/registered/pdf_files" in payload["error"]["message"]


def test_order_import_rejects_duplicate_quotation_for_same_supplier(client):
    client.post("/api/manufacturers", json={"name": "API-DUP-QUOTE-MFG"})
    client.post(
        "/api/items",
        json={
            "item_number": "API-DUP-QUOTE-ITEM",
            "manufacturer_name": "API-DUP-QUOTE-MFG",
            "category": "Lens",
        },
    )

    output = StringIO()
    writer = csv.DictWriter(
        output,
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
            "item_number": "API-DUP-QUOTE-ITEM",
            "quantity": "1",
            "quotation_number": "Q-DUP-001",
            "issue_date": "2026-02-21",
            "order_date": "2026-02-22",
            "expected_arrival": "2026-03-01",
            "pdf_link": "Q-DUP-001.pdf",
        }
    )

    first = client.post(
        "/api/orders/import",
        files={"file": ("orders.csv", output.getvalue().encode("utf-8"), "text/csv")},
        data={"supplier_name": "SupplierDup"},
    )
    assert first.status_code == 200
    assert first.json()["data"]["status"] == "ok"

    second = client.post(
        "/api/orders/import",
        files={"file": ("orders.csv", output.getvalue().encode("utf-8"), "text/csv")},
        data={"supplier_name": "SupplierDup"},
    )
    assert second.status_code == 409
    payload = second.json()
    assert payload["status"] == "error"
    assert payload["error"]["code"] == "DUPLICATE_QUOTATION_IMPORT"
    assert payload["error"]["details"]["quotation_numbers"] == ["Q-DUP-001"]


def test_order_import_accepts_slash_date_format(client):
    client.post("/api/manufacturers", json={"name": "API-SLASH-DATE-MFG"})
    client.post(
        "/api/items",
        json={
            "item_number": "API-SLASH-DATE-ITEM",
            "manufacturer_name": "API-SLASH-DATE-MFG",
            "category": "Lens",
        },
    )

    output = StringIO()
    writer = csv.DictWriter(
        output,
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
            "item_number": "API-SLASH-DATE-ITEM",
            "quantity": "1",
            "quotation_number": "Q-SLASH-001",
            "issue_date": "2026/2/21",
            "order_date": "2026/2/22",
            "expected_arrival": "2026/3/1",
            "pdf_link": "",
        }
    )
    response = client.post(
        "/api/orders/import",
        files={"file": ("orders.csv", output.getvalue().encode("utf-8"), "text/csv")},
        data={"supplier_name": "SupplierSlashDate"},
    )
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "ok"


def test_items_import_endpoint(client):
    output = StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=["item_number", "manufacturer_name", "category", "url", "description"],
    )
    writer.writeheader()
    writer.writerow(
        {
            "item_number": "CSV-ITEM-001",
            "manufacturer_name": "CSV-MFG",
            "category": "Lens",
            "url": "",
            "description": "first row",
        }
    )
    writer.writerow(
        {
            "item_number": "CSV-ITEM-001",
            "manufacturer_name": "CSV-MFG",
            "category": "Lens",
            "url": "",
            "description": "duplicate row",
        }
    )
    writer.writerow(
        {
            "item_number": "",
            "manufacturer_name": "CSV-MFG",
            "category": "Lens",
            "url": "",
            "description": "invalid row",
        }
    )

    response = client.post(
        "/api/items/import",
        files={"file": ("items.csv", output.getvalue().encode("utf-8"), "text/csv")},
        data={"continue_on_error": "true"},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "partial"
    assert data["processed"] == 3
    assert data["created_count"] == 1
    assert data["duplicate_count"] == 1
    assert data["failed_count"] == 1

    created_rows = [row for row in data["rows"] if row["status"] == "created"]
    duplicate_rows = [row for row in data["rows"] if row["status"] == "duplicate"]
    error_rows = [row for row in data["rows"] if row["status"] == "error"]
    assert len(created_rows) == 1
    assert len(duplicate_rows) == 1
    assert len(error_rows) == 1

    listing = client.get("/api/items?q=CSV-ITEM-001&per_page=50")
    assert listing.status_code == 200
    rows = listing.json()["data"]
    assert len(rows) == 1
    assert rows[0]["item_number"] == "CSV-ITEM-001"


def test_items_import_endpoint_supports_alias_rows(client):
    output = StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "row_type",
            "item_number",
            "manufacturer_name",
            "category",
            "url",
            "description",
            "supplier",
            "canonical_item_number",
            "units_per_order",
        ],
    )
    writer.writeheader()
    writer.writerow(
        {
            "row_type": "item",
            "item_number": "CSV-ALIAS-CANONICAL",
            "manufacturer_name": "CSV-MFG",
            "category": "Lens",
            "url": "",
            "description": "canonical",
            "supplier": "",
            "canonical_item_number": "",
            "units_per_order": "",
        }
    )
    writer.writerow(
        {
            "row_type": "alias",
            "item_number": "CSV-ALIAS-CANONICAL-P4",
            "manufacturer_name": "",
            "category": "",
            "url": "",
            "description": "",
            "supplier": "CSV-ALIAS-SUPPLIER",
            "canonical_item_number": "CSV-ALIAS-CANONICAL",
            "units_per_order": "4",
        }
    )

    response = client.post(
        "/api/items/import",
        files={"file": ("items_alias.csv", output.getvalue().encode("utf-8"), "text/csv")},
        data={"continue_on_error": "true"},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "ok"
    assert data["processed"] == 2
    assert data["created_count"] == 2
    assert data["failed_count"] == 0

    alias_rows = [row for row in data["rows"] if row.get("entry_type") == "alias"]
    assert len(alias_rows) == 1

    suppliers = client.get("/api/suppliers")
    assert suppliers.status_code == 200
    supplier = next(
        row for row in suppliers.json()["data"] if row["name"] == "CSV-ALIAS-SUPPLIER"
    )
    alias_list = client.get(f"/api/suppliers/{supplier['supplier_id']}/aliases")
    assert alias_list.status_code == 200
    aliases = alias_list.json()["data"]
    assert len(aliases) == 1
    assert aliases[0]["ordered_item_number"] == "CSV-ALIAS-CANONICAL-P4"
    assert aliases[0]["canonical_item_number"] == "CSV-ALIAS-CANONICAL"
    assert aliases[0]["units_per_order"] == 4


def test_items_import_endpoint_supports_alias_rows_before_canonical_row(client):
    output = StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "row_type",
            "item_number",
            "manufacturer_name",
            "category",
            "url",
            "description",
            "supplier",
            "canonical_item_number",
            "units_per_order",
        ],
    )
    writer.writeheader()
    writer.writerow(
        {
            "row_type": "alias",
            "item_number": "CSV-ALIAS-FIRST-P5",
            "manufacturer_name": "",
            "category": "",
            "url": "",
            "description": "",
            "supplier": "CSV-ALIAS-FIRST-SUPPLIER",
            "canonical_item_number": "CSV-ALIAS-FIRST-CANONICAL",
            "units_per_order": "5",
        }
    )
    writer.writerow(
        {
            "row_type": "item",
            "item_number": "CSV-ALIAS-FIRST-CANONICAL",
            "manufacturer_name": "CSV-MFG",
            "category": "Lens",
            "url": "",
            "description": "canonical appears later",
            "supplier": "",
            "canonical_item_number": "",
            "units_per_order": "",
        }
    )

    response = client.post(
        "/api/items/import",
        files={"file": ("items_alias_before_canonical.csv", output.getvalue().encode("utf-8"), "text/csv")},
        data={"continue_on_error": "true"},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "ok"
    assert data["processed"] == 2
    assert data["created_count"] == 2
    assert data["failed_count"] == 0

    alias_rows = [row for row in data["rows"] if row.get("entry_type") == "alias"]
    assert len(alias_rows) == 1
    assert alias_rows[0]["item_number"] == "CSV-ALIAS-FIRST-P5"
    assert alias_rows[0]["canonical_item_number"] == "CSV-ALIAS-FIRST-CANONICAL"
    assert alias_rows[0]["units_per_order"] == 5

    suppliers = client.get("/api/suppliers")
    assert suppliers.status_code == 200
    supplier = next(
        row for row in suppliers.json()["data"] if row["name"] == "CSV-ALIAS-FIRST-SUPPLIER"
    )
    alias_list = client.get(f"/api/suppliers/{supplier['supplier_id']}/aliases")
    assert alias_list.status_code == 200
    aliases = alias_list.json()["data"]
    assert len(aliases) == 1
    assert aliases[0]["ordered_item_number"] == "CSV-ALIAS-FIRST-P5"
    assert aliases[0]["canonical_item_number"] == "CSV-ALIAS-FIRST-CANONICAL"
    assert aliases[0]["units_per_order"] == 5


def test_items_import_alias_rejects_direct_item_number_collision(client):
    client.post(
        "/api/items",
        json={
            "item_number": "CSV-ALIAS-CONFLICT",
            "manufacturer_name": "CSV-MFG",
            "category": "Lens",
        },
    )

    output = StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "row_type",
            "item_number",
            "supplier",
            "canonical_item_number",
            "units_per_order",
        ],
    )
    writer.writeheader()
    writer.writerow(
        {
            "row_type": "alias",
            "item_number": "CSV-ALIAS-CONFLICT",
            "supplier": "CSV-ALIAS-SUPPLIER",
            "canonical_item_number": "CSV-ALIAS-CONFLICT",
            "units_per_order": "2",
        }
    )

    response = client.post(
        "/api/items/import",
        files={"file": ("items_alias_conflict.csv", output.getvalue().encode("utf-8"), "text/csv")},
        data={"continue_on_error": "true"},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "error"
    assert data["processed"] == 1
    assert data["created_count"] == 0
    assert data["failed_count"] == 1
    assert data["rows"][0]["code"] == "ALIAS_CONFLICT_DIRECT_ITEM"


def test_items_import_job_undo_and_redo_flow(client):
    output = StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "row_type",
            "item_number",
            "manufacturer_name",
            "category",
            "url",
            "description",
            "supplier",
            "canonical_item_number",
            "units_per_order",
        ],
    )
    writer.writeheader()
    writer.writerow(
        {
            "row_type": "item",
            "item_number": "JOB-UNDO-CANONICAL",
            "manufacturer_name": "JOB-UNDO-MFG",
            "category": "Lens",
            "url": "",
            "description": "canonical row",
            "supplier": "",
            "canonical_item_number": "",
            "units_per_order": "",
        }
    )
    writer.writerow(
        {
            "row_type": "alias",
            "item_number": "JOB-UNDO-CANONICAL-P2",
            "manufacturer_name": "",
            "category": "",
            "url": "",
            "description": "",
            "supplier": "JOB-UNDO-SUPPLIER",
            "canonical_item_number": "JOB-UNDO-CANONICAL",
            "units_per_order": "2",
        }
    )

    response = client.post(
        "/api/items/import",
        files={"file": ("job_undo_items.csv", output.getvalue().encode("utf-8"), "text/csv")},
        data={"continue_on_error": "true"},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "ok"
    assert data["created_count"] == 2
    assert "import_job_id" in data
    import_job_id = int(data["import_job_id"])

    job_detail = client.get(f"/api/items/import-jobs/{import_job_id}")
    assert job_detail.status_code == 200
    assert job_detail.json()["data"]["job"]["import_job_id"] == import_job_id

    undo = client.post(f"/api/items/import-jobs/{import_job_id}/undo")
    assert undo.status_code == 200
    undo_data = undo.json()["data"]
    assert undo_data["status"] == "undone"
    assert undo_data["removed_items"] == 1
    assert undo_data["removed_aliases"] == 1

    items_after_undo = client.get("/api/items?q=JOB-UNDO-CANONICAL&per_page=50").json()["data"]
    assert items_after_undo == []

    suppliers = client.get("/api/suppliers")
    assert suppliers.status_code == 200
    supplier = next(row for row in suppliers.json()["data"] if row["name"] == "JOB-UNDO-SUPPLIER")
    alias_after_undo = client.get(f"/api/suppliers/{supplier['supplier_id']}/aliases")
    assert alias_after_undo.status_code == 200
    assert alias_after_undo.json()["data"] == []

    redo = client.post(f"/api/items/import-jobs/{import_job_id}/redo")
    assert redo.status_code == 200
    redo_data = redo.json()["data"]
    assert redo_data["source_job_id"] == import_job_id
    assert redo_data["redo_job_id"] > import_job_id
    assert redo_data["import_result"]["status"] == "ok"
    assert redo_data["import_result"]["created_count"] == 2

    items_after_redo = client.get("/api/items?q=JOB-UNDO-CANONICAL&per_page=50").json()["data"]
    assert len(items_after_redo) == 1
    alias_after_redo = client.get(f"/api/suppliers/{supplier['supplier_id']}/aliases")
    assert alias_after_redo.status_code == 200
    assert len(alias_after_redo.json()["data"]) == 1


def test_items_import_jobs_listing_endpoint(client):
    response = client.get("/api/items/import-jobs?per_page=20")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert isinstance(payload["data"], list)
    assert "pagination" in payload


def test_items_import_job_undo_blocks_when_item_changed_after_import(client):
    output = StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=["row_type", "item_number", "manufacturer_name", "category", "url", "description"],
    )
    writer.writeheader()
    writer.writerow(
        {
            "row_type": "item",
            "item_number": "JOB-UNDO-BLOCKED-ITEM",
            "manufacturer_name": "JOB-UNDO-BLOCKED-MFG",
            "category": "Lens",
            "url": "",
            "description": "before change",
        }
    )

    response = client.post(
        "/api/items/import",
        files={"file": ("job_undo_blocked_items.csv", output.getvalue().encode("utf-8"), "text/csv")},
        data={"continue_on_error": "true"},
    )
    assert response.status_code == 200
    import_job_id = int(response.json()["data"]["import_job_id"])

    item = client.get("/api/items?q=JOB-UNDO-BLOCKED-ITEM&per_page=50").json()["data"][0]
    mutate = client.put(
        f"/api/items/{item['item_id']}",
        json={"description": "changed after import"},
    )
    assert mutate.status_code == 200

    undo = client.post(f"/api/items/import-jobs/{import_job_id}/undo")
    assert undo.status_code == 409
    payload = undo.json()
    assert payload["status"] == "error"
    assert payload["error"]["code"] == "IMPORT_UNDO_CONFLICT"


def test_update_item_blocks_identity_change_when_referenced(client):
    item = client.post(
        "/api/items",
        json={
            "item_number": "IMMUTABLE-REF-001",
            "manufacturer_name": "IMMUTABLE-MFG-A",
            "category": "Lens",
        },
    ).json()["data"]

    seed = client.post(
        "/api/inventory/adjust",
        json={
            "item_id": item["item_id"],
            "quantity_delta": 1,
            "location": "STOCK",
            "note": "seed reference",
        },
    )
    assert seed.status_code == 200

    metadata_update = client.put(
        f"/api/items/{item['item_id']}",
        json={"description": "metadata-only update"},
    )
    assert metadata_update.status_code == 200
    assert metadata_update.json()["data"]["description"] == "metadata-only update"

    rename = client.put(
        f"/api/items/{item['item_id']}",
        json={"item_number": "IMMUTABLE-REF-RENAMED"},
    )
    assert rename.status_code == 409
    rename_payload = rename.json()
    assert rename_payload["status"] == "error"
    assert rename_payload["error"]["code"] == "ITEM_REFERENCED_IMMUTABLE"

    remanufacturer = client.put(
        f"/api/items/{item['item_id']}",
        json={"manufacturer_name": "IMMUTABLE-MFG-B"},
    )
    assert remanufacturer.status_code == 409
    remanufacturer_payload = remanufacturer.json()
    assert remanufacturer_payload["status"] == "error"
    assert remanufacturer_payload["error"]["code"] == "ITEM_REFERENCED_IMMUTABLE"


def test_update_item_allows_identity_change_when_unreferenced(client):
    item = client.post(
        "/api/items",
        json={
            "item_number": "MUTABLE-ITEM-001",
            "manufacturer_name": "MUTABLE-MFG-A",
            "category": "Lens",
        },
    ).json()["data"]

    update = client.put(
        f"/api/items/{item['item_id']}",
        json={
            "item_number": "MUTABLE-ITEM-RENAMED",
            "manufacturer_name": "MUTABLE-MFG-B",
            "description": "updated",
        },
    )
    assert update.status_code == 200
    payload = update.json()["data"]
    assert payload["item_number"] == "MUTABLE-ITEM-RENAMED"
    assert payload["manufacturer_name"] == "MUTABLE-MFG-B"
    assert payload["description"] == "updated"


def test_bulk_update_item_metadata_endpoint(client):
    item_a = client.post(
        "/api/items",
        json={
            "item_number": "META-BULK-001",
            "manufacturer_name": "META-MFG",
            "category": "Lens",
        },
    ).json()["data"]
    item_b = client.post(
        "/api/items",
        json={
            "item_number": "META-BULK-002",
            "manufacturer_name": "META-MFG",
            "category": "Mirror",
        },
    ).json()["data"]

    seed = client.post(
        "/api/inventory/adjust",
        json={
            "item_id": item_a["item_id"],
            "quantity_delta": 2,
            "location": "STOCK",
            "note": "reference for metadata update",
        },
    )
    assert seed.status_code == 200

    response = client.post(
        "/api/items/metadata/bulk",
        json={
            "rows": [
                {
                    "item_id": item_a["item_id"],
                    "category": "Updated Lens",
                    "description": "bulk-updated-a",
                },
                {
                    "item_id": item_b["item_id"],
                    "url": "https://example.com/meta-bulk-002",
                },
            ],
            "continue_on_error": True,
        },
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "ok"
    assert data["processed"] == 2
    assert data["updated_count"] == 2
    assert data["failed_count"] == 0

    rows_a = client.get("/api/items?q=META-BULK-001&per_page=50").json()["data"]
    assert len(rows_a) == 1
    assert rows_a[0]["category"] == "Updated Lens"
    assert rows_a[0]["description"] == "bulk-updated-a"

    rows_b = client.get("/api/items?q=META-BULK-002&per_page=50").json()["data"]
    assert len(rows_b) == 1
    assert rows_b[0]["url"] == "https://example.com/meta-bulk-002"


def test_bulk_update_item_metadata_endpoint_partial_on_missing_item(client):
    item = client.post(
        "/api/items",
        json={
            "item_number": "META-BULK-PARTIAL-001",
            "manufacturer_name": "META-MFG",
            "category": "Lens",
        },
    ).json()["data"]

    response = client.post(
        "/api/items/metadata/bulk",
        json={
            "rows": [
                {"item_id": item["item_id"], "description": "ok-update"},
                {"item_id": 999999, "category": "missing"},
            ],
            "continue_on_error": True,
        },
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "partial"
    assert data["processed"] == 2
    assert data["updated_count"] == 1
    assert data["failed_count"] == 1
    assert any(row.get("code") == "ITEM_NOT_FOUND" for row in data["rows"])

    rows = client.get("/api/items?q=META-BULK-PARTIAL-001&per_page=50").json()["data"]
    assert len(rows) == 1
    assert rows[0]["description"] == "ok-update"


def test_register_missing_rows_endpoint(client):
    response = client.post(
        "/api/register-missing/rows",
        json={
            "rows": [
                {
                    "supplier": "SupplierResolver",
                    "item_number": "MISS-ITEM-NEW",
                    "manufacturer_name": "RESOLVER-MFG",
                    "resolution_type": "new_item",
                    "category": "Lens",
                    "description": "from resolver",
                }
            ]
        },
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["created_items"] == 1

    items = client.get("/api/items?q=MISS-ITEM-NEW&per_page=50")
    assert items.status_code == 200
    rows = items.json()["data"]
    assert len(rows) == 1
    assert rows[0]["item_number"] == "MISS-ITEM-NEW"
    assert rows[0]["manufacturer_name"] == "RESOLVER-MFG"


def test_register_missing_rows_endpoint_accepts_manufacturer_alias_field(client):
    response = client.post(
        "/api/register-missing/rows",
        json={
            "rows": [
                {
                    "supplier": "SupplierResolver",
                    "item_number": "MISS-ITEM-NEW-ALIAS",
                    "manufacturer": "RESOLVER-MFG-ALIAS",
                    "resolution_type": "new_item",
                    "category": "Lens",
                    "description": "from resolver alias",
                }
            ]
        },
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["created_items"] == 1

    items = client.get("/api/items?q=MISS-ITEM-NEW-ALIAS&per_page=50")
    assert items.status_code == 200
    rows = items.json()["data"]
    assert len(rows) == 1
    assert rows[0]["manufacturer_name"] == "RESOLVER-MFG-ALIAS"


def test_register_missing_rows_endpoint_rejects_unresolved_new_item(client):
    response = client.post(
        "/api/register-missing/rows",
        json={
            "rows": [
                {
                    "supplier": "SupplierResolver",
                    "item_number": "MISS-ITEM-UNRESOLVED",
                    "resolution_type": "new_item",
                    "category": "",
                    "url": "",
                    "description": "",
                }
            ]
        },
    )
    assert response.status_code == 422
    payload = response.json()
    assert payload["status"] == "error"
    assert payload["error"]["code"] == "MISSING_ITEM_UNRESOLVED"


def test_retry_unregistered_file_endpoint(client, tmp_path: Path):
    unregistered_root = tmp_path / "quotations" / "unregistered"
    registered_root = tmp_path / "quotations" / "registered"
    supplier_dir = unregistered_root / "csv_files" / "SupplierRetry"
    supplier_dir.mkdir(parents=True, exist_ok=True)

    csv_path = supplier_dir / "QR-001.csv"
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
                "item_number": "BATCH-MISSING-001",
                "quantity": "3",
                "quotation_number": "QR-001",
                "issue_date": "2026-02-22",
                "order_date": "2026-02-23",
                "expected_arrival": "2026-03-05",
                "pdf_link": "",
            }
        )

    initial = client.post(
        "/api/orders/import-unregistered",
        json={
            "unregistered_root": str(unregistered_root),
            "registered_root": str(registered_root),
            "continue_on_error": False,
        },
    )
    assert initial.status_code == 200
    initial_data = initial.json()["data"]
    assert initial_data["missing_items"] == 1
    assert initial_data["files"][0]["status"] == "missing_items"

    reg = client.post(
        "/api/register-missing/rows",
        json={
            "rows": [
                {
                    "supplier": "SupplierRetry",
                    "item_number": "BATCH-MISSING-001",
                    "resolution_type": "new_item",
                    "category": "Lens",
                }
            ]
        },
    )
    assert reg.status_code == 200
    assert reg.json()["data"]["created_items"] == 1

    retry = client.post(
        "/api/orders/retry-unregistered-file",
        json={
            "csv_path": str(csv_path),
            "unregistered_root": str(unregistered_root),
            "registered_root": str(registered_root),
        },
    )
    assert retry.status_code == 200
    retry_data = retry.json()["data"]
    assert retry_data["status"] == "ok"
    assert retry_data["imported_count"] == 1
    assert not csv_path.exists()
    assert (registered_root / "csv_files" / "SupplierRetry" / "QR-001.csv").exists()


def test_retry_unregistered_legacy_layout_returns_warnings(client, tmp_path: Path):
    client.post("/api/manufacturers", json={"name": "API-LEGACY-MFG"})
    client.post(
        "/api/items",
        json={
            "item_number": "API-LEGACY-ITEM",
            "manufacturer_name": "API-LEGACY-MFG",
            "category": "Lens",
        },
    )

    unregistered_root = tmp_path / "quotations" / "unregistered"
    registered_root = tmp_path / "quotations" / "registered"
    legacy_supplier_dir = unregistered_root / "LegacySupplier"
    legacy_supplier_dir.mkdir(parents=True, exist_ok=True)

    pdf_path = legacy_supplier_dir / "QL-001.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 legacy")

    csv_path = legacy_supplier_dir / "QL-001.csv"
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
                "item_number": "API-LEGACY-ITEM",
                "quantity": "1",
                "quotation_number": "QL-001",
                "issue_date": "2026-02-25",
                "order_date": "2026-02-26",
                "expected_arrival": "2026-03-03",
                "pdf_link": "QL-001.pdf",
            }
        )

    retry = client.post(
        "/api/orders/retry-unregistered-file",
        json={
            "csv_path": str(csv_path),
            "unregistered_root": str(unregistered_root),
            "registered_root": str(registered_root),
        },
    )
    assert retry.status_code == 200
    retry_data = retry.json()["data"]
    assert retry_data["status"] == "ok"
    assert retry_data["imported_count"] == 1
    assert retry_data["warnings"]
    assert any("Legacy unregistered CSV layout detected" in msg for msg in retry_data["warnings"])
    assert not csv_path.exists()
    assert (registered_root / "csv_files" / "LegacySupplier" / "QL-001.csv").exists()
    assert (registered_root / "pdf_files" / "LegacySupplier" / "QL-001.pdf").exists()
