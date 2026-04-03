from __future__ import annotations

import csv
import json
from io import StringIO

from app import service

def _make_orders_csv(rows: list[dict[str, str]]) -> bytes:
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
        "/api/purchase-order-lines/import",
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

    orders = client.get("/api/purchase-order-lines").json()["data"]
    order = next(row for row in orders if row["quotation_number"] == "Q-DOC-001")
    assert order["quotation_document_url"] == "https://example.sharepoint.com/sites/procurement/Q-DOC-001"
    assert order["purchase_order_document_url"] == "https://example.sharepoint.com/sites/procurement/PO-DOC-001"

    quotations = client.get("/api/quotations").json()["data"]
    quotation = next(row for row in quotations if row["quotation_number"] == "Q-DOC-001")
    assert quotation["quotation_document_url"] == "https://example.sharepoint.com/sites/procurement/Q-DOC-001"

    jobs = client.get("/api/purchase-order-lines/import-jobs")
    assert jobs.status_code == 200
    job = next(row for row in jobs.json()["data"] if row["import_job_id"] == payload["data"]["import_job_id"])
    assert job["import_type"] == "orders"
    assert job["status"] == "ok"

    detail = client.get(f"/api/purchase-order-lines/import-jobs/{payload['data']['import_job_id']}")
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
        "/api/purchase-order-lines/import",
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

    jobs = client.get("/api/purchase-order-lines/import-jobs")
    assert jobs.status_code == 200
    rows = jobs.json()["data"]
    assert len(rows) == 1
    assert rows[0]["source_name"] == "orders.csv"
    assert rows[0]["status"] == "error"
    assert rows[0]["failed_count"] == 1


def test_generated_artifact_metadata_hides_workspace_paths(client):
    response = client.post(
        "/api/purchase-order-lines/import",
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

    detail = client.get(f"/api/purchase-order-lines/import-jobs/{payload['import_job_id']}")
    assert detail.status_code == 200
    assert any(effect["effect_type"] == "order_missing_item" for effect in detail.json()["data"]["effects"])


def test_order_import_preview_accepts_normalized_document_reference(client):
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
        "/api/purchase-order-lines/import-preview",
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

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["rows"][0]["quotation_document_url"] == "not-a-url"


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
        "/api/purchase-order-lines/import",
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

    detail = client.get(f"/api/purchase-order-lines/import-jobs/{import_job_id}")
    assert detail.status_code == 200
    detail_payload = detail.json()["data"]
    assert detail_payload["job"]["request_metadata"]["row_overrides"]["2"]["item_id"] == item["item_id"]
    assert detail_payload["job"]["request_metadata"]["alias_saves"][0]["ordered_item_number"] == "SUP-ORDER-UNDO-001"
    effect_types = {effect["effect_type"] for effect in detail_payload["effects"]}
    assert {"order_created", "quotation_created", "alias_created"} <= effect_types

    orders = client.get("/api/purchase-order-lines?supplier=SupplierOrderUndo&per_page=50")
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

    undo = client.post(f"/api/purchase-order-lines/import-jobs/{import_job_id}/undo")
    assert undo.status_code == 200
    undo_data = undo.json()["data"]
    assert undo_data["status"] == "undone"
    assert undo_data["removed_orders"] == 1
    assert undo_data["removed_quotations"] == 1
    assert undo_data["removed_aliases"] == 1

    orders_after_undo = client.get("/api/purchase-order-lines?supplier=SupplierOrderUndo&per_page=50")
    assert orders_after_undo.status_code == 200
    assert orders_after_undo.json()["data"] == []

    quotations_after_undo = client.get("/api/quotations")
    assert quotations_after_undo.status_code == 200
    assert not any(row["quotation_number"] == "Q-ORDER-UNDO-001" for row in quotations_after_undo.json()["data"])

    aliases_after_undo = client.get(f"/api/suppliers/{supplier['supplier_id']}/aliases")
    assert aliases_after_undo.status_code == 200
    assert aliases_after_undo.json()["data"] == []

    redo = client.post(f"/api/purchase-order-lines/import-jobs/{import_job_id}/redo")
    assert redo.status_code == 200
    redo_data = redo.json()["data"]
    assert redo_data["source_job_id"] == import_job_id
    assert redo_data["redo_job_id"] > import_job_id
    assert redo_data["import_result"]["status"] == "ok"
    assert redo_data["import_result"]["imported_count"] == 1
    assert redo_data["import_result"]["saved_alias_count"] == 1

    orders_after_redo = client.get("/api/purchase-order-lines?supplier=SupplierOrderUndo&per_page=50")
    assert orders_after_redo.status_code == 200
    assert len(orders_after_redo.json()["data"]) == 1

    quotations_after_redo = client.get("/api/quotations")
    assert quotations_after_redo.status_code == 200
    assert any(row["quotation_number"] == "Q-ORDER-UNDO-001" for row in quotations_after_redo.json()["data"])

    aliases_after_redo = client.get(f"/api/suppliers/{supplier['supplier_id']}/aliases")
    assert aliases_after_redo.status_code == 200
    assert len(aliases_after_redo.json()["data"]) == 1


def test_order_import_job_redo_hides_nested_missing_item_paths(client, monkeypatch):
    def _fake_redo_orders_import_job(conn, import_job_id: int):
        return {
            "source_job_id": import_job_id,
            "redo_job_id": import_job_id + 1,
            "import_result": {
                "status": "missing_items",
                "missing_csv_path": "/tmp/private-missing-items.csv",
                "missing_storage_ref": "local://generated_artifacts/private.csv",
                "missing_artifact": {
                    "artifact_id": "artifact-123",
                    "detail_path": "/api/artifacts/artifact-123",
                    "download_path": "/api/artifacts/artifact-123/download",
                },
            },
        }

    monkeypatch.setattr(service, "redo_orders_import_job", _fake_redo_orders_import_job)

    response = client.post("/api/purchase-order-lines/import-jobs/41/redo")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["source_job_id"] == 41
    assert payload["redo_job_id"] == 42
    assert payload["import_result"]["status"] == "missing_items"
    assert "missing_csv_path" not in payload["import_result"]
    assert "missing_storage_ref" not in payload["import_result"]
    assert payload["import_result"]["missing_artifact"]["artifact_id"] == "artifact-123"


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
        "/api/purchase-order-lines/import",
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
        f"/api/purchase-order-lines/{order_id}",
        json={
            "purchase_order_document_url": "https://example.sharepoint.com/sites/procurement/PO-ORDER-UNDO-BLOCKED-UPDATED",
        },
    )
    assert mutate.status_code == 200

    undo = client.post(f"/api/purchase-order-lines/import-jobs/{import_job_id}/undo")
    assert undo.status_code == 409
    undo_payload = undo.json()
    assert undo_payload["status"] == "error"
    assert undo_payload["error"]["code"] == "IMPORT_UNDO_CONFLICT"

    detail = client.get(f"/api/purchase-order-lines/import-jobs/{import_job_id}")
    assert detail.status_code == 200
    assert detail.json()["data"]["job"]["lifecycle_state"] == "active"


def test_update_order_allows_purchase_order_document_url_change_on_current_header(client):
    client.post("/api/manufacturers", json={"name": "API-PO-UPDATE-MFG"})
    client.post(
        "/api/items",
        json={
            "item_number": "API-PO-UPDATE-ITEM",
            "manufacturer_name": "API-PO-UPDATE-MFG",
            "category": "Lens",
        },
    )

    imported = client.post(
        "/api/purchase-order-lines/import",
        files={
            "file": (
                "orders.csv",
                _make_orders_csv(
                    [
                        {
                            "item_number": "API-PO-UPDATE-ITEM",
                            "quantity": "1",
                            "purchase_order_number": "PO-UPDATE-URL-001",
                            "quotation_number": "Q-UPDATE-URL-001",
                            "issue_date": "2026-02-21",
                            "quotation_document_url": "https://example.sharepoint.com/sites/procurement/Q-UPDATE-URL-001",
                            "purchase_order_document_url": "https://example.sharepoint.com/sites/procurement/PO-UPDATE-URL-001",
                            "order_date": "2026-02-22",
                            "expected_arrival": "2026-03-01",
                        }
                    ]
                ),
                "text/csv",
            )
        },
        data={"supplier_name": "SupplierPurchaseOrderUpdate"},
    )
    assert imported.status_code == 200
    order_id = int(imported.json()["data"]["order_ids"][0])
    before = client.get(f"/api/purchase-order-lines/{order_id}")
    assert before.status_code == 200
    before_order = before.json()["data"]

    updated = client.put(
        f"/api/purchase-order-lines/{order_id}",
        json={
            "purchase_order_document_url": "https://example.sharepoint.com/sites/procurement/PO-UPDATE-URL-UPDATED",
        },
    )

    assert updated.status_code == 200
    after_order = updated.json()["data"]
    assert int(after_order["purchase_order_id"]) == int(before_order["purchase_order_id"])
    assert after_order["purchase_order_document_url"] == "https://example.sharepoint.com/sites/procurement/PO-UPDATE-URL-UPDATED"

    purchase_orders = client.get("/api/purchase-orders")
    assert purchase_orders.status_code == 200
    header = next(
        row
        for row in purchase_orders.json()["data"]
        if int(row["purchase_order_id"]) == int(before_order["purchase_order_id"])
    )
    assert header["purchase_order_document_url"] == "https://example.sharepoint.com/sites/procurement/PO-UPDATE-URL-UPDATED"


def test_update_order_can_reassign_to_existing_purchase_order_by_document_url(client):
    client.post("/api/manufacturers", json={"name": "API-PO-REASSIGN-MFG"})
    client.post(
        "/api/items",
        json={
            "item_number": "API-PO-REASSIGN-ITEM",
            "manufacturer_name": "API-PO-REASSIGN-MFG",
            "category": "Lens",
        },
    )

    imported = client.post(
        "/api/purchase-order-lines/import",
        files={
            "file": (
                "orders.csv",
                _make_orders_csv(
                    [
                        {
                            "item_number": "API-PO-REASSIGN-ITEM",
                            "quantity": "1",
                            "purchase_order_number": "PO-REASSIGN-001",
                            "quotation_number": "Q-REASSIGN-001",
                            "issue_date": "2026-02-21",
                            "quotation_document_url": "https://example.sharepoint.com/sites/procurement/Q-REASSIGN-001",
                            "purchase_order_document_url": "https://example.sharepoint.com/sites/procurement/PO-REASSIGN-001",
                            "order_date": "2026-02-22",
                            "expected_arrival": "2026-03-01",
                        },
                        {
                            "item_number": "API-PO-REASSIGN-ITEM",
                            "quantity": "2",
                            "purchase_order_number": "PO-REASSIGN-002",
                            "quotation_number": "Q-REASSIGN-002",
                            "issue_date": "2026-02-22",
                            "quotation_document_url": "https://example.sharepoint.com/sites/procurement/Q-REASSIGN-002",
                            "purchase_order_document_url": "https://example.sharepoint.com/sites/procurement/PO-REASSIGN-002",
                            "order_date": "2026-02-23",
                            "expected_arrival": "2026-03-02",
                        },
                    ]
                ),
                "text/csv",
            )
        },
        data={"supplier_name": "SupplierPurchaseOrderReassign"},
    )
    assert imported.status_code == 200
    first_order_id = int(imported.json()["data"]["order_ids"][0])
    second_order_id = int(imported.json()["data"]["order_ids"][1])

    first_before = client.get(f"/api/purchase-order-lines/{first_order_id}")
    second_before = client.get(f"/api/purchase-order-lines/{second_order_id}")
    assert first_before.status_code == 200
    assert second_before.status_code == 200
    first_header_id = int(first_before.json()["data"]["purchase_order_id"])
    second_header_id = int(second_before.json()["data"]["purchase_order_id"])
    assert first_header_id != second_header_id

    updated = client.put(
        f"/api/purchase-order-lines/{first_order_id}",
        json={
            "purchase_order_document_url": "https://example.sharepoint.com/sites/procurement/PO-REASSIGN-002",
        },
    )

    assert updated.status_code == 200
    after_order = updated.json()["data"]
    assert int(after_order["purchase_order_id"]) == second_header_id
    assert after_order["purchase_order_number"] == "PO-REASSIGN-002"
    assert after_order["purchase_order_document_url"] == "https://example.sharepoint.com/sites/procurement/PO-REASSIGN-002"

    purchase_orders = client.get("/api/purchase-orders")
    assert purchase_orders.status_code == 200
    purchase_order_ids = {int(row["purchase_order_id"]) for row in purchase_orders.json()["data"]}
    assert second_header_id in purchase_order_ids
    assert first_header_id not in purchase_order_ids
