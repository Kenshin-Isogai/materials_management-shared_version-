from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, File, Form, Header, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import get_auth_mode
from .db import get_connection, init_db
from .errors import AppError
from . import service
from .schemas import (
    AliasUpsertRequest,
    AssemblyCreate,
    AssemblyUpdate,
    BomAnalyzeRequest,
    BomReserveRequest,
    CategoryMergeRequest,
    InventoryAdjustRequest,
    InventoryBatchRequest,
    InventoryConsumeRequest,
    InventoryMoveRequest,
    ItemCreate,
    ItemMetadataBulkUpdateRequest,
    ItemUpdate,
    LocationAssemblySetRequest,
    MissingItemRegistrationRequest,
    ManufacturerCreate,
    OrderMergeRequest,
    OrderUpdateRequest,
    PartialArrivalRequest,
    PurchaseCandidateUpdate,
    PurchaseCandidatesFromBomRequest,
    PurchaseCandidatesFromProjectRequest,
    ProjectCreate,
    ProjectUpdate,
    ReservationActionRequest,
    ReservationBatchRequest,
    ReservationCreate,
    ReservationUpdate,
    SupplierCreate,
    TransactionUndoRequest,
    UnregisteredBatchRequest,
    UnregisteredFileRetryRequest,
)


def ok(data: Any, pagination: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"status": "ok", "data": data}
    if pagination is not None:
        payload["pagination"] = pagination
    return payload


def _db_dep(app: FastAPI):
    def _get_db():
        conn = get_connection(app.state.db_path)
        try:
            yield conn
        finally:
            conn.close()

    return _get_db


def _optional_role_dep():
    def _get_role(x_user_role: str | None = Header(default=None, alias="X-User-Role")) -> str | None:
        if x_user_role is None:
            return None
        normalized = x_user_role.strip().lower()
        return normalized or None

    return _get_role


def create_app(db_path: str | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        init_db(db_path=app.state.db_path)
        yield

    app = FastAPI(
        title="Optical Component Inventory Management API",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.db_path = db_path

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(AppError)
    async def app_error_handler(_, exc: AppError):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "status": "error",
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                },
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={
                "status": "error",
                "error": {
                    "code": "INVALID_REQUEST",
                    "message": "Request validation failed",
                    "details": {"errors": exc.errors()},
                },
            },
        )

    db = Depends(_db_dep(app))
    role = Depends(_optional_role_dep())

    @app.get("/api/health")
    def healthcheck():
        return ok({"healthy": True})

    @app.get("/api/auth/capabilities")
    def get_auth_capabilities(current_role: str | None = role):
        auth_mode = get_auth_mode()
        planned_roles = ["admin", "operator", "viewer"]
        effective_role = current_role or "operator"
        return ok(
            {
                "auth_mode": auth_mode,
                "auth_enforced": auth_mode != "none",
                "planned_roles": planned_roles,
                "effective_role": effective_role,
            }
        )

    @app.get("/api/dashboard/summary")
    def get_dashboard_summary(conn= db):
        data = service.dashboard_summary(conn)
        return ok(data)

    @app.get("/api/items")
    def get_items(
        q: str | None = None,
        category: str | None = None,
        manufacturer: str | None = None,
        page: int = 1,
        per_page: int = 50,
        conn= db,
    ):
        data, pagination = service.list_items(
            conn,
            q=q,
            category=category,
            manufacturer=manufacturer,
            page=page,
            per_page=per_page,
        )
        return ok(data, pagination)

    @app.post("/api/items")
    def post_item(body: ItemCreate, conn= db):
        result = service.create_item(conn, body.model_dump())
        conn.commit()
        return ok(result)

    @app.post("/api/items/import")
    async def post_items_import(
        file: UploadFile = File(...),
        continue_on_error: bool = Form(default=True),
        conn= db,
    ):
        content = await file.read()
        result = service.import_items_from_content_with_job(
            conn,
            content=content,
            source_name=file.filename or "items_import.csv",
            continue_on_error=continue_on_error,
        )
        conn.commit()
        return ok(result)

    @app.get("/api/items/import-jobs")
    def get_items_import_jobs(
        page: int = 1,
        per_page: int = 50,
        conn= db,
    ):
        data, pagination = service.list_items_import_jobs(
            conn,
            page=page,
            per_page=per_page,
        )
        return ok(data, pagination)

    @app.get("/api/items/import-jobs/{import_job_id}")
    def get_items_import_job(import_job_id: int, conn= db):
        return ok(service.get_items_import_job(conn, import_job_id))

    @app.post("/api/items/import-jobs/{import_job_id}/undo")
    def post_undo_items_import_job(import_job_id: int, conn= db):
        result = service.undo_items_import_job(conn, import_job_id)
        conn.commit()
        return ok(result)

    @app.post("/api/items/import-jobs/{import_job_id}/redo")
    def post_redo_items_import_job(import_job_id: int, conn= db):
        result = service.redo_items_import_job(conn, import_job_id)
        conn.commit()
        return ok(result)

    @app.get("/api/items/{item_id}")
    def get_item(item_id: int, conn= db):
        return ok(service.get_item(conn, item_id))

    @app.put("/api/items/{item_id}")
    def put_item(item_id: int, body: ItemUpdate, conn= db):
        result = service.update_item(conn, item_id, body.model_dump(exclude_unset=True))
        conn.commit()
        return ok(result)

    @app.post("/api/items/metadata/bulk")
    def post_items_metadata_bulk(body: ItemMetadataBulkUpdateRequest, conn= db):
        result = service.bulk_update_item_metadata(
            conn,
            rows=[row.model_dump(exclude_unset=True) for row in body.rows],
            continue_on_error=body.continue_on_error,
        )
        conn.commit()
        return ok(result)

    @app.delete("/api/items/{item_id}")
    def remove_item(item_id: int, conn= db):
        service.delete_item(conn, item_id)
        conn.commit()
        return ok({"deleted": True})

    @app.get("/api/items/{item_id}/history")
    def get_item_history(item_id: int, conn= db):
        return ok(service.list_item_history(conn, item_id))

    @app.get("/api/items/{item_id}/flow")
    def get_item_flow(item_id: int, conn= db):
        return ok(service.get_item_flow_timeline(conn, item_id))

    @app.get("/api/inventory")
    def get_inventory(
        item_id: int | None = None,
        location: str | None = None,
        page: int = 1,
        per_page: int = 50,
        conn= db,
    ):
        data, pagination = service.list_inventory(
            conn,
            item_id=item_id,
            location=location,
            page=page,
            per_page=per_page,
        )
        return ok(data, pagination)

    @app.get("/api/inventory/snapshot")
    def get_inventory_snapshot(
        date: str | None = None,
        mode: str | None = None,
        conn= db,
    ):
        return ok(service.get_inventory_snapshot(conn, target_date=date, mode=mode))

    @app.post("/api/inventory/move")
    def post_inventory_move(body: InventoryMoveRequest, conn= db):
        result = service.move_inventory(conn, **body.model_dump())
        conn.commit()
        return ok(result)

    @app.post("/api/inventory/consume")
    def post_inventory_consume(body: InventoryConsumeRequest, conn= db):
        result = service.consume_inventory(conn, **body.model_dump())
        conn.commit()
        return ok(result)

    @app.post("/api/inventory/adjust")
    def post_inventory_adjust(body: InventoryAdjustRequest, conn= db):
        result = service.adjust_inventory(conn, **body.model_dump())
        conn.commit()
        return ok(result)


    @app.post("/api/inventory/import-csv")
    async def post_inventory_import_csv(
        file: UploadFile = File(...),
        batch_id: str | None = Form(default=None),
        conn= db,
    ):
        content = await file.read()
        result = service.import_inventory_movements_from_content(
            conn,
            content=content,
            batch_id=batch_id,
        )
        conn.commit()
        return ok(result)

    @app.post("/api/inventory/batch")
    def post_inventory_batch(body: InventoryBatchRequest, conn= db):
        result = service.batch_inventory_operations(
            conn,
            operations=[op.model_dump() for op in body.operations],
            batch_id=body.batch_id,
        )
        conn.commit()
        return ok(result)

    @app.get("/api/orders")
    def get_orders(
        status: str | None = None,
        supplier: str | None = None,
        include_arrived: bool = True,
        page: int = 1,
        per_page: int = 50,
        conn= db,
    ):
        data, pagination = service.list_orders(
            conn,
            status=status,
            supplier=supplier,
            include_arrived=include_arrived,
            page=page,
            per_page=per_page,
        )
        return ok(data, pagination)

    @app.get("/api/orders/{order_id}")
    def get_order(order_id: int, conn= db):
        return ok(service.get_order(conn, order_id))

    @app.put("/api/orders/{order_id}")
    def put_order(order_id: int, body: OrderUpdateRequest, conn= db):
        result = service.update_order(conn, order_id, body.model_dump(exclude_unset=True))
        conn.commit()
        return ok(result)

    @app.delete("/api/orders/{order_id}")
    def delete_order(order_id: int, conn= db):
        result = service.delete_order(conn, order_id)
        conn.commit()
        return ok(result)

    @app.post("/api/orders/merge")
    def post_merge_orders(body: OrderMergeRequest, conn= db):
        result = service.merge_open_orders(
            conn,
            source_order_id=body.source_order_id,
            target_order_id=body.target_order_id,
            expected_arrival=body.expected_arrival,
        )
        conn.commit()
        return ok(result)

    @app.get("/api/orders/{order_id}/lineage")
    def get_order_lineage(order_id: int, conn= db):
        return ok(service.list_order_lineage_events(conn, order_id=order_id))

    @app.post("/api/orders/import")
    async def post_orders_import(
        file: UploadFile = File(...),
        supplier_id: int | None = Form(default=None),
        supplier_name: str | None = Form(default=None),
        default_order_date: str | None = Form(default=None),
        conn= db,
    ):
        content = await file.read()
        result = service.import_orders_from_content(
            conn,
            supplier_id=supplier_id,
            supplier_name=supplier_name,
            content=content,
            default_order_date=default_order_date,
            source_name=file.filename or "order_import.csv",
        )
        conn.commit()
        return ok(result)

    @app.post("/api/orders/register-unregistered-missing")
    def post_register_unregistered_missing(body: UnregisteredBatchRequest, conn= db):
        result = service.register_unregistered_missing_items_csvs(
            conn,
            unregistered_root=body.unregistered_root,
            registered_root=body.registered_root,
            continue_on_error=body.continue_on_error,
        )
        conn.commit()
        return ok(result)

    @app.post("/api/orders/import-unregistered")
    def post_import_unregistered_orders(body: UnregisteredBatchRequest, conn= db):
        result = service.import_unregistered_order_csvs(
            conn,
            unregistered_root=body.unregistered_root,
            registered_root=body.registered_root,
            default_order_date=body.default_order_date,
            continue_on_error=body.continue_on_error,
        )
        conn.commit()
        return ok(result)

    @app.post("/api/orders/retry-unregistered-file")
    def post_retry_unregistered_file(body: UnregisteredFileRetryRequest, conn= db):
        result = service.retry_unregistered_order_csv(
            conn,
            csv_path=body.csv_path,
            unregistered_root=body.unregistered_root,
            registered_root=body.registered_root,
            default_order_date=body.default_order_date,
        )
        conn.commit()
        return ok(result)

    @app.post("/api/orders/{order_id}/arrival")
    def post_order_arrival(order_id: int, body: PartialArrivalRequest | None = None, conn= db):
        quantity = None
        if body is not None:
            quantity = body.quantity
        result = service.process_order_arrival(conn, order_id=order_id, quantity=quantity)
        conn.commit()
        return ok(result)

    @app.post("/api/orders/{order_id}/partial-arrival")
    def post_order_partial_arrival(order_id: int, body: PartialArrivalRequest, conn= db):
        result = service.process_order_arrival(conn, order_id=order_id, quantity=body.quantity)
        conn.commit()
        return ok(result)

    @app.get("/api/quotations")
    def get_quotations(
        supplier: str | None = None,
        page: int = 1,
        per_page: int = 50,
        conn= db,
    ):
        data, pagination = service.list_quotations(
            conn,
            supplier=supplier,
            page=page,
            per_page=per_page,
        )
        return ok(data, pagination)

    @app.put("/api/quotations/{quotation_id}")
    def put_quotation(quotation_id: int, payload: dict[str, Any], conn= db):
        result = service.update_quotation(conn, quotation_id, payload)
        conn.commit()
        return ok(result)

    @app.delete("/api/quotations/{quotation_id}")
    def delete_quotation(quotation_id: int, conn= db):
        result = service.delete_quotation(conn, quotation_id)
        conn.commit()
        return ok(result)

    @app.get("/api/reservations")
    def get_reservations(
        status: str | None = None,
        item_id: int | None = None,
        page: int = 1,
        per_page: int = 50,
        conn= db,
    ):
        data, pagination = service.list_reservations(
            conn,
            status=status,
            item_id=item_id,
            page=page,
            per_page=per_page,
        )
        return ok(data, pagination)

    @app.post("/api/reservations")
    def post_reservation(body: ReservationCreate, conn= db):
        result = service.create_reservation(conn, body.model_dump())
        conn.commit()
        return ok(result)

    @app.put("/api/reservations/{reservation_id}")
    def put_reservation(reservation_id: int, body: ReservationUpdate, conn= db):
        result = service.update_reservation(conn, reservation_id, body.model_dump(exclude_unset=True))
        conn.commit()
        return ok(result)

    @app.post("/api/reservations/{reservation_id}/release")
    def post_release_reservation(
        reservation_id: int,
        body: ReservationActionRequest | None = None,
        conn= db,
    ):
        result = service.release_reservation(
            conn,
            reservation_id,
            quantity=body.quantity if body else None,
            note=body.note if body else None,
        )
        conn.commit()
        return ok(result)

    @app.post("/api/reservations/{reservation_id}/consume")
    def post_consume_reservation(
        reservation_id: int,
        body: ReservationActionRequest | None = None,
        conn= db,
    ):
        result = service.consume_reservation(
            conn,
            reservation_id,
            quantity=body.quantity if body else None,
            note=body.note if body else None,
        )
        conn.commit()
        return ok(result)


    @app.post("/api/reservations/import-csv")
    async def post_reservations_import_csv(
        file: UploadFile = File(...),
        conn= db,
    ):
        content = await file.read()
        result = service.import_reservations_from_content(conn, content=content)
        conn.commit()
        return ok(result)

    @app.post("/api/reservations/batch")
    def post_batch_reservations(body: ReservationBatchRequest, conn= db):
        result = service.batch_create_reservations(
            conn, [entry.model_dump() for entry in body.reservations]
        )
        conn.commit()
        return ok(result)

    @app.get("/api/assemblies")
    def get_assemblies(page: int = 1, per_page: int = 50, conn= db):
        data, pagination = service.list_assemblies(conn, page=page, per_page=per_page)
        return ok(data, pagination)

    @app.get("/api/assemblies/{assembly_id}")
    def get_one_assembly(assembly_id: int, conn= db):
        return ok(service.get_assembly(conn, assembly_id))

    @app.post("/api/assemblies")
    def post_assembly(body: AssemblyCreate, conn= db):
        result = service.create_assembly(conn, body.model_dump())
        conn.commit()
        return ok(result)

    @app.put("/api/assemblies/{assembly_id}")
    def put_assembly(assembly_id: int, body: AssemblyUpdate, conn= db):
        result = service.update_assembly(conn, assembly_id, body.model_dump(exclude_unset=True))
        conn.commit()
        return ok(result)

    @app.delete("/api/assemblies/{assembly_id}")
    def delete_one_assembly(assembly_id: int, conn= db):
        service.delete_assembly(conn, assembly_id)
        conn.commit()
        return ok({"deleted": True})

    @app.get("/api/assemblies/{assembly_id}/locations")
    def get_assembly_location_view(assembly_id: int, conn= db):
        return ok(service.get_assembly_locations(conn, assembly_id))

    @app.put("/api/locations/{location}/assemblies")
    def put_location_assemblies(location: str, body: LocationAssemblySetRequest, conn= db):
        result = service.set_location_assemblies(
            conn,
            location=location,
            assignments=[entry.model_dump() for entry in body.assignments],
        )
        conn.commit()
        return ok(result)

    @app.get("/api/projects")
    def get_projects(page: int = 1, per_page: int = 50, conn= db):
        data, pagination = service.list_projects(conn, page=page, per_page=per_page)
        return ok(data, pagination)

    @app.get("/api/projects/{project_id}")
    def get_project(project_id: int, conn= db):
        return ok(service.get_project(conn, project_id))

    @app.post("/api/projects")
    def post_project(body: ProjectCreate, conn= db):
        result = service.create_project(conn, body.model_dump())
        conn.commit()
        return ok(result)

    @app.put("/api/projects/{project_id}")
    def put_project(project_id: int, body: ProjectUpdate, conn= db):
        result = service.update_project(conn, project_id, body.model_dump(exclude_unset=True))
        conn.commit()
        return ok(result)

    @app.delete("/api/projects/{project_id}")
    def delete_project(project_id: int, conn= db):
        service.delete_project(conn, project_id)
        conn.commit()
        return ok({"deleted": True})

    @app.get("/api/projects/{project_id}/gap-analysis")
    def get_project_gap(project_id: int, target_date: str | None = None, conn= db):
        return ok(service.project_gap_analysis(conn, project_id, target_date=target_date))

    @app.post("/api/projects/{project_id}/reserve")
    def post_project_reserve(project_id: int, conn= db):
        result = service.reserve_project_requirements(conn, project_id)
        conn.commit()
        return ok(result)

    @app.post("/api/bom/analyze")
    def post_bom_analyze(body: BomAnalyzeRequest, conn= db):
        result = service.analyze_bom_rows(
            conn,
            [row.model_dump() for row in body.rows],
            target_date=body.target_date,
        )
        return ok(result)

    @app.post("/api/bom/reserve")
    def post_bom_reserve(body: BomReserveRequest, conn= db):
        result = service.reserve_bom_rows(
            conn,
            rows=[row.model_dump() for row in body.rows],
            purpose=body.purpose,
            deadline=body.deadline,
            note=body.note,
        )
        conn.commit()
        return ok(result)

    @app.get("/api/purchase-candidates")
    def get_purchase_candidates(
        status: str | None = None,
        source_type: str | None = None,
        target_date: str | None = None,
        page: int = 1,
        per_page: int = 50,
        conn= db,
    ):
        data, pagination = service.list_purchase_candidates(
            conn,
            status=status,
            source_type=source_type,
            target_date=target_date,
            page=page,
            per_page=per_page,
        )
        return ok(data, pagination)

    @app.get("/api/purchase-candidates/{candidate_id}")
    def get_purchase_candidate(candidate_id: int, conn= db):
        return ok(service.get_purchase_candidate(conn, candidate_id))

    @app.post("/api/purchase-candidates/from-bom")
    def post_purchase_candidates_from_bom(body: PurchaseCandidatesFromBomRequest, conn= db):
        result = service.create_purchase_candidates_from_bom(
            conn,
            rows=[row.model_dump() for row in body.rows],
            target_date=body.target_date,
            note=body.note,
        )
        conn.commit()
        return ok(result)

    @app.post("/api/purchase-candidates/from-project/{project_id}")
    def post_purchase_candidates_from_project(
        project_id: int,
        body: PurchaseCandidatesFromProjectRequest,
        conn= db,
    ):
        result = service.create_purchase_candidates_from_project_gap(
            conn,
            project_id,
            target_date=body.target_date,
            note=body.note,
        )
        conn.commit()
        return ok(result)

    @app.put("/api/purchase-candidates/{candidate_id}")
    def put_purchase_candidate(candidate_id: int, body: PurchaseCandidateUpdate, conn= db):
        result = service.update_purchase_candidate(
            conn,
            candidate_id,
            body.model_dump(exclude_unset=True),
        )
        conn.commit()
        return ok(result)

    @app.get("/api/locations")
    def get_locations(conn= db):
        return ok(service.list_locations(conn))

    @app.get("/api/locations/{location}")
    def get_location(location: str, conn= db):
        return ok(service.inspect_location(conn, location))

    @app.post("/api/locations/{location}/disassemble")
    def post_location_disassemble(location: str, conn= db):
        result = service.disassemble_location(conn, location)
        conn.commit()
        return ok(result)

    @app.get("/api/transactions")
    def get_transactions(
        item_id: int | None = None,
        batch_id: str | None = None,
        page: int = 1,
        per_page: int = 50,
        conn= db,
    ):
        data, pagination = service.list_transactions(
            conn,
            item_id=item_id,
            batch_id=batch_id,
            page=page,
            per_page=per_page,
        )
        return ok(data, pagination)

    @app.post("/api/transactions/{log_id}/undo")
    def post_undo_transaction(log_id: int, body: TransactionUndoRequest | None = None, conn= db):
        note = body.note if body else None
        result = service.undo_transaction(conn, log_id, note=note)
        conn.commit()
        return ok(result)

    @app.get("/api/manufacturers")
    def get_manufacturers(conn= db):
        return ok(service.list_manufacturers(conn))

    @app.post("/api/manufacturers")
    def post_manufacturer(body: ManufacturerCreate, conn= db):
        result = service.create_manufacturer(conn, body.name)
        conn.commit()
        return ok(result)

    @app.get("/api/suppliers")
    def get_suppliers(conn= db):
        return ok(service.list_suppliers(conn))

    @app.post("/api/suppliers")
    def post_supplier(body: SupplierCreate, conn= db):
        result = service.create_supplier(conn, body.name)
        conn.commit()
        return ok(result)

    @app.get("/api/suppliers/{supplier_id}/aliases")
    def get_supplier_aliases(supplier_id: int, conn= db):
        return ok(service.list_supplier_item_aliases(conn, supplier_id))

    @app.post("/api/suppliers/{supplier_id}/aliases")
    def post_supplier_alias(supplier_id: int, body: AliasUpsertRequest, conn= db):
        result = service.upsert_supplier_item_alias(
            conn,
            supplier_id=supplier_id,
            **body.model_dump(),
        )
        conn.commit()
        return ok(result)

    @app.delete("/api/aliases/{alias_id}")
    def delete_alias(alias_id: int, conn= db):
        service.delete_supplier_item_alias(conn, alias_id)
        conn.commit()
        return ok({"deleted": True})

    @app.get("/api/categories")
    def get_categories(conn= db):
        return ok(service.list_categories(conn))

    @app.get("/api/categories/raw")
    def get_raw_categories(conn= db):
        return ok(service.list_raw_categories(conn))

    @app.get("/api/categories/aliases")
    def get_category_aliases(conn= db):
        return ok(service.list_category_aliases(conn))

    @app.post("/api/categories/merge")
    def post_category_merge(body: CategoryMergeRequest, conn= db):
        result = service.merge_category_alias(
            conn,
            source_category=body.alias_category,
            target_category=body.canonical_category,
        )
        conn.commit()
        return ok(result)

    @app.delete("/api/categories/aliases/{alias_category}")
    def delete_category_alias(alias_category: str, conn= db):
        service.remove_category_alias(conn, alias_category)
        conn.commit()
        return ok({"deleted": True})

    @app.post("/api/register-missing")
    async def post_register_missing(file: UploadFile = File(...), conn= db):
        content = await file.read()
        result = service.register_missing_items_from_content(conn, content)
        conn.commit()
        return ok(result)

    @app.post("/api/register-missing/rows")
    def post_register_missing_rows(body: MissingItemRegistrationRequest, conn= db):
        result = service.register_missing_items_from_rows(
            conn,
            [row.model_dump() for row in body.rows],
        )
        conn.commit()
        return ok(result)

    return app


app = create_app()
