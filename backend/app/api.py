from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
import json
import logging
import re
from time import perf_counter
from typing import Any
from uuid import uuid4

from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware

from .config import (
    APP_PORT,
    APP_DATA_ROOT,
    AUTH_MODE_NONE,
    AUTH_MODE_OIDC_DRY_RUN,
    AUTH_MODE_OIDC_ENFORCED,
    AUTO_MIGRATE_ON_STARTUP,
    BACKEND_PUBLIC_BASE_URL,
    CLOUD_RUN_CONCURRENCY_TARGET,
    DB_MAX_OVERFLOW,
    DB_POOL_RECYCLE_SECONDS,
    DB_POOL_SIZE,
    DB_POOL_TIMEOUT,
    FRONTEND_PUBLIC_BASE_URL,
    HEAVY_REQUEST_TARGET_SECONDS,
    INSTANCE_CONNECTION_NAME,
    MAX_UPLOAD_BYTES,
    LOG_LEVEL,
    OIDC_PROVIDER,
    get_diagnostics_auth_role,
    RBAC_MODE_DRY_RUN,
    RBAC_MODE_ENFORCED,
    STRUCTURED_LOGGING,
    get_auth_mode,
    get_cors_allowed_origins,
    get_recovery_policy_summary,
    get_rbac_mode,
    get_runtime_target,
    is_cloud_run_runtime,
    uses_cloud_sql_unix_socket,
)
from .auth import (
    auth_allows_dry_run,
    auth_is_enforced,
    authorization_mode_summary,
    build_identity_resolver,
    endpoint_policy_summary,
    map_identity_to_user,
    rbac_allows_dry_run,
    rbac_is_enforced,
    request_user_role,
    required_role_for_request,
    role_satisfies,
)
from .db import get_connection, init_db
from .errors import AppError
from . import service, storage
from .schemas import (
    AliasUpsertBySupplierNameRequest,
    AliasUpsertRequest,
    BomAnalyzeRequest,
    BomReserveRequest,
    CategoryMergeRequest,
    ConfirmAllocationRequest,
    ConfirmProcurementLinksRequest,
    InventoryAdjustRequest,
    InventoryBatchRequest,
    InventoryConsumeRequest,
    InventoryMoveRequest,
    ItemCreate,
    ItemMetadataBulkUpdateRequest,
    ItemUpdate,
    ManufacturerCreate,
    OrderMergeRequest,
    OrderUpdateRequest,
    PartialArrivalRequest,
    ProcurementBatchAddLinesRequest,
    ProcurementBatchCreateRequest,
    ProcurementBatchUpdate,
    ProcurementLineUpdate,
    QuotationUpdateRequest,
    ProjectCreate,
    ProjectRequirementUnresolvedItemsCsvRequest,
    ProjectRequirementPreviewRequest,
    ProjectUpdate,
    ReservationActionRequest,
    ReservationBatchRequest,
    ReservationCreate,
    ReservationUpdate,
    ShortageInboxToProcurementRequest,
    SupplierCreate,
    TransactionUndoRequest,
    UserCreate,
    UserUpdate,
)


LOGGER = logging.getLogger("materials.api")
_AUDITED_EXPORT_PATTERNS = (
    re.compile(r"^/api/artifacts/[^/]+/download$"),
    re.compile(r"^/api/workspace/planning-export(?:-multi)?$"),
    re.compile(r"^/api/procurement-batches/[^/]+/export\.csv$"),
)
_AUDIT_EXCLUDED_NON_GET_PATTERNS = (
    re.compile(r"^/api/.+/preview(?:/.*)?$"),
    re.compile(r"^/api/projects/requirements/preview/unresolved-items\.csv$"),
    re.compile(r"^/api/bom/analyze$"),
)


class _StructuredLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "severity": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        }
        structured_fields = getattr(record, "structured_fields", None)
        if isinstance(structured_fields, dict):
            payload.update(structured_fields)
        return json.dumps(payload, ensure_ascii=True, default=str)


def _configure_logging() -> None:
    target_config = (STRUCTURED_LOGGING, LOG_LEVEL.lower())
    if getattr(LOGGER, "_materials_config", None) == target_config:
        return
    handler = logging.StreamHandler()
    if STRUCTURED_LOGGING:
        handler.setFormatter(_StructuredLogFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    LOGGER.handlers.clear()
    LOGGER.addHandler(handler)
    LOGGER.setLevel(getattr(logging, LOG_LEVEL.upper(), logging.INFO))
    LOGGER.propagate = False
    setattr(LOGGER, "_materials_config", target_config)


def _log_event(level: int, message: str, **structured_fields: Any) -> None:
    LOGGER.log(level, message, extra={"structured_fields": structured_fields})


def _db_ready(database_url: str | None) -> tuple[bool, str | None]:
    conn = None
    try:
        conn = get_connection(database_url)
        row = conn.execute("SELECT 1 AS ready").fetchone()
        return bool(row and int(row["ready"]) == 1), None
    except Exception as exc:
        _log_event(
            logging.WARNING,
            "Readiness database check failed",
            probe_path="/readyz",
            error_type=exc.__class__.__name__,
            error_message=str(exc),
        )
        return False, "DATABASE_UNAVAILABLE"
    finally:
        if conn is not None:
            conn.close()


def ok(data: Any, pagination: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"status": "ok", "data": data}
    if pagination is not None:
        payload["pagination"] = pagination
    return payload


def csv_attachment(filename: str, content: bytes) -> Response:
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def file_attachment(filename: str, content: bytes) -> Response:
    media_type = "text/csv; charset=utf-8" if filename.lower().endswith(".csv") else "application/octet-stream"
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _without_missing_item_locations(data: dict[str, Any]) -> dict[str, Any]:
    sanitized = dict(data)
    sanitized.pop("missing_csv_path", None)
    sanitized.pop("missing_storage_ref", None)
    return sanitized


def _parse_optional_json_form(value: str | None, field_name: str) -> Any | None:
    if value is None or not str(value).strip():
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise AppError(
            code="INVALID_REQUEST",
            message=f"{field_name} must be valid JSON",
            status_code=422,
        ) from exc


def _public_order_import_result(result: dict[str, Any]) -> dict[str, Any]:
    payload = _without_missing_item_locations(result)
    import_result = payload.get("import_result")
    if isinstance(import_result, dict):
        payload["import_result"] = _without_missing_item_locations(import_result)
    return payload


def _public_item_import_result(result: dict[str, Any]) -> dict[str, Any]:
    payload = dict(result)
    archive = payload.get("archive")
    if isinstance(archive, dict):
        archive_payload = dict(archive)
        archive_payload.pop("cleanup_unreg_file", None)
        archive_payload.pop("archive_storage_ref", None)
        payload["archive"] = archive_payload
    return payload


def _request_too_large_error() -> AppError:
    return AppError(
        code="REQUEST_TOO_LARGE",
        message=f"Request body exceeds the configured limit of {MAX_UPLOAD_BYTES} bytes",
        status_code=413,
        details={"max_upload_bytes": MAX_UPLOAD_BYTES},
    )


def _db_dep(app: FastAPI):
    def _get_db(request: Request):
        conn = get_connection(app.state.database_url)
        current_user = getattr(request.state, "user", None)
        conn.set_actor(None if current_user is None else int(current_user["user_id"]))
        try:
            yield conn
        finally:
            conn.close()

    return _get_db

def cleanup_unreg_file_with_retry(path_str: str) -> None:
    import time
    from pathlib import Path
    p = Path(path_str)
    for _ in range(5):
        time.sleep(1)
        try:
            if p.is_file():
                p.unlink()
            return
        except OSError:
            pass

def _allows_first_user_bootstrap(request: Request) -> bool:
    return request.method == "POST" and request.url.path == "/api/users"


def _app_error_response(exc: AppError) -> JSONResponse:
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


def _should_emit_domain_audit(request: Request, response: Response) -> bool:
    path = request.url.path
    method = request.method.upper()
    if not path.startswith("/api/"):
        return False
    if response.status_code >= 400:
        return False
    if method == "GET":
        return any(pattern.match(path) for pattern in _AUDITED_EXPORT_PATTERNS)
    return not any(pattern.match(path) for pattern in _AUDIT_EXCLUDED_NON_GET_PATTERNS)


def _emit_domain_audit_event(request: Request, response: Response) -> None:
    user = getattr(request.state, "user", None)
    identity = getattr(request.state, "identity", None)
    _log_event(
        logging.INFO,
        "Domain audit event",
        event="domain.audit",
        request_id=getattr(request.state, "request_id", None),
        method=request.method,
        path=request.url.path,
        query=str(request.url.query),
        status_code=response.status_code,
        actor_username=None if not isinstance(user, dict) else user.get("username"),
        actor_role=request_user_role(request),
        actor_user_id=None if not isinstance(user, dict) else user.get("user_id"),
        identity_subject=None if not isinstance(identity, dict) else identity.get("subject"),
        identity_email=None if not isinstance(identity, dict) else identity.get("email"),
        identity_provider=None if not isinstance(identity, dict) else identity.get("provider"),
    )


class RequestIdentityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request.state.identity = None
        request.state.user = None
        request.state.bootstrap_allowed = False
        required_role = required_role_for_request(request)
        if _allows_first_user_bootstrap(request):
            conn = get_connection(request.app.state.database_url)
            try:
                if not service.has_active_users(conn):
                    request.state.bootstrap_allowed = True
                    return await call_next(request)
            finally:
                conn.close()
        resolver = getattr(request.app.state, "identity_resolver", None)
        try:
            identity = None if resolver is None else resolver.resolve(request)
        except AppError as exc:
            if required_role is not None and auth_allows_dry_run():
                _log_event(
                    logging.WARNING,
                    "Auth dry-run would reject request",
                    event="authentication.dry_run_denied",
                    path=request.url.path,
                    method=request.method,
                    error_code=exc.code,
                    error_details=exc.details,
                )
                return await call_next(request)
            return _app_error_response(exc)
        if identity is not None:
            request.state.identity = identity.as_dict()
            try:
                user = map_identity_to_user(request.app.state.database_url, identity)
            except AppError as exc:
                if required_role is not None and auth_allows_dry_run():
                    _log_event(
                        logging.WARNING,
                        "Auth dry-run would reject mapped identity",
                        event="authentication.dry_run_denied",
                        path=request.url.path,
                        method=request.method,
                        error_code=exc.code,
                        error_details=exc.details,
                        identity_subject=identity.subject,
                        identity_provider=identity.provider,
                    )
                    return await call_next(request)
                return _app_error_response(exc)
            if user is None:
                missing_user_error = AppError(
                    code="USER_NOT_FOUND",
                    message="JWT identity is not mapped to an active user",
                    status_code=403,
                    details={
                        "email": identity.email,
                        "subject": identity.subject,
                        "provider": identity.provider,
                        "hosted_domain": identity.hosted_domain,
                    },
                )
                if required_role is not None and auth_allows_dry_run():
                    _log_event(
                        logging.WARNING,
                        "Auth dry-run would reject unmapped identity",
                        event="authentication.dry_run_denied",
                        path=request.url.path,
                        method=request.method,
                        error_code=missing_user_error.code,
                        error_details=missing_user_error.details,
                    )
                    return await call_next(request)
                return _app_error_response(missing_user_error)
            request.state.user = user

        if required_role is not None and not getattr(request.state, "bootstrap_allowed", False):
            user = getattr(request.state, "user", None)
            if user is None:
                if auth_is_enforced():
                    return _app_error_response(
                        AppError(code="AUTH_REQUIRED", message="Bearer token is required", status_code=401)
                    )
                if auth_allows_dry_run():
                    _log_event(
                        logging.WARNING,
                        "Auth dry-run would require bearer token",
                        event="authentication.dry_run_denied",
                        path=request.url.path,
                        method=request.method,
                        required_role=required_role,
                    )
            elif required_role != "viewer" and not role_satisfies(request_user_role(request), required_role):
                details = {
                    "required_role": required_role,
                    "actual_role": request_user_role(request),
                    "path": request.url.path,
                    "rbac_mode": get_rbac_mode(),
                }
                if rbac_allows_dry_run():
                    _log_event(
                        logging.WARNING,
                        "RBAC dry-run would deny request",
                        event="authorization.dry_run_denied",
                        **details,
                    )
                elif rbac_is_enforced():
                    return _app_error_response(
                        AppError(
                            code="FORBIDDEN",
                            message=f"{required_role.capitalize()} role is required for this endpoint",
                            status_code=403,
                            details=details,
                        )
                    )
        return await call_next(request)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = (request.headers.get("X-Request-Id") or "").strip() or uuid4().hex
        request.state.request_id = request_id
        start = perf_counter()
        response: Response | None = None
        try:
            response = await call_next(request)
        except Exception as exc:
            duration_ms = round((perf_counter() - start) * 1000, 2)
            _log_event(
                logging.ERROR,
                "Unhandled request exception",
                event="request.unhandled_exception",
                request_id=request_id,
                method=request.method,
                path=request.url.path,
                query=str(request.url.query),
                duration_ms=duration_ms,
                user=getattr(getattr(request.state, "user", None), "get", lambda *_: None)("username"),
                role=request_user_role(request),
                exception_type=exc.__class__.__name__,
            )
            raise
        duration_ms = round((perf_counter() - start) * 1000, 2)
        response.headers["X-Request-Id"] = request_id
        status_code = response.status_code
        severity = logging.INFO
        if status_code >= 500:
            severity = logging.ERROR
        elif status_code >= 400:
            severity = logging.WARNING
        user = getattr(request.state, "user", None)
        _log_event(
            severity,
            "Request completed",
            event="request.completed",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            query=str(request.url.query),
            status_code=status_code,
            duration_ms=duration_ms,
            user=None if not isinstance(user, dict) else user.get("username"),
            role=request_user_role(request),
            auth_mode=get_auth_mode(),
            rbac_mode=get_rbac_mode(),
        )
        if _should_emit_domain_audit(request, response):
            _emit_domain_audit_event(request, response)
        return response


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        try:
            content_length = request.headers.get("content-length")
            if content_length:
                try:
                    if int(content_length) > MAX_UPLOAD_BYTES:
                        raise _request_too_large_error()
                except ValueError:
                    pass

            received = 0
            original_receive = request.receive

            async def receive_with_limit():
                nonlocal received
                message = await original_receive()
                if message.get("type") == "http.request":
                    received += len(message.get("body") or b"")
                    if received > MAX_UPLOAD_BYTES:
                        raise _request_too_large_error()
                return message

            request._receive = receive_with_limit  # type: ignore[attr-defined]
            return await call_next(request)
        except AppError as exc:
            handler = request.app.exception_handlers.get(AppError)
            if handler is None:
                raise
            return await handler(request, exc)


def create_app(database_url: str | None = None, db_path: str | None = None) -> FastAPI:
    _configure_logging()
    cors_allowed_origins = get_cors_allowed_origins()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        _log_event(
            logging.INFO,
            "Application startup",
            event="application.startup",
            runtime_target=get_runtime_target(),
            cloud_run_mode=is_cloud_run_runtime(),
            migration_strategy="startup" if AUTO_MIGRATE_ON_STARTUP else "external",
            structured_logging=STRUCTURED_LOGGING,
        )
        if AUTO_MIGRATE_ON_STARTUP:
            init_db(database_url=app.state.database_url)
        try:
            yield
        finally:
            _log_event(
                logging.INFO,
                "Application shutdown",
                event="application.shutdown",
                runtime_target=get_runtime_target(),
                cloud_run_mode=is_cloud_run_runtime(),
            )

    app = FastAPI(
        title="Optical Component Inventory Management API",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.database_url = database_url or db_path
    app.state.identity_resolver = None if get_auth_mode() == AUTH_MODE_NONE else build_identity_resolver()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestSizeLimitMiddleware)
    app.add_middleware(RequestIdentityMiddleware)
    app.add_middleware(RequestLoggingMiddleware)

    @app.exception_handler(AppError)
    async def app_error_handler(_, exc: AppError):
        return _app_error_response(exc)

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

    @app.get("/healthz")
    def liveness_probe():
        return ok({"alive": True, "runtime_target": get_runtime_target()})

    @app.get("/readyz")
    def readiness_probe():
        ready, error_code = _db_ready(app.state.database_url)
        database_check: dict[str, Any] = {"ready": ready}
        if error_code:
            database_check["error_code"] = error_code
        payload = {
            "ready": ready,
            "runtime_target": get_runtime_target(),
            "checks": {"database": database_check},
        }
        if ready:
            return ok(payload)
        return JSONResponse(
            status_code=503,
            content={
                "status": "error",
                "error": {
                    "code": "NOT_READY",
                    "message": "Application is not ready to serve traffic",
                    "details": payload,
                },
            },
        )

    @app.get("/api/health")
    def healthcheck():
        storage_summary = storage.get_storage_backend_summary()
        recovery_policy = get_recovery_policy_summary()
        return ok(
            {
                "healthy": True,
                "runtime_target": get_runtime_target(),
                "cloud_run_mode": is_cloud_run_runtime(),
                "app_port": APP_PORT,
                "app_data_root": str(APP_DATA_ROOT),
                "auto_migrate_on_startup": AUTO_MIGRATE_ON_STARTUP,
                "migration_strategy": "startup" if AUTO_MIGRATE_ON_STARTUP else "external",
                "cors_allowed_origins": cors_allowed_origins,
                "db_pool": {
                    "pool_size": DB_POOL_SIZE,
                    "max_overflow": DB_MAX_OVERFLOW,
                    "pool_timeout": DB_POOL_TIMEOUT,
                    "pool_recycle_seconds": DB_POOL_RECYCLE_SECONDS,
                },
                "upload_limits": {
                    "max_upload_bytes": MAX_UPLOAD_BYTES,
                    "max_upload_mebibytes": round(MAX_UPLOAD_BYTES / (1024 * 1024), 2),
                },
                "operating_targets": {
                    "heavy_request_target_seconds": HEAVY_REQUEST_TARGET_SECONDS,
                    "cloud_run_concurrency_target": CLOUD_RUN_CONCURRENCY_TARGET,
                },
                "cloud_sql": {
                    "strategy": "connector_unix_socket",
                    "instance_connection_name_configured": bool(INSTANCE_CONNECTION_NAME),
                    "database_url_uses_unix_socket": uses_cloud_sql_unix_socket(app.state.database_url),
                },
                "readiness": {
                    "probe_path": "/readyz",
                    "liveness_path": "/healthz",
                },
                "storage": storage_summary,
                "recovery_policy": recovery_policy,
                "public_urls": {
                    "backend_public_base_url": BACKEND_PUBLIC_BASE_URL or None,
                    "frontend_public_base_url": FRONTEND_PUBLIC_BASE_URL or None,
                },
                "temporary_identity_model": None,
                "auth": authorization_mode_summary(),
                "diagnostics": {
                    "auth_role": get_diagnostics_auth_role(),
                    "public_probe_paths": ["/healthz", "/readyz"],
                    "api_diagnostic_paths": ["/api/health", "/api/auth/capabilities"],
                },
            }
        )

    @app.get("/api/auth/capabilities")
    def get_auth_capabilities(request: Request):
        user = getattr(request.state, "user", None)
        identity = getattr(request.state, "identity", None)
        identity_provider = identity.get("provider") if isinstance(identity, dict) else None
        return ok(
            {
                **authorization_mode_summary(),
                "effective_role": request_user_role(request),
                "current_user": None if not isinstance(user, dict) else user,
                "current_identity": identity,
                "mutation_identity": {
                    "mode": "bearer_jwt",
                    "provider": identity_provider or OIDC_PROVIDER,
                    "temporary": False,
                    "stronger_auth_required": False,
                },
                "endpoint_policy": endpoint_policy_summary(),
            }
        )

    @app.get("/api/artifacts")
    def get_artifacts(artifact_type: str | None = None, conn= db):
        return ok(service.list_generated_artifacts(conn, artifact_type=artifact_type))

    @app.get("/api/artifacts/{artifact_id}")
    def get_artifact_detail(artifact_id: str, conn= db):
        return ok(service.get_generated_artifact(conn, artifact_id))

    @app.get("/api/artifacts/{artifact_id}/download")
    def download_artifact(artifact_id: str, conn= db):
        filename, content = service.get_generated_artifact_download(conn, artifact_id)
        return file_attachment(filename, content)

    @app.get("/api/users")
    def get_users(include_inactive: bool = False, conn= db):
        return ok(service.list_users(conn, include_inactive=include_inactive))

    @app.get("/api/users/me")
    def get_current_user(request: Request):
        user = getattr(request.state, "user", None)
        if user is None:
            raise AppError(
                code="USER_REQUIRED",
                message="An active user mapped from a bearer token is required",
                status_code=403,
                details={"requires": "Authorization: Bearer <JWT> mapped to an active user"},
            )
        return ok(user)

    @app.get("/api/users/{user_id}")
    def get_user(user_id: int, conn= db):
        return ok(service.get_user(conn, user_id))

    @app.post("/api/users")
    def post_user(body: UserCreate, conn= db):
        result = service.create_user(conn, body.model_dump())
        conn.commit()
        return ok(result)

    @app.put("/api/users/{user_id}")
    def put_user(user_id: int, body: UserUpdate, conn= db):
        result = service.update_user(conn, user_id, body.model_dump(exclude_unset=True))
        conn.commit()
        return ok(result)

    @app.delete("/api/users/{user_id}")
    def delete_user(user_id: int, conn= db):
        result = service.deactivate_user(conn, user_id)
        conn.commit()
        return ok(result)

    @app.get("/api/dashboard/summary")
    def get_dashboard_summary(conn= db):
        data = service.dashboard_summary(conn)
        return ok(data)

    @app.get("/api/catalog/search")
    def get_catalog_search(
        q: str,
        types: str | None = None,
        limit_per_type: int = 8,
        conn= db,
    ):
        entity_types = [part.strip().lower() for part in str(types or "").split(",") if part.strip()]
        return ok(
            service.catalog_search(
                conn,
                q=q,
                entity_types=entity_types or None,
                limit_per_type=limit_per_type,
            )
        )

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
        background_tasks: BackgroundTasks,
        file: UploadFile = File(...),
        continue_on_error: bool = Form(default=True),
        row_overrides: str | None = Form(default=None),
        conn= db,
    ):
        content = await file.read()
        result = service.import_items_from_content_with_job(
            conn,
            content=content,
            source_name=file.filename or "items_import.csv",
            continue_on_error=continue_on_error,
            row_overrides=_parse_optional_json_form(row_overrides, "row_overrides"),
        )
        conn.commit()
        if result.get("archive") and result["archive"].get("cleanup_unreg_file"):
            background_tasks.add_task(cleanup_unreg_file_with_retry, result["archive"]["cleanup_unreg_file"])
        return ok(_public_item_import_result(result))

    @app.post("/api/items/import-preview")
    async def post_items_import_preview(
        file: UploadFile = File(...),
        conn= db,
    ):
        content = await file.read()
        result = service.preview_items_import_from_content(
            conn,
            content=content,
            source_name=file.filename or "items_import.csv",
        )
        return ok(result)

    @app.get("/api/items/import-template")
    def get_items_import_template():
        filename, content = service.get_import_template_csv("items")
        return csv_attachment(filename, content)

    @app.get("/api/items/import-reference")
    def get_items_import_reference(conn= db):
        filename, content = service.get_items_import_reference_csv(conn)
        return csv_attachment(filename, content)

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

    @app.get("/api/items/{item_id}/planning-context")
    def get_item_planning_context(
        item_id: int,
        preview_project_id: int | None = None,
        target_date: str | None = None,
        conn= db,
    ):
        return ok(
            service.get_item_planning_context(
                conn,
                item_id,
                preview_project_id=preview_project_id,
                target_date=target_date,
            )
        )

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
        basis: str | None = None,
        conn= db,
    ):
        return ok(service.get_inventory_snapshot(conn, target_date=date, mode=mode, basis=basis))

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
        row_overrides: str | None = Form(default=None),
        conn= db,
    ):
        content = await file.read()
        result = service.import_inventory_movements_from_content(
            conn,
            content=content,
            batch_id=batch_id,
            row_overrides=_parse_optional_json_form(row_overrides, "row_overrides"),
        )
        conn.commit()
        return ok(result)

    @app.post("/api/inventory/import-preview")
    async def post_inventory_import_preview(
        file: UploadFile = File(...),
        batch_id: str | None = Form(default=None),
        conn= db,
    ):
        content = await file.read()
        result = service.preview_inventory_movements_from_content(
            conn,
            content=content,
            batch_id=batch_id,
            source_name=file.filename or "inventory_import.csv",
        )
        return ok(result)

    @app.get("/api/inventory/import-template")
    def get_inventory_import_template():
        filename, content = service.get_import_template_csv("inventory")
        return csv_attachment(filename, content)

    @app.get("/api/inventory/import-reference")
    def get_inventory_import_reference(conn= db):
        filename, content = service.get_inventory_import_reference_csv(conn)
        return csv_attachment(filename, content)

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
        item_id: int | None = None,
        project_id: int | None = None,
        include_arrived: bool = True,
        page: int = 1,
        per_page: int = 50,
        conn= db,
    ):
        data, pagination = service.list_orders(
            conn,
            status=status,
            supplier=supplier,
            item_id=item_id,
            project_id=project_id,
            include_arrived=include_arrived,
            page=page,
            per_page=per_page,
        )
        return ok(data, pagination)

    @app.get("/api/orders/import-template")
    def get_orders_import_template():
        filename, content = service.get_import_template_csv("orders")
        return csv_attachment(filename, content)

    @app.get("/api/orders/import-reference")
    def get_orders_import_reference(supplier_name: str | None = None, conn= db):
        filename, content = service.get_orders_import_reference_csv(
            conn,
            supplier_name=supplier_name,
        )
        return csv_attachment(filename, content)

    @app.post("/api/orders/import-preview")
    async def post_orders_import_preview(
        file: UploadFile = File(...),
        supplier_id: int | None = Form(default=None),
        supplier_name: str | None = Form(default=None),
        default_order_date: str | None = Form(default=None),
        conn= db,
    ):
        content = await file.read()
        result = service.preview_orders_import_from_content(
            conn,
            supplier_id=supplier_id,
            supplier_name=supplier_name,
            content=content,
            default_order_date=default_order_date,
            source_name=file.filename or "order_import.csv",
        )
        return ok(result)

    @app.post("/api/orders/import")
    async def post_orders_import(
        file: UploadFile = File(...),
        supplier_id: int | None = Form(default=None),
        supplier_name: str | None = Form(default=None),
        default_order_date: str | None = Form(default=None),
        row_overrides: str | None = Form(default=None),
        alias_saves: str | None = Form(default=None),
        conn= db,
    ):
        content = await file.read()
        try:
            result = service.import_orders_from_content_with_job(
                conn,
                supplier_id=supplier_id,
                supplier_name=supplier_name,
                content=content,
                default_order_date=default_order_date,
                source_name=file.filename or "order_import.csv",
                missing_output_dir=None,
                row_overrides=_parse_optional_json_form(row_overrides, "row_overrides"),
                alias_saves=_parse_optional_json_form(alias_saves, "alias_saves"),
            )
        except Exception:
            conn.commit()
            raise
        conn.commit()
        return ok(_public_order_import_result(result))

    @app.get("/api/orders/import-jobs")
    def get_order_import_jobs(
        page: int = 1,
        per_page: int = 50,
        conn= db,
    ):
        data, pagination = service.list_order_import_jobs(
            conn,
            page=page,
            per_page=per_page,
        )
        return ok(data, pagination)

    @app.get("/api/orders/import-jobs/{import_job_id}")
    def get_order_import_job(import_job_id: int, conn= db):
        return ok(service.get_order_import_job(conn, import_job_id))

    @app.post("/api/orders/import-jobs/{import_job_id}/undo")
    def post_undo_order_import_job(import_job_id: int, conn= db):
        result = service.undo_orders_import_job(conn, import_job_id)
        conn.commit()
        return ok(result)

    @app.post("/api/orders/import-jobs/{import_job_id}/redo")
    def post_redo_order_import_job(import_job_id: int, conn= db):
        result = service.redo_orders_import_job(conn, import_job_id)
        conn.commit()
        return ok(_public_order_import_result(result))

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

    @app.post("/api/orders/import/confirm-procurement-links")
    def post_confirm_procurement_links(body: ConfirmProcurementLinksRequest, conn= db):
        result = service.confirm_procurement_links(
            conn,
            links=[row.model_dump() for row in body.links],
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
    def put_quotation(quotation_id: int, payload: QuotationUpdateRequest, conn= db):
        result = service.update_quotation(conn, quotation_id, payload.model_dump(exclude_unset=True))
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

    @app.get("/api/reservations/import-template")
    def get_reservations_import_template():
        filename, content = service.get_import_template_csv("reservations")
        return csv_attachment(filename, content)

    @app.get("/api/reservations/import-reference")
    def get_reservations_import_reference(conn= db):
        filename, content = service.get_reservations_import_reference_csv(conn)
        return csv_attachment(filename, content)

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
        row_overrides: str | None = Form(default=None),
        conn= db,
    ):
        content = await file.read()
        result = service.import_reservations_from_content(
            conn,
            content=content,
            row_overrides=_parse_optional_json_form(row_overrides, "row_overrides"),
        )
        conn.commit()
        return ok(result)

    @app.post("/api/reservations/import-preview")
    async def post_reservations_import_preview(
        file: UploadFile = File(...),
        conn= db,
    ):
        content = await file.read()
        result = service.preview_reservations_from_content(
            conn,
            content=content,
            source_name=file.filename or "reservations_import.csv",
        )
        return ok(result)

    @app.post("/api/reservations/batch")
    def post_batch_reservations(body: ReservationBatchRequest, conn= db):
        result = service.batch_create_reservations(
            conn, [entry.model_dump() for entry in body.reservations]
        )
        conn.commit()
        return ok(result)

    @app.get("/api/projects")
    def get_projects(page: int = 1, per_page: int = 50, conn= db):
        data, pagination = service.list_projects(conn, page=page, per_page=per_page)
        return ok(data, pagination)

    @app.get("/api/workspace/summary")
    def get_workspace_summary(conn= db):
        return ok(service.get_workspace_summary(conn))

    @app.get("/api/workspace/planning-export")
    def get_workspace_planning_export(
        project_id: int,
        target_date: str | None = None,
        conn= db,
    ):
        filename, content = service.export_workspace_planning_csv(
            conn,
            project_id=project_id,
            target_date=target_date,
        )
        return csv_attachment(filename, content)

    @app.get("/api/workspace/planning-export-multi")
    def get_workspace_planning_multi_export(
        project_id: int | None = None,
        target_date: str | None = None,
        conn= db,
    ):
        filename, content = service.export_workspace_planning_multi_csv(
            conn,
            project_id=project_id,
            target_date=target_date,
        )
        return csv_attachment(filename, content)

    @app.get("/api/projects/{project_id}")
    def get_project(project_id: int, conn= db):
        return ok(service.get_project(conn, project_id))

    @app.post("/api/projects")
    def post_project(body: ProjectCreate, conn= db):
        result = service.create_project(conn, body.model_dump())
        conn.commit()
        return ok(result)

    @app.post("/api/projects/requirements/preview")
    def post_project_requirements_preview(body: ProjectRequirementPreviewRequest, conn= db):
        return ok(service.preview_project_requirement_bulk_text(conn, text=body.text))

    @app.post("/api/projects/requirements/preview/unresolved-items.csv")
    def post_project_requirements_unresolved_items_csv(body: ProjectRequirementUnresolvedItemsCsvRequest, conn= db):
        filename, content = service.export_project_requirement_unresolved_items_csv(
            conn,
            text=body.text,
            rows=[row.model_dump() for row in body.rows],
        )
        return csv_attachment(filename, content)

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

    @app.get("/api/projects/{project_id}/planning-analysis")
    def get_project_planning_analysis(project_id: int, target_date: str | None = None, conn= db):
        return ok(service.project_planning_analysis(conn, project_id, target_date=target_date))

    @app.post("/api/projects/{project_id}/confirm-allocation")
    def post_project_confirm_allocation(project_id: int, body: ConfirmAllocationRequest, conn= db):
        result = service.confirm_project_allocation(
            conn,
            project_id,
            target_date=body.target_date,
            dry_run=body.dry_run,
            expected_snapshot_signature=body.expected_snapshot_signature,
        )
        if not body.dry_run:
            conn.commit()
        return ok(result)

    @app.post("/api/projects/{project_id}/reserve")
    def post_project_reserve(project_id: int, conn= db):
        result = service.reserve_project_requirements(conn, project_id)
        conn.commit()
        return ok(result)

    @app.post("/api/projects/{project_id}/rfq-batches")
    def post_project_rfq_batch(project_id: int, body: dict[str, Any] | None = None, conn= db):
        payload = body or {}
        result = service.create_project_rfq_batch_from_analysis(
            conn,
            project_id,
            title=payload.get("title"),
            note=payload.get("note"),
            target_date=payload.get("target_date"),
        )
        conn.commit()
        return ok(result)

    @app.get("/api/planning/pipeline")
    def get_planning_pipeline(
        preview_project_id: int | None = None,
        target_date: str | None = None,
        conn= db,
    ):
        return ok(
            service.list_planning_pipeline(
                conn,
                preview_project_id=preview_project_id,
                target_date=target_date,
            )
        )

    @app.get("/api/procurement-batches")
    def get_procurement_batches(
        status: str | None = None,
        item_id: int | None = None,
        project_id: int | None = None,
        page: int = 1,
        per_page: int = 50,
        conn= db,
    ):
        data, pagination = service.list_procurement_batches(
            conn,
            status=status,
            item_id=item_id,
            project_id=project_id,
            page=page,
            per_page=per_page,
        )
        return ok(data, pagination)

    @app.post("/api/procurement-batches")
    def post_procurement_batch(body: ProcurementBatchCreateRequest, conn= db):
        result = service.create_procurement_batch(conn, body.model_dump())
        conn.commit()
        return ok(result)

    @app.get("/api/procurement-batches/{batch_id}")
    def get_procurement_batch(batch_id: int, conn= db):
        return ok(service.get_procurement_batch(conn, batch_id))

    @app.put("/api/procurement-batches/{batch_id}")
    def put_procurement_batch(batch_id: int, body: ProcurementBatchUpdate, conn= db):
        result = service.update_procurement_batch(conn, batch_id, body.model_dump(exclude_unset=True))
        conn.commit()
        return ok(result)

    @app.delete("/api/procurement-batches/{batch_id}")
    def delete_procurement_batch(batch_id: int, conn= db):
        result = service.delete_procurement_batch(conn, batch_id)
        conn.commit()
        return ok(result)

    @app.get("/api/procurement-batches/{batch_id}/export.csv")
    def get_procurement_batch_export(batch_id: int, conn= db):
        filename, content = service.export_procurement_batch_csv(conn, batch_id)
        return csv_attachment(filename, content)

    @app.post("/api/procurement-batches/{batch_id}/lines")
    def post_procurement_batch_lines(batch_id: int, body: ProcurementBatchAddLinesRequest, conn= db):
        result = service.add_procurement_lines(
            conn,
            batch_id=batch_id,
            lines=[row.model_dump() for row in body.lines],
        )
        conn.commit()
        return ok(result)

    @app.put("/api/procurement-lines/{line_id}")
    def put_procurement_line(line_id: int, body: ProcurementLineUpdate, conn= db):
        result = service.update_procurement_line(conn, line_id, body.model_dump(exclude_unset=True))
        conn.commit()
        return ok(result)

    @app.delete("/api/procurement-lines/{line_id}")
    def delete_procurement_line(line_id: int, conn= db):
        result = service.delete_procurement_line(conn, line_id)
        conn.commit()
        return ok(result)

    @app.get("/api/rfq-batches")
    def get_rfq_batches(
        status: str | None = None,
        project_id: int | None = None,
        page: int = 1,
        per_page: int = 50,
        conn= db,
    ):
        data, pagination = service.list_rfq_batches(
            conn,
            status=status,
            project_id=project_id,
            page=page,
            per_page=per_page,
        )
        return ok(data, pagination)

    @app.get("/api/rfq-batches/{rfq_id}")
    def get_rfq_batch(rfq_id: int, conn= db):
        return ok(service.get_rfq_batch(conn, rfq_id))

    @app.put("/api/rfq-batches/{rfq_id}")
    def put_rfq_batch(rfq_id: int, body: dict[str, Any], conn= db):
        result = service.update_rfq_batch(conn, rfq_id, body)
        conn.commit()
        return ok(result)

    @app.put("/api/rfq-lines/{line_id}")
    def put_rfq_line(line_id: int, body: dict[str, Any], conn= db):
        result = service.update_rfq_line(conn, line_id, body)
        conn.commit()
        return ok(result)

    @app.get("/api/purchase-candidates")
    def get_purchase_candidates(
        status: str | None = None,
        source_type: str | None = None,
        project_id: int | None = None,
        page: int = 1,
        per_page: int = 50,
        conn= db,
    ):
        data, pagination = service.list_purchase_candidates(
            conn,
            status=status,
            source_type=source_type,
            project_id=project_id,
            page=page,
            per_page=per_page,
        )
        return ok(data, pagination)

    @app.get("/api/purchase-candidates/{candidate_id}")
    def get_purchase_candidate(candidate_id: int, conn= db):
        return ok(service.get_purchase_candidate(conn, candidate_id))

    @app.post("/api/purchase-candidates/from-bom")
    def post_purchase_candidates_from_bom(body: dict[str, Any], conn= db):
        result = service.create_purchase_candidates_from_bom(
            conn,
            rows=list(body.get("rows") or []),
            target_date=body.get("target_date"),
            note=body.get("note"),
        )
        conn.commit()
        return ok(result)

    @app.post("/api/purchase-candidates/from-project/{project_id}")
    def post_purchase_candidates_from_project(project_id: int, body: dict[str, Any] | None = None, conn= db):
        payload = body or {}
        result = service.create_purchase_candidates_from_project_gap(
            conn,
            project_id,
            target_date=payload.get("target_date"),
            note=payload.get("note"),
        )
        conn.commit()
        return ok(result)

    @app.put("/api/purchase-candidates/{candidate_id}")
    def put_purchase_candidate(candidate_id: int, body: dict[str, Any], conn= db):
        result = service.update_purchase_candidate(conn, candidate_id, body)
        conn.commit()
        return ok(result)

    @app.get("/api/shortage-inbox")
    def get_shortage_inbox(conn= db):
        return ok(service.get_shortage_inbox(conn))

    @app.post("/api/shortage-inbox/to-procurement")
    def post_shortage_inbox_to_procurement(body: ShortageInboxToProcurementRequest, conn= db):
        result = service.add_shortages_to_procurement(
            conn,
            batch_id=body.batch_id,
            create_batch_title=body.create_batch_title,
            create_batch_note=body.create_batch_note,
            confirm_project_id=body.confirm_project_id,
            confirm_target_date=body.confirm_target_date,
            lines=[row.model_dump() for row in body.lines],
        )
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

    @app.post("/api/bom/preview")
    def post_bom_preview(body: BomAnalyzeRequest, conn= db):
        result = service.preview_bom_rows(
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

    @app.get("/api/assemblies")
    def get_assemblies(page: int = 1, per_page: int = 50, conn= db):
        data, pagination = service.list_assemblies(conn, page=page, per_page=per_page)
        return ok(data, pagination)

    @app.post("/api/assemblies")
    def post_assembly(body: dict[str, Any], conn= db):
        result = service.create_assembly(conn, body)
        conn.commit()
        return ok(result)

    @app.get("/api/assemblies/{assembly_id}")
    def get_assembly(assembly_id: int, conn= db):
        return ok(service.get_assembly(conn, assembly_id))

    @app.put("/api/assemblies/{assembly_id}")
    def put_assembly(assembly_id: int, body: dict[str, Any], conn= db):
        result = service.update_assembly(conn, assembly_id, body)
        conn.commit()
        return ok(result)

    @app.delete("/api/assemblies/{assembly_id}")
    def delete_assembly(assembly_id: int, conn= db):
        service.delete_assembly(conn, assembly_id)
        conn.commit()
        return ok({"deleted": True})

    @app.get("/api/assemblies/{assembly_id}/locations")
    def get_assembly_locations(assembly_id: int, conn= db):
        return ok(service.get_assembly_locations(conn, assembly_id))

    @app.put("/api/locations/{location}/assemblies")
    def put_location_assemblies(location: str, body: dict[str, Any], conn= db):
        result = service.set_location_assemblies(
            conn,
            location=location,
            assignments=list(body.get("assignments") or []),
        )
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

    @app.post("/api/aliases/upsert")
    def post_alias_by_supplier_name(body: AliasUpsertBySupplierNameRequest, conn= db):
        result = service.upsert_supplier_item_alias_by_name(
            conn,
            supplier_name=body.supplier_name,
            ordered_item_number=body.ordered_item_number,
            canonical_item_id=body.canonical_item_id,
            canonical_item_number=body.canonical_item_number,
            units_per_order=body.units_per_order,
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

    return app


app = create_app()
