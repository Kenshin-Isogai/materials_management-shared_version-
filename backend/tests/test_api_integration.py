from __future__ import annotations

import csv
import json
from io import StringIO
from pathlib import Path

from app import service

FUTURE_TARGET_DATE = "2999-12-31"


def read_csv_response(response):
    reader = csv.DictReader(StringIO(response.content.decode("utf-8-sig")))
    return reader.fieldnames or [], list(reader)


def make_csv_bytes(fieldnames, rows):
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return output.getvalue().encode("utf-8")


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
    assert quantities["STOCK"] == 10
    assert "RESERVED" not in quantities

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
    assert quantities["STOCK"] == 10
    assert "RESERVED" not in quantities

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


def test_orders_import_preview_endpoint_classifies_matches_and_duplicate_quotations(client):
    client.post("/api/manufacturers", json={"name": "API-PREVIEW-MFG"})
    item = client.post(
        "/api/items",
        json={
            "item_number": "KM100",
            "manufacturer_name": "API-PREVIEW-MFG",
            "category": "Mirror Mount",
        },
    ).json()["data"]
    supplier = client.post("/api/suppliers", json={"name": "SupplierPreview"}).json()["data"]
    alias = client.post(
        f"/api/suppliers/{supplier['supplier_id']}/aliases",
        json={
            "ordered_item_number": "ThorLabs KM100",
            "canonical_item_id": item["item_id"],
            "units_per_order": 2,
        },
    )
    assert alias.status_code == 200

    existing_csv = StringIO()
    existing_writer = csv.DictWriter(
        existing_csv,
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
    existing_writer.writeheader()
    existing_writer.writerow(
        {
            "item_number": "KM100",
            "quantity": "1",
            "quotation_number": "Q-DUP-PREVIEW",
            "issue_date": "2026-02-21",
            "order_date": "2026-02-22",
            "expected_arrival": "2026-03-01",
            "pdf_link": "",
        }
    )
    imported = client.post(
        "/api/orders/import",
        files={"file": ("existing.csv", existing_csv.getvalue().encode("utf-8"), "text/csv")},
        data={"supplier_name": "SupplierPreview"},
    )
    assert imported.status_code == 200

    preview_csv = StringIO()
    preview_writer = csv.DictWriter(
        preview_csv,
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
    preview_writer.writeheader()
    preview_writer.writerow(
        {
            "item_number": "ThorLabs KM100",
            "quantity": "2",
            "quotation_number": "Q-DUP-PREVIEW",
            "issue_date": "2026-02-21",
            "order_date": "2026-02-22",
            "expected_arrival": "2026-03-01",
            "pdf_link": "Q-DUP-PREVIEW.pdf",
        }
    )
    preview_writer.writerow(
        {
            "item_number": "KM100 mount",
            "quantity": "1",
            "quotation_number": "Q-REVIEW-PREVIEW",
            "issue_date": "2026-02-21",
            "order_date": "2026-02-22",
            "expected_arrival": "2026-03-01",
            "pdf_link": "",
        }
    )
    preview_writer.writerow(
        {
            "item_number": "NO-MATCH-XYZ",
            "quantity": "1",
            "quotation_number": "Q-UNRESOLVED-PREVIEW",
            "issue_date": "2026-02-21",
            "order_date": "2026-02-22",
            "expected_arrival": "2026-03-01",
            "pdf_link": "",
        }
    )

    response = client.post(
        "/api/orders/import-preview",
        files={"file": ("preview.csv", preview_csv.getvalue().encode("utf-8"), "text/csv")},
        data={"supplier_name": "SupplierPreview"},
    )
    assert response.status_code == 200
    payload = response.json()["data"]

    assert payload["supplier"]["supplier_id"] == supplier["supplier_id"]
    assert payload["supplier"]["exists"] is True
    assert payload["summary"]["exact"] == 1
    assert payload["summary"]["needs_review"] == 1
    assert payload["summary"]["unresolved"] == 1
    assert payload["can_auto_accept"] is False
    assert payload["duplicate_quotation_numbers"] == ["Q-DUP-PREVIEW"]
    assert payload["blocking_errors"]

    rows = payload["rows"]
    assert rows[0]["status"] == "exact"
    assert rows[0]["suggested_match"]["canonical_item_number"] == "KM100"
    assert rows[0]["suggested_match"]["units_per_order"] == 2
    assert "Quotation already imported for this supplier." in rows[0]["warnings"]

    assert rows[1]["status"] == "needs_review"
    assert rows[1]["suggested_match"]["canonical_item_number"] == "KM100"
    assert rows[1]["confidence_score"] >= 70

    assert rows[2]["status"] == "unresolved"
    assert rows[2]["suggested_match"] is None


def test_orders_import_accepts_preview_overrides_and_alias_saves(client):
    client.post("/api/manufacturers", json={"name": "API-PREVIEW-APPLY-MFG"})
    item = client.post(
        "/api/items",
        json={
            "item_number": "KM100",
            "manufacturer_name": "API-PREVIEW-APPLY-MFG",
            "category": "Mirror Mount",
        },
    ).json()["data"]

    upload = StringIO()
    writer = csv.DictWriter(
        upload,
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
            "item_number": "ThorLabs KM100",
            "quantity": "2",
            "quotation_number": "Q-PREVIEW-APPLY-001",
            "issue_date": "2026-02-21",
            "order_date": "2026-02-22",
            "expected_arrival": "2026-03-01",
            "pdf_link": "",
        }
    )

    response = client.post(
        "/api/orders/import",
        files={"file": ("apply.csv", upload.getvalue().encode("utf-8"), "text/csv")},
        data={
            "supplier_name": "SupplierPreviewApply",
            "row_overrides": json.dumps(
                {
                    "2": {
                        "item_id": item["item_id"],
                        "units_per_order": 3,
                    }
                }
            ),
            "alias_saves": json.dumps(
                [
                    {
                        "ordered_item_number": "ThorLabs KM100",
                        "item_id": item["item_id"],
                        "units_per_order": 3,
                    }
                ]
            ),
        },
    )
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["status"] == "ok"
    assert payload["imported_count"] == 1
    assert payload["saved_alias_count"] == 1

    orders = client.get("/api/orders?supplier=SupplierPreviewApply&per_page=50")
    assert orders.status_code == 200
    assert orders.json()["data"][0]["canonical_item_number"] == "KM100"
    assert orders.json()["data"][0]["ordered_item_number"] == "ThorLabs KM100"
    assert orders.json()["data"][0]["order_amount"] == 6

    second_upload = StringIO()
    second_writer = csv.DictWriter(
        second_upload,
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
    second_writer.writeheader()
    second_writer.writerow(
        {
            "item_number": "ThorLabs KM100",
            "quantity": "1",
            "quotation_number": "Q-PREVIEW-APPLY-002",
            "issue_date": "2026-02-21",
            "order_date": "2026-02-22",
            "expected_arrival": "2026-03-01",
            "pdf_link": "",
        }
    )
    second_response = client.post(
        "/api/orders/import",
        files={"file": ("apply-second.csv", second_upload.getvalue().encode("utf-8"), "text/csv")},
        data={"supplier_name": "SupplierPreviewApply"},
    )
    assert second_response.status_code == 200
    assert second_response.json()["data"]["status"] == "ok"

    refreshed_orders = client.get("/api/orders?supplier=SupplierPreviewApply&per_page=50")
    assert refreshed_orders.status_code == 200
    order_amounts = {
        row["quotation_number"]: row["order_amount"]
        for row in refreshed_orders.json()["data"]
    }
    assert order_amounts["Q-PREVIEW-APPLY-001"] == 6
    assert order_amounts["Q-PREVIEW-APPLY-002"] == 3


def test_orders_import_rejects_malformed_preview_override_json(client):
    csv_content = make_csv_bytes(
        [
            "item_number",
            "quantity",
            "quotation_number",
            "issue_date",
            "order_date",
            "expected_arrival",
            "pdf_link",
        ],
        [
            {
                "item_number": "ORDERS-MALFORMED-JSON-ITEM",
                "quantity": "1",
                "quotation_number": "Q-ORDERS-MALFORMED-001",
                "issue_date": "2026-02-21",
                "order_date": "2026-02-22",
                "expected_arrival": "2026-03-01",
                "pdf_link": "",
            }
        ],
    )

    response = client.post(
        "/api/orders/import",
        files={"file": ("orders-malformed.json.csv", csv_content, "text/csv")},
        data={
            "supplier_name": "SupplierMalformedJson",
            "row_overrides": "{",
        },
    )
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "INVALID_REQUEST"
    assert error["message"] == "row_overrides must be valid JSON"


def test_orders_import_rejects_non_array_alias_saves(client):
    client.post("/api/manufacturers", json={"name": "ORDER-ALIAS-SHAPE-MFG"})
    client.post(
        "/api/items",
        json={
            "item_number": "ORDER-ALIAS-SHAPE-ITEM",
            "manufacturer_name": "ORDER-ALIAS-SHAPE-MFG",
            "category": "Lens",
        },
    )
    csv_content = make_csv_bytes(
        [
            "item_number",
            "quantity",
            "quotation_number",
            "issue_date",
            "order_date",
            "expected_arrival",
            "pdf_link",
        ],
        [
            {
                "item_number": "ORDER-ALIAS-SHAPE-ITEM",
                "quantity": "1",
                "quotation_number": "Q-ORDER-ALIAS-SHAPE-001",
                "issue_date": "2026-02-21",
                "order_date": "2026-02-22",
                "expected_arrival": "2026-03-01",
                "pdf_link": "",
            }
        ],
    )

    response = client.post(
        "/api/orders/import",
        files={"file": ("orders-alias-shape.csv", csv_content, "text/csv")},
        data={
            "supplier_name": "SupplierAliasShape",
            "alias_saves": json.dumps({"ordered_item_number": "ORDER-ALIAS-SHAPE-ITEM"}),
        },
    )
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "INVALID_ORDER_IMPORT_ALIAS"
    assert error["message"] == "Order import alias_saves must be a JSON array"


def test_orders_endpoint_filters_by_item_id(client):
    client.post("/api/manufacturers", json={"name": "API-ORDER-FILTER-MFG"})
    item_a = client.post(
        "/api/items",
        json={
            "item_number": "API-ORDER-FILTER-A",
            "manufacturer_name": "API-ORDER-FILTER-MFG",
            "category": "Lens",
        },
    ).json()["data"]
    item_b = client.post(
        "/api/items",
        json={
            "item_number": "API-ORDER-FILTER-B",
            "manufacturer_name": "API-ORDER-FILTER-MFG",
            "category": "Mirror",
        },
    ).json()["data"]

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
            "item_number": item_a["item_number"],
            "quantity": "2",
            "quotation_number": "Q-API-ORDER-FILTER-001",
            "issue_date": "2026-03-01",
            "order_date": "2026-03-02",
            "expected_arrival": FUTURE_TARGET_DATE,
            "pdf_link": "",
        }
    )
    writer.writerow(
        {
            "item_number": item_b["item_number"],
            "quantity": "3",
            "quotation_number": "Q-API-ORDER-FILTER-002",
            "issue_date": "2026-03-01",
            "order_date": "2026-03-02",
            "expected_arrival": FUTURE_TARGET_DATE,
            "pdf_link": "",
        }
    )
    imported = client.post(
        "/api/orders/import",
        files={"file": ("order-filter.csv", output.getvalue().encode("utf-8"), "text/csv")},
        data={"supplier_name": "ApiOrderFilterSupplier"},
    )
    assert imported.status_code == 200

    response = client.get("/api/orders", params={"item_id": item_a["item_id"], "per_page": 50})
    assert response.status_code == 200
    rows = response.json()["data"]
    assert len(rows) == 1
    assert rows[0]["item_id"] == item_a["item_id"]


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


def test_items_import_preview_endpoint_classifies_duplicate_and_alias_resolution(client):
    client.post("/api/manufacturers", json={"name": "ITEM-PREVIEW-MFG"})
    client.post(
        "/api/items",
        json={
            "item_number": "ITEM-PREVIEW-DUP",
            "manufacturer_name": "ITEM-PREVIEW-MFG",
            "category": "Lens",
        },
    )
    canonical = client.post(
        "/api/items",
        json={
            "item_number": "ITEM-PREVIEW-CANONICAL",
            "manufacturer_name": "ITEM-PREVIEW-MFG",
            "category": "Lens",
        },
    ).json()["data"]

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
            "item_number": "ITEM-PREVIEW-DUP",
            "manufacturer_name": "ITEM-PREVIEW-MFG",
            "category": "Lens",
            "url": "",
            "description": "",
            "supplier": "",
            "canonical_item_number": "",
            "units_per_order": "",
        }
    )
    writer.writerow(
        {
            "row_type": "alias",
            "item_number": "ITEM-PREVIEW-ALIAS",
            "manufacturer_name": "",
            "category": "",
            "url": "",
            "description": "",
            "supplier": "ITEM-PREVIEW-SUPPLIER",
            "canonical_item_number": "ITEM-PREVIEW-CANONCAL",
            "units_per_order": "2",
        }
    )

    response = client.post(
        "/api/items/import-preview",
        files={"file": ("items-preview.csv", output.getvalue().encode("utf-8"), "text/csv")},
    )
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["summary"]["needs_review"] >= 1
    assert payload["summary"]["total_rows"] == 2

    rows = payload["rows"]
    assert rows[0]["status"] == "needs_review"
    assert rows[0]["action"] == "duplicate_item"
    assert rows[1]["status"] in {"high_confidence", "needs_review"}
    assert rows[1]["requires_user_selection"] is True
    assert rows[1]["allowed_entity_types"] == ["item"]
    assert rows[1]["suggested_match"]["entity_id"] == canonical["item_id"]
    assert rows[1]["suggested_match"]["value_text"] == "ITEM-PREVIEW-CANONICAL"


def test_items_import_accepts_preview_override_for_alias_canonical_item(client):
    client.post("/api/manufacturers", json={"name": "ITEM-PREVIEW-OVERRIDE-MFG"})
    canonical = client.post(
        "/api/items",
        json={
            "item_number": "ITEM-PREVIEW-OVERRIDE-CANONICAL",
            "manufacturer_name": "ITEM-PREVIEW-OVERRIDE-MFG",
            "category": "Lens",
        },
    ).json()["data"]

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
            "item_number": "ITEM-PREVIEW-OVERRIDE-ALIAS",
            "manufacturer_name": "",
            "category": "",
            "url": "",
            "description": "",
            "supplier": "ITEM-PREVIEW-OVERRIDE-SUPPLIER",
            "canonical_item_number": "ITEM-PREVIEW-OVERRIDE-CANONCAL",
            "units_per_order": "1",
        }
    )

    response = client.post(
        "/api/items/import",
        files={"file": ("items-override.csv", output.getvalue().encode("utf-8"), "text/csv")},
        data={
            "continue_on_error": "true",
            "row_overrides": json.dumps(
                {
                    "2": {
                        "canonical_item_number": canonical["item_number"],
                        "units_per_order": 3,
                    }
                }
            ),
        },
    )
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["status"] == "ok"
    assert payload["created_count"] == 1

    suppliers = client.get("/api/suppliers")
    supplier = next(
        row
        for row in suppliers.json()["data"]
        if row["name"] == "ITEM-PREVIEW-OVERRIDE-SUPPLIER"
    )
    aliases = client.get(f"/api/suppliers/{supplier['supplier_id']}/aliases").json()["data"]
    assert aliases[0]["ordered_item_number"] == "ITEM-PREVIEW-OVERRIDE-ALIAS"
    assert aliases[0]["canonical_item_number"] == canonical["item_number"]
    assert aliases[0]["units_per_order"] == 3


def test_items_import_rejects_non_object_row_overrides(client):
    csv_content = make_csv_bytes(
        [
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
        [
            {
                "row_type": "item",
                "item_number": "ITEM-OVERRIDE-SHAPE-001",
                "manufacturer_name": "ITEM-OVERRIDE-SHAPE-MFG",
                "category": "Lens",
                "url": "",
                "description": "",
                "supplier": "",
                "canonical_item_number": "",
                "units_per_order": "",
            }
        ],
    )

    response = client.post(
        "/api/items/import",
        files={"file": ("items-override-shape.csv", csv_content, "text/csv")},
        data={
            "continue_on_error": "true",
            "row_overrides": json.dumps([{"row": 2, "canonical_item_number": "IGNORED"}]),
        },
    )
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "INVALID_ITEM_IMPORT_OVERRIDE"
    assert error["message"] == "Item import row_overrides must be a JSON object keyed by CSV row number"


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


def test_register_missing_rows_endpoint_accepts_legacy_row_type_item(client):
    response = client.post(
        "/api/register-missing/rows",
        json={
            "rows": [
                {
                    "supplier": "SupplierResolver",
                    "item_number": "MISS-ITEM-ROW-TYPE",
                    "row_type": "item",
                    "manufacturer_name": "ROW-TYPE-MFG",
                    "category": "Lens",
                    "description": "legacy row_type mapping",
                }
            ]
        },
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["created_items"] == 1

    items = client.get("/api/items?q=MISS-ITEM-ROW-TYPE&per_page=50")
    assert items.status_code == 200
    rows = items.json()["data"]
    assert len(rows) == 1
    assert rows[0]["manufacturer_name"] == "ROW-TYPE-MFG"

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

def test_delete_order_endpoint(client):
    client.post("/api/manufacturers", json={"name": "API-DEL-ORDER-MFG"})
    client.post(
        "/api/items",
        json={
            "item_number": "API-DEL-ORDER-ITEM",
            "manufacturer_name": "API-DEL-ORDER-MFG",
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
            "item_number": "API-DEL-ORDER-ITEM",
            "quantity": "2",
            "quotation_number": "Q-DEL-ORDER-001",
            "issue_date": "2026-03-01",
            "order_date": "2026-03-01",
            "expected_arrival": "2026-03-10",
            "pdf_link": "",
        }
    )

    imported = client.post(
        "/api/orders/import",
        files={"file": ("orders.csv", output.getvalue().encode("utf-8"), "text/csv")},
        data={"supplier_name": "SupplierDeleteOrder"},
    )
    assert imported.status_code == 200
    order_id = imported.json()["data"]["order_ids"][0]

    deleted = client.delete(f"/api/orders/{order_id}")
    assert deleted.status_code == 200
    assert deleted.json()["data"]["deleted"] is True

def test_merge_orders_endpoint_merges_and_returns_lineage(client):
    client.post("/api/manufacturers", json={"name": "API-MERGE-MFG"})
    client.post(
        "/api/items",
        json={
            "item_number": "API-MERGE-ITEM",
            "manufacturer_name": "API-MERGE-MFG",
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
            "item_number": "API-MERGE-ITEM",
            "quantity": "20",
            "quotation_number": "Q-MERGE-001",
            "issue_date": "2026-03-01",
            "order_date": "2026-03-01",
            "expected_arrival": "2026-03-10",
            "pdf_link": "",
        }
    )
    writer.writerow(
        {
            "item_number": "API-MERGE-ITEM",
            "quantity": "30",
            "quotation_number": "Q-MERGE-001",
            "issue_date": "2026-03-01",
            "order_date": "2026-03-01",
            "expected_arrival": "2026-03-15",
            "pdf_link": "",
        }
    )

    imported = client.post(
        "/api/orders/import",
        files={"file": ("orders.csv", output.getvalue().encode("utf-8"), "text/csv")},
        data={"supplier_name": "SupplierMergeApi"},
    )
    assert imported.status_code == 200
    source_order_id = imported.json()["data"]["order_ids"][0]
    target_order_id = imported.json()["data"]["order_ids"][1]

    merged = client.post(
        "/api/orders/merge",
        json={
            "source_order_id": source_order_id,
            "target_order_id": target_order_id,
            "expected_arrival": "2026-03-20",
        },
    )
    assert merged.status_code == 200
    assert merged.json()["data"]["target_order"]["order_amount"] == 50
    assert merged.json()["data"]["target_order"]["expected_arrival"] == "2026-03-20"

    lineage = client.get(f"/api/orders/{target_order_id}/lineage")
    assert lineage.status_code == 200
    assert any(
        row["event_type"] == "ETA_MERGE" and row["source_order_id"] == source_order_id
        for row in lineage.json()["data"]
    )


def test_delete_quotation_endpoint_removes_related_orders(client):
    client.post("/api/manufacturers", json={"name": "API-DEL-QUO-MFG"})
    client.post(
        "/api/items",
        json={
            "item_number": "API-DEL-QUO-ITEM",
            "manufacturer_name": "API-DEL-QUO-MFG",
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
            "item_number": "API-DEL-QUO-ITEM",
            "quantity": "2",
            "quotation_number": "Q-DEL-QUO-001",
            "issue_date": "2026-03-01",
            "order_date": "2026-03-01",
            "expected_arrival": "2026-03-10",
            "pdf_link": "",
        }
    )

    imported = client.post(
        "/api/orders/import",
        files={"file": ("orders.csv", output.getvalue().encode("utf-8"), "text/csv")},
        data={"supplier_name": "SupplierDeleteQuotation"},
    )
    assert imported.status_code == 200

    quotations = client.get("/api/quotations?supplier=SupplierDeleteQuotation&per_page=50")
    assert quotations.status_code == 200
    quotation_id = quotations.json()["data"][0]["quotation_id"]

    deleted = client.delete(f"/api/quotations/{quotation_id}")
    assert deleted.status_code == 200
    assert deleted.json()["data"]["deleted"] is True

    remaining_orders = client.get("/api/orders?supplier=SupplierDeleteQuotation&per_page=50")
    assert remaining_orders.status_code == 200
    assert remaining_orders.json()["data"] == []


def test_import_template_endpoints_return_header_only_bom_csv(client):
    expected_headers = {
        "/api/items/import-template": [
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
        "/api/inventory/import-template": [
            "operation_type",
            "item_id",
            "quantity",
            "from_location",
            "to_location",
            "location",
            "note",
        ],
        "/api/orders/import-template": [
            "item_number",
            "quantity",
            "quotation_number",
            "issue_date",
            "order_date",
            "expected_arrival",
            "pdf_link",
        ],
        "/api/reservations/import-template": [
            "item_id",
            "assembly",
            "assembly_quantity",
            "quantity",
            "purpose",
            "deadline",
            "note",
            "project_id",
        ],
    }

    for path, headers in expected_headers.items():
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/csv")
        assert response.content[:3] == b"\xef\xbb\xbf"
        fieldnames, rows = read_csv_response(response)
        assert fieldnames == headers
        assert rows == []


def test_items_import_reference_endpoint_includes_canonical_items_and_aliases(client):
    manufacturer = client.post("/api/manufacturers", json={"name": "API-ITEM-REF-MFG"}).json()["data"]
    item = client.post(
        "/api/items",
        json={
            "item_number": "API-ITEM-REF-001",
            "manufacturer_id": manufacturer["manufacturer_id"],
            "category": "Mirror",
        },
    ).json()["data"]
    supplier = client.post("/api/suppliers", json={"name": "SupplierItemReference"}).json()["data"]
    alias = client.post(
        f"/api/suppliers/{supplier['supplier_id']}/aliases",
        json={
            "ordered_item_number": "SUP-ITEM-REF-001",
            "canonical_item_id": item["item_id"],
            "units_per_order": 6,
        },
    )
    assert alias.status_code == 200

    response = client.get("/api/items/import-reference")
    assert response.status_code == 200

    _, rows = read_csv_response(response)
    assert any(
        row["reference_type"] == "item"
        and row["item_number"] == "API-ITEM-REF-001"
        and row["manufacturer_name"] == "API-ITEM-REF-MFG"
        for row in rows
    )
    assert any(
        row["reference_type"] == "supplier_item_alias"
        and row["supplier"] == "SupplierItemReference"
        and row["ordered_item_number"] == "SUP-ITEM-REF-001"
        and row["units_per_order"] == "6"
        for row in rows
    )


def test_inventory_import_reference_endpoint_includes_live_item_ids_and_quantities(client):
    manufacturer = client.post("/api/manufacturers", json={"name": "API-INV-REF-MFG"}).json()["data"]
    item = client.post(
        "/api/items",
        json={
            "item_number": "API-INV-REF-001",
            "manufacturer_id": manufacturer["manufacturer_id"],
            "category": "Lens",
        },
    ).json()["data"]
    seeded = client.post(
        "/api/inventory/adjust",
        json={
            "item_id": item["item_id"],
            "quantity_delta": 9,
            "location": "STOCK",
        },
    )
    assert seeded.status_code == 200

    response = client.get("/api/inventory/import-reference")
    assert response.status_code == 200

    _, rows = read_csv_response(response)
    assert any(
        row["item_id"] == str(item["item_id"])
        and row["item_number"] == "API-INV-REF-001"
        and row["location"] == "STOCK"
        and row["current_quantity"] == "9"
        for row in rows
    )


def test_orders_import_reference_endpoint_filters_aliases_by_supplier(client):
    manufacturer = client.post("/api/manufacturers", json={"name": "API-ORD-REF-MFG"}).json()["data"]
    item = client.post(
        "/api/items",
        json={
            "item_number": "API-ORD-REF-001",
            "manufacturer_id": manufacturer["manufacturer_id"],
            "category": "Lens",
        },
    ).json()["data"]
    supplier_a = client.post("/api/suppliers", json={"name": "SupplierOrdersReferenceA"}).json()["data"]
    supplier_b = client.post("/api/suppliers", json={"name": "SupplierOrdersReferenceB"}).json()["data"]
    alias_a = client.post(
        f"/api/suppliers/{supplier_a['supplier_id']}/aliases",
        json={
            "ordered_item_number": "SUP-A-ORD-REF",
            "canonical_item_id": item["item_id"],
            "units_per_order": 4,
        },
    )
    alias_b = client.post(
        f"/api/suppliers/{supplier_b['supplier_id']}/aliases",
        json={
            "ordered_item_number": "SUP-B-ORD-REF",
            "canonical_item_id": item["item_id"],
            "units_per_order": 2,
        },
    )
    assert alias_a.status_code == 200
    assert alias_b.status_code == 200

    response = client.get("/api/orders/import-reference?supplier_name=SupplierOrdersReferenceA")
    assert response.status_code == 200

    _, rows = read_csv_response(response)
    assert any(
        row["reference_type"] == "canonical_item"
        and row["supplier_name"] == "SupplierOrdersReferenceA"
        and row["canonical_item_number"] == "API-ORD-REF-001"
        for row in rows
    )
    assert any(
        row["reference_type"] == "supplier_item_alias"
        and row["supplier_name"] == "SupplierOrdersReferenceA"
        and row["ordered_item_number"] == "SUP-A-ORD-REF"
        for row in rows
    )
    assert not any(row["supplier_name"] == "SupplierOrdersReferenceB" for row in rows)


def test_reservations_import_reference_endpoint_includes_items_assemblies_and_projects(client):
    manufacturer = client.post("/api/manufacturers", json={"name": "API-RES-REF-MFG"}).json()["data"]
    item = client.post(
        "/api/items",
        json={
            "item_number": "API-RES-REF-001",
            "manufacturer_id": manufacturer["manufacturer_id"],
            "category": "Mirror",
        },
    ).json()["data"]
    assembly = client.post(
        "/api/assemblies",
        json={"name": "AssemblyReservationsReference", "components": [{"item_id": item["item_id"], "quantity": 2}]},
    ).json()["data"]
    project = client.post(
        "/api/projects",
        json={"name": "ProjectReservationsReference"},
    ).json()["data"]

    response = client.get("/api/reservations/import-reference")
    assert response.status_code == 200

    _, rows = read_csv_response(response)
    assert any(
        row["reference_type"] == "item"
        and row["item_id"] == str(item["item_id"])
        and row["item_number"] == "API-RES-REF-001"
        for row in rows
    )
    assert any(
        row["reference_type"] == "assembly"
        and row["assembly_id"] == str(assembly["assembly_id"])
        and row["assembly_name"] == "AssemblyReservationsReference"
        for row in rows
    )
    assert any(
        row["reference_type"] == "project"
        and row["project_id"] == str(project["project_id"])
        and row["project_name"] == "ProjectReservationsReference"
        for row in rows
    )


def test_catalog_search_endpoint_returns_typed_results_and_alias_matches(client):
    manufacturer = client.post("/api/manufacturers", json={"name": "API-CATALOG-MFG"}).json()["data"]
    item = client.post(
        "/api/items",
        json={
            "item_number": "KM100",
            "manufacturer_id": manufacturer["manufacturer_id"],
            "category": "Mirror Mount",
            "description": "Kinematic mirror mount",
        },
    ).json()["data"]
    supplier = client.post("/api/suppliers", json={"name": "Thorlabs Search Supplier"}).json()["data"]
    alias = client.post(
        f"/api/suppliers/{supplier['supplier_id']}/aliases",
        json={
            "ordered_item_number": "ThorLabs KM100",
            "canonical_item_id": item["item_id"],
            "units_per_order": 1,
        },
    )
    assert alias.status_code == 200
    assembly = client.post(
        "/api/assemblies",
        json={"name": "KM100 Mount Kit", "components": [{"item_id": item["item_id"], "quantity": 2}]},
    ).json()["data"]
    project = client.post(
        "/api/projects",
        json={"name": "KM100 Upgrade Project"},
    ).json()["data"]

    response = client.get(
        "/api/catalog/search?q=KM100&types=item,assembly,supplier,project"
    )
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["query"] == "KM100"
    results = payload["results"]

    assert any(
        row["entity_type"] == "item"
        and row["entity_id"] == item["item_id"]
        and row["value_text"] == "KM100"
        and row["match_source"] in {"item_number", "supplier_item_alias"}
        for row in results
    )
    assert any(
        row["entity_type"] == "assembly"
        and row["entity_id"] == assembly["assembly_id"]
        for row in results
    )
    assert any(
        row["entity_type"] == "project"
        and row["entity_id"] == project["project_id"]
        for row in results
    )

    alias_response = client.get("/api/catalog/search?q=ThorLabs%20KM100&types=item")
    assert alias_response.status_code == 200
    alias_results = alias_response.json()["data"]["results"]
    assert any(
        row["entity_type"] == "item"
        and row["entity_id"] == item["item_id"]
        and row["value_text"] == "KM100"
        and row["match_source"] == "supplier_item_alias"
        for row in alias_results
    )


def test_catalog_search_endpoint_rejects_invalid_types(client):
    response = client.get("/api/catalog/search?q=test&types=item,unknown")
    assert response.status_code == 422
    payload = response.json()
    assert payload["status"] == "error"
    assert payload["error"]["code"] == "INVALID_CATALOG_TYPE"


def test_inventory_import_csv_endpoint(client):
    manufacturer = client.post("/api/manufacturers", json={"name": "API-MOVE-CSV-MFG"}).json()["data"]
    item = client.post(
        "/api/items",
        json={
            "item_number": "API-MOVE-CSV-ITEM",
            "manufacturer_id": manufacturer["manufacturer_id"],
            "category": "Lens",
        },
    ).json()["data"]
    client.post(
        "/api/inventory/adjust",
        json={"item_id": item["item_id"], "quantity_delta": 10, "location": "STOCK"},
    )

    csv_content = (
        "operation_type,item_id,quantity,from_location,to_location,location,note\n"
        f"MOVE,{item['item_id']},4,STOCK,BENCH_A,,bulk move\n"
    ).encode("utf-8")

    response = client.post(
        "/api/inventory/import-csv",
        files={"file": ("movements.csv", csv_content, "text/csv")},
        data={"batch_id": "api-move-csv-batch"},
    )
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["batch_id"] == "api-move-csv-batch"
    assert len(payload["operations"]) == 1


def test_inventory_import_preview_endpoint_flags_missing_item_and_stock_shortage(client):
    manufacturer = client.post("/api/manufacturers", json={"name": "API-MOVE-PREVIEW-MFG"}).json()["data"]
    item = client.post(
        "/api/items",
        json={
            "item_number": "API-MOVE-PREVIEW-ITEM",
            "manufacturer_id": manufacturer["manufacturer_id"],
            "category": "Lens",
        },
    ).json()["data"]
    client.post(
        "/api/inventory/adjust",
        json={"item_id": item["item_id"], "quantity_delta": 5, "location": "STOCK"},
    )

    csv_content = (
        "operation_type,item_id,quantity,from_location,to_location,location,note\n"
        "MOVE,abc,2,STOCK,BENCH_A,,manual resolve\n"
        f"MOVE,{item['item_id']},10,STOCK,BENCH_A,,too much\n"
    ).encode("utf-8")

    response = client.post(
        "/api/inventory/import-preview",
        files={"file": ("movements-preview.csv", csv_content, "text/csv")},
    )
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["summary"]["unresolved"] == 1
    assert payload["summary"]["needs_review"] == 1
    assert payload["can_auto_accept"] is False
    assert payload["rows"][0]["requires_user_selection"] is True
    assert payload["rows"][0]["allowed_entity_types"] == ["item"]
    assert payload["rows"][1]["status"] == "needs_review"
    assert "Not enough inventory" in payload["rows"][1]["message"]


def test_inventory_import_accepts_preview_item_override(client):
    manufacturer = client.post("/api/manufacturers", json={"name": "API-MOVE-OVERRIDE-MFG"}).json()["data"]
    item = client.post(
        "/api/items",
        json={
            "item_number": "API-MOVE-OVERRIDE-ITEM",
            "manufacturer_id": manufacturer["manufacturer_id"],
            "category": "Lens",
        },
    ).json()["data"]
    client.post(
        "/api/inventory/adjust",
        json={"item_id": item["item_id"], "quantity_delta": 5, "location": "STOCK"},
    )

    csv_content = (
        "operation_type,item_id,quantity,from_location,to_location,location,note\n"
        "MOVE,abc,2,STOCK,BENCH_A,,override item\n"
    ).encode("utf-8")
    response = client.post(
        "/api/inventory/import-csv",
        files={"file": ("movements-override.csv", csv_content, "text/csv")},
        data={"row_overrides": json.dumps({"2": {"item_id": item["item_id"]}})},
    )
    assert response.status_code == 200
    payload = response.json()["data"]
    assert len(payload["operations"]) == 1

    inventory = client.get(f"/api/inventory?item_id={item['item_id']}&per_page=50")
    quantities = {row["location"]: row["quantity"] for row in inventory.json()["data"]}
    assert quantities["STOCK"] == 3
    assert quantities["BENCH_A"] == 2


def test_inventory_import_rejects_unknown_override_row_number(client):
    manufacturer = client.post("/api/manufacturers", json={"name": "API-MOVE-ROWREF-MFG"}).json()["data"]
    item = client.post(
        "/api/items",
        json={
            "item_number": "API-MOVE-ROWREF-ITEM",
            "manufacturer_id": manufacturer["manufacturer_id"],
            "category": "Lens",
        },
    ).json()["data"]
    csv_content = make_csv_bytes(
        [
            "operation_type",
            "item_id",
            "quantity",
            "from_location",
            "to_location",
            "location",
            "note",
        ],
        [
            {
                "operation_type": "ARRIVAL",
                "item_id": str(item["item_id"]),
                "quantity": "2",
                "from_location": "",
                "to_location": "STOCK",
                "location": "",
                "note": "rowref",
            }
        ],
    )

    response = client.post(
        "/api/inventory/import-csv",
        files={"file": ("movements-rowref.csv", csv_content, "text/csv")},
        data={"row_overrides": json.dumps({"99": {"item_id": item["item_id"]}})},
    )
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "INVALID_INVENTORY_IMPORT_OVERRIDE"
    assert "99" in error["message"]


def test_inventory_import_csv_endpoint_rejects_non_numeric_fields(client):
    csv_content = (
        "operation_type,item_id,quantity,from_location,to_location\n"
        "MOVE,abc,1,STOCK,BENCH_A\n"
    ).encode("utf-8")

    response = client.post(
        "/api/inventory/import-csv",
        files={"file": ("movements-invalid.csv", csv_content, "text/csv")},
    )
    assert response.status_code == 422

def test_reservations_import_csv_endpoint_rejects_non_numeric_fields(client):
    csv_content = (
        "item_id,quantity\n"
        "abc,1\n"
    ).encode("utf-8")

    response = client.post(
        "/api/reservations/import-csv",
        files={"file": ("reservations-invalid.csv", csv_content, "text/csv")},
    )
    assert response.status_code == 422
def test_reservations_import_csv_endpoint_with_assembly(client):
    manufacturer = client.post("/api/manufacturers", json={"name": "API-RES-CSV-MFG"}).json()["data"]
    item = client.post(
        "/api/items",
        json={
            "item_number": "API-RES-CSV-ITEM",
            "manufacturer_id": manufacturer["manufacturer_id"],
            "category": "Mirror",
        },
    ).json()["data"]
    client.post(
        "/api/inventory/adjust",
        json={"item_id": item["item_id"], "quantity_delta": 50, "location": "STOCK"},
    )
    assembly = client.post(
        "/api/assemblies",
        json={"name": "API-CSV-ASM", "components": [{"item_id": item["item_id"], "quantity": 2}]},
    ).json()["data"]

    csv_content = (
        "assembly,assembly_quantity,quantity,purpose\n"
        f"{assembly['name']},3,2,api csv reservation\n"
    ).encode("utf-8")
    response = client.post(
        "/api/reservations/import-csv",
        files={"file": ("reservations.csv", csv_content, "text/csv")},
    )
    assert response.status_code == 200
    rows = response.json()["data"]
    assert len(rows) == 1
    assert rows[0]["quantity"] == 12


def test_reservations_import_preview_endpoint_flags_target_resolution_and_stock_shortage(client):
    manufacturer = client.post("/api/manufacturers", json={"name": "API-RES-PREVIEW-MFG"}).json()["data"]
    item = client.post(
        "/api/items",
        json={
            "item_number": "API-RES-PREVIEW-ITEM",
            "manufacturer_id": manufacturer["manufacturer_id"],
            "category": "Mirror",
        },
    ).json()["data"]
    client.post(
        "/api/inventory/adjust",
        json={"item_id": item["item_id"], "quantity_delta": 12, "location": "STOCK"},
    )
    client.post(
        "/api/assemblies",
        json={"name": "API-RES-PREVIEW-ASM", "components": [{"item_id": item["item_id"], "quantity": 2}]},
    )

    csv_content = (
        "item_id,assembly,assembly_quantity,quantity,purpose\n"
        ",API-RES-PREVIEW-AMS,1,2,assembly typo\n"
        f"{item['item_id']},, ,50,too much\n"
    ).encode("utf-8")
    response = client.post(
        "/api/reservations/import-preview",
        files={"file": ("reservations-preview.csv", csv_content, "text/csv")},
    )
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["summary"]["needs_review"] >= 1
    assert payload["can_auto_accept"] is False
    assert payload["rows"][0]["requires_user_selection"] is True
    assert payload["rows"][0]["allowed_entity_types"] == ["item", "assembly"]
    assert payload["rows"][0]["suggested_match"]["entity_type"] == "assembly"
    assert payload["rows"][1]["status"] == "needs_review"
    assert "Not enough available inventory" in payload["rows"][1]["message"]


def test_reservations_import_accepts_preview_target_override(client):
    manufacturer = client.post("/api/manufacturers", json={"name": "API-RES-OVERRIDE-MFG"}).json()["data"]
    item = client.post(
        "/api/items",
        json={
            "item_number": "API-RES-OVERRIDE-ITEM",
            "manufacturer_id": manufacturer["manufacturer_id"],
            "category": "Mirror",
        },
    ).json()["data"]
    client.post(
        "/api/inventory/adjust",
        json={"item_id": item["item_id"], "quantity_delta": 10, "location": "STOCK"},
    )

    csv_content = (
        "assembly,quantity,purpose\n"
        "API-RES-OVERRIDE-ASM,3,override target\n"
    ).encode("utf-8")
    response = client.post(
        "/api/reservations/import-csv",
        files={"file": ("reservations-override.csv", csv_content, "text/csv")},
        data={"row_overrides": json.dumps({"2": {"item_id": item["item_id"]}})},
    )
    assert response.status_code == 200
    rows = response.json()["data"]
    assert len(rows) == 1
    assert rows[0]["item_id"] == item["item_id"]
    assert rows[0]["quantity"] == 3


def test_reservations_import_rejects_override_without_target_field(client):
    csv_content = make_csv_bytes(
        ["assembly", "quantity", "purpose"],
        [
            {
                "assembly": "API-RES-MISSING-TARGET-ASM",
                "quantity": "1",
                "purpose": "missing target override",
            }
        ],
    )

    response = client.post(
        "/api/reservations/import-csv",
        files={"file": ("reservations-missing-target.csv", csv_content, "text/csv")},
        data={"row_overrides": json.dumps({"2": {}})},
    )
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "INVALID_RESERVATION_IMPORT_OVERRIDE"
    assert error["message"] == "Reservation import override for row 2 must include item_id or assembly_id"


def test_bom_analyze_endpoint_supports_target_date_projection(client):
    client.post("/api/manufacturers", json={"name": "API-BOM-DATE-MFG"})
    item = client.post(
        "/api/items",
        json={
            "item_number": "API-BOM-DATE-ITEM",
            "manufacturer_name": "API-BOM-DATE-MFG",
            "category": "Lens",
        },
    ).json()["data"]
    client.post(
        "/api/inventory/adjust",
        json={
            "item_id": item["item_id"],
            "quantity_delta": 2,
            "location": "STOCK",
            "note": "seed",
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
            "item_number": "API-BOM-DATE-ITEM",
            "quantity": "5",
            "quotation_number": "Q-BOM-DATE-001",
            "issue_date": "2026-03-01",
            "order_date": "2026-03-02",
            "expected_arrival": "2026-03-20",
            "pdf_link": "",
        }
    )
    imported = client.post(
        "/api/orders/import",
        files={"file": ("orders.csv", output.getvalue().encode("utf-8"), "text/csv")},
        data={"supplier_name": "SupplierBomDate"},
    )
    assert imported.status_code == 200

    without_date = client.post(
        "/api/bom/analyze",
        json={
            "rows": [
                {
                    "supplier": "SupplierBomDate",
                    "item_number": "API-BOM-DATE-ITEM",
                    "required_quantity": 6,
                }
            ]
        },
    )
    assert without_date.status_code == 200
    without_rows = without_date.json()["data"]["rows"]
    assert int(without_rows[0]["available_stock"]) == 2
    assert int(without_rows[0]["shortage"]) == 4

    with_date = client.post(
        "/api/bom/analyze",
        json={
            "target_date": FUTURE_TARGET_DATE,
            "rows": [
                {
                    "supplier": "SupplierBomDate",
                    "item_number": "API-BOM-DATE-ITEM",
                    "required_quantity": 6,
                }
            ],
        },
    )
    assert with_date.status_code == 200
    with_payload = with_date.json()["data"]
    assert with_payload["target_date"] == FUTURE_TARGET_DATE
    with_rows = with_payload["rows"]
    assert int(with_rows[0]["available_stock"]) == 7
    assert int(with_rows[0]["shortage"]) == 0


def test_bom_analyze_endpoint_rejects_past_target_date(client):
    response = client.post(
        "/api/bom/analyze",
        json={
            "target_date": "2000-01-01",
            "rows": [
                {
                    "supplier": "SupplierPastDate",
                    "item_number": "ANY-ITEM",
                    "required_quantity": 1,
                }
            ],
        },
    )
    assert response.status_code == 422
    payload = response.json()
    assert payload["status"] == "error"
    assert payload["error"]["code"] == "INVALID_TARGET_DATE"


def test_bom_preview_endpoint_classifies_exact_review_and_unresolved_rows(client):
    supplier = client.post("/api/suppliers", json={"name": "API-BOM-PREVIEW-SUPPLIER"}).json()["data"]
    client.post("/api/manufacturers", json={"name": "API-BOM-PREVIEW-MFG-A"})
    client.post("/api/manufacturers", json={"name": "API-BOM-PREVIEW-MFG-B"})
    exact_item = client.post(
        "/api/items",
        json={
            "item_number": "API-BOM-PREVIEW-CANON",
            "manufacturer_name": "API-BOM-PREVIEW-MFG-A",
            "category": "Lens",
        },
    ).json()["data"]
    duplicate_a = client.post(
        "/api/items",
        json={
            "item_number": "API-BOM-PREVIEW-DUP",
            "manufacturer_name": "API-BOM-PREVIEW-MFG-A",
            "category": "Lens",
        },
    ).json()["data"]
    duplicate_b = client.post(
        "/api/items",
        json={
            "item_number": "API-BOM-PREVIEW-DUP",
            "manufacturer_name": "API-BOM-PREVIEW-MFG-B",
            "category": "Mirror",
        },
    ).json()["data"]
    alias_response = client.post(
        f"/api/suppliers/{supplier['supplier_id']}/aliases",
        json={
            "ordered_item_number": "API-BOM-PREVIEW-ALIAS",
            "canonical_item_id": exact_item["item_id"],
            "units_per_order": 3,
        },
    )
    assert alias_response.status_code == 200
    seed_inventory = client.post(
        "/api/inventory/adjust",
        json={
            "item_id": exact_item["item_id"],
            "quantity_delta": 4,
            "location": "STOCK",
            "note": "seed bom preview",
        },
    )
    assert seed_inventory.status_code == 200

    response = client.post(
        "/api/bom/preview",
        json={
            "rows": [
                {
                    "supplier": "API-BOM-PREVIEW-SUPPLIER",
                    "item_number": "API-BOM-PREVIEW-ALIAS",
                    "required_quantity": 2,
                },
                {
                    "supplier": "API-BOM-PREVIEW-SUPPLIER",
                    "item_number": "API-BOM-PREVIEW-DUP",
                    "required_quantity": 1,
                },
                {
                    "supplier": "",
                    "item_number": "UNREGISTERED-BOM-ROW",
                    "required_quantity": 5,
                },
            ],
            "target_date": FUTURE_TARGET_DATE,
        },
    )
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["summary"] == {
        "total_rows": 3,
        "exact": 1,
        "high_confidence": 0,
        "needs_review": 1,
        "unresolved": 1,
    }
    assert payload["target_date"] == FUTURE_TARGET_DATE

    rows = payload["rows"]
    assert rows[0]["status"] == "exact"
    assert rows[0]["supplier_status"] == "exact"
    assert rows[0]["item_status"] == "exact"
    assert rows[0]["suggested_match"]["entity_id"] == exact_item["item_id"]
    assert rows[0]["canonical_item_number"] == "API-BOM-PREVIEW-CANON"
    assert rows[0]["units_per_order"] == 3
    assert rows[0]["canonical_required_quantity"] == 6
    assert rows[0]["available_stock"] == 4
    assert rows[0]["shortage"] == 2

    assert rows[1]["status"] == "needs_review"
    assert rows[1]["requires_item_selection"] is True
    assert {candidate["entity_id"] for candidate in rows[1]["candidates"]} == {
        duplicate_a["item_id"],
        duplicate_b["item_id"],
    }

    assert rows[2]["status"] == "unresolved"
    assert rows[2]["requires_supplier_selection"] is True
    assert rows[2]["requires_item_selection"] is True


def test_bom_analyze_endpoint_does_not_create_unknown_supplier_for_direct_item(client):
    client.post("/api/manufacturers", json={"name": "API-BOM-ANALYZE-MFG"})
    item = client.post(
        "/api/items",
        json={
            "item_number": "API-BOM-ANALYZE-DIRECT",
            "manufacturer_name": "API-BOM-ANALYZE-MFG",
            "category": "Lens",
        },
    ).json()["data"]
    supplier_list_before = client.get("/api/suppliers")
    assert supplier_list_before.status_code == 200
    before_names = [row["name"] for row in supplier_list_before.json()["data"]]

    response = client.post(
        "/api/bom/analyze",
        json={
            "rows": [
                {
                    "supplier": "API-BOM-UNKNOWN-SUPPLIER",
                    "item_number": "API-BOM-ANALYZE-DIRECT",
                    "required_quantity": 1,
                }
            ]
        },
    )
    assert response.status_code == 200
    row = response.json()["data"]["rows"][0]
    assert row["status"] == "ok"
    assert row["item_id"] == item["item_id"]

    supplier_list_after = client.get("/api/suppliers")
    assert supplier_list_after.status_code == 200
    after_names = [row["name"] for row in supplier_list_after.json()["data"]]
    assert after_names == before_names


def test_project_gap_analysis_endpoint_supports_target_date(client):
    client.post("/api/manufacturers", json={"name": "API-PROJ-GAP-DATE-MFG"})
    item = client.post(
        "/api/items",
        json={
            "item_number": "API-PROJ-GAP-DATE-ITEM",
            "manufacturer_name": "API-PROJ-GAP-DATE-MFG",
            "category": "Lens",
        },
    ).json()["data"]
    client.post(
        "/api/inventory/adjust",
        json={"item_id": item["item_id"], "quantity_delta": 2, "location": "STOCK"},
    )
    project = client.post(
        "/api/projects",
        json={
            "name": "API-PROJ-GAP-DATE-001",
            "requirements": [{"item_id": item["item_id"], "quantity": 6}],
        },
    ).json()["data"]

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
            "item_number": "API-PROJ-GAP-DATE-ITEM",
            "quantity": "5",
            "quotation_number": "Q-PROJ-GAP-001",
            "issue_date": "2026-03-01",
            "order_date": "2026-03-02",
            "expected_arrival": "2026-03-20",
            "pdf_link": "",
        }
    )
    imported = client.post(
        "/api/orders/import",
        files={"file": ("orders.csv", output.getvalue().encode("utf-8"), "text/csv")},
        data={"supplier_name": "SupplierProjectGapDate"},
    )
    assert imported.status_code == 200

    without_date = client.get(f"/api/projects/{project['project_id']}/gap-analysis")
    assert without_date.status_code == 200
    without_payload = without_date.json()["data"]
    assert without_payload["target_date"] == service.today_jst()
    without_rows = without_payload["rows"]
    assert int(without_rows[0]["available_stock"]) == 2
    assert int(without_rows[0]["shortage"]) == 4

    with_date = client.get(
        f"/api/projects/{project['project_id']}/gap-analysis?target_date={FUTURE_TARGET_DATE}"
    )
    assert with_date.status_code == 200
    with_payload = with_date.json()["data"]
    assert with_payload["target_date"] == FUTURE_TARGET_DATE
    with_rows = with_payload["rows"]
    assert int(with_rows[0]["available_stock"]) == 7
    assert int(with_rows[0]["shortage"]) == 0


def test_project_requirements_preview_endpoint_classifies_exact_ambiguous_and_unresolved_rows(client):
    client.post("/api/manufacturers", json={"name": "API-PROJECT-PREVIEW-MFG-A"})
    client.post("/api/manufacturers", json={"name": "API-PROJECT-PREVIEW-MFG-B"})
    exact_item = client.post(
        "/api/items",
        json={
            "item_number": "API-PROJECT-PREVIEW-EXACT",
            "manufacturer_name": "API-PROJECT-PREVIEW-MFG-A",
            "category": "Lens",
        },
    ).json()["data"]
    ambiguous_a = client.post(
        "/api/items",
        json={
            "item_number": "API-PROJECT-PREVIEW-DUP",
            "manufacturer_name": "API-PROJECT-PREVIEW-MFG-A",
            "category": "Lens",
        },
    ).json()["data"]
    ambiguous_b = client.post(
        "/api/items",
        json={
            "item_number": "API-PROJECT-PREVIEW-DUP",
            "manufacturer_name": "API-PROJECT-PREVIEW-MFG-B",
            "category": "Mirror",
        },
    ).json()["data"]

    response = client.post(
        "/api/projects/requirements/preview",
        json={
            "text": "\n".join(
                    [
                        "API-PROJECT-PREVIEW-EXACT,2",
                        "API-PROJECT-PREVIEW-DUP,3",
                        "ZZZ-UNREGISTERED-REQUIREMENT,4",
                    ]
                )
            },
        )
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["summary"]["total_rows"] == 3
    assert payload["summary"]["exact"] == 1
    assert payload["summary"]["needs_review"] == 1
    assert payload["summary"]["unresolved"] == 1

    rows = payload["rows"]
    assert rows[0]["status"] == "exact"
    assert rows[0]["suggested_match"]["entity_id"] == exact_item["item_id"]
    assert rows[0]["quantity"] == "2"

    assert rows[1]["status"] == "needs_review"
    assert rows[1]["requires_user_selection"] is True
    assert {candidate["entity_id"] for candidate in rows[1]["candidates"]} == {
        ambiguous_a["item_id"],
        ambiguous_b["item_id"],
    }

    assert rows[2]["status"] == "unresolved"
    assert rows[2]["requires_user_selection"] is True


def test_project_requirements_preview_endpoint_defaults_invalid_quantity_to_one(client):
    client.post("/api/manufacturers", json={"name": "API-PROJECT-PREVIEW-QTY-MFG"})
    item = client.post(
        "/api/items",
        json={
            "item_number": "API-PROJECT-PREVIEW-QTY",
            "manufacturer_name": "API-PROJECT-PREVIEW-QTY-MFG",
            "category": "Lens",
        },
    ).json()["data"]

    response = client.post(
        "/api/projects/requirements/preview",
        json={"text": "API-PROJECT-PREVIEW-QTY,abc"},
    )
    assert response.status_code == 200
    payload = response.json()["data"]
    row = payload["rows"][0]
    assert row["status"] == "needs_review"
    assert row["quantity"] == "1"
    assert row["quantity_defaulted"] is True
    assert row["suggested_match"]["entity_id"] == item["item_id"]


def test_project_planning_analysis_endpoint_allows_started_committed_projects(client):
    client.post("/api/manufacturers", json={"name": "API-PLAN-INFLIGHT-MFG"})
    item = client.post(
        "/api/items",
        json={
            "item_number": "API-PLAN-INFLIGHT-ITEM",
            "manufacturer_name": "API-PLAN-INFLIGHT-MFG",
            "category": "Lens",
        },
    ).json()["data"]
    project = client.post(
        "/api/projects",
        json={
            "name": "API-PLAN-INFLIGHT-001",
            "status": "ACTIVE",
            "planned_start": "2000-01-01",
            "requirements": [{"item_id": item["item_id"], "quantity": 1}],
        },
    ).json()["data"]

    response = client.get(f"/api/projects/{project['project_id']}/planning-analysis")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["target_date"] == "2000-01-01"
    assert payload["summary"]["planned_start"] == "2000-01-01"
    assert int(payload["rows"][0]["shortage_at_start"]) == 1


def test_workspace_summary_endpoint_returns_committed_and_draft_semantics(client):
    client.post("/api/manufacturers", json={"name": "API-WORKSPACE-SUMMARY-MFG"})
    item = client.post(
        "/api/items",
        json={
            "item_number": "API-WORKSPACE-SUMMARY-ITEM",
            "manufacturer_name": "API-WORKSPACE-SUMMARY-MFG",
            "category": "Lens",
        },
    ).json()["data"]
    committed = client.post(
        "/api/projects",
        json={
            "name": "API-WORKSPACE-SUMMARY-COMMITTED",
            "status": "CONFIRMED",
            "planned_start": FUTURE_TARGET_DATE,
            "requirements": [{"item_id": item["item_id"], "quantity": 2}],
        },
    ).json()["data"]
    draft = client.post(
        "/api/projects",
        json={
            "name": "API-WORKSPACE-SUMMARY-DRAFT",
            "status": "PLANNING",
            "planned_start": "2999-07-01",
            "requirements": [{"item_id": item["item_id"], "quantity": 1}],
        },
    ).json()["data"]

    created = client.post(
        f"/api/projects/{committed['project_id']}/rfq-batches",
        json={"target_date": FUTURE_TARGET_DATE},
    )
    assert created.status_code == 200

    response = client.get("/api/workspace/summary")

    assert response.status_code == 200
    payload = response.json()["data"]
    committed_row = next(
        row for row in payload["projects"] if int(row["project_id"]) == committed["project_id"]
    )
    draft_row = next(
        row for row in payload["projects"] if int(row["project_id"]) == draft["project_id"]
    )

    assert payload["generated_at"]
    assert committed_row["summary_mode"] == "authoritative"
    assert int(committed_row["planning_summary"]["shortage_at_start_total"]) == 2
    assert int(committed_row["rfq_summary"]["open_batch_count"]) == 1
    assert draft_row["summary_mode"] == "preview_required"
    assert draft_row["planning_summary"] is None
    assert any(
        int(row["project_id"]) == committed["project_id"]
        and "cumulative_generic_consumed_before_total" in row
        for row in payload["pipeline"]
    )


def test_item_planning_context_endpoint_and_workspace_export(client):
    client.post("/api/manufacturers", json={"name": "API-WORKSPACE-CONTEXT-MFG"})
    item = client.post(
        "/api/items",
        json={
            "item_number": "API-WORKSPACE-CONTEXT-ITEM",
            "manufacturer_name": "API-WORKSPACE-CONTEXT-MFG",
            "category": "Lens",
        },
    ).json()["data"]
    client.post(
        "/api/inventory/adjust",
        json={
            "item_id": item["item_id"],
            "quantity_delta": 2,
            "location": "STOCK",
            "note": "workspace context seed",
        },
    )
    committed = client.post(
        "/api/projects",
        json={
            "name": "API-WORKSPACE-CONTEXT-COMMITTED",
            "status": "CONFIRMED",
            "planned_start": "2999-05-01",
            "requirements": [{"item_id": item["item_id"], "quantity": 1}],
        },
    ).json()["data"]
    preview = client.post(
        "/api/projects",
        json={
            "name": "API-WORKSPACE-CONTEXT-PREVIEW",
            "status": "PLANNING",
            "planned_start": FUTURE_TARGET_DATE,
            "requirements": [{"item_id": item["item_id"], "quantity": 3}],
        },
    ).json()["data"]

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
            "item_number": item["item_number"],
            "quantity": "1",
            "quotation_number": "Q-API-WORKSPACE-CONTEXT-001",
            "issue_date": "2026-03-01",
            "order_date": "2026-03-02",
            "expected_arrival": FUTURE_TARGET_DATE,
            "pdf_link": "",
        }
    )
    imported = client.post(
        "/api/orders/import",
        files={"file": ("orders.csv", output.getvalue().encode("utf-8"), "text/csv")},
        data={"supplier_name": "ApiWorkspaceContextSupplier"},
    )
    assert imported.status_code == 200

    planning_context = client.get(
        f"/api/items/{item['item_id']}/planning-context",
        params={
            "preview_project_id": preview["project_id"],
            "target_date": FUTURE_TARGET_DATE,
        },
    )
    assert planning_context.status_code == 200
    context_payload = planning_context.json()["data"]
    assert [int(row["project_id"]) for row in context_payload["projects"]] == [
        committed["project_id"],
        preview["project_id"],
    ]
    assert context_payload["projects"][1]["is_planning_preview"] is True

    export_response = client.get(
        "/api/workspace/planning-export",
        params={"project_id": preview["project_id"], "target_date": FUTURE_TARGET_DATE},
    )
    assert export_response.status_code == 200
    assert "text/csv" in export_response.headers["content-type"]
    export_text = export_response.content.decode("utf-8-sig")
    assert "section,project_id,project_name" in export_text
    assert "selected_project_item" in export_text
    assert "pipeline" in export_text


def test_project_rfq_batch_endpoint_uses_requested_target_date(client):
    client.post("/api/manufacturers", json={"name": "API-RFQ-TARGET-DATE-MFG"})
    item = client.post(
        "/api/items",
        json={
            "item_number": "API-RFQ-TARGET-DATE-ITEM",
            "manufacturer_name": "API-RFQ-TARGET-DATE-MFG",
            "category": "Lens",
        },
    ).json()["data"]
    project = client.post(
        "/api/projects",
        json={
            "name": "API-RFQ-TARGET-DATE-001",
            "planned_start": "2999-01-01",
            "requirements": [{"item_id": item["item_id"], "quantity": 5}],
        },
    ).json()["data"]

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
            "item_number": "API-RFQ-TARGET-DATE-ITEM",
            "quantity": "3",
            "quotation_number": "Q-RFQ-TARGET-DATE-001",
            "issue_date": "2026-03-01",
            "order_date": "2026-03-02",
            "expected_arrival": "2999-03-01",
            "pdf_link": "",
        }
    )
    imported = client.post(
        "/api/orders/import",
        files={"file": ("orders.csv", output.getvalue().encode("utf-8"), "text/csv")},
        data={"supplier_name": "ApiRfqTargetDateSupplier"},
    )
    assert imported.status_code == 200

    created = client.post(
        f"/api/projects/{project['project_id']}/rfq-batches",
        json={"target_date": "2999-06-01"},
    )

    assert created.status_code == 200
    payload = created.json()["data"]
    assert payload["target_date"] == "2999-06-01"
    assert int(payload["lines"][0]["requested_quantity"]) == 2

    refreshed_project = client.get(f"/api/projects/{project['project_id']}")
    assert refreshed_project.status_code == 200
    assert refreshed_project.json()["data"]["planned_start"] == "2999-06-01"


def test_update_order_endpoint_rejects_manual_project_override_for_rfq_owned_order(client):
    client.post("/api/manufacturers", json={"name": "API-RFQ-ORDER-GUARD-MFG"})
    item = client.post(
        "/api/items",
        json={
            "item_number": "API-RFQ-ORDER-GUARD-ITEM",
            "manufacturer_name": "API-RFQ-ORDER-GUARD-MFG",
            "category": "Lens",
        },
    ).json()["data"]
    owner_project = client.post(
        "/api/projects",
        json={
            "name": "API-RFQ-ORDER-GUARD-OWNER",
            "planned_start": FUTURE_TARGET_DATE,
            "requirements": [{"item_id": item["item_id"], "quantity": 5}],
        },
    ).json()["data"]
    other_project = client.post(
        "/api/projects",
        json={
            "name": "API-RFQ-ORDER-GUARD-OTHER",
            "planned_start": FUTURE_TARGET_DATE,
            "requirements": [{"item_id": item["item_id"], "quantity": 1}],
        },
    ).json()["data"]
    rfq = client.post(
        f"/api/projects/{owner_project['project_id']}/rfq-batches",
        json={"target_date": FUTURE_TARGET_DATE},
    )
    assert rfq.status_code == 200
    line_id = rfq.json()["data"]["lines"][0]["line_id"]

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
            "item_number": "API-RFQ-ORDER-GUARD-ITEM",
            "quantity": "5",
            "quotation_number": "Q-API-RFQ-ORDER-GUARD-001",
            "issue_date": "2026-03-01",
            "order_date": "2026-03-02",
            "expected_arrival": FUTURE_TARGET_DATE,
            "pdf_link": "",
        }
    )
    imported = client.post(
        "/api/orders/import",
        files={"file": ("orders.csv", output.getvalue().encode("utf-8"), "text/csv")},
        data={"supplier_name": "ApiRfqOrderGuardSupplier"},
    )
    assert imported.status_code == 200
    order_id = imported.json()["data"]["order_ids"][0]

    linked = client.put(
        f"/api/rfq-lines/{line_id}",
        json={"linked_order_id": order_id, "status": "ORDERED"},
    )
    assert linked.status_code == 200

    blocked = client.put(
        f"/api/orders/{order_id}",
        json={"project_id": other_project["project_id"]},
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "ORDER_PROJECT_MANAGED_BY_RFQ"

    refreshed_order = client.get(f"/api/orders/{order_id}")
    assert refreshed_order.status_code == 200
    assert refreshed_order.json()["data"]["project_id"] == owner_project["project_id"]


def test_rfq_line_endpoint_clears_stale_link_when_reverted_to_quoted(client):
    client.post("/api/manufacturers", json={"name": "API-RFQ-STALE-LINK-MFG"})
    item = client.post(
        "/api/items",
        json={
            "item_number": "API-RFQ-STALE-LINK-ITEM",
            "manufacturer_name": "API-RFQ-STALE-LINK-MFG",
            "category": "Lens",
        },
    ).json()["data"]
    project = client.post(
        "/api/projects",
        json={
            "name": "API-RFQ-STALE-LINK-PROJECT",
            "planned_start": FUTURE_TARGET_DATE,
            "requirements": [{"item_id": item["item_id"], "quantity": 5}],
        },
    ).json()["data"]
    rfq = client.post(
        f"/api/projects/{project['project_id']}/rfq-batches",
        json={"target_date": FUTURE_TARGET_DATE},
    )
    assert rfq.status_code == 200
    line_id = rfq.json()["data"]["lines"][0]["line_id"]

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
            "item_number": "API-RFQ-STALE-LINK-ITEM",
            "quantity": "5",
            "quotation_number": "Q-API-RFQ-STALE-LINK-001",
            "issue_date": "2026-03-01",
            "order_date": "2026-03-02",
            "expected_arrival": FUTURE_TARGET_DATE,
            "pdf_link": "",
        }
    )
    imported = client.post(
        "/api/orders/import",
        files={"file": ("orders.csv", output.getvalue().encode("utf-8"), "text/csv")},
        data={"supplier_name": "ApiRfqStaleLinkSupplier"},
    )
    assert imported.status_code == 200
    order_id = imported.json()["data"]["order_ids"][0]

    ordered = client.put(
        f"/api/rfq-lines/{line_id}",
        json={"linked_order_id": order_id, "status": "ORDERED"},
    )
    assert ordered.status_code == 200

    quoted = client.put(
        f"/api/rfq-lines/{line_id}",
        json={
            "expected_arrival": FUTURE_TARGET_DATE,
            "linked_order_id": order_id,
            "status": "QUOTED",
        },
    )
    assert quoted.status_code == 200
    line = quoted.json()["data"]["line"]
    assert line["status"] == "QUOTED"
    assert line["linked_order_id"] is None

    refreshed_order = client.get(f"/api/orders/{order_id}")
    assert refreshed_order.status_code == 200
    assert refreshed_order.json()["data"]["project_id"] is None


def test_purchase_candidates_endpoints_flow(client):
    client.post("/api/manufacturers", json={"name": "API-PURCHASE-CAND-MFG"})
    item = client.post(
        "/api/items",
        json={
            "item_number": "API-PURCHASE-CAND-ITEM",
            "manufacturer_name": "API-PURCHASE-CAND-MFG",
            "category": "Lens",
        },
    ).json()["data"]
    client.post(
        "/api/inventory/adjust",
        json={"item_id": item["item_id"], "quantity_delta": 2, "location": "STOCK"},
    )
    project = client.post(
        "/api/projects",
        json={
            "name": "API-PURCHASE-CAND-PROJ-001",
            "requirements": [{"item_id": item["item_id"], "quantity": 6}],
        },
    ).json()["data"]

    from_project = client.post(
        f"/api/purchase-candidates/from-project/{project['project_id']}",
        json={"target_date": FUTURE_TARGET_DATE},
    )
    assert from_project.status_code == 200
    from_project_payload = from_project.json()["data"]
    assert from_project_payload["created_count"] == 1
    candidate_id = from_project_payload["created"][0]["candidate_id"]

    listed = client.get("/api/purchase-candidates?status=OPEN&per_page=50")
    assert listed.status_code == 200
    assert any(int(row["candidate_id"]) == int(candidate_id) for row in listed.json()["data"])

    updated = client.put(
        f"/api/purchase-candidates/{candidate_id}",
        json={"status": "ORDERING", "note": "RFQ in progress"},
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["status"] == "ORDERING"
    assert updated.json()["data"]["note"] == "RFQ in progress"

    from_bom = client.post(
        "/api/purchase-candidates/from-bom",
        json={
            "rows": [
                {
                    "supplier": "SupplierPurchaseCandidate",
                    "item_number": "API-PURCHASE-CAND-ITEM",
                    "required_quantity": 5,
                },
                {
                    "supplier": "SupplierPurchaseCandidate",
                    "item_number": "MISSING-PURCHASE-CAND",
                    "required_quantity": 2,
                },
            ]
        },
    )
    assert from_bom.status_code == 200
    assert from_bom.json()["data"]["created_count"] == 2
