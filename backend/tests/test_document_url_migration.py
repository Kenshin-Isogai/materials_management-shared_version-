from __future__ import annotations

import csv
import json
from io import StringIO

def _make_orders_csv(rows: list[dict[str, str]]) -> bytes:
    output = StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "item_number",
            "quantity",
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


def test_manual_order_import_accepts_external_document_urls(client):
    client.post("/api/manufacturers", json={"name": "API-DOC-URL-MFG"})
    client.post(
        "/api/items",
        json={
            "item_number": "API-DOC-URL-ITEM",
            "manufacturer_name": "API-DOC-URL-MFG",
            "category": "Lens",
        },
    )

    response = client.post(
        "/api/orders/import",
        files={
            "file": (
                "orders.csv",
                _make_orders_csv(
                    [
                        {
                            "item_number": "API-DOC-URL-ITEM",
                            "quantity": "2",
                            "quotation_number": "Q-DOC-001",
                            "issue_date": "2026-02-21",
                            "quotation_document_url": "https://example.sharepoint.com/sites/procurement/Q-DOC-001",
                            "purchase_order_document_url": "https://example.sharepoint.com/sites/procurement/PO-DOC-001",
                            "order_date": "2026-02-22",
                            "expected_arrival": "2026-03-01",
                        }
                    ]
                ),
                "text/csv",
            )
        },
        data={"supplier_name": "SupplierDocumentUrl"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["data"]["imported_count"] == 1
    assert isinstance(payload["data"]["import_job_id"], int)

    orders = client.get("/api/orders").json()["data"]
    order = next(row for row in orders if row["quotation_number"] == "Q-DOC-001")
    assert order["quotation_document_url"] == "https://example.sharepoint.com/sites/procurement/Q-DOC-001"
    assert order["purchase_order_document_url"] == "https://example.sharepoint.com/sites/procurement/PO-DOC-001"

    quotations = client.get("/api/quotations").json()["data"]
    quotation = next(row for row in quotations if row["quotation_number"] == "Q-DOC-001")
    assert quotation["quotation_document_url"] == "https://example.sharepoint.com/sites/procurement/Q-DOC-001"

    jobs = client.get("/api/orders/import-jobs")
    assert jobs.status_code == 200
    job = next(row for row in jobs.json()["data"] if row["import_job_id"] == payload["data"]["import_job_id"])
    assert job["import_type"] == "orders"
    assert job["status"] == "ok"

    detail = client.get(f"/api/orders/import-jobs/{payload['data']['import_job_id']}")
    assert detail.status_code == 200
    detail_payload = detail.json()["data"]
    assert detail_payload["job"]["import_type"] == "orders"
    assert any(effect["effect_type"] == "order_created" for effect in detail_payload["effects"])


def test_manual_order_import_requires_quotation_document_url(client):
    client.post("/api/manufacturers", json={"name": "API-DOC-REQUIRED-MFG"})
    client.post(
        "/api/items",
        json={
            "item_number": "API-DOC-REQUIRED-ITEM",
            "manufacturer_name": "API-DOC-REQUIRED-MFG",
            "category": "Lens",
        },
    )

    response = client.post(
        "/api/orders/import",
        files={
            "file": (
                "orders.csv",
                _make_orders_csv(
                    [
                        {
                            "item_number": "API-DOC-REQUIRED-ITEM",
                            "quantity": "1",
                            "quotation_number": "Q-DOC-REQ-001",
                            "issue_date": "2026-02-21",
                            "quotation_document_url": "",
                            "purchase_order_document_url": "",
                            "order_date": "2026-02-22",
                            "expected_arrival": "2026-03-01",
                        }
                    ]
                ),
                "text/csv",
            )
        },
        data={"supplier_name": "SupplierDocumentRequired"},
    )

    assert response.status_code == 422
    payload = response.json()
    assert payload["status"] == "error"
    assert payload["error"]["code"] == "INVALID_FIELD"
    assert "quotation_document_url" in payload["error"]["message"]

    jobs = client.get("/api/orders/import-jobs")
    assert jobs.status_code == 200
    rows = jobs.json()["data"]
    assert len(rows) == 1
    assert rows[0]["source_name"] == "orders.csv"
    assert rows[0]["status"] == "error"
    assert rows[0]["failed_count"] == 1


def test_generated_artifact_metadata_hides_workspace_paths(client):
    response = client.post(
        "/api/orders/import",
        files={
            "file": (
                "orders.csv",
                _make_orders_csv(
                    [
                        {
                            "item_number": "MISSING-ARTIFACT-ITEM",
                            "quantity": "1",
                            "quotation_number": "Q-ART-001",
                            "issue_date": "2026-02-21",
                            "quotation_document_url": "https://example.sharepoint.com/sites/procurement/Q-ART-001",
                            "purchase_order_document_url": "",
                            "order_date": "2026-02-22",
                            "expected_arrival": "2026-03-01",
                        }
                    ]
                ),
                "text/csv",
            )
        },
        data={"supplier_name": "SupplierArtifactHidden"},
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["status"] == "missing_items"
    assert isinstance(payload["import_job_id"], int)
    assert "missing_csv_path" not in payload
    assert "missing_storage_ref" not in payload
    artifact = payload["missing_artifact"]
    assert "relative_path" not in artifact
    assert artifact["detail_path"] == f"/api/artifacts/{artifact['artifact_id']}"
    assert artifact["download_path"] == f"/api/artifacts/{artifact['artifact_id']}/download"

    detail = client.get(f"/api/orders/import-jobs/{payload['import_job_id']}")
    assert detail.status_code == 200
    assert any(effect["effect_type"] == "order_missing_item" for effect in detail.json()["data"]["effects"])


def test_order_import_preview_rejects_non_https_document_url(client):
    client.post("/api/manufacturers", json={"name": "API-DOC-PREVIEW-MFG"})
    client.post(
        "/api/items",
        json={
            "item_number": "API-DOC-PREVIEW-ITEM",
            "manufacturer_name": "API-DOC-PREVIEW-MFG",
            "category": "Lens",
        },
    )

    response = client.post(
        "/api/orders/import-preview",
        files={
            "file": (
                "orders.csv",
                _make_orders_csv(
                    [
                        {
                            "item_number": "API-DOC-PREVIEW-ITEM",
                            "quantity": "1",
                            "quotation_number": "Q-DOC-PREVIEW-001",
                            "issue_date": "2026-02-21",
                            "quotation_document_url": "not-a-url",
                            "purchase_order_document_url": "",
                            "order_date": "2026-02-22",
                            "expected_arrival": "2026-03-01",
                        }
                    ]
                ),
                "text/csv",
            )
        },
        data={"supplier_name": "SupplierDocumentPreview"},
    )

    assert response.status_code == 422
    payload = response.json()
    assert payload["status"] == "error"
    assert payload["error"]["code"] == "INVALID_DOCUMENT_URL"


def test_order_import_job_undo_and_redo_flow(client):
    client.post("/api/manufacturers", json={"name": "API-ORDER-UNDO-MFG"})
    item = client.post(
        "/api/items",
        json={
            "item_number": "API-ORDER-UNDO-CANONICAL",
            "manufacturer_name": "API-ORDER-UNDO-MFG",
            "category": "Lens",
        },
    ).json()["data"]

    response = client.post(
        "/api/orders/import",
        files={
            "file": (
                "order_undo.csv",
                _make_orders_csv(
                    [
                        {
                            "item_number": "SUP-ORDER-UNDO-001",
                            "quantity": "2",
                            "quotation_number": "Q-ORDER-UNDO-001",
                            "issue_date": "2026-02-21",
                            "quotation_document_url": "https://example.sharepoint.com/sites/procurement/Q-ORDER-UNDO-001",
                            "purchase_order_document_url": "https://example.sharepoint.com/sites/procurement/PO-ORDER-UNDO-001",
                            "order_date": "2026-02-22",
                            "expected_arrival": "2026-03-01",
                        }
                    ]
                ),
                "text/csv",
            )
        },
        data={
            "supplier_name": "SupplierOrderUndo",
            "row_overrides": json.dumps(
                {
                    "2": {
                        "item_id": item["item_id"],
                        "units_per_order": 4,
                    }
                }
            ),
            "alias_saves": json.dumps(
                [
                    {
                        "ordered_item_number": "SUP-ORDER-UNDO-001",
                        "item_id": item["item_id"],
                        "units_per_order": 4,
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
    import_job_id = int(payload["import_job_id"])

    detail = client.get(f"/api/orders/import-jobs/{import_job_id}")
    assert detail.status_code == 200
    detail_payload = detail.json()["data"]
    assert detail_payload["job"]["request_metadata"]["row_overrides"]["2"]["item_id"] == item["item_id"]
    assert detail_payload["job"]["request_metadata"]["alias_saves"][0]["ordered_item_number"] == "SUP-ORDER-UNDO-001"
    effect_types = {effect["effect_type"] for effect in detail_payload["effects"]}
    assert {"order_created", "quotation_created", "alias_created"} <= effect_types

    orders = client.get("/api/orders?supplier=SupplierOrderUndo&per_page=50")
    assert orders.status_code == 200
    assert len(orders.json()["data"]) == 1

    quotations = client.get("/api/quotations")
    assert quotations.status_code == 200
    assert any(row["quotation_number"] == "Q-ORDER-UNDO-001" for row in quotations.json()["data"])

    suppliers = client.get("/api/suppliers")
    assert suppliers.status_code == 200
    supplier = next(row for row in suppliers.json()["data"] if row["name"] == "SupplierOrderUndo")
    aliases = client.get(f"/api/suppliers/{supplier['supplier_id']}/aliases")
    assert aliases.status_code == 200
    assert len(aliases.json()["data"]) == 1

    undo = client.post(f"/api/orders/import-jobs/{import_job_id}/undo")
    assert undo.status_code == 200
    undo_data = undo.json()["data"]
    assert undo_data["status"] == "undone"
    assert undo_data["removed_orders"] == 1
    assert undo_data["removed_quotations"] == 1
    assert undo_data["removed_aliases"] == 1

    orders_after_undo = client.get("/api/orders?supplier=SupplierOrderUndo&per_page=50")
    assert orders_after_undo.status_code == 200
    assert orders_after_undo.json()["data"] == []

    quotations_after_undo = client.get("/api/quotations")
    assert quotations_after_undo.status_code == 200
    assert not any(row["quotation_number"] == "Q-ORDER-UNDO-001" for row in quotations_after_undo.json()["data"])

    aliases_after_undo = client.get(f"/api/suppliers/{supplier['supplier_id']}/aliases")
    assert aliases_after_undo.status_code == 200
    assert aliases_after_undo.json()["data"] == []

    redo = client.post(f"/api/orders/import-jobs/{import_job_id}/redo")
    assert redo.status_code == 200
    redo_data = redo.json()["data"]
    assert redo_data["source_job_id"] == import_job_id
    assert redo_data["redo_job_id"] > import_job_id
    assert redo_data["import_result"]["status"] == "ok"
    assert redo_data["import_result"]["imported_count"] == 1
    assert redo_data["import_result"]["saved_alias_count"] == 1

    orders_after_redo = client.get("/api/orders?supplier=SupplierOrderUndo&per_page=50")
    assert orders_after_redo.status_code == 200
    assert len(orders_after_redo.json()["data"]) == 1

    quotations_after_redo = client.get("/api/quotations")
    assert quotations_after_redo.status_code == 200
    assert any(row["quotation_number"] == "Q-ORDER-UNDO-001" for row in quotations_after_redo.json()["data"])

    aliases_after_redo = client.get(f"/api/suppliers/{supplier['supplier_id']}/aliases")
    assert aliases_after_redo.status_code == 200
    assert len(aliases_after_redo.json()["data"]) == 1


def test_order_import_job_undo_blocks_when_order_changed_after_import(client):
    client.post("/api/manufacturers", json={"name": "API-ORDER-UNDO-BLOCKED-MFG"})
    client.post(
        "/api/items",
        json={
            "item_number": "API-ORDER-UNDO-BLOCKED-ITEM",
            "manufacturer_name": "API-ORDER-UNDO-BLOCKED-MFG",
            "category": "Lens",
        },
    )

    response = client.post(
        "/api/orders/import",
        files={
            "file": (
                "order_undo_blocked.csv",
                _make_orders_csv(
                    [
                        {
                            "item_number": "API-ORDER-UNDO-BLOCKED-ITEM",
                            "quantity": "1",
                            "quotation_number": "Q-ORDER-UNDO-BLOCKED-001",
                            "issue_date": "2026-02-21",
                            "quotation_document_url": "https://example.sharepoint.com/sites/procurement/Q-ORDER-UNDO-BLOCKED-001",
                            "purchase_order_document_url": "",
                            "order_date": "2026-02-22",
                            "expected_arrival": "2026-03-01",
                        }
                    ]
                ),
                "text/csv",
            )
        },
        data={"supplier_name": "SupplierOrderUndoBlocked"},
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    import_job_id = int(payload["import_job_id"])
    order_id = int(payload["order_ids"][0])

    mutate = client.put(
        f"/api/orders/{order_id}",
        json={
            "purchase_order_document_url": "https://example.sharepoint.com/sites/procurement/PO-ORDER-UNDO-BLOCKED-UPDATED",
        },
    )
    assert mutate.status_code == 200

    undo = client.post(f"/api/orders/import-jobs/{import_job_id}/undo")
    assert undo.status_code == 409
    undo_payload = undo.json()
    assert undo_payload["status"] == "error"
    assert undo_payload["error"]["code"] == "IMPORT_UNDO_CONFLICT"

    detail = client.get(f"/api/orders/import-jobs/{import_job_id}")
    assert detail.status_code == 200
    assert detail.json()["data"]["job"]["lifecycle_state"] == "active"
