from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from io import StringIO
import json
import re
import unicodedata
from pathlib import Path
import shutil
import sqlite3
from typing import Any, Iterable, NoReturn
from uuid import uuid4

from .config import (
    ITEMS_IMPORT_STAGING_ROOT,
    ITEMS_IMPORT_UNREGISTERED_ROOT,
    ITEMS_IMPORT_REGISTERED_ROOT,
    ORDERS_IMPORT_REGISTERED_CSV_ROOT,
    ORDERS_IMPORT_REGISTERED_PDF_ROOT,
)
from .errors import AppError
from .order_import_paths import (
    build_roots,
    ensure_roots,
    registered_csv_supplier_dir,
    registered_pdf_supplier_dir,
    supplier_from_unregistered_csv_path,
)
from .storage import (
    GENERATED_ARTIFACTS_BUCKET,
    ITEMS_REGISTERED_ARCHIVES_BUCKET,
    ITEMS_UNREGISTERED_BUCKET,
    ORDERS_REGISTERED_CSV_BUCKET,
    ORDERS_REGISTERED_PDF_BUCKET,
    StoredObject,
    delete_storage_ref,
    is_local_storage_backend,
    move_file_to_storage,
    read_storage_bytes,
    stat_storage_ref,
    write_storage_bytes,
)
from .utils import (
    normalize_document_reference,
    normalize_optional_date,
    now_jst_iso,
    require_non_empty,
    require_positive_int,
    to_dict,
    today_jst,
)


@dataclass
class Pagination:
    page: int
    per_page: int
    total: int
    total_pages: int


LOCAL_SOURCE_SYSTEM = "local"
EXTERNAL_SOURCE_SYSTEM = "external"
LOCAL_SPLIT_RECONCILIATION_MODE = "propagate_external_changes"


def _rows_to_dict(rows: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


def _infer_generated_artifact_type(path: Path) -> str:
    name = path.name.lower()
    if "missing_items_registration" in name:
        return "missing_items_register"
    return "generated_file"


def _infer_generated_artifact_type_from_filename(filename: str) -> str:
    return _infer_generated_artifact_type(Path(filename))


def _disabled_items_archive_rollup_result() -> dict[str, Any]:
    return {
        "consolidated": 0,
        "folders": [],
        "disabled": True,
        "reason": "storage_backed_archives_are_not_rescanned",
    }


def _csv_archive_sync_disabled_result() -> dict[str, Any]:
    return {
        "enabled": False,
        "reason": "database_is_source_of_truth_for_order_and_quotation_edits",
    }


def _require_entity_source_system(entity: dict[str, Any], *, entity_label: str, entity_id: Any) -> str:
    raw_source_system = entity.get("source_system")
    normalized_source_system = str(raw_source_system).strip() if raw_source_system is not None else ""
    if normalized_source_system:
        return normalized_source_system
    raise AppError(
        code=f"{entity_label.upper()}_SOURCE_SYSTEM_MISSING",
        message=f"{entity_label.capitalize()} {entity_id} is missing source_system metadata",
        status_code=500,
    )


def _assert_item_is_locally_managed(item: dict[str, Any]) -> None:
    if _require_entity_source_system(item, entity_label="item", entity_id=item.get("item_id")) == LOCAL_SOURCE_SYSTEM:
        return
    raise AppError(
        code="ITEM_MANAGED_EXTERNALLY",
        message="This item is managed externally and cannot be edited locally",
        status_code=409,
    )


def _assert_order_is_locally_managed(order: dict[str, Any]) -> None:
    if _require_entity_source_system(order, entity_label="order", entity_id=order.get("order_id")) == LOCAL_SOURCE_SYSTEM:
        return
    raise AppError(
        code="ORDER_MANAGED_EXTERNALLY",
        message="This order is managed externally and cannot be edited locally",
        status_code=409,
    )


def _decode_manual_override_fields(raw_value: Any, *, order_id: Any | None = None) -> list[str] | None:
    if raw_value is None:
        return None
    if isinstance(raw_value, list):
        normalized = sorted({str(field).strip() for field in raw_value if str(field).strip()})
        return normalized

    text = str(raw_value).strip()
    if not text:
        return []

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AppError(
            code="ORDER_SPLIT_METADATA_INVALID",
            message=f"Order {order_id} has invalid split manual override metadata",
            status_code=500,
        ) from exc
    if not isinstance(parsed, list):
        raise AppError(
            code="ORDER_SPLIT_METADATA_INVALID",
            message=f"Order {order_id} has invalid split manual override metadata",
            status_code=500,
        )
    return sorted({str(field).strip() for field in parsed if str(field).strip()})


def _normalize_order_read_row(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    data = dict(row)
    data["split_manual_override_fields"] = _decode_manual_override_fields(
        data.get("split_manual_override_fields"),
        order_id=data.get("order_id"),
    )
    return data


def _artifact_payload_from_row(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    data = dict(row)
    artifact_id = str(data["artifact_id"])
    payload = {
        "artifact_id": artifact_id,
        "artifact_type": str(data["artifact_type"]),
        "filename": str(data["filename"]),
        "size_bytes": int(data["size_bytes"]),
        "created_at": str(data["created_at"]),
        "detail_path": f"/api/artifacts/{artifact_id}",
        "download_path": f"/api/artifacts/{artifact_id}/download",
    }
    if data.get("source_job_type"):
        payload["source_job_type"] = str(data["source_job_type"])
    if data.get("source_job_id"):
        payload["source_job_id"] = str(data["source_job_id"])
    return payload


def _stored_object_from_path(path: Path) -> StoredObject:
    resolved = path.resolve()
    if not resolved.exists() or not resolved.is_file():
        raise AppError(
            code="ARTIFACT_NOT_FOUND",
            message=f"Generated artifact '{path}' not found",
            status_code=404,
        )

    stats = resolved.stat()
    return StoredObject(
        storage_ref=str(resolved),
        filename=resolved.name,
        size_bytes=int(stats.st_size),
        created_at=datetime.fromtimestamp(stats.st_mtime).isoformat(timespec="seconds"),
        path=resolved,
    )


def _safe_stat_storage_ref(storage_ref: str) -> StoredObject | None:
    try:
        return stat_storage_ref(storage_ref)
    except AppError:
        return None


def _register_generated_artifact(
    conn: sqlite3.Connection,
    stored: StoredObject,
    *,
    source_job_type: str | None = None,
    source_job_id: str | None = None,
) -> dict[str, Any]:
    artifact_type = _infer_generated_artifact_type_from_filename(stored.filename)
    existing = conn.execute(
        """
        SELECT
            artifact_id,
            artifact_type,
            filename,
            storage_path,
            size_bytes,
            created_at,
            source_job_type,
            source_job_id
        FROM generated_artifacts
        WHERE storage_path = ?
        ORDER BY created_at DESC, artifact_id DESC
        LIMIT 1
        """,
        (stored.storage_ref,),
    ).fetchone()
    if existing is not None:
        return _artifact_payload_from_row(existing)

    artifact_id = uuid4().hex
    conn.execute(
        """
        INSERT INTO generated_artifacts (
            artifact_id,
            artifact_type,
            filename,
            storage_path,
            size_bytes,
            created_at,
            source_job_type,
            source_job_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            artifact_id,
            artifact_type,
            stored.filename,
            stored.storage_ref,
            stored.size_bytes,
            stored.created_at,
            source_job_type,
            source_job_id,
        ),
    )
    return _artifact_payload_from_row(
        {
            "artifact_id": artifact_id,
            "artifact_type": artifact_type,
            "filename": stored.filename,
            "size_bytes": stored.size_bytes,
            "created_at": stored.created_at,
            "source_job_type": source_job_type,
            "source_job_id": source_job_id,
        }
    )


def _build_generated_artifact(
    conn: sqlite3.Connection,
    path: Path,
    *,
    source_job_type: str | None = None,
    source_job_id: str | None = None,
) -> dict[str, Any]:
    return _register_generated_artifact(
        conn,
        _stored_object_from_path(path),
        source_job_type=source_job_type,
        source_job_id=source_job_id,
    )


def _build_generated_artifact_from_stored_object(
    conn: sqlite3.Connection,
    stored: StoredObject,
    *,
    source_job_type: str | None = None,
    source_job_id: str | None = None,
) -> dict[str, Any]:
    return _register_generated_artifact(
        conn,
        stored,
        source_job_type=source_job_type,
        source_job_id=source_job_id,
    )


def _get_generated_artifact_row(conn: sqlite3.Connection, artifact_id: str) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT
            artifact_id,
            artifact_type,
            filename,
            storage_path,
            size_bytes,
            created_at,
            source_job_type,
            source_job_id
        FROM generated_artifacts
        WHERE artifact_id = ?
        """,
        (artifact_id,),
    ).fetchone()


def get_generated_artifact(conn: sqlite3.Connection, artifact_id: str) -> dict[str, Any]:
    row = _get_generated_artifact_row(conn, artifact_id)
    if row is None:
        raise AppError(
            code="ARTIFACT_NOT_FOUND",
            message=f"Generated artifact '{artifact_id}' not found",
            status_code=404,
        )
    storage_ref = str(row["storage_path"])
    if _safe_stat_storage_ref(storage_ref) is not None:
        return _artifact_payload_from_row(row)
    raise AppError(
        code="ARTIFACT_NOT_FOUND",
        message=f"Generated artifact '{artifact_id}' not found",
        status_code=404,
    )


def list_generated_artifacts(conn: sqlite3.Connection, *, artifact_type: str | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    sql = """
        SELECT
            artifact_id,
            artifact_type,
            filename,
            storage_path,
            size_bytes,
            created_at,
            source_job_type,
            source_job_id
        FROM generated_artifacts
    """
    params: tuple[Any, ...] = tuple()
    if artifact_type:
        sql += " WHERE artifact_type = ?"
        params = (artifact_type,)
    sql += " ORDER BY created_at DESC, artifact_id DESC"
    for row in conn.execute(sql, params).fetchall():
        storage_ref = str(row["storage_path"])
        stored = _safe_stat_storage_ref(storage_ref)
        if stored is None:
            continue
        rows.append(_artifact_payload_from_row(row))
    return rows


def get_generated_artifact_download(conn: sqlite3.Connection, artifact_id: str) -> tuple[str, bytes]:
    row = _get_generated_artifact_row(conn, artifact_id)
    if row is None:
        raise AppError(
            code="ARTIFACT_NOT_FOUND",
            message=f"Generated artifact '{artifact_id}' not found",
            status_code=404,
        )
    storage_ref = str(row["storage_path"])
    stored = _safe_stat_storage_ref(storage_ref)
    if stored is not None:
        return read_storage_bytes(storage_ref)
    raise AppError(
        code="ARTIFACT_NOT_FOUND",
        message=f"Generated artifact '{artifact_id}' not found",
        status_code=404,
    )


def _safe_staging_component(value: str, default: str) -> str:
    text = unicodedata.normalize("NFKC", (value or "").strip())
    safe = re.sub(r"[^\w.-]+", "_", text, flags=re.UNICODE).strip(".")
    return safe or default


def _safe_staging_filename(value: str, default: str) -> str:
    source_name = Path(value or default).name
    default_name = Path(default).name
    source_path = Path(source_name)
    default_path = Path(default_name)

    suffix = source_path.suffix or default_path.suffix
    stem_default = default_path.stem or "upload"
    stem = _safe_staging_component(source_path.stem, stem_default)
    if not suffix:
        return stem
    return f"{stem}{suffix}"


def _create_upload_job_id(prefix: str) -> str:
    return f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:8]}"


def _move_file_preserve_name_bytes(content: bytes, dst_dir: Path, filename: str) -> Path:
    dst_dir.mkdir(parents=True, exist_ok=True)
    target = dst_dir / filename
    if not target.exists():
        target.write_bytes(content)
        return target

    stem = target.stem
    suffix = target.suffix
    index = 1
    while True:
        candidate = dst_dir / f"{stem}_{index}{suffix}"
        if not candidate.exists():
            candidate.write_bytes(content)
            return candidate
        index += 1


def list_users(
    conn: sqlite3.Connection,
    *,
    include_inactive: bool = False,
) -> list[dict[str, Any]]:
    where_clause = "" if include_inactive else "WHERE is_active = TRUE"
    rows = conn.execute(
        f"""
        SELECT
            user_id,
            username,
            display_name,
            email,
            external_subject,
            identity_provider,
            hosted_domain,
            role,
            is_active,
            created_at,
            updated_at
        FROM users
        {where_clause}
        ORDER BY is_active DESC, lower(display_name), lower(username), user_id
        """
    ).fetchall()
    return _rows_to_dict(rows)


def get_user(conn: sqlite3.Connection, user_id: int) -> dict[str, Any]:
    row = _get_entity_or_404(
        conn,
        "users",
        "user_id",
        user_id,
        "USER_NOT_FOUND",
        f"User with id {user_id} not found",
    )
    return dict(row)


def get_active_user_by_identity(
    conn: sqlite3.Connection,
    *,
    email: str | None = None,
    external_subject: str | None = None,
    identity_provider: str | None = None,
    hosted_domain: str | None = None,
) -> dict[str, Any] | None:
    normalized_email = _normalize_optional_email(email)
    normalized_subject = _normalize_optional_identity_text(external_subject)
    normalized_provider = _normalize_optional_identity_text(identity_provider, lower=True)
    normalized_hosted_domain = _normalize_optional_identity_text(hosted_domain, lower=True)
    if normalized_subject and normalized_provider:
        row = conn.execute(
            """
            SELECT
                user_id,
                username,
                display_name,
                email,
                external_subject,
                identity_provider,
                hosted_domain,
                role,
                is_active,
                created_at,
                updated_at
            FROM users
            WHERE identity_provider = ? AND external_subject = ? AND is_active = TRUE
            ORDER BY user_id
            """,
            (normalized_provider, normalized_subject),
        ).fetchone()
        if row is not None:
            user = dict(row)
            _ensure_hosted_domain_matches(user, normalized_hosted_domain)
            return user
    if normalized_email:
        row = conn.execute(
            """
            SELECT
                user_id,
                username,
                display_name,
                email,
                external_subject,
                identity_provider,
                hosted_domain,
                role,
                is_active,
                created_at,
                updated_at
            FROM users
            WHERE lower(email) = lower(?) AND is_active = TRUE
            ORDER BY user_id
            """,
            (normalized_email,),
        ).fetchone()
        if row is not None:
            user = dict(row)
            _ensure_hosted_domain_matches(user, normalized_hosted_domain)
            return user
    return None


def has_active_users(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        """
        SELECT EXISTS(
            SELECT 1
            FROM users
            WHERE is_active = TRUE
        ) AS has_active_users
        """
    ).fetchone()
    return bool(row[0]) if row is not None else False


def list_registration_requests(
    conn: sqlite3.Connection,
    *,
    include_resolved: bool = False,
) -> list[dict[str, Any]]:
    where_clause = "" if include_resolved else "WHERE rr.status = 'pending'"
    rows = conn.execute(
        f"""
        SELECT
            rr.request_id,
            rr.email,
            rr.username,
            rr.display_name,
            rr.memo,
            rr.requested_role,
            rr.identity_provider,
            rr.external_subject,
            rr.status,
            rr.rejection_reason,
            rr.reviewed_by_user_id,
            reviewer.username AS reviewed_by_username,
            rr.approved_user_id,
            rr.reviewed_at,
            rr.created_at,
            rr.updated_at
        FROM registration_requests rr
        LEFT JOIN users reviewer ON reviewer.user_id = rr.reviewed_by_user_id
        {where_clause}
        ORDER BY
            CASE rr.status WHEN 'pending' THEN 0 WHEN 'rejected' THEN 1 ELSE 2 END,
            rr.created_at DESC,
            rr.request_id DESC
        """
    ).fetchall()
    return _rows_to_dict(rows)


def get_registration_request(conn: sqlite3.Connection, request_id: int) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT
            rr.request_id,
            rr.email,
            rr.username,
            rr.display_name,
            rr.memo,
            rr.requested_role,
            rr.identity_provider,
            rr.external_subject,
            rr.status,
            rr.rejection_reason,
            rr.reviewed_by_user_id,
            reviewer.username AS reviewed_by_username,
            rr.approved_user_id,
            rr.reviewed_at,
            rr.created_at,
            rr.updated_at
        FROM registration_requests rr
        LEFT JOIN users reviewer ON reviewer.user_id = rr.reviewed_by_user_id
        WHERE rr.request_id = ?
        """,
        (request_id,),
    ).fetchone()
    if row is None:
        raise AppError(
            code="REGISTRATION_REQUEST_NOT_FOUND",
            message=f"Registration request with id {request_id} not found",
            status_code=404,
        )
    return dict(row)


def _get_latest_registration_request_for_identity(
    conn: sqlite3.Connection,
    *,
    email: str | None,
    external_subject: str | None,
    identity_provider: str | None,
) -> dict[str, Any] | None:
    normalized_email = _normalize_optional_email(email)
    normalized_subject = _normalize_optional_identity_text(external_subject)
    normalized_provider = _normalize_optional_identity_text(identity_provider, lower=True)
    if normalized_email is None and not (normalized_subject and normalized_provider):
        return None
    where_clauses: list[str] = []
    params: list[Any] = []
    if normalized_email is not None:
        where_clauses.append("lower(email) = lower(?)")
        params.append(normalized_email)
    if normalized_subject and normalized_provider:
        where_clauses.append("(identity_provider = ? AND external_subject = ?)")
        params.extend([normalized_provider, normalized_subject])
    row = conn.execute(
        f"""
        SELECT
            request_id,
            email,
            username,
            display_name,
            memo,
            requested_role,
            identity_provider,
            external_subject,
            status,
            rejection_reason,
            reviewed_by_user_id,
            approved_user_id,
            reviewed_at,
            created_at,
            updated_at
        FROM registration_requests
        WHERE {" OR ".join(where_clauses)}
        ORDER BY created_at DESC, request_id DESC
        LIMIT 1
        """,
        tuple(params),
    ).fetchone()
    return None if row is None else dict(row)


def get_registration_status(
    conn: sqlite3.Connection,
    *,
    email: str | None,
    external_subject: str | None,
    identity_provider: str | None,
    current_user: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_email = _normalize_optional_email(email)
    normalized_subject = _normalize_optional_identity_text(external_subject)
    normalized_provider = _normalize_optional_identity_text(identity_provider, lower=True)
    if current_user is not None:
        return {
            "state": "approved",
            "email": normalized_email,
            "identity_provider": normalized_provider,
            "external_subject": normalized_subject,
            "request": None,
            "current_user": current_user,
        }
    latest_request = _get_latest_registration_request_for_identity(
        conn,
        email=normalized_email,
        external_subject=normalized_subject,
        identity_provider=normalized_provider,
    )
    state = "not_requested" if latest_request is None else str(latest_request["status"])
    return {
        "state": state,
        "email": normalized_email,
        "identity_provider": normalized_provider,
        "external_subject": normalized_subject,
        "request": latest_request,
        "current_user": None,
    }


def create_registration_request(
    conn: sqlite3.Connection,
    *,
    data: dict[str, Any],
    email: str | None,
    external_subject: str | None,
    identity_provider: str | None,
) -> dict[str, Any]:
    normalized_email = _normalize_optional_email(email)
    normalized_subject = _normalize_optional_identity_text(external_subject)
    normalized_provider = _normalize_optional_identity_text(identity_provider, lower=True)
    if not normalized_email:
        raise AppError(
            code="REGISTRATION_EMAIL_REQUIRED",
            message="A verified identity email is required to submit a registration request",
            status_code=422,
        )
    username = require_non_empty(str(data.get("username") or ""), "username")
    display_name = require_non_empty(str(data.get("display_name") or ""), "display_name")
    memo = _normalize_optional_identity_text(data.get("memo"))
    requested_role = _require_valid_role(str(data.get("requested_role") or "viewer"))

    if get_active_user_by_identity(
        conn,
        email=normalized_email,
        external_subject=normalized_subject,
        identity_provider=normalized_provider,
    ):
        raise AppError(
            code="REGISTRATION_ALREADY_APPROVED",
            message="This identity is already mapped to an active user",
            status_code=409,
        )

    pending_email = conn.execute(
        """
        SELECT request_id
        FROM registration_requests
        WHERE lower(email) = lower(?) AND status = 'pending'
        ORDER BY request_id DESC
        LIMIT 1
        """,
        (normalized_email,),
    ).fetchone()
    if pending_email is not None:
        raise AppError(
            code="REGISTRATION_REQUEST_PENDING",
            message="A registration request for this email is already pending",
            status_code=409,
            details={"request_id": int(pending_email["request_id"])},
        )

    existing_username = conn.execute(
        """
        SELECT user_id
        FROM users
        WHERE lower(username) = lower(?)
        LIMIT 1
        """,
        (username,),
    ).fetchone()
    if existing_username is not None:
        raise AppError(
            code="USERNAME_ALREADY_EXISTS",
            message="Username is already in use",
            status_code=409,
        )

    pending_username = conn.execute(
        """
        SELECT request_id
        FROM registration_requests
        WHERE lower(username) = lower(?) AND status = 'pending'
        LIMIT 1
        """,
        (username,),
    ).fetchone()
    if pending_username is not None:
        raise AppError(
            code="USERNAME_ALREADY_PENDING",
            message="Username is already reserved by another pending request",
            status_code=409,
        )

    created_at = now_jst_iso()
    cursor = conn.execute(
        """
        INSERT INTO registration_requests (
            email,
            username,
            display_name,
            memo,
            requested_role,
            identity_provider,
            external_subject,
            status,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
        """,
        (
            normalized_email,
            username,
            display_name,
            memo,
            requested_role,
            normalized_provider,
            normalized_subject,
            created_at,
            created_at,
        ),
    )
    return get_registration_request(conn, int(cursor.lastrowid))


def approve_registration_request(
    conn: sqlite3.Connection,
    request_id: int,
    *,
    reviewer_user_id: int,
    data: dict[str, Any],
    ) -> dict[str, Any]:
    request_row = get_registration_request(conn, request_id)
    if request_row["status"] != "pending":
        raise AppError(
            code="REGISTRATION_REQUEST_NOT_PENDING",
            message="Only pending registration requests can be approved",
            status_code=409,
        )
    username = require_non_empty(str(data.get("username") or request_row["username"]), "username")
    display_name = require_non_empty(
        str(data.get("display_name") or request_row["display_name"]),
        "display_name",
    )
    requested_role = request_row.get("requested_role")
    role = _require_valid_role(str(data.get("role") or requested_role or "viewer"))
    existing_username = conn.execute(
        """
        SELECT user_id
        FROM users
        WHERE lower(username) = lower(?)
        LIMIT 1
        """,
        (username,),
    ).fetchone()
    if existing_username is not None:
        raise AppError(
            code="USERNAME_ALREADY_EXISTS",
            message="Username is already in use",
            status_code=409,
        )
    existing_email = conn.execute(
        """
        SELECT user_id
        FROM users
        WHERE lower(email) = lower(?)
        LIMIT 1
        """,
        (str(request_row["email"]),),
    ).fetchone()
    if existing_email is not None:
        raise AppError(
            code="EMAIL_ALREADY_EXISTS",
            message="Email is already mapped to another user",
            status_code=409,
        )
    if request_row["identity_provider"] and request_row["external_subject"]:
        existing_identity = conn.execute(
            """
            SELECT user_id
            FROM users
            WHERE identity_provider = ? AND external_subject = ?
            LIMIT 1
            """,
            (request_row["identity_provider"], request_row["external_subject"]),
        ).fetchone()
        if existing_identity is not None:
            raise AppError(
                code="IDENTITY_ALREADY_EXISTS",
                message="Identity subject is already mapped to another user",
                status_code=409,
            )
    created_user = create_user(
        conn,
        {
            "username": username,
            "display_name": display_name,
            "email": request_row["email"],
            "external_subject": request_row["external_subject"],
            "identity_provider": request_row["identity_provider"],
            "role": role,
            "is_active": True,
        },
    )
    reviewed_at = now_jst_iso()
    conn.execute(
        """
        UPDATE registration_requests
        SET
            username = ?,
            display_name = ?,
            status = 'approved',
            rejection_reason = NULL,
            reviewed_by_user_id = ?,
            approved_user_id = ?,
            reviewed_at = ?,
            updated_at = ?
        WHERE request_id = ?
        """,
        (
            username,
            display_name,
            reviewer_user_id,
            created_user["user_id"],
            reviewed_at,
            reviewed_at,
            request_id,
        ),
    )
    return get_registration_request(conn, request_id)


def reject_registration_request(
    conn: sqlite3.Connection,
    request_id: int,
    *,
    reviewer_user_id: int,
    rejection_reason: str,
) -> dict[str, Any]:
    request_row = get_registration_request(conn, request_id)
    if request_row["status"] != "pending":
        raise AppError(
            code="REGISTRATION_REQUEST_NOT_PENDING",
            message="Only pending registration requests can be rejected",
            status_code=409,
        )
    reason = require_non_empty(str(rejection_reason or ""), "rejection_reason")
    reviewed_at = now_jst_iso()
    conn.execute(
        """
        UPDATE registration_requests
        SET
            status = 'rejected',
            rejection_reason = ?,
            reviewed_by_user_id = ?,
            approved_user_id = NULL,
            reviewed_at = ?,
            updated_at = ?
        WHERE request_id = ?
        """,
        (
            reason,
            reviewer_user_id,
            reviewed_at,
            reviewed_at,
            request_id,
        ),
    )
    return get_registration_request(conn, request_id)


def _require_valid_role(role: str) -> str:
    """
    Ensure that the given role is non-empty and one of the supported roles.
    """
    role = require_non_empty(role, "role")
    if role not in {"admin", "operator", "viewer"}:
        # Keep roles consistent with what the authorization layer expects.
        raise AppError("INVALID_ROLE", f"Invalid role: {role}")
    return role


def create_user(conn: sqlite3.Connection, data: dict[str, Any]) -> dict[str, Any]:
    username = require_non_empty(str(data.get("username") or ""), "username")
    display_name = require_non_empty(str(data.get("display_name") or ""), "display_name")
    email, external_subject, identity_provider, hosted_domain = _normalize_user_identity_fields(data)
    raw_role = str(data.get("role") or "operator")
    role = _require_valid_role(raw_role)
    is_active = bool(data.get("is_active", True))
    created_at = now_jst_iso()
    try:
        cursor = conn.execute(
            """
            INSERT INTO users (
                username,
                display_name,
                email,
                external_subject,
                identity_provider,
                hosted_domain,
                role,
                is_active,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                username,
                display_name,
                email,
                external_subject,
                identity_provider,
                hosted_domain,
                role,
                is_active,
                created_at,
                created_at,
            ),
        )
    except sqlite3.IntegrityError as exc:
        _raise_user_identity_conflict(
            exc,
            username=username,
            email=email,
            identity_provider=identity_provider,
            external_subject=external_subject,
        )
    return get_user(conn, int(cursor.lastrowid))


def update_user(conn: sqlite3.Connection, user_id: int, data: dict[str, Any]) -> dict[str, Any]:
    existing = get_user(conn, user_id)
    username = require_non_empty(str(data.get("username", existing["username"])), "username")
    display_name = require_non_empty(str(data.get("display_name", existing["display_name"])), "display_name")
    email, external_subject, identity_provider, hosted_domain = _normalize_user_identity_fields(data, existing=existing)
    role = _require_valid_role(str(data.get("role", existing["role"])))
    is_active = bool(data.get("is_active", existing["is_active"]))
    try:
        conn.execute(
            """
            UPDATE users
            SET
                username = ?,
                display_name = ?,
                email = ?,
                external_subject = ?,
                identity_provider = ?,
                hosted_domain = ?,
                role = ?,
                is_active = ?,
                updated_at = ?
            WHERE user_id = ?
            """,
            (
                username,
                display_name,
                email,
                external_subject,
                identity_provider,
                hosted_domain,
                role,
                is_active,
                now_jst_iso(),
                user_id,
            ),
        )
    except sqlite3.IntegrityError as exc:
        _raise_user_identity_conflict(
            exc,
            username=username,
            email=email,
            identity_provider=identity_provider,
            external_subject=external_subject,
        )
    return get_user(conn, user_id)


def deactivate_user(conn: sqlite3.Connection, user_id: int) -> dict[str, Any]:
    _ = get_user(conn, user_id)
    conn.execute(
        "UPDATE users SET is_active = FALSE, updated_at = ? WHERE user_id = ?",
        (now_jst_iso(), user_id),
    )
    return get_user(conn, user_id)


def _normalize_optional_identity_text(value: Any, *, lower: bool = False) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    if not normalized:
        return None
    return normalized.lower() if lower else normalized


def _normalize_optional_email(value: Any) -> str | None:
    return _normalize_optional_identity_text(value, lower=True)


def _normalize_user_identity_fields(
    data: dict[str, Any],
    *,
    existing: dict[str, Any] | None = None,
) -> tuple[str | None, str | None, str | None, str | None]:
    email = _normalize_optional_email(data.get("email", None if existing is None else existing.get("email")))
    external_subject = _normalize_optional_identity_text(
        data.get("external_subject", None if existing is None else existing.get("external_subject"))
    )
    identity_provider = _normalize_optional_identity_text(
        data.get("identity_provider", None if existing is None else existing.get("identity_provider")),
        lower=True,
    )
    hosted_domain = _normalize_optional_identity_text(
        data.get("hosted_domain", None if existing is None else existing.get("hosted_domain")),
        lower=True,
    )
    if (external_subject is None) != (identity_provider is None):
        raise AppError(
            code="INVALID_USER_IDENTITY",
            message="identity_provider and external_subject must be set together",
            status_code=422,
        )
    return email, external_subject, identity_provider, hosted_domain


def _ensure_hosted_domain_matches(user: dict[str, Any], hosted_domain: str | None) -> None:
    required_hosted_domain = _normalize_optional_identity_text(user.get("hosted_domain"), lower=True)
    if required_hosted_domain and required_hosted_domain != hosted_domain:
        raise AppError(
            code="HOSTED_DOMAIN_MISMATCH",
            message="OIDC hosted domain does not match the user mapping",
            status_code=403,
            details={
                "required_hosted_domain": required_hosted_domain,
                "hosted_domain": hosted_domain,
                "username": user.get("username"),
            },
        )


def _raise_user_identity_conflict(
    exc: sqlite3.IntegrityError,
    *,
    username: str,
    email: str | None,
    identity_provider: str | None,
    external_subject: str | None,
) -> NoReturn:
    message = str(exc).lower()
    if "idx_users_username" in message or "users_username_key" in message or "(username)" in message:
        raise AppError(
            code="USERNAME_ALREADY_EXISTS",
            message="Username is already in use",
            status_code=409,
            details={"username": username},
        ) from exc
    if "idx_users_email_ci" in message or "lower(email" in message:
        raise AppError(
            code="EMAIL_ALREADY_EXISTS",
            message="Email is already mapped to another user",
            status_code=409,
            details={"email": email},
        ) from exc
    if "idx_users_external_identity" in message or "(identity_provider, external_subject)" in message:
        raise AppError(
            code="IDENTITY_ALREADY_EXISTS",
            message="Identity subject is already mapped to another user",
            status_code=409,
            details={
                "identity_provider": identity_provider,
                "external_subject": external_subject,
            },
        ) from exc
    raise AppError(
        code="USER_IDENTITY_CONFLICT",
        message="User identity fields conflict with an existing user",
        status_code=409,
    ) from exc


def _require_json_object(
    value: Any,
    *,
    code: str,
    label: str,
) -> dict[str | int, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise AppError(
            code=code,
            message=f"{label} must be a JSON object keyed by CSV row number",
            status_code=422,
        )
    return value


def _require_json_array(
    value: Any,
    *,
    code: str,
    label: str,
) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise AppError(
            code=code,
            message=f"{label} must be a JSON array",
            status_code=422,
        )
    return value


def _csv_row_has_content(row: dict[str, Any]) -> bool:
    return any(str(value or "").strip() for value in row.values())


def _valid_csv_row_numbers(
    rows: list[dict[str, Any]],
    *,
    skip_blank_rows: bool = False,
) -> set[int]:
    valid_row_numbers: set[int] = set()
    for row_number, row in enumerate(rows, start=2):
        if skip_blank_rows and not _csv_row_has_content(row):
            continue
        valid_row_numbers.add(row_number)
    return valid_row_numbers


def _validate_import_override_rows(
    overrides: dict[int, Any],
    *,
    valid_row_numbers: set[int],
    code: str,
    label: str,
) -> None:
    invalid_rows = sorted(set(overrides) - valid_row_numbers)
    if invalid_rows:
        invalid_rows_text = ", ".join(str(row_number) for row_number in invalid_rows)
        raise AppError(
            code=code,
            message=f"{label} references row(s) not present in the uploaded CSV: {invalid_rows_text}",
            status_code=422,
        )


def _paginate(
    conn: sqlite3.Connection,
    sql: str,
    params: tuple[Any, ...],
    page: int,
    per_page: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    page = max(1, int(page))
    per_page = max(1, int(per_page))
    total = int(conn.execute(f"SELECT COUNT(*) AS c FROM ({sql}) AS _q", params).fetchone()["c"])
    offset = (page - 1) * per_page
    rows = conn.execute(f"{sql} LIMIT ? OFFSET ?", (*params, per_page, offset)).fetchall()
    total_pages = (total + per_page - 1) // per_page if total else 0
    return _rows_to_dict(rows), asdict(Pagination(page, per_page, total, total_pages))


def _get_entity_or_404(
    conn: sqlite3.Connection,
    table: str,
    key_name: str,
    key_value: Any,
    code: str,
    message: str,
) -> sqlite3.Row:
    row = conn.execute(
        f"SELECT * FROM {table} WHERE {key_name} = ?",
        (key_value,),
    ).fetchone()
    if row is None:
        raise AppError(code=code, message=message, status_code=404)
    return row


def _item_reference_queries() -> dict[str, str]:
    return {
        "orders": "SELECT 1 FROM orders WHERE item_id = ? LIMIT 1",
        "inventory": "SELECT 1 FROM inventory_ledger WHERE item_id = ? LIMIT 1",
        "reservations": "SELECT 1 FROM reservations WHERE item_id = ? LIMIT 1",
        "project_requirements": "SELECT 1 FROM project_requirements WHERE item_id = ? LIMIT 1",
        "assembly_components": "SELECT 1 FROM assembly_components WHERE item_id = ? LIMIT 1",
        "rfq_lines": "SELECT 1 FROM rfq_lines WHERE item_id = ? LIMIT 1",
        "purchase_candidates": "SELECT 1 FROM purchase_candidates WHERE item_id = ? LIMIT 1",
        "procurement_lines": "SELECT 1 FROM procurement_lines WHERE item_id = ? LIMIT 1",
        "aliases": "SELECT 1 FROM supplier_item_aliases WHERE canonical_item_id = ? LIMIT 1",
    }


def _first_item_reference(conn: sqlite3.Connection, item_id: int) -> str | None:
    for label, sql in _item_reference_queries().items():
        if conn.execute(sql, (item_id,)).fetchone():
            return label
    return None


def _resolve_item_by_number(conn: sqlite3.Connection, item_number: str) -> int | None:
    rows = conn.execute(
        "SELECT item_id FROM items_master WHERE item_number = ? ORDER BY item_id",
        (item_number,),
    ).fetchall()
    if not rows:
        return None
    if len(rows) > 1:
        raise AppError(
            code="AMBIGUOUS_ITEM_NUMBER",
            message=f"Multiple items found for item_number '{item_number}'. Use canonical_item_id.",
            status_code=409,
        )
    return int(rows[0]["item_id"])


def _get_or_create_manufacturer(conn: sqlite3.Connection, name: str) -> int:
    normalized = require_non_empty(name, "manufacturer_name")
    row = conn.execute(
        "SELECT manufacturer_id FROM manufacturers WHERE name = ?",
        (normalized,),
    ).fetchone()
    if row:
        return int(row["manufacturer_id"])
    try:
        cur = conn.execute("INSERT INTO manufacturers (name) VALUES (?)", (normalized,))
    except sqlite3.IntegrityError:
        existing = conn.execute(
            "SELECT manufacturer_id FROM manufacturers WHERE name = ?",
            (normalized,),
        ).fetchone()
        if existing is not None:
            return int(existing["manufacturer_id"])
        raise
    return int(cur.lastrowid)


def _get_or_create_supplier(conn: sqlite3.Connection, name: str) -> int:
    normalized = require_non_empty(name, "supplier")
    row = conn.execute("SELECT supplier_id FROM suppliers WHERE name = ?", (normalized,)).fetchone()
    if row:
        return int(row["supplier_id"])
    casefold_rows = conn.execute(
        "SELECT supplier_id FROM suppliers WHERE lower(name) = lower(?) ORDER BY supplier_id",
        (normalized,),
    ).fetchall()
    if len(casefold_rows) == 1:
        return int(casefold_rows[0]["supplier_id"])
    if len(casefold_rows) > 1:
        raise AppError(
            code="AMBIGUOUS_SUPPLIER_NAME",
            message=(
                f"Multiple suppliers match '{normalized}' case-insensitively. "
                "Use supplier_id to disambiguate."
            ),
            status_code=409,
        )
    try:
        cur = conn.execute("INSERT INTO suppliers (name) VALUES (?)", (normalized,))
    except sqlite3.IntegrityError:
        existing = conn.execute(
            "SELECT supplier_id FROM suppliers WHERE name = ?",
            (normalized,),
        ).fetchone()
        if existing is not None:
            return int(existing["supplier_id"])
        existing_casefold_rows = conn.execute(
            "SELECT supplier_id FROM suppliers WHERE lower(name) = lower(?) ORDER BY supplier_id",
            (normalized,),
        ).fetchall()
        if len(existing_casefold_rows) == 1:
            return int(existing_casefold_rows[0]["supplier_id"])
        if len(existing_casefold_rows) > 1:
            raise AppError(
                code="AMBIGUOUS_SUPPLIER_NAME",
                message=(
                    f"Multiple suppliers match '{normalized}' case-insensitively. "
                    "Use supplier_id to disambiguate."
                ),
                status_code=409,
            ) from None
        raise
    return int(cur.lastrowid)


def _raise_manufacturer_already_exists(name: str, *, exc: Exception | None = None) -> None:
    raise AppError(
        code="MANUFACTURER_ALREADY_EXISTS",
        message=f"Manufacturer '{name}' already exists",
        status_code=409,
    ) from exc


def _raise_supplier_already_exists(name: str, *, exc: Exception | None = None) -> None:
    raise AppError(
        code="SUPPLIER_ALREADY_EXISTS",
        message=f"Supplier '{name}' already exists",
        status_code=409,
    ) from exc


def _item_reference_label_for_delete(conn: sqlite3.Connection, item_id: int) -> str:
    return _first_item_reference(conn, item_id) or "another record"


def _resolve_supplier_id(
    conn: sqlite3.Connection,
    supplier_id: int | None = None,
    supplier_name: str | None = None,
) -> int:
    if supplier_id is not None:
        _get_entity_or_404(
            conn,
            "suppliers",
            "supplier_id",
            supplier_id,
            "SUPPLIER_NOT_FOUND",
            f"Supplier with id {supplier_id} not found",
        )
        return int(supplier_id)
    if supplier_name is None:
        raise AppError(
            code="INVALID_SUPPLIER",
            message="supplier_id or supplier_name is required",
            status_code=422,
        )
    return _get_or_create_supplier(conn, supplier_name)


def _find_supplier_id_by_name(conn: sqlite3.Connection, supplier_name: str) -> int | None:
    normalized = require_non_empty(supplier_name, "supplier")
    row = conn.execute(
        "SELECT supplier_id FROM suppliers WHERE name = ?",
        (normalized,),
    ).fetchone()
    if row is not None:
        return int(row["supplier_id"])
    casefold_rows = conn.execute(
        "SELECT supplier_id FROM suppliers WHERE lower(name) = lower(?) ORDER BY supplier_id",
        (normalized,),
    ).fetchall()
    if len(casefold_rows) == 1:
        return int(casefold_rows[0]["supplier_id"])
    if len(casefold_rows) > 1:
        raise AppError(
            code="AMBIGUOUS_SUPPLIER_NAME",
            message=(
                f"Multiple suppliers match '{normalized}' case-insensitively. "
                "Use supplier_id to disambiguate."
            ),
            status_code=409,
        )
    return None


def _resolve_order_import_supplier_context(
    conn: sqlite3.Connection,
    supplier_id: int | None = None,
    supplier_name: str | None = None,
) -> dict[str, Any]:
    if supplier_id is not None:
        supplier = _get_entity_or_404(
            conn,
            "suppliers",
            "supplier_id",
            supplier_id,
            "SUPPLIER_NOT_FOUND",
            f"Supplier with id {supplier_id} not found",
        )
        return {
            "supplier_id": int(supplier["supplier_id"]),
            "supplier_name": str(supplier["name"]),
            "exists": True,
        }
    if supplier_name is None:
        raise AppError(
            code="INVALID_SUPPLIER",
            message="supplier_id or supplier_name is required",
            status_code=422,
        )
    normalized_name = require_non_empty(supplier_name, "supplier")
    resolved_supplier_id = _find_supplier_id_by_name(conn, normalized_name)
    if resolved_supplier_id is None:
        return {
            "supplier_id": None,
            "supplier_name": normalized_name,
            "exists": False,
        }
    supplier = _get_entity_or_404(
        conn,
        "suppliers",
        "supplier_id",
        resolved_supplier_id,
        "SUPPLIER_NOT_FOUND",
        f"Supplier with id {resolved_supplier_id} not found",
    )
    return {
        "supplier_id": int(supplier["supplier_id"]),
        "supplier_name": str(supplier["name"]),
        "exists": True,
    }


def _resolve_order_import_row_supplier_context(
    conn: sqlite3.Connection,
    *,
    row: dict[str, str],
    row_number: int,
    default_supplier_id: int | None = None,
    default_supplier_name: str | None = None,
) -> dict[str, Any]:
    row_supplier_name = str(row.get("supplier") or "").strip()
    if row_supplier_name:
        return _resolve_order_import_supplier_context(
            conn,
            supplier_name=row_supplier_name,
        )
    if default_supplier_id is not None or default_supplier_name is not None:
        return _resolve_order_import_supplier_context(
            conn,
            supplier_id=default_supplier_id,
            supplier_name=default_supplier_name,
        )
    raise AppError(
        code="INVALID_CSV",
        message=f"supplier is required (row {row_number})",
        status_code=422,
    )


def _summarize_order_import_supplier_contexts(
    contexts: list[dict[str, Any]],
) -> dict[str, Any]:
    if not contexts:
        return {
            "supplier_id": None,
            "supplier_name": "",
            "exists": False,
            "mode": "empty",
        }
    unique_pairs = {
        (
            context.get("supplier_id"),
            str(context.get("supplier_name") or ""),
            bool(context.get("exists")),
        )
        for context in contexts
    }
    if len(unique_pairs) == 1:
        supplier_id, supplier_name, exists = next(iter(unique_pairs))
        return {
            "supplier_id": supplier_id,
            "supplier_name": supplier_name,
            "exists": exists,
            "mode": "single",
        }
    return {
        "supplier_id": None,
        "supplier_name": "Multiple suppliers",
        "exists": False,
        "mode": "per_row",
    }


def _resolve_order_item(
    conn: sqlite3.Connection,
    supplier_id: int | None,
    ordered_item_number: str,
) -> tuple[int | None, int]:
    direct = _resolve_item_by_number(conn, ordered_item_number)
    if direct is not None:
        return direct, 1
    if supplier_id is None:
        return None, 1
    alias = conn.execute(
        """
        SELECT canonical_item_id, units_per_order
        FROM supplier_item_aliases
        WHERE supplier_id = ? AND ordered_item_number = ?
        """,
        (supplier_id, ordered_item_number),
    ).fetchone()
    if alias is None:
        alias_rows = conn.execute(
            """
            SELECT canonical_item_id, units_per_order
            FROM supplier_item_aliases
            WHERE supplier_id = ? AND lower(ordered_item_number) = lower(?)
            ORDER BY alias_id
            """,
            (supplier_id, ordered_item_number),
        ).fetchall()
        if len(alias_rows) > 1:
            raise AppError(
                code="AMBIGUOUS_ORDERED_ITEM_ALIAS",
                message=(
                    f"Multiple aliases found for '{ordered_item_number}' under supplier {supplier_id} "
                    "when matching case-insensitively."
                ),
                status_code=409,
            )
        if len(alias_rows) == 1:
            alias = alias_rows[0]
    if alias is None:
        normalized_lookup = _normalize_item_number_for_lookup(ordered_item_number)
        if normalized_lookup:
            candidate_rows = conn.execute(
                """
                SELECT ordered_item_number, canonical_item_id, units_per_order
                FROM supplier_item_aliases
                WHERE supplier_id = ?
                ORDER BY alias_id
                """,
                (supplier_id,),
            ).fetchall()
            normalized_matches = [
                row
                for row in candidate_rows
                if _normalize_item_number_for_lookup(str(row["ordered_item_number"])) == normalized_lookup
            ]
            if len(normalized_matches) > 1:
                raise AppError(
                    code="AMBIGUOUS_ORDERED_ITEM_ALIAS",
                    message=(
                        f"Multiple aliases found for '{ordered_item_number}' under supplier {supplier_id} "
                        "when matching normalized item numbers."
                    ),
                    status_code=409,
                )
            if len(normalized_matches) == 1:
                alias = normalized_matches[0]
    if alias is None:
        return None, 1
    return int(alias["canonical_item_id"]), int(alias["units_per_order"])


def _normalize_item_number_for_lookup(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).strip().casefold()
    if not normalized:
        return ""
    for dash in ("−", "‐", "‑", "‒", "–", "—", "―", "ー", "－"):
        normalized = normalized.replace(dash, "-")
    normalized = re.sub(r"\s+", "", normalized)
    return normalized


def _normalize_search_text(value: Any) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).strip().casefold()
    if not normalized:
        return ""
    return re.sub(r"\s+", "", normalized)


def _split_search_terms(value: Any) -> list[str]:
    raw = unicodedata.normalize("NFKC", str(value or "")).strip()
    if not raw:
        return []
    terms = [_normalize_search_text(part) for part in re.split(r"\s+", raw) if part.strip()]
    return [term for term in terms if term]


def _search_text_sql(expression: str) -> str:
    return (
        "regexp_replace("
        f"lower(COALESCE({expression}, '')),"
        " '[[:space:]]+', '', 'g'"
        ")"
    )


def _append_search_term_clauses(
    clauses: list[str],
    params: list[Any],
    *,
    terms: list[str],
    expressions: list[str],
) -> None:
    if not terms:
        return
    normalized_expressions = [_search_text_sql(expression) for expression in expressions]
    for term in terms:
        wildcard = f"%{term}%"
        clauses.append("(" + " OR ".join(f"{expression} LIKE ?" for expression in normalized_expressions) + ")")
        params.extend([wildcard] * len(normalized_expressions))


ORDER_IMPORT_AUTO_ACCEPT_SCORE = 95
ORDER_IMPORT_REVIEW_SCORE = 70
ORDER_IMPORT_PREVIEW_CANDIDATE_LIMIT = 5


def _get_inventory_quantity(conn: sqlite3.Connection, item_id: int, location: str) -> int:
    row = conn.execute(
        "SELECT quantity FROM inventory_ledger WHERE item_id = ? AND location = ?",
        (item_id, location),
    ).fetchone()
    if row is None:
        return 0
    return int(row["quantity"])


def _get_reserved_allocation_quantity(
    conn: sqlite3.Connection, item_id: int, location: str
) -> int:
    row = conn.execute(
        """
        SELECT COALESCE(SUM(quantity), 0) AS qty
        FROM reservation_allocations
        WHERE item_id = ? AND location = ? AND status = 'ACTIVE'
        """,
        (item_id, location),
    ).fetchone()
    if row is None:
        return 0
    return int(row["qty"] or 0)


def _get_available_inventory_quantity(conn: sqlite3.Connection, item_id: int, location: str) -> int:
    on_hand = _get_inventory_quantity(conn, item_id, location)
    allocated = _get_reserved_allocation_quantity(conn, item_id, location)
    return max(0, on_hand - allocated)


def _list_item_available_inventory(
    conn: sqlite3.Connection, item_id: int
) -> list[tuple[str, int]]:
    rows = conn.execute(
        """
        SELECT location, quantity
        FROM inventory_ledger
        WHERE item_id = ? AND quantity > 0 AND location <> 'RESERVED'
        ORDER BY CASE WHEN location = 'STOCK' THEN 0 ELSE 1 END, location
        """,
        (item_id,),
    ).fetchall()
    available_rows: list[tuple[str, int]] = []
    for row in rows:
        location = str(row["location"])
        available = _get_available_inventory_quantity(conn, item_id, location)
        if available > 0:
            available_rows.append((location, available))
    return available_rows


def _get_total_available_inventory(conn: sqlite3.Connection, item_id: int) -> int:
    return sum(qty for _, qty in _list_item_available_inventory(conn, item_id))


def _get_active_allocation_summary_by_item_location(
    conn: sqlite3.Connection,
    item_ids: list[int],
) -> dict[tuple[int, str], dict[str, Any]]:
    if not item_ids:
        return {}
    placeholders = ",".join("?" for _ in item_ids)
    rows = conn.execute(
        f"""
        SELECT
            ra.item_id,
            ra.location,
            ra.quantity,
            ra.reservation_id,
            p.name AS project_name
        FROM reservation_allocations ra
        LEFT JOIN reservations r ON r.reservation_id = ra.reservation_id
        LEFT JOIN projects p ON p.project_id = r.project_id
        WHERE ra.status = 'ACTIVE'
          AND ra.item_id IN ({placeholders})
        ORDER BY ra.item_id, ra.location, ra.reservation_id
        """,
        tuple(item_ids),
    ).fetchall()
    summary: dict[tuple[int, str], dict[str, Any]] = {}
    for row in rows:
        key = (int(row["item_id"]), str(row["location"]))
        current = summary.setdefault(
            key,
            {
                "allocated_quantity": 0,
                "reservation_ids": set(),
                "project_names": [],
            },
        )
        current["allocated_quantity"] += int(row["quantity"] or 0)
        current["reservation_ids"].add(int(row["reservation_id"]))
        project_name = str(row["project_name"]).strip() if row["project_name"] is not None else ""
        if project_name and project_name not in current["project_names"]:
            current["project_names"].append(project_name)
    normalized: dict[tuple[int, str], dict[str, Any]] = {}
    for key, value in summary.items():
        normalized[key] = {
            "allocated_quantity": int(value["allocated_quantity"]),
            "active_reservation_count": len(value["reservation_ids"]),
            "allocated_project_names": list(value["project_names"]),
        }
    return normalized


def _get_pending_arrival_quantity_by_date(
    conn: sqlite3.Connection,
    item_id: int,
    target_date: str,
) -> int:
    row = conn.execute(
        """
        SELECT COALESCE(SUM(order_amount), 0) AS qty
        FROM orders
        WHERE item_id = ?
          AND project_id IS NULL
          AND status <> 'Arrived'
          AND expected_arrival IS NOT NULL
          AND date(expected_arrival) <= date(?)
        """,
        (item_id, target_date),
    ).fetchone()
    if row is None:
        return 0
    return int(row["qty"] or 0)


def _get_projected_available_inventory(
    conn: sqlite3.Connection,
    item_id: int,
    *,
    target_date: str | None = None,
) -> int:
    available_now = _get_total_available_inventory(conn, item_id)
    if target_date is None:
        return available_now
    pending_arrivals = _get_pending_arrival_quantity_by_date(conn, item_id, target_date)
    return available_now + pending_arrivals


def _lock_inventory_item_state(conn: sqlite3.Connection, item_id: int) -> None:
    conn.execute("SELECT pg_advisory_xact_lock(?, ?)", (7101, int(item_id)))


def _lock_reservation_state(conn: sqlite3.Connection, reservation_id: int) -> None:
    conn.execute("SELECT pg_advisory_xact_lock(?, ?)", (7102, int(reservation_id)))


def _lock_order_state(conn: sqlite3.Connection, order_id: int) -> None:
    conn.execute("SELECT pg_advisory_xact_lock(?, ?)", (7103, int(order_id)))


def _lock_transaction_state(conn: sqlite3.Connection, log_id: int) -> None:
    conn.execute("SELECT pg_advisory_xact_lock(?, ?)", (7104, int(log_id)))


def _lock_purchase_order_number_state(
    conn: sqlite3.Connection,
    supplier_id: int,
    purchase_order_number: str,
) -> None:
    conn.execute(
        "SELECT pg_advisory_xact_lock(?, hashtext(?))",
        (7105, f"{int(supplier_id)}:{str(purchase_order_number).strip().casefold()}"),
    )


def _lock_reservation_item_state(conn: sqlite3.Connection, reservation_id: int, item_id: int) -> None:
    _lock_reservation_state(conn, reservation_id)
    _lock_inventory_item_state(conn, item_id)


def _lock_order_item_state(conn: sqlite3.Connection, order_id: int, item_id: int) -> None:
    _lock_order_state(conn, order_id)
    _lock_inventory_item_state(conn, item_id)


def _normalize_future_target_date(target_date: str | None, *, field_name: str = "target_date") -> str | None:
    normalized = normalize_optional_date(target_date, field_name)
    if normalized is not None and normalized < today_jst():
        raise AppError(
            code="INVALID_TARGET_DATE",
            message=f"{field_name} must be today or later",
            status_code=422,
        )
    return normalized


def _apply_inventory_delta(
    conn: sqlite3.Connection,
    item_id: int,
    location: str,
    delta: int,
) -> int:
    normalized_location = require_non_empty(location, "location")
    normalized_delta = int(delta)
    timestamp = now_jst_iso()
    if normalized_delta > 0:
        row = conn.execute(
            """
            INSERT INTO inventory_ledger (item_id, location, quantity, last_updated)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (item_id, location)
            DO UPDATE SET
                quantity = inventory_ledger.quantity + EXCLUDED.quantity,
                last_updated = EXCLUDED.last_updated
            RETURNING quantity
            """,
            (item_id, normalized_location, normalized_delta, timestamp),
        ).fetchone()
        return int(row["quantity"]) if row is not None else normalized_delta

    row = conn.execute(
        """
        UPDATE inventory_ledger
        SET quantity = quantity + ?, last_updated = ?
        WHERE item_id = ? AND location = ? AND quantity + ? >= 0
        RETURNING quantity
        """,
        (normalized_delta, timestamp, item_id, normalized_location, normalized_delta),
    ).fetchone()
    if row is None:
        current = _get_inventory_quantity(conn, item_id, normalized_location)
        raise AppError(
            code="INSUFFICIENT_STOCK",
            message=f"Not enough inventory at {normalized_location}",
            status_code=409,
            details={
                "item_id": item_id,
                "location": normalized_location,
                "requested_delta": delta,
                "available": current,
            },
        )
    updated = int(row["quantity"] or 0)
    if updated == 0:
        conn.execute(
            "DELETE FROM inventory_ledger WHERE item_id = ? AND location = ? AND quantity = 0",
            (item_id, normalized_location),
        )
    return updated


def _log_transaction(
    conn: sqlite3.Connection,
    *,
    operation_type: str,
    item_id: int,
    quantity: int,
    from_location: str | None,
    to_location: str | None,
    note: str | None = None,
    batch_id: str | None = None,
    undo_of_log_id: int | None = None,
) -> dict[str, Any]:
    cur = conn.execute(
        """
        INSERT INTO transaction_log (
            timestamp,
            operation_type,
            item_id,
            quantity,
            from_location,
            to_location,
            note,
            batch_id,
            undo_of_log_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            now_jst_iso(),
            operation_type,
            item_id,
            quantity,
            from_location,
            to_location,
            note,
            batch_id,
            undo_of_log_id,
        ),
    )
    return get_transaction(conn, int(cur.lastrowid))


_RESERVATION_CREATE_BATCH_RE = re.compile(r"^reservation-(\d+)$")
_RESERVATION_RELEASE_BATCH_RE = re.compile(r"^reservation-release-(\d+)-log-(\d+)$")
_RESERVATION_CONSUME_BATCH_RE = re.compile(r"^reservation-consume-(\d+)-log-(\d+)$")


def _set_transaction_batch_id(conn: sqlite3.Connection, log_id: int, batch_id: str) -> None:
    conn.execute("UPDATE transaction_log SET batch_id = ? WHERE log_id = ?", (batch_id, log_id))


def _append_reservation_tx_marker(note: str | None, log_id: int) -> str:
    base = str(note or "").rstrip()
    marker = f"[[tx:{int(log_id)}]]"
    return f"{base} {marker}".strip() if base else marker


def _remove_reservation_tx_marker(note: str | None, log_id: int) -> str | None:
    if note is None:
        return None
    cleaned = re.sub(rf"\s*\[\[tx:{int(log_id)}]]$", "", str(note)).strip()
    return cleaned or None


def _reservation_event_note(override_note: str | None, existing_note: Any, log_id: int) -> str:
    base_note = override_note if override_note is not None else _remove_reservation_tx_marker(existing_note, log_id)
    return _append_reservation_tx_marker(None if base_note is None else str(base_note), log_id)


def _get_or_create_quotation(
    conn: sqlite3.Connection,
    supplier_id: int,
    quotation_number: str,
    issue_date: str | None,
    quotation_document_url: str | None,
) -> int:
    normalized_number = require_non_empty(quotation_number, "quotation_number")
    normalized_issue_date = normalize_optional_date(issue_date, "issue_date")
    row = conn.execute(
        """
        SELECT quotation_id FROM quotations
        WHERE supplier_id = ? AND quotation_number = ?
        """,
        (supplier_id, normalized_number),
    ).fetchone()
    if row:
        conn.execute(
            """
            UPDATE quotations
            SET issue_date = COALESCE(?, issue_date),
                quotation_document_url = COALESCE(?, quotation_document_url)
            WHERE quotation_id = ?
            """,
            (normalized_issue_date, quotation_document_url, int(row["quotation_id"])),
        )
        return int(row["quotation_id"])
    cur = conn.execute(
        """
        INSERT INTO quotations (supplier_id, quotation_number, issue_date, quotation_document_url)
        VALUES (?, ?, ?, ?)
        """,
        (supplier_id, normalized_number, normalized_issue_date, quotation_document_url),
    )
    return int(cur.lastrowid)


def _get_quotation_row_by_id(conn: sqlite3.Connection, quotation_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT
            q.quotation_id,
            q.supplier_id,
            s.name AS supplier_name,
            q.quotation_number,
            q.issue_date,
            q.quotation_document_url
        FROM quotations q
        JOIN suppliers s ON s.supplier_id = q.supplier_id
        WHERE q.quotation_id = ?
        """,
        (quotation_id,),
    ).fetchone()
    return dict(row) if row is not None else None


def _find_purchase_order_row(
    conn: sqlite3.Connection,
    *,
    supplier_id: int,
    purchase_order_number: str | None,
) -> dict[str, Any] | None:
    if purchase_order_number is None:
        row = conn.execute(
            """
            SELECT purchase_order_id
            FROM purchase_orders
            WHERE supplier_id = ? AND purchase_order_number IS NULL
            ORDER BY purchase_order_id
            LIMIT 1
            """,
            (supplier_id,),
        ).fetchone()
    else:
        row = conn.execute(
            """
            SELECT purchase_order_id
            FROM purchase_orders
            WHERE supplier_id = ? AND purchase_order_number = ?
            """,
            (supplier_id, purchase_order_number),
        ).fetchone()
    if row is None:
        return None
    return _get_purchase_order_row_by_id(conn, int(row["purchase_order_id"]))


def _find_purchase_order_row_by_document_url(
    conn: sqlite3.Connection,
    *,
    supplier_id: int,
    purchase_order_document_url: str | None,
) -> dict[str, Any] | None:
    if purchase_order_document_url is None:
        return None
    row = conn.execute(
        """
        SELECT purchase_order_id
        FROM purchase_orders
        WHERE supplier_id = ? AND purchase_order_document_url = ?
        """,
        (supplier_id, purchase_order_document_url),
    ).fetchone()
    if row is None:
        return None
    return _get_purchase_order_row_by_id(conn, int(row["purchase_order_id"]))


def _create_purchase_order(
    conn: sqlite3.Connection,
    supplier_id: int,
    purchase_order_number: str | None,
    purchase_order_document_url: str | None,
    *,
    import_locked: bool = True,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO purchase_orders (
            supplier_id,
            purchase_order_number,
            purchase_order_document_url,
            import_locked
        )
        VALUES (?, ?, ?, ?)
        """,
        (supplier_id, purchase_order_number, purchase_order_document_url, bool(import_locked)),
    )
    return int(cur.lastrowid)


def _set_purchase_order_document_url(
    conn: sqlite3.Connection,
    purchase_order_id: int,
    purchase_order_document_url: str | None,
) -> None:
    conn.execute(
        """
        UPDATE purchase_orders
        SET purchase_order_document_url = ?
        WHERE purchase_order_id = ?
        """,
        (purchase_order_document_url, int(purchase_order_id)),
    )


def _get_or_create_purchase_order(
    conn: sqlite3.Connection,
    supplier_id: int,
    purchase_order_number: str | None,
    purchase_order_document_url: str | None,
    *,
    current_purchase_order_id: int | None = None,
) -> int:
    if purchase_order_number is not None:
        _lock_purchase_order_number_state(conn, supplier_id, purchase_order_number)
    existing = _find_purchase_order_row(
        conn,
        supplier_id=supplier_id,
        purchase_order_number=purchase_order_number,
    )
    if existing is not None:
        existing_purchase_order_id = int(existing["purchase_order_id"])
        is_current_purchase_order = (
            current_purchase_order_id is not None
            and existing_purchase_order_id == int(current_purchase_order_id)
        )
        current_document_url = existing.get("purchase_order_document_url")
        if current_document_url == purchase_order_document_url:
            return existing_purchase_order_id
        if purchase_order_document_url is not None:
            duplicate_document = _find_purchase_order_row_by_document_url(
                conn,
                supplier_id=supplier_id,
                purchase_order_document_url=purchase_order_document_url,
            )
            if duplicate_document is not None and int(duplicate_document["purchase_order_id"]) != existing_purchase_order_id:
                if is_current_purchase_order:
                    return int(duplicate_document["purchase_order_id"])
                raise AppError(
                    code="PURCHASE_ORDER_ALREADY_EXISTS",
                    message="Another purchase order already uses this document URL for the same supplier",
                    status_code=409,
                )
        if current_document_url is not None and not is_current_purchase_order:
            if purchase_order_document_url is None:
                return existing_purchase_order_id
            raise AppError(
                code="PURCHASE_ORDER_DOCUMENT_URL_CONFLICT",
                message=(
                    "Purchase order number already exists for this supplier with a different document URL"
                ),
                status_code=409,
            )
        _set_purchase_order_document_url(
            conn,
            existing_purchase_order_id,
            purchase_order_document_url,
        )
        return existing_purchase_order_id
    duplicate_document = _find_purchase_order_row_by_document_url(
        conn,
        supplier_id=supplier_id,
        purchase_order_document_url=purchase_order_document_url,
    )
    if duplicate_document is not None:
        if current_purchase_order_id is not None:
            return int(duplicate_document["purchase_order_id"])
        raise AppError(
            code="PURCHASE_ORDER_ALREADY_EXISTS",
            message="Another purchase order already uses this document URL for the same supplier",
            status_code=409,
        )
    if current_purchase_order_id is not None and purchase_order_number is None:
        current_purchase_order = _get_purchase_order_row_by_id(conn, int(current_purchase_order_id))
        if current_purchase_order is not None and int(current_purchase_order["supplier_id"]) == supplier_id:
            _set_purchase_order_document_url(
                conn,
                int(current_purchase_order_id),
                purchase_order_document_url,
            )
            return int(current_purchase_order_id)
    return _create_purchase_order(
        conn,
        supplier_id,
        purchase_order_number,
        purchase_order_document_url,
        import_locked=True,
    )


def _get_purchase_order_row_by_id(conn: sqlite3.Connection, purchase_order_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT
            po.purchase_order_id,
            po.supplier_id,
            s.name AS supplier_name,
            po.purchase_order_number,
            po.purchase_order_document_url,
            po.import_locked
        FROM purchase_orders po
        JOIN suppliers s ON s.supplier_id = po.supplier_id
        WHERE po.purchase_order_id = ?
        """,
        (purchase_order_id,),
    ).fetchone()
    return dict(row) if row is not None else None


def _set_purchase_order_import_locked(
    conn: sqlite3.Connection,
    *,
    supplier_id: int,
    purchase_order_number: str,
    import_locked: bool,
) -> dict[str, Any]:
    _lock_purchase_order_number_state(conn, supplier_id, purchase_order_number)
    current = _find_purchase_order_row(
        conn,
        supplier_id=supplier_id,
        purchase_order_number=purchase_order_number,
    )
    if current is None:
        raise AppError(
            code="PURCHASE_ORDER_NOT_FOUND",
            message=(
                "Purchase order not found for supplier "
                f"{supplier_id} and purchase_order_number '{purchase_order_number}'"
            ),
            status_code=404,
        )
    conn.execute(
        """
        UPDATE purchase_orders
        SET import_locked = ?
        WHERE purchase_order_id = ?
        """,
        (bool(import_locked), int(current["purchase_order_id"])),
    )
    updated = _get_purchase_order_row_by_id(conn, int(current["purchase_order_id"]))
    return updated if updated is not None else current


def _delete_purchase_order_if_orphaned(conn: sqlite3.Connection, purchase_order_id: int | None) -> bool:
    if purchase_order_id is None:
        return False
    remaining = conn.execute(
        "SELECT COUNT(*) AS c FROM orders WHERE purchase_order_id = ?",
        (purchase_order_id,),
    ).fetchone()
    if int(remaining["c"] or 0) > 0:
        return False
    try:
        conn.execute("DELETE FROM purchase_orders WHERE purchase_order_id = ?", (purchase_order_id,))
    except sqlite3.IntegrityError:
        return False
    return True


def _decode_csv_bytes(content: bytes) -> str:
    """Decode CSV bytes, falling back to cp932 when the content is not valid UTF-8.

    Batch-registration CSVs are always written as UTF-8 by this service, but
    externally edited files (e.g. opened and re-saved on a Japanese Windows
    machine) may contain CP932-encoded text for Japanese supplier names.
    """
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return content.decode("cp932")


def _load_csv_rows_from_content(content: bytes) -> list[dict[str, str]]:
    text = _decode_csv_bytes(content)
    reader = csv.DictReader(StringIO(text))
    return [{k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in row.items() if k is not None} for row in reader]


def _read_csv_text(content: bytes) -> str:
    return _decode_csv_bytes(content)


def _read_import_job_source_text(content: bytes) -> str:
    """Capture a text snapshot for import jobs even when the CSV bytes are malformed."""
    try:
        return _read_csv_text(content)
    except UnicodeDecodeError:
        return content.decode("utf-8-sig", errors="replace")


def _load_csv_rows_from_path(path: str | Path) -> list[dict[str, str]]:
    content = Path(path).read_bytes()
    text = _decode_csv_bytes(content)
    reader = csv.DictReader(StringIO(text))
    return [{k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in row.items() if k is not None} for row in reader]


def _load_csv_rows_with_fieldnames_from_path(path: str | Path) -> tuple[list[str], list[dict[str, str]]]:
    content = Path(path).read_bytes()
    text = _decode_csv_bytes(content)
    reader = csv.DictReader(StringIO(text))
    fieldnames = [str(name).strip() for name in (reader.fieldnames or []) if name is not None]
    rows = [{k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in row.items() if k is not None} for row in reader]
    return fieldnames, rows


IMPORT_TEMPLATE_SPECS: dict[str, dict[str, Any]] = {
    "items": {
        "filename": "items_import_template.csv",
        "fieldnames": [
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
    },
    "inventory": {
        "filename": "inventory_import_template.csv",
        "fieldnames": [
            "operation_type",
            "item_id",
            "quantity",
            "from_location",
            "to_location",
            "location",
            "note",
        ],
    },
    "orders": {
        "filename": "orders_import_template.csv",
        "fieldnames": [
            "supplier",
            "item_number",
            "quantity",
            "purchase_order_number",
            "quotation_number",
            "issue_date",
            "quotation_document_url",
            "order_date",
            "expected_arrival",
            "purchase_order_document_url",
        ],
    },
    "reservations": {
        "filename": "reservations_import_template.csv",
        "fieldnames": [
            "item_id",
            "assembly",
            "assembly_quantity",
            "quantity",
            "purpose",
            "deadline",
            "note",
            "project_id",
        ],
    },
}


def _csv_bytes(fieldnames: list[str], rows: list[dict[str, Any]]) -> bytes:
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                field: "" if row.get(field) is None else row.get(field)
                for field in fieldnames
            }
        )
    return output.getvalue().encode("utf-8-sig")


def get_import_template_csv(flow_type: str) -> tuple[str, bytes]:
    spec = IMPORT_TEMPLATE_SPECS.get(flow_type)
    if spec is None:
        raise AppError(
            code="IMPORT_TEMPLATE_NOT_SUPPORTED",
            message=f"Import template is not defined for flow '{flow_type}'",
            status_code=404,
        )
    return str(spec["filename"]), _csv_bytes(list(spec["fieldnames"]), [])


def get_items_import_reference_csv(conn: sqlite3.Connection) -> tuple[str, bytes]:
    fieldnames = [
        "row_type",
        "item_number",
        "manufacturer_name",
        "category",
        "url",
        "description",
        "supplier",
        "canonical_item_number",
        "units_per_order",
    ]
    item_rows = conn.execute(
        """
        SELECT
            im.item_id,
            im.item_number,
            m.name AS manufacturer_name,
            COALESCE(ca.canonical_category, im.category) AS category,
            im.url,
            im.description
        FROM items_master im
        JOIN manufacturers m ON m.manufacturer_id = im.manufacturer_id
        LEFT JOIN category_aliases ca ON ca.alias_category = im.category
        ORDER BY im.item_number, im.item_id
        """
    ).fetchall()
    alias_rows = conn.execute(
        """
        SELECT
            im.item_id,
            im.item_number,
            m.name AS manufacturer_name,
            COALESCE(ca.canonical_category, im.category) AS category,
            im.url,
            im.description,
            s.name AS supplier,
            a.ordered_item_number,
            a.units_per_order
        FROM supplier_item_aliases a
        JOIN suppliers s ON s.supplier_id = a.supplier_id
        JOIN items_master im ON im.item_id = a.canonical_item_id
        JOIN manufacturers m ON m.manufacturer_id = im.manufacturer_id
        LEFT JOIN category_aliases ca ON ca.alias_category = im.category
        ORDER BY s.name, a.ordered_item_number
        """
    ).fetchall()
    rows = [
        {
            "row_type": "item",
            "item_number": row["item_number"],
            "manufacturer_name": row["manufacturer_name"],
            "category": row["category"],
            "url": row["url"],
            "description": row["description"],
            "supplier": "",
            "canonical_item_number": "",
            "units_per_order": "",
        }
        for row in item_rows
    ]
    rows.extend(
        {
            "row_type": "alias",
            "item_number": row["ordered_item_number"],
            "manufacturer_name": row["manufacturer_name"],
            "category": row["category"],
            "url": row["url"],
            "description": row["description"],
            "supplier": row["supplier"],
            "canonical_item_number": row["item_number"],
            "units_per_order": int(row["units_per_order"]),
        }
        for row in alias_rows
    )
    return "items_import_reference.csv", _csv_bytes(fieldnames, rows)


def get_inventory_import_reference_csv(conn: sqlite3.Connection) -> tuple[str, bytes]:
    fieldnames = [
        "item_id",
        "item_number",
        "manufacturer_name",
        "category",
        "location",
        "current_quantity",
    ]
    rows = conn.execute(
        """
        SELECT
            im.item_id,
            im.item_number,
            m.name AS manufacturer_name,
            COALESCE(ca.canonical_category, im.category) AS category,
            il.location,
            COALESCE(il.quantity, 0) AS current_quantity
        FROM items_master im
        JOIN manufacturers m ON m.manufacturer_id = im.manufacturer_id
        LEFT JOIN category_aliases ca ON ca.alias_category = im.category
        LEFT JOIN inventory_ledger il ON il.item_id = im.item_id
        ORDER BY im.item_number, il.location, im.item_id
        """
    ).fetchall()
    return "inventory_import_reference.csv", _csv_bytes(fieldnames, _rows_to_dict(rows))


def get_orders_import_reference_csv(
    conn: sqlite3.Connection,
    *,
    supplier_name: str | None = None,
) -> tuple[str, bytes]:
    fieldnames = [
        "reference_type",
        "supplier_name",
        "canonical_item_number",
        "manufacturer_name",
        "ordered_item_number",
        "units_per_order",
    ]
    normalized_supplier = str(supplier_name or "").strip() or None
    item_rows = conn.execute(
        """
        SELECT im.item_number AS canonical_item_number, m.name AS manufacturer_name
        FROM items_master im
        JOIN manufacturers m ON m.manufacturer_id = im.manufacturer_id
        ORDER BY im.item_number, im.item_id
        """
    ).fetchall()
    alias_params: tuple[Any, ...]
    alias_where = ""
    if normalized_supplier is not None:
        alias_where = "WHERE s.name = ?"
        alias_params = (normalized_supplier,)
    else:
        alias_params = ()
    alias_rows = conn.execute(
        f"""
        SELECT
            s.name AS supplier_name,
            im.item_number AS canonical_item_number,
            m.name AS manufacturer_name,
            a.ordered_item_number,
            a.units_per_order
        FROM supplier_item_aliases a
        JOIN suppliers s ON s.supplier_id = a.supplier_id
        JOIN items_master im ON im.item_id = a.canonical_item_id
        JOIN manufacturers m ON m.manufacturer_id = im.manufacturer_id
        {alias_where}
        ORDER BY s.name, a.ordered_item_number
        """,
        alias_params,
    ).fetchall()
    rows = [
        {
            "reference_type": "canonical_item",
            "supplier_name": normalized_supplier or "",
            "canonical_item_number": row["canonical_item_number"],
            "manufacturer_name": row["manufacturer_name"],
            "ordered_item_number": "",
            "units_per_order": "",
        }
        for row in item_rows
    ]
    rows.extend(
        {
            "reference_type": "supplier_item_alias",
            "supplier_name": row["supplier_name"],
            "canonical_item_number": row["canonical_item_number"],
            "manufacturer_name": row["manufacturer_name"],
            "ordered_item_number": row["ordered_item_number"],
            "units_per_order": int(row["units_per_order"]),
        }
        for row in alias_rows
    )
    filename = "orders_import_reference.csv"
    if normalized_supplier is not None:
        filename = f"orders_import_reference_{_safe_filename_component(normalized_supplier)}.csv"
    return filename, _csv_bytes(fieldnames, rows)


def get_reservations_import_reference_csv(conn: sqlite3.Connection) -> tuple[str, bytes]:
    fieldnames = [
        "reference_type",
        "item_id",
        "item_number",
        "manufacturer_name",
        "assembly_id",
        "assembly_name",
        "project_id",
        "project_name",
        "project_status",
    ]
    item_rows = conn.execute(
        """
        SELECT
            im.item_id,
            im.item_number,
            m.name AS manufacturer_name
        FROM items_master im
        JOIN manufacturers m ON m.manufacturer_id = im.manufacturer_id
        ORDER BY im.item_number, im.item_id
        """
    ).fetchall()
    project_rows = conn.execute(
        """
        SELECT project_id, name, status
        FROM projects
        ORDER BY name, project_id
        """
    ).fetchall()
    assembly_rows = conn.execute(
        """
        SELECT assembly_id, name AS assembly_name
        FROM assemblies
        ORDER BY assembly_name, assembly_id
        """
    ).fetchall()
    rows = [
        {
            "reference_type": "item",
            "item_id": int(row["item_id"]),
            "item_number": row["item_number"],
            "manufacturer_name": row["manufacturer_name"],
            "assembly_id": "",
            "assembly_name": "",
            "project_id": "",
            "project_name": "",
            "project_status": "",
        }
        for row in item_rows
    ]
    rows.extend(
        {
            "reference_type": "assembly",
            "item_id": "",
            "item_number": "",
            "manufacturer_name": "",
            "assembly_id": int(row["assembly_id"]),
            "assembly_name": row["assembly_name"],
            "project_id": "",
            "project_name": "",
            "project_status": "",
        }
        for row in assembly_rows
    )
    rows.extend(
        {
            "reference_type": "project",
            "item_id": "",
            "item_number": "",
            "manufacturer_name": "",
            "assembly_id": "",
            "assembly_name": "",
            "project_id": int(row["project_id"]),
            "project_name": row["name"],
            "project_status": row["status"],
        }
        for row in project_rows
    )
    return "reservations_import_reference.csv", _csv_bytes(fieldnames, rows)


def _to_json_text(value: dict[str, Any] | None) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=True, sort_keys=True)


def _to_json_value_text(value: Any | None) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=True, sort_keys=True)


def _from_json_text(value: str | None) -> dict[str, Any] | None:
    if value is None:
        return None
    try:
        loaded = json.loads(value)
    except json.JSONDecodeError:
        return None
    if not isinstance(loaded, dict):
        return None
    return loaded


def _from_json_value_text(value: str | None) -> Any | None:
    if value is None:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


def _alias_row_by_supplier_and_ordered(
    conn: sqlite3.Connection,
    *,
    supplier_id: int,
    ordered_item_number: str,
) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT
            a.alias_id,
            a.supplier_id,
            s.name AS supplier_name,
            a.ordered_item_number,
            a.canonical_item_id,
            im.item_number AS canonical_item_number,
            a.units_per_order,
            a.created_at
        FROM supplier_item_aliases a
        JOIN suppliers s ON s.supplier_id = a.supplier_id
        JOIN items_master im ON im.item_id = a.canonical_item_id
        WHERE a.supplier_id = ? AND a.ordered_item_number = ?
        """,
        (supplier_id, ordered_item_number),
    ).fetchone()
    return dict(row) if row is not None else None


def _record_import_job(
    conn: sqlite3.Connection,
    *,
    import_type: str,
    source_name: str,
    source_content: str,
    continue_on_error: bool,
    redo_of_job_id: int | None = None,
    request_metadata: dict[str, Any] | None = None,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO import_jobs (
            import_type,
            source_name,
            source_content,
            request_metadata,
            continue_on_error,
            created_at,
            redo_of_job_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            import_type,
            source_name,
            source_content,
            _to_json_value_text(request_metadata),
            1 if continue_on_error else 0,
            now_jst_iso(),
            redo_of_job_id,
        ),
    )
    return int(cur.lastrowid)


def _record_import_job_effect(
    conn: sqlite3.Connection,
    *,
    import_job_id: int,
    row_number: int,
    status: str,
    effect_type: str,
    entry_type: str | None = None,
    item_id: int | None = None,
    alias_id: int | None = None,
    supplier_id: int | None = None,
    item_number: str | None = None,
    supplier_name: str | None = None,
    canonical_item_number: str | None = None,
    units_per_order: int | None = None,
    message: str | None = None,
    code: str | None = None,
    before_state: dict[str, Any] | None = None,
    after_state: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO import_job_effects (
            import_job_id,
            row_number,
            status,
            entry_type,
            effect_type,
            item_id,
            alias_id,
            supplier_id,
            item_number,
            supplier_name,
            canonical_item_number,
            units_per_order,
            message,
            code,
            before_state,
            after_state,
            created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            import_job_id,
            row_number,
            status,
            entry_type,
            effect_type,
            item_id,
            alias_id,
            supplier_id,
            item_number,
            supplier_name,
            canonical_item_number,
            units_per_order,
            message,
            code,
            _to_json_text(before_state),
            _to_json_text(after_state),
            now_jst_iso(),
        ),
    )


def _finalize_import_job(conn: sqlite3.Connection, *, import_job_id: int, result: dict[str, Any]) -> None:
    result_status = str(result["status"])
    if result_status == "missing_items":
        job_status = "partial"
    elif result_status in {"ok", "partial", "error"}:
        job_status = result_status
    else:
        job_status = "error"
    conn.execute(
        """
        UPDATE import_jobs
        SET
            status = ?,
            processed = ?,
            created_count = ?,
            duplicate_count = ?,
            failed_count = ?
        WHERE import_job_id = ?
        """,
        (
            job_status,
            int(result["processed"]),
            int(result["created_count"]),
            int(result["duplicate_count"]),
            int(result["failed_count"]),
            import_job_id,
        ),
    )


def _normalize_import_job_row(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["continue_on_error"] = bool(data.get("continue_on_error"))
    request_metadata = _from_json_value_text(data.get("request_metadata"))
    data["request_metadata"] = request_metadata if isinstance(request_metadata, dict) else None
    return data


def _normalize_import_job_effect_row(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["before_state"] = _from_json_text(data.get("before_state"))
    data["after_state"] = _from_json_text(data.get("after_state"))
    return data


def _legacy_batch_file_public_name(path_text: str | None, fallback: str = "batch.csv") -> str:
    if path_text:
        name = Path(str(path_text)).name.strip()
        if name:
            return name
    return fallback


def _record_legacy_order_batch_file_effect(
    conn: sqlite3.Connection,
    *,
    import_job_id: int,
    row_number: int,
    file_report: dict[str, Any],
    unregistered_root: Path,
    registered_root: Path,
    staged_file_id: int | None = None,
) -> int:
    status_text = str(file_report.get("status") or "error")
    effect_status = "created" if status_text == "ok" else "error"
    effect_type = {
        "ok": "legacy_order_batch_file_imported",
        "missing_items": "legacy_order_batch_file_missing_items",
    }.get(status_text, "legacy_order_batch_file_error")
    source_path = str(file_report.get("file") or "")
    moved_to = str(file_report.get("moved_to") or "")
    supplier_name = str(file_report.get("supplier") or "")
    cur = conn.execute(
        """
        INSERT INTO import_job_effects (
            import_job_id,
            row_number,
            status,
            effect_type,
            supplier_name,
            item_number,
            message,
            after_state,
            created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            import_job_id,
            row_number,
            effect_status,
            effect_type,
            supplier_name or None,
            _legacy_batch_file_public_name(source_path),
            str(file_report.get("error") or ""),
            _to_json_text(
                {
                    "source_csv_path": source_path,
                    "registered_csv_path": moved_to or None,
                    "supplier_name": supplier_name or None,
                    "public_file_name": _legacy_batch_file_public_name(source_path),
                    "staged_file_id": staged_file_id,
                    "unregistered_root": str(unregistered_root),
                    "registered_root": str(registered_root),
                }
            ),
            now_jst_iso(),
        ),
    )
    return int(cur.lastrowid)


def _import_job_matches_state(
    current: dict[str, Any] | None,
    expected: dict[str, Any] | None,
    keys: tuple[str, ...],
) -> bool:
    if current is None or expected is None:
        return False
    for key in keys:
        if current.get(key) != expected.get(key):
            return False
    return True


def _raise_import_undo_conflict(message: str, *, effect_id: int, row_number: int) -> None:
    raise AppError(
        code="IMPORT_UNDO_CONFLICT",
        message=message,
        status_code=409,
        details={"effect_id": effect_id, "row": row_number},
    )


MISSING_ITEMS_FIELDNAMES = [
    "item_number",
    "supplier",
    "manufacturer_name",
    "resolution_type",
    "category",
    "url",
    "description",
    "canonical_item_number",
    "units_per_order",
]




def _safe_filename_component(value: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value).strip())
    return sanitized.strip("._") or "unknown"


def _write_missing_items_csv(
    rows: list[dict[str, Any]],
    source_name: str,
    output_dir: str | Path | None = None,
) -> StoredObject:
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=MISSING_ITEMS_FIELDNAMES)
    writer.writeheader()
    for row in rows:
        writer.writerow({k: row.get(k, "") for k in MISSING_ITEMS_FIELDNAMES})

    stem = Path(source_name).stem or "order_import"
    filename = f"{stem}_missing_items_registration.csv"
    if output_dir is None:
        return write_storage_bytes(
            bucket=GENERATED_ARTIFACTS_BUCKET,
            subdir="missing_items",
            filename=filename,
            content=output.getvalue().encode("utf-8"),
        )

    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    file_path = target_dir / filename
    with file_path.open("w", encoding="utf-8", newline="") as fp:
        fp.write(output.getvalue())
    return _stored_object_from_path(file_path)


def _write_batch_missing_items_register(
    missing_reports: list[dict[str, Any]],
    *,
    output_dir: Path,
) -> StoredObject:
    batch_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output = StringIO()
    fieldnames = [
        "source_csv",
        "source_supplier",
        *MISSING_ITEMS_FIELDNAMES,
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    seen_missing_keys: set[tuple[str, str, str]] = set()
    for report in missing_reports:
        source_csv = str(report.get("file", ""))
        source_supplier = str(report.get("supplier", ""))
        for row in report.get("missing_rows", []):
            item_number = str(row.get("item_number", "")).strip()
            manufacturer_name = str(row.get("manufacturer_name", "")).strip()
            supplier_name = str(row.get("supplier", source_supplier)).strip()
            dedupe_key = (
                supplier_name.casefold(),
                manufacturer_name.casefold(),
                item_number.casefold(),
            )
            if dedupe_key in seen_missing_keys:
                continue
            seen_missing_keys.add(dedupe_key)
            out_row = {
                "source_csv": source_csv,
                "source_supplier": source_supplier,
            }
            for key in MISSING_ITEMS_FIELDNAMES:
                out_row[key] = row.get(key, "")
            writer.writerow(out_row)

    filename = f"batch_missing_items_registration_{batch_timestamp}.csv"
    if output_dir.resolve() == ITEMS_IMPORT_UNREGISTERED_ROOT.resolve():
        return write_storage_bytes(
            bucket=ITEMS_UNREGISTERED_BUCKET,
            filename=filename,
            content=output.getvalue().encode("utf-8"),
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    target_path = output_dir / filename
    with target_path.open("w", encoding="utf-8", newline="") as fp:
        fp.write(output.getvalue())
    return _stored_object_from_path(target_path)
def _target_path_preserve_name(dst_dir: Path, filename: str) -> Path:
    dst_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(filename).name or "items_import.csv"
    target = dst_dir / safe_name
    if target.exists():
        stem = target.stem
        suffix = target.suffix
        idx = 1
        while True:
            candidate = dst_dir / f"{stem}_{idx}{suffix}"
            if not candidate.exists():
                return candidate
            idx += 1
    return target


def _move_file_preserve_name(src: Path, dst_dir: Path) -> Path:
    target = _target_path_preserve_name(dst_dir, src.name)
    shutil.move(str(src), str(target))
    return target


def _move_file_to_target(src: Path, target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(target))
    return target


def _write_bytes_preserve_name(content: bytes, dst_dir: Path, filename: str) -> Path:
    target = _target_path_preserve_name(dst_dir, filename)
    temp_path = dst_dir / f".tmp_{target.name}.{uuid4().hex}"
    try:
        temp_path.write_bytes(content)
        temp_path.replace(target)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
    return target


def _archive_imported_items_csv(
    content: bytes,
    *,
    source_name: str = "items_import.csv",
    registered_root: str | Path | None = None,
    unregistered_root: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(registered_root) if registered_root else ITEMS_IMPORT_REGISTERED_ROOT
    unreg_root = Path(unregistered_root) if unregistered_root else ITEMS_IMPORT_UNREGISTERED_ROOT

    month_subdir = today_jst()[:7]
    if root.resolve() == ITEMS_IMPORT_REGISTERED_ROOT.resolve():
        archived = write_storage_bytes(
            bucket=ITEMS_REGISTERED_ARCHIVES_BUCKET,
            subdir=month_subdir,
            filename=source_name,
            content=content,
        )
    else:
        month_dir = root / month_subdir
        archived_path = _write_bytes_preserve_name(content, month_dir, source_name)
        archived = _stored_object_from_path(archived_path)

    cleanup_file = None
    safe_name = Path(source_name).name
    if safe_name:
        potential_unreg_file = unreg_root / safe_name
        if potential_unreg_file.is_file():
            cleanup_file = str(potential_unreg_file)

    return {
        "archive_storage_ref": archived.storage_ref,
        "archived_filename": archived.filename,
        "consolidation": _disabled_items_archive_rollup_result(),
        "cleanup_unreg_file": cleanup_file,
    }


def _execute_planned_file_moves(planned_moves: list[tuple[Path, Path]]) -> None:
    applied_moves: list[tuple[Path, Path]] = []
    try:
        for src, target in planned_moves:
            src_path = src.resolve()
            target_path = target.resolve()
            if str(src_path).casefold() == str(target_path).casefold():
                continue
            if not src_path.exists():
                raise AppError(
                    code="FILE_MOVE_FAILED",
                    message=f"Source file does not exist: {src_path}",
                    status_code=500,
                )
            moved_to = _move_file_to_target(src_path, target_path)
            applied_moves.append((moved_to.resolve(), src_path))
    except Exception as exc:  # noqa: BLE001
        rollback_errors: list[str] = []
        for moved_to, original_src in reversed(applied_moves):
            try:
                if moved_to.exists():
                    _move_file_to_target(moved_to, original_src)
            except Exception as rollback_exc:  # noqa: BLE001
                rollback_errors.append(f"{moved_to} -> {original_src}: {rollback_exc}")
        detail = f"Failed to move import files: {exc}"
        if rollback_errors:
            detail += f" (rollback issues: {'; '.join(rollback_errors)})"
        raise AppError(
            code="FILE_MOVE_FAILED",
            message=detail,
            status_code=500,
        ) from exc


def _supplier_name_from_unregistered_path(csv_path: Path, roots: OrderImportRoots) -> tuple[str, list[str]]:
    return supplier_from_unregistered_csv_path(csv_path, roots=roots)


def _supplier_name_from_registered_path(csv_path: Path, roots: OrderImportRoots) -> tuple[str, list[str]]:
    resolved_csv = csv_path.resolve()
    resolved_registered_csv_root = roots.registered_csv_root.resolve()
    try:
        relative = resolved_csv.relative_to(resolved_registered_csv_root)
    except ValueError as exc:
        raise AppError(
            code="INVALID_REGISTERED_PATH",
            message=f"{resolved_csv} is not under {resolved_registered_csv_root}",
            status_code=422,
        ) from exc
    if len(relative.parts) < 2:
        raise AppError(
            code="INVALID_REGISTERED_LAYOUT",
            message=(
                "CSV must be placed under "
                "<registered>/csv_files/<supplier>/<file>.csv: "
                f"{resolved_csv}"
            ),
            status_code=422,
        )
    return relative.parts[0], []


def list_items(
    conn: sqlite3.Connection,
    *,
    q: str | None = None,
    category: str | None = None,
    manufacturer: str | None = None,
    page: int = 1,
    per_page: int = 50,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    search_terms = _split_search_terms(q)
    _append_search_term_clauses(
        clauses,
        params,
        terms=search_terms,
        expressions=["im.item_number", "im.description", "im.category", "m.name"],
    )
    if category:
        clauses.append("COALESCE(ca.canonical_category, im.category) = ?")
        params.append(category)
    if manufacturer:
        clauses.append("m.name = ?")
        params.append(manufacturer)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"""
        SELECT
            im.item_id,
            im.item_number,
            im.category AS raw_category,
            COALESCE(ca.canonical_category, im.category) AS category,
            im.url,
            im.description,
            im.source_system,
            im.external_item_id,
            (im.source_system = 'local') AS is_locally_managed,
            m.manufacturer_id,
            m.name AS manufacturer_name
        FROM items_master im
        JOIN manufacturers m ON m.manufacturer_id = im.manufacturer_id
        LEFT JOIN category_aliases ca ON ca.alias_category = im.category
        {where}
        ORDER BY im.item_number, im.item_id
    """
    return _paginate(conn, sql, tuple(params), page, per_page)


def get_item(conn: sqlite3.Connection, item_id: int) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT
            im.item_id,
            im.item_number,
            im.category AS raw_category,
            COALESCE(ca.canonical_category, im.category) AS category,
            im.url,
            im.description,
            im.source_system,
            im.external_item_id,
            (im.source_system = 'local') AS is_locally_managed,
            m.manufacturer_id,
            m.name AS manufacturer_name
        FROM items_master im
        JOIN manufacturers m ON m.manufacturer_id = im.manufacturer_id
        LEFT JOIN category_aliases ca ON ca.alias_category = im.category
        WHERE im.item_id = ?
        """,
        (item_id,),
    ).fetchone()
    if row is None:
        raise AppError(
            code="ITEM_NOT_FOUND",
            message=f"Item with id {item_id} not found",
            status_code=404,
        )
    return dict(row)


def _order_read_select_columns() -> str:
    return """
            o.*,
            o.source_system,
            o.external_order_id,
            (o.source_system = 'local') AS is_locally_managed,
            los.root_order_id AS split_root_order_id,
            los.split_type,
            los.reconciliation_mode AS split_reconciliation_mode,
            los.is_manual_override AS split_is_manual_override,
            los.manual_override_fields AS split_manual_override_fields,
            los.last_manual_override_at AS split_last_manual_override_at,
            (los.split_id IS NOT NULL) AS is_split_child,
            im.item_number AS canonical_item_number,
            p.name AS project_name,
            q.quotation_number,
            q.issue_date,
            q.quotation_document_url,
            po.purchase_order_number,
            po.purchase_order_document_url,
            po.import_locked,
            s.supplier_id,
            s.name AS supplier_name
    """


def _order_read_joins() -> str:
    return """
        FROM orders o
        JOIN items_master im ON im.item_id = o.item_id
        JOIN purchase_orders po ON po.purchase_order_id = o.purchase_order_id
        JOIN suppliers s ON s.supplier_id = po.supplier_id
        LEFT JOIN quotations q ON q.quotation_id = o.quotation_id
        LEFT JOIN projects p ON p.project_id = o.project_id
        LEFT JOIN local_order_splits los ON los.child_order_id = o.order_id
    """


def create_item(conn: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    manufacturer_id = payload.get("manufacturer_id")
    manufacturer_name = payload.get("manufacturer_name")
    if manufacturer_id is None:
        if manufacturer_name:
            manufacturer_id = _get_or_create_manufacturer(conn, manufacturer_name)
        else:
            manufacturer_id = _get_or_create_manufacturer(conn, "UNKNOWN")
    else:
        _get_entity_or_404(
            conn,
            "manufacturers",
            "manufacturer_id",
            manufacturer_id,
            "MANUFACTURER_NOT_FOUND",
            f"Manufacturer with id {manufacturer_id} not found",
        )
    try:
        cur = conn.execute(
            """
            INSERT INTO items_master (
                item_number, manufacturer_id, category, url, description
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                require_non_empty(payload["item_number"], "item_number"),
                int(manufacturer_id),
                payload.get("category"),
                payload.get("url"),
                payload.get("description"),
            ),
        )
    except sqlite3.IntegrityError as exc:
        raise AppError(
            code="ITEM_ALREADY_EXISTS",
            message="Item already exists for this manufacturer and item_number",
            status_code=409,
        ) from exc
    return get_item(conn, int(cur.lastrowid))


def _normalize_item_import_row_type(row: dict[str, Any]) -> str:
    row_type_raw = (row.get("row_type") or row.get("resolution_type") or "item").strip().lower()
    return "item" if row_type_raw in {"", "item", "new_item"} else row_type_raw


def _normalize_items_import_overrides(
    row_overrides: dict[str | int, Any] | None,
) -> dict[int, dict[str, Any]]:
    normalized: dict[int, dict[str, Any]] = {}
    override_payload = _require_json_object(
        row_overrides,
        code="INVALID_ITEM_IMPORT_OVERRIDE",
        label="Item import row_overrides",
    )
    for raw_row_number, raw_override in override_payload.items():
        try:
            row_number = int(raw_row_number)
        except Exception as exc:  # noqa: BLE001
            raise AppError(
                code="INVALID_ITEM_IMPORT_OVERRIDE",
                message=f"Item import override row '{raw_row_number}' is not a valid integer",
                status_code=422,
            ) from exc
        if row_number < 2:
            raise AppError(
                code="INVALID_ITEM_IMPORT_OVERRIDE",
                message=f"Item import override row '{row_number}' must be >= 2",
                status_code=422,
            )
        if not isinstance(raw_override, dict):
            raise AppError(
                code="INVALID_ITEM_IMPORT_OVERRIDE",
                message=f"Item import override for row {row_number} must be an object",
                status_code=422,
            )
        override: dict[str, Any] = {}
        unexpected_fields = sorted(set(raw_override) - {"canonical_item_number", "units_per_order"})
        if unexpected_fields:
            raise AppError(
                code="INVALID_ITEM_IMPORT_OVERRIDE",
                message=(
                    f"Item import override for row {row_number} has unsupported field(s): "
                    f"{', '.join(unexpected_fields)}"
                ),
                status_code=422,
            )
        if "canonical_item_number" in raw_override:
            canonical_item_number = str(raw_override.get("canonical_item_number") or "").strip()
            if not canonical_item_number:
                raise AppError(
                    code="INVALID_ITEM_IMPORT_OVERRIDE",
                    message=f"canonical_item_number override must be a non-empty string (row {row_number})",
                    status_code=422,
                )
            override["canonical_item_number"] = canonical_item_number
        if "units_per_order" in raw_override:
            if raw_override.get("units_per_order") in (None, ""):
                raise AppError(
                    code="INVALID_ITEM_IMPORT_OVERRIDE",
                    message=f"units_per_order override must be an integer > 0 (row {row_number})",
                    status_code=422,
                )
            try:
                override["units_per_order"] = require_positive_int(
                    int(raw_override["units_per_order"]),
                    f"units_per_order override (row {row_number})",
                )
            except Exception as exc:  # noqa: BLE001
                raise AppError(
                    code="INVALID_ITEM_IMPORT_OVERRIDE",
                    message=f"units_per_order override must be an integer > 0 (row {row_number})",
                    status_code=422,
                ) from exc
        if not override:
            raise AppError(
                code="INVALID_ITEM_IMPORT_OVERRIDE",
                message=(
                    f"Item import override for row {row_number} must include "
                    "canonical_item_number or units_per_order"
                ),
                status_code=422,
            )
        normalized[row_number] = override
    return normalized


def _get_item_by_number_and_manufacturer(
    conn: sqlite3.Connection,
    *,
    item_number: str,
    manufacturer_name: str,
) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT
            im.item_id,
            im.item_number,
            COALESCE(ca.canonical_category, im.category) AS category,
            m.name AS manufacturer_name
        FROM items_master im
        JOIN manufacturers m ON m.manufacturer_id = im.manufacturer_id
        LEFT JOIN category_aliases ca ON ca.alias_category = im.category
        WHERE im.item_number = ? AND m.name = ?
        ORDER BY im.item_id
        """,
        (item_number, manufacturer_name),
    ).fetchone()
    return dict(row) if row is not None else None


def _load_item_preview_catalog_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
            im.item_id,
            im.item_number,
            COALESCE(ca.canonical_category, im.category) AS category,
            im.description,
            m.name AS manufacturer_name
        FROM items_master im
        JOIN manufacturers m ON m.manufacturer_id = im.manufacturer_id
        LEFT JOIN category_aliases ca ON ca.alias_category = im.category
        ORDER BY im.item_number, im.item_id
        """
    ).fetchall()
    return _rows_to_dict(rows)


def _build_item_catalog_summary_bits(item_row: dict[str, Any]) -> list[str]:
    summary_bits = [str(item_row["manufacturer_name"])]
    if item_row.get("category"):
        summary_bits.append(str(item_row["category"]))
    if item_row.get("description"):
        summary_bits.append(str(item_row["description"]))
    summary_bits.append(f"#{int(item_row['item_id'])}")
    return summary_bits


def _build_item_preview_match(
    item_row: dict[str, Any],
    *,
    match_source: str = "item_number",
    confidence_score: int | None = None,
    match_reason: str | None = None,
) -> dict[str, Any]:
    return {
        "entity_type": "item",
        "entity_id": int(item_row["item_id"]),
        "value_text": str(item_row["item_number"]),
        "display_label": f"{item_row['item_number']} ({item_row['manufacturer_name']}) #{int(item_row['item_id'])}",
        "summary": " | ".join(_build_item_catalog_summary_bits(item_row)),
        "match_source": match_source,
        "confidence_score": confidence_score,
        "match_reason": match_reason,
    }


def _rank_item_preview_candidates(
    item_rows: list[dict[str, Any]],
    raw_value: str,
    *,
    limit: int = ORDER_IMPORT_PREVIEW_CANDIDATE_LIMIT,
) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for item_row in item_rows:
        confidence_score, score_reason = _score_order_import_candidate(
            raw_value,
            str(item_row["item_number"]),
        )
        if confidence_score <= 0:
            continue
        ranked.append(
            _build_item_preview_match(
                item_row,
                match_source="item_number",
                confidence_score=confidence_score,
                match_reason=f"item_number_{score_reason}",
            )
        )
    ranked.sort(
        key=lambda entry: (
            -int(entry.get("confidence_score") or 0),
            str(entry["value_text"]).casefold(),
            int(entry["entity_id"]),
        )
    )
    return ranked[:limit]


def preview_items_import_from_rows(
    conn: sqlite3.Connection,
    *,
    rows: list[dict[str, str]],
    source_name: str = "items_import.csv",
) -> dict[str, Any]:
    processed_rows = [
        row
        for row in rows
        if any(str(value or "").strip() for value in row.values())
    ]
    item_catalog_rows = _load_item_preview_catalog_rows(conn)
    csv_item_numbers = {
        (row.get("item_number") or "").strip()
        for row in processed_rows
        if _normalize_item_import_row_type(row) == "item"
        and (row.get("item_number") or "").strip()
    }

    preview_rows: list[dict[str, Any]] = []
    summary = {
        "total_rows": 0,
        "exact": 0,
        "high_confidence": 0,
        "needs_review": 0,
        "unresolved": 0,
    }
    blocking_errors: list[str] = []

    for idx, raw_row in enumerate(rows, start=2):
        if not any(str(value or "").strip() for value in raw_row.values()):
            continue

        row = dict(raw_row)
        item_number = str(row.get("item_number") or "").strip()
        row_type = _normalize_item_import_row_type(row)
        raw_row_type = str(row.get("row_type") or row.get("resolution_type") or "item").strip().lower()
        base_preview = {
            "row": idx,
            "entry_type": row_type if row_type in {"item", "alias"} else raw_row_type or "item",
            "item_number": item_number,
            "manufacturer_name": (
                str(row.get("manufacturer_name") or row.get("manufacturer") or "UNKNOWN").strip()
                or "UNKNOWN"
            ),
            "supplier": str(row.get("supplier") or "").strip(),
            "canonical_item_number": str(row.get("canonical_item_number") or "").strip(),
            "units_per_order": str(row.get("units_per_order") or "").strip() or "1",
            "category": str(row.get("category") or "").strip(),
            "url": str(row.get("url") or "").strip(),
            "description": str(row.get("description") or "").strip(),
            "allowed_entity_types": [],
            "requires_user_selection": False,
            "blocking": False,
            "suggested_match": None,
            "candidates": [],
        }

        if row_type not in {"item", "alias"}:
            preview_row = {
                **base_preview,
                "status": "unresolved",
                "action": "invalid_row_type",
                "message": "row_type must be either 'item' or 'alias'",
                "blocking": True,
            }
            preview_rows.append(preview_row)
            summary["total_rows"] += 1
            summary["unresolved"] += 1
            blocking_errors.append(f"row {idx}: {preview_row['message']}")
            continue

        if row_type == "item":
            if not item_number:
                preview_row = {
                    **base_preview,
                    "status": "unresolved",
                    "action": "invalid_item",
                    "message": "item_number is required",
                    "blocking": True,
                }
            else:
                existing_item = _get_item_by_number_and_manufacturer(
                    conn,
                    item_number=item_number,
                    manufacturer_name=str(base_preview["manufacturer_name"]),
                )
                if existing_item is not None:
                    preview_row = {
                        **base_preview,
                        "status": "needs_review",
                        "action": "duplicate_item",
                        "message": "Item already exists; import will record this row as duplicate.",
                        "suggested_match": _build_item_preview_match(existing_item),
                    }
                else:
                    preview_row = {
                        **base_preview,
                        "status": "exact",
                        "action": "create_item",
                        "message": "Ready to create item.",
                    }
            preview_rows.append(preview_row)
            summary["total_rows"] += 1
            summary[str(preview_row["status"])] += 1
            if preview_row["blocking"]:
                blocking_errors.append(f"row {idx}: {preview_row['message']}")
            continue

        if not item_number:
            preview_row = {
                **base_preview,
                "status": "unresolved",
                "action": "invalid_alias",
                "message": "item_number is required for alias rows",
                "blocking": True,
            }
            preview_rows.append(preview_row)
            summary["total_rows"] += 1
            summary["unresolved"] += 1
            blocking_errors.append(f"row {idx}: {preview_row['message']}")
            continue

        if item_number in csv_item_numbers or _resolve_item_by_number(conn, item_number) is not None:
            preview_row = {
                **base_preview,
                "status": "unresolved",
                "action": "alias_conflict_direct_item",
                "message": (
                    f"ordered_item_number '{item_number}' matches an existing direct item_number; "
                    "alias would never be used"
                ),
                "blocking": True,
            }
            preview_rows.append(preview_row)
            summary["total_rows"] += 1
            summary["unresolved"] += 1
            blocking_errors.append(f"row {idx}: {preview_row['message']}")
            continue

        supplier_name = str(base_preview["supplier"])
        if not supplier_name:
            preview_row = {
                **base_preview,
                "status": "unresolved",
                "action": "invalid_alias",
                "message": "supplier is required for alias rows",
                "blocking": True,
            }
            preview_rows.append(preview_row)
            summary["total_rows"] += 1
            summary["unresolved"] += 1
            blocking_errors.append(f"row {idx}: {preview_row['message']}")
            continue

        try:
            units_per_order = require_positive_int(
                int(str(base_preview["units_per_order"]).strip() or "1"),
                "units_per_order",
            )
        except Exception as exc:  # noqa: BLE001
            preview_row = {
                **base_preview,
                "status": "unresolved",
                "action": "invalid_alias",
                "message": "units_per_order must be a positive integer",
                "blocking": True,
            }
            preview_rows.append(preview_row)
            summary["total_rows"] += 1
            summary["unresolved"] += 1
            blocking_errors.append(f"row {idx}: {preview_row['message']}")
            continue

        canonical_item_number = str(base_preview["canonical_item_number"])
        candidate_matches = _rank_item_preview_candidates(item_catalog_rows, canonical_item_number)
        suggested_match = candidate_matches[0] if candidate_matches else None
        canonical_item_id = _resolve_item_by_number(conn, canonical_item_number) if canonical_item_number else None

        if canonical_item_id is None and canonical_item_number and canonical_item_number in csv_item_numbers:
            preview_row = {
                **base_preview,
                "status": "exact",
                "action": "create_alias",
                "message": "Ready to create alias after canonical item rows in this CSV are inserted.",
            }
            preview_rows.append(preview_row)
            summary["total_rows"] += 1
            summary["exact"] += 1
            continue

        if canonical_item_id is not None:
            canonical_item_row = next(
                (item_row for item_row in item_catalog_rows if int(item_row["item_id"]) == canonical_item_id),
                None,
            )
            resolved_match = (
                _build_item_preview_match(canonical_item_row)
                if canonical_item_row is not None
                else None
            )
            supplier_id = _find_supplier_id_by_name(conn, supplier_name)
            existing_alias = (
                _alias_row_by_supplier_and_ordered(
                    conn,
                    supplier_id=supplier_id,
                    ordered_item_number=item_number,
                )
                if supplier_id is not None
                else None
            )
            if existing_alias is None:
                preview_row = {
                    **base_preview,
                    "status": "exact",
                    "action": "create_alias",
                    "message": "Ready to create alias mapping.",
                    "suggested_match": resolved_match,
                    "units_per_order": str(units_per_order),
                }
            elif (
                str(existing_alias["canonical_item_number"]) == canonical_item_number
                and int(existing_alias["units_per_order"]) == units_per_order
            ):
                preview_row = {
                    **base_preview,
                    "status": "exact",
                    "action": "alias_no_change",
                    "message": "Alias already matches the current mapping.",
                    "suggested_match": resolved_match,
                    "units_per_order": str(units_per_order),
                }
            else:
                preview_row = {
                    **base_preview,
                    "status": "needs_review",
                    "action": "update_alias",
                    "message": "Alias already exists and will be updated by this import.",
                    "suggested_match": resolved_match,
                    "units_per_order": str(units_per_order),
                }
            preview_rows.append(preview_row)
            summary["total_rows"] += 1
            summary[str(preview_row["status"])] += 1
            continue

        preview_status = _classify_ranked_preview_status(
            confidence_score=int(suggested_match["confidence_score"]) if suggested_match else None,
            match_reason=str(suggested_match["match_reason"]) if suggested_match else None,
        )
        preview_row = {
            **base_preview,
            "status": preview_status,
            "action": "resolve_alias_canonical_item",
            "message": (
                "Select the canonical item for this alias row."
                if canonical_item_number
                else "canonical_item_number is required for alias rows"
            ),
            "blocking": True,
            "requires_user_selection": True,
            "allowed_entity_types": ["item"],
            "suggested_match": suggested_match,
            "candidates": candidate_matches,
            "units_per_order": str(units_per_order),
        }
        preview_rows.append(preview_row)
        summary["total_rows"] += 1
        summary[str(preview_status)] += 1
        blocking_errors.append(f"row {idx}: {preview_row['message']}")

    return {
        "source_name": source_name,
        "summary": summary,
        "blocking_errors": blocking_errors,
        "can_auto_accept": summary["needs_review"] == 0 and summary["unresolved"] == 0,
        "rows": preview_rows,
    }


def import_items_from_rows(
    conn: sqlite3.Connection,
    *,
    rows: list[dict[str, str]],
    continue_on_error: bool = True,
    import_job_id: int | None = None,
    row_overrides: dict[str | int, Any] | None = None,
) -> dict[str, Any]:
    processed = 0
    created_count = 0
    duplicate_count = 0
    failed_count = 0
    report: list[dict[str, Any]] = []
    deferred_aliases: list[dict[str, Any]] = []
    normalized_overrides = _normalize_items_import_overrides(row_overrides)
    _validate_import_override_rows(
        normalized_overrides,
        valid_row_numbers=_valid_csv_row_numbers(rows, skip_blank_rows=True),
        code="INVALID_ITEM_IMPORT_OVERRIDE",
        label="Item import row_overrides",
    )

    csv_item_numbers = {
        (row.get("item_number") or "").strip()
        for row in rows
        if _csv_row_has_content(row)
        and _normalize_item_import_row_type(row) == "item"
        and (row.get("item_number") or "").strip()
    }

    for idx, raw_row in enumerate(rows, start=2):
        if not any(str(value or "").strip() for value in raw_row.values()):
            continue
        processed += 1
        row = dict(raw_row)
        override = normalized_overrides.get(idx, {})
        if override.get("canonical_item_number"):
            row["canonical_item_number"] = str(override["canonical_item_number"])
        if override.get("units_per_order") is not None:
            row["units_per_order"] = str(int(override["units_per_order"]))

        item_number = (row.get("item_number") or "").strip()
        row_type = _normalize_item_import_row_type(row)

        if row_type not in {"item", "alias"}:
            failed_count += 1
            error_row = {
                "row": idx,
                "status": "error",
                "item_number": item_number or None,
                "error": "row_type must be either 'item' or 'alias'",
                "code": "INVALID_ROW_TYPE",
            }
            report.append(error_row)
            if import_job_id is not None:
                _record_import_job_effect(
                    conn,
                    import_job_id=import_job_id,
                    row_number=idx,
                    status="error",
                    entry_type=None,
                    effect_type="invalid_row_type",
                    item_number=item_number or None,
                    message=error_row["error"],
                    code=error_row["code"],
                )
            if not continue_on_error:
                break
            continue

        try:
            if row_type == "item":
                manufacturer_name = (
                    (row.get("manufacturer_name") or row.get("manufacturer") or "UNKNOWN").strip()
                    or "UNKNOWN"
                )
                payload = {
                    "item_number": item_number,
                    "manufacturer_name": manufacturer_name,
                    "category": (row.get("category") or "").strip() or None,
                    "url": (row.get("url") or "").strip() or None,
                    "description": (row.get("description") or "").strip() or None,
                }
                if not item_number:
                    raise AppError(
                        code="INVALID_ITEM_NUMBER",
                        message="item_number is required",
                        status_code=422,
                    )
                item = create_item(conn, payload)
                created_count += 1
                created_row = {
                    "row": idx,
                    "status": "created",
                    "item_id": item["item_id"],
                    "item_number": item["item_number"],
                    "entry_type": "item",
                }
                report.append(created_row)
                if import_job_id is not None:
                    _record_import_job_effect(
                        conn,
                        import_job_id=import_job_id,
                        row_number=idx,
                        status="created",
                        entry_type="item",
                        effect_type="item_created",
                        item_id=int(item["item_id"]),
                        item_number=item["item_number"],
                        after_state={
                            "item_id": int(item["item_id"]),
                            "item_number": item["item_number"],
                            "manufacturer_id": int(item["manufacturer_id"]),
                            "category": item.get("category"),
                            "url": item.get("url"),
                            "description": item.get("description"),
                        },
                    )
            else:
                if not item_number:
                    raise AppError(
                        code="INVALID_ALIAS",
                        message="item_number is required for alias rows",
                        status_code=422,
                    )
                if item_number in csv_item_numbers or _resolve_item_by_number(conn, item_number) is not None:
                    raise AppError(
                        code="ALIAS_CONFLICT_DIRECT_ITEM",
                        message=(
                            f"ordered_item_number '{item_number}' matches an existing direct item_number; "
                            "alias would never be used"
                        ),
                        status_code=409,
                    )
                supplier_name = require_non_empty(str(row.get("supplier", "")), "supplier")
                canonical_item_number = require_non_empty(
                    str(row.get("canonical_item_number", "")),
                    "canonical_item_number",
                )
                units_raw = str(row.get("units_per_order") or "").strip()
                units_per_order = require_positive_int(int(units_raw), "units_per_order") if units_raw else 1
                canonical_exists = _resolve_item_by_number(conn, canonical_item_number) is not None
                canonical_in_csv = canonical_item_number in csv_item_numbers
                if not canonical_exists and not canonical_in_csv:
                    raise AppError(
                        code="ITEM_NOT_FOUND",
                        message=f"Canonical item '{canonical_item_number}' not found",
                        status_code=404,
                    )
                deferred_aliases.append(
                    {
                        "row": idx,
                        "item_number": item_number,
                        "supplier_name": supplier_name,
                        "canonical_item_number": canonical_item_number,
                        "units_per_order": units_per_order,
                    }
                )
        except AppError as exc:
            if exc.code == "ITEM_ALREADY_EXISTS":
                duplicate_count += 1
                duplicate_row = {
                    "row": idx,
                    "status": "duplicate",
                    "item_number": item_number,
                    "error": exc.message,
                }
                report.append(duplicate_row)
                if import_job_id is not None:
                    _record_import_job_effect(
                        conn,
                        import_job_id=import_job_id,
                        row_number=idx,
                        status="duplicate",
                        entry_type="item",
                        effect_type="item_duplicate",
                        item_number=item_number or None,
                        message=exc.message,
                        code=exc.code,
                    )
            else:
                failed_count += 1
                error_row = {
                    "row": idx,
                    "status": "error",
                    "item_number": item_number or None,
                    "error": exc.message,
                    "code": exc.code,
                }
                report.append(error_row)
                if import_job_id is not None:
                    _record_import_job_effect(
                        conn,
                        import_job_id=import_job_id,
                        row_number=idx,
                        status="error",
                        entry_type=row_type if row_type in {"item", "alias"} else None,
                        effect_type=f"{row_type}_error" if row_type in {"item", "alias"} else "import_row_error",
                        item_number=item_number or None,
                        message=exc.message,
                        code=exc.code,
                    )
            if not continue_on_error:
                break
        except Exception as exc:  # noqa: BLE001
            failed_count += 1
            error_row = {
                "row": idx,
                "status": "error",
                "item_number": item_number or None,
                "error": str(exc),
            }
            report.append(error_row)
            if import_job_id is not None:
                _record_import_job_effect(
                    conn,
                    import_job_id=import_job_id,
                    row_number=idx,
                    status="error",
                    entry_type=row_type if row_type in {"item", "alias"} else None,
                    effect_type="import_row_exception",
                    item_number=item_number or None,
                    message=error_row["error"],
                )
            if not continue_on_error:
                break

    for alias_row in deferred_aliases:
        try:
            supplier_name = str(alias_row["supplier_name"])
            supplier_id = _get_or_create_supplier(conn, supplier_name)
            before_alias = _alias_row_by_supplier_and_ordered(
                conn,
                supplier_id=supplier_id,
                ordered_item_number=str(alias_row["item_number"]),
            )
            alias = upsert_supplier_item_alias(
                conn,
                supplier_id=supplier_id,
                ordered_item_number=str(alias_row["item_number"]),
                canonical_item_number=str(alias_row["canonical_item_number"]),
                units_per_order=int(alias_row["units_per_order"]),
            )
            created_count += 1
            created_row = {
                "row": alias_row["row"],
                "status": "created",
                "item_number": alias_row["item_number"],
                "entry_type": "alias",
                "supplier": supplier_name,
                "canonical_item_number": alias["canonical_item_number"],
                "units_per_order": alias["units_per_order"],
            }
            report.append(created_row)
            if import_job_id is not None:
                effect_type = "alias_updated" if before_alias is not None else "alias_created"
                _record_import_job_effect(
                    conn,
                    import_job_id=import_job_id,
                    row_number=int(alias_row["row"]),
                    status="created",
                    entry_type="alias",
                    effect_type=effect_type,
                    item_number=str(alias_row["item_number"]),
                    supplier_id=int(alias["supplier_id"]),
                    supplier_name=supplier_name,
                    alias_id=int(alias["alias_id"]),
                    canonical_item_number=alias["canonical_item_number"],
                    units_per_order=int(alias["units_per_order"]),
                    before_state=before_alias,
                    after_state=alias,
                )
        except AppError as exc:
            failed_count += 1
            error_row = {
                "row": alias_row["row"],
                "status": "error",
                "item_number": alias_row["item_number"] or None,
                "error": exc.message,
                "code": exc.code,
            }
            report.append(error_row)
            if import_job_id is not None:
                _record_import_job_effect(
                    conn,
                    import_job_id=import_job_id,
                    row_number=int(alias_row["row"]),
                    status="error",
                    entry_type="alias",
                    effect_type="alias_error",
                    item_number=str(alias_row["item_number"]),
                    supplier_name=str(alias_row["supplier_name"]),
                    canonical_item_number=str(alias_row["canonical_item_number"]),
                    units_per_order=int(alias_row["units_per_order"]),
                    message=exc.message,
                    code=exc.code,
                )
            if not continue_on_error:
                break
        except Exception as exc:  # noqa: BLE001
            failed_count += 1
            error_row = {
                "row": alias_row["row"],
                "status": "error",
                "item_number": alias_row["item_number"] or None,
                "error": str(exc),
            }
            report.append(error_row)
            if import_job_id is not None:
                _record_import_job_effect(
                    conn,
                    import_job_id=import_job_id,
                    row_number=int(alias_row["row"]),
                    status="error",
                    entry_type="alias",
                    effect_type="alias_exception",
                    item_number=str(alias_row["item_number"]),
                    supplier_name=str(alias_row["supplier_name"]),
                    canonical_item_number=str(alias_row["canonical_item_number"]),
                    units_per_order=int(alias_row["units_per_order"]),
                    message=error_row["error"],
                )
            if not continue_on_error:
                break

    report.sort(key=lambda row: int(row.get("row", 0)))
    status = "ok" if failed_count == 0 else ("partial" if (created_count or duplicate_count) else "error")
    return {
        "status": status,
        "processed": processed,
        "created_count": created_count,
        "duplicate_count": duplicate_count,
        "failed_count": failed_count,
        "rows": report,
    }


def import_items_from_content(
    conn: sqlite3.Connection,
    *,
    content: bytes,
    continue_on_error: bool = True,
    row_overrides: dict[str | int, Any] | None = None,
) -> dict[str, Any]:
    rows = _load_csv_rows_from_content(content)
    return import_items_from_rows(
        conn,
        rows=rows,
        continue_on_error=continue_on_error,
        row_overrides=row_overrides,
    )


def import_items_from_csv_path(
    conn: sqlite3.Connection,
    *,
    csv_path: str | Path,
    continue_on_error: bool = True,
) -> dict[str, Any]:
    rows = _load_csv_rows_from_path(csv_path)
    return import_items_from_rows(
        conn,
        rows=rows,
        continue_on_error=continue_on_error,
    )


def import_items_from_content_with_job(
    conn: sqlite3.Connection,
    *,
    content: bytes,
    source_name: str = "items_import.csv",
    continue_on_error: bool = True,
    redo_of_job_id: int | None = None,
    row_overrides: dict[str | int, Any] | None = None,
    archive_registered_csv: bool = True,
) -> dict[str, Any]:
    source_text = _read_import_job_source_text(content)
    import_job_id = _record_import_job(
        conn,
        import_type="items",
        source_name=source_name,
        source_content=source_text,
        continue_on_error=continue_on_error,
        redo_of_job_id=redo_of_job_id,
        request_metadata={"row_overrides": row_overrides or None},
    )
    conn.execute("SAVEPOINT item_import_job")
    try:
        rows = _load_csv_rows_from_content(content)
        result = import_items_from_rows(
            conn,
            rows=rows,
            continue_on_error=continue_on_error,
            import_job_id=import_job_id,
            row_overrides=row_overrides,
        )
    except Exception:
        conn.execute("ROLLBACK TO SAVEPOINT item_import_job")
        conn.execute("RELEASE SAVEPOINT item_import_job")
        _finalize_import_job(
            conn,
            import_job_id=import_job_id,
            result={"status": "error", "processed": 0, "created_count": 0, "duplicate_count": 0, "failed_count": 1},
        )
        raise
    conn.execute("RELEASE SAVEPOINT item_import_job")
    _finalize_import_job(conn, import_job_id=import_job_id, result=result)
    payload = {**result, "import_job_id": import_job_id}
    if archive_registered_csv and result["status"] != "error":
        payload["archive_requested"] = True
    return payload


def preview_items_import_from_content(
    conn: sqlite3.Connection,
    *,
    content: bytes,
    source_name: str = "items_import.csv",
) -> dict[str, Any]:
    rows = _load_csv_rows_from_content(content)
    return preview_items_import_from_rows(
        conn,
        rows=rows,
        source_name=source_name,
    )


def _get_items_import_job_row(conn: sqlite3.Connection, import_job_id: int) -> sqlite3.Row:
    row = conn.execute(
        """
        SELECT
            import_job_id,
            import_type,
            source_name,
            source_content,
            request_metadata,
            continue_on_error,
            status,
            processed,
            created_count,
            duplicate_count,
            failed_count,
            lifecycle_state,
            created_at,
            undone_at,
            redo_of_job_id,
            last_redo_job_id
        FROM import_jobs
        WHERE import_job_id = ? AND import_type = 'items'
        """,
        (import_job_id,),
    ).fetchone()
    if row is None:
        raise AppError(
            code="IMPORT_JOB_NOT_FOUND",
            message=f"Items import job {import_job_id} not found",
            status_code=404,
        )
    return row


def list_items_import_jobs(
    conn: sqlite3.Connection,
    *,
    page: int = 1,
    per_page: int = 50,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    sql = """
        SELECT
            import_job_id,
            import_type,
            source_name,
            request_metadata,
            continue_on_error,
            status,
            processed,
            created_count,
            duplicate_count,
            failed_count,
            lifecycle_state,
            created_at,
            undone_at,
            redo_of_job_id,
            last_redo_job_id
        FROM import_jobs
        WHERE import_type = 'items'
        ORDER BY created_at DESC, import_job_id DESC
    """
    rows, pagination = _paginate(conn, sql, tuple(), page, per_page)
    normalized = []
    for row in rows:
        row["continue_on_error"] = bool(row.get("continue_on_error"))
        normalized.append(row)
    return normalized, pagination


def get_items_import_job(conn: sqlite3.Connection, import_job_id: int) -> dict[str, Any]:
    job = _normalize_import_job_row(_get_items_import_job_row(conn, import_job_id))
    effects = conn.execute(
        """
        SELECT
            effect_id,
            import_job_id,
            row_number,
            status,
            entry_type,
            effect_type,
            item_id,
            alias_id,
            supplier_id,
            item_number,
            supplier_name,
            canonical_item_number,
            units_per_order,
            message,
            code,
            before_state,
            after_state,
            created_at
        FROM import_job_effects
        WHERE import_job_id = ?
        ORDER BY row_number, effect_id
        """,
        (import_job_id,),
    ).fetchall()
    return {
        "job": job,
        "effects": [_normalize_import_job_effect_row(row) for row in effects],
    }


def undo_items_import_job(conn: sqlite3.Connection, import_job_id: int) -> dict[str, Any]:
    job_row = _get_items_import_job_row(conn, import_job_id)
    job = _normalize_import_job_row(job_row)
    if job["lifecycle_state"] == "undone":
        raise AppError(
            code="IMPORT_JOB_ALREADY_UNDONE",
            message=f"Items import job {import_job_id} has already been undone",
            status_code=409,
        )

    effects = conn.execute(
        """
        SELECT
            effect_id,
            row_number,
            status,
            entry_type,
            effect_type,
            item_id,
            alias_id,
            supplier_id,
            item_number,
            supplier_name,
            canonical_item_number,
            units_per_order,
            message,
            code,
            before_state,
            after_state
        FROM import_job_effects
        WHERE import_job_id = ? AND status = 'created'
        ORDER BY effect_id DESC
        """,
        (import_job_id,),
    ).fetchall()
    effect_rows = [_normalize_import_job_effect_row(row) for row in effects]
    alias_effects = [row for row in effect_rows if row["effect_type"] in {"alias_created", "alias_updated"}]
    item_effects = [row for row in effect_rows if row["effect_type"] == "item_created"]

    savepoint = f"sp_undo_items_import_{uuid4().hex}"
    conn.execute(f"SAVEPOINT {savepoint}")
    undone_aliases = 0
    restored_aliases = 0
    undone_items = 0
    try:
        for effect in alias_effects:
            effect_id = int(effect["effect_id"])
            row_number = int(effect["row_number"])
            effect_type = str(effect["effect_type"])
            after_state = effect.get("after_state")
            if not isinstance(after_state, dict):
                _raise_import_undo_conflict(
                    "Missing alias after_state snapshot for undo",
                    effect_id=effect_id,
                    row_number=row_number,
                )
            supplier_id = int(after_state["supplier_id"])
            ordered_item_number = str(after_state["ordered_item_number"])
            current_alias = _alias_row_by_supplier_and_ordered(
                conn,
                supplier_id=supplier_id,
                ordered_item_number=ordered_item_number,
            )
            if effect_type == "alias_created":
                if not _import_job_matches_state(
                    current_alias,
                    after_state,
                    (
                        "alias_id",
                        "supplier_id",
                        "ordered_item_number",
                        "canonical_item_id",
                        "units_per_order",
                    ),
                ):
                    _raise_import_undo_conflict(
                        (
                            "Alias no longer matches imported state; "
                            f"cannot safely undo row {row_number}"
                        ),
                        effect_id=effect_id,
                        row_number=row_number,
                    )
                delete_supplier_item_alias(conn, int(current_alias["alias_id"]))
                undone_aliases += 1
                continue

            if effect_type == "alias_updated":
                before_state = effect.get("before_state")
                if not isinstance(before_state, dict):
                    _raise_import_undo_conflict(
                        "Missing alias before_state snapshot for undo",
                        effect_id=effect_id,
                        row_number=row_number,
                    )
                if not _import_job_matches_state(
                    current_alias,
                    after_state,
                    (
                        "alias_id",
                        "supplier_id",
                        "ordered_item_number",
                        "canonical_item_id",
                        "units_per_order",
                    ),
                ):
                    _raise_import_undo_conflict(
                        (
                            "Alias was modified after import; "
                            f"cannot safely undo row {row_number}"
                        ),
                        effect_id=effect_id,
                        row_number=row_number,
                    )
                upsert_supplier_item_alias(
                    conn,
                    supplier_id=int(before_state["supplier_id"]),
                    ordered_item_number=str(before_state["ordered_item_number"]),
                    canonical_item_id=int(before_state["canonical_item_id"]),
                    units_per_order=int(before_state["units_per_order"]),
                )
                restored_aliases += 1
                continue

        for effect in item_effects:
            effect_id = int(effect["effect_id"])
            row_number = int(effect["row_number"])
            after_state = effect.get("after_state")
            if not isinstance(after_state, dict):
                _raise_import_undo_conflict(
                    "Missing item after_state snapshot for undo",
                    effect_id=effect_id,
                    row_number=row_number,
                )
            item_id = int(after_state["item_id"])
            current_item_row = conn.execute(
                """
                SELECT item_id, item_number, manufacturer_id, category, url, description
                FROM items_master
                WHERE item_id = ?
                """,
                (item_id,),
            ).fetchone()
            current_item = dict(current_item_row) if current_item_row is not None else None
            if not _import_job_matches_state(
                current_item,
                after_state,
                ("item_id", "item_number", "manufacturer_id", "category", "url", "description"),
            ):
                _raise_import_undo_conflict(
                    (
                        "Item was modified after import; "
                        f"cannot safely undo row {row_number}"
                    ),
                    effect_id=effect_id,
                    row_number=row_number,
                )
            delete_item(conn, item_id)
            undone_items += 1

        undone_at = now_jst_iso()
        conn.execute(
            """
            UPDATE import_jobs
            SET lifecycle_state = 'undone', undone_at = ?
            WHERE import_job_id = ?
            """,
            (undone_at, import_job_id),
        )
        conn.execute(f"RELEASE {savepoint}")
        return {
            "import_job_id": import_job_id,
            "status": "undone",
            "undone_at": undone_at,
            "removed_aliases": undone_aliases,
            "restored_aliases": restored_aliases,
            "removed_items": undone_items,
        }
    except Exception:
        conn.execute(f"ROLLBACK TO {savepoint}")
        conn.execute(f"RELEASE {savepoint}")
        raise


def redo_items_import_job(conn: sqlite3.Connection, import_job_id: int) -> dict[str, Any]:
    job_row = _get_items_import_job_row(conn, import_job_id)
    job = _normalize_import_job_row(job_row)
    if job["lifecycle_state"] != "undone":
        raise AppError(
            code="IMPORT_JOB_REDO_REQUIRES_UNDONE",
            message=f"Items import job {import_job_id} must be undone before redo",
            status_code=409,
        )
    source_text = str(job_row["source_content"] or "")
    if not source_text:
        raise AppError(
            code="IMPORT_JOB_SOURCE_MISSING",
            message=f"Items import job {import_job_id} does not have source content to redo",
            status_code=422,
        )

    request_metadata = job.get("request_metadata") or {}
    result = import_items_from_content_with_job(
        conn,
        content=source_text.encode("utf-8"),
        source_name=str(job_row["source_name"]),
        continue_on_error=bool(job["continue_on_error"]),
        redo_of_job_id=import_job_id,
        row_overrides=request_metadata.get("row_overrides"),
        archive_registered_csv=False,
    )
    redo_job_id = int(result["import_job_id"])
    conn.execute(
        "UPDATE import_jobs SET last_redo_job_id = ? WHERE import_job_id = ?",
        (redo_job_id, import_job_id),
    )
    return {
        "source_job_id": import_job_id,
        "redo_job_id": redo_job_id,
        "import_result": result,
    }


def update_item(conn: sqlite3.Connection, item_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    current = get_item(conn, item_id)
    _assert_item_is_locally_managed(current)
    updates: list[str] = []
    params: list[Any] = []
    resolved_item_number = current["item_number"]
    resolved_manufacturer_id = int(current["manufacturer_id"])
    pending_manufacturer_name: str | None = None
    manufacturer_changed = False
    item_number_changed = False

    if "item_number" in payload and payload["item_number"] is not None:
        resolved_item_number = require_non_empty(payload["item_number"], "item_number")
        item_number_changed = resolved_item_number != current["item_number"]

    if payload.get("manufacturer_id") is not None:
        mid = int(payload["manufacturer_id"])
        _get_entity_or_404(
            conn,
            "manufacturers",
            "manufacturer_id",
            mid,
            "MANUFACTURER_NOT_FOUND",
            f"Manufacturer with id {mid} not found",
        )
        resolved_manufacturer_id = mid
        manufacturer_changed = resolved_manufacturer_id != int(current["manufacturer_id"])
    elif payload.get("manufacturer_name"):
        normalized = require_non_empty(payload["manufacturer_name"], "manufacturer_name")
        if normalized != current["manufacturer_name"]:
            existing = conn.execute(
                "SELECT manufacturer_id FROM manufacturers WHERE name = ?",
                (normalized,),
            ).fetchone()
            if existing is None:
                pending_manufacturer_name = normalized
                resolved_manufacturer_id = -1
            else:
                resolved_manufacturer_id = int(existing["manufacturer_id"])
            manufacturer_changed = True

    identity_changed = item_number_changed or manufacturer_changed
    if identity_changed:
        ref = _first_item_reference(conn, item_id)
        if ref is not None:
            raise AppError(
                code="ITEM_REFERENCED_IMMUTABLE",
                message=f"Item identity cannot be changed because it is referenced by {ref}",
                status_code=409,
            )

    if item_number_changed:
        updates.append("item_number = ?")
        params.append(resolved_item_number)
    if manufacturer_changed:
        if pending_manufacturer_name is not None:
            resolved_manufacturer_id = _get_or_create_manufacturer(conn, pending_manufacturer_name)
        updates.append("manufacturer_id = ?")
        params.append(resolved_manufacturer_id)

    for key in ("category", "url", "description"):
        if key in payload:
            updates.append(f"{key} = ?")
            params.append(payload.get(key))
    if updates:
        try:
            conn.execute(
                f"UPDATE items_master SET {', '.join(updates)} WHERE item_id = ?",
                (*params, item_id),
            )
        except sqlite3.IntegrityError as exc:
            raise AppError(
                code="ITEM_ALREADY_EXISTS",
                message="Item already exists for this manufacturer and item_number",
                status_code=409,
            ) from exc
    return get_item(conn, item_id)


def bulk_update_item_metadata(
    conn: sqlite3.Connection,
    *,
    rows: list[dict[str, Any]],
    continue_on_error: bool = True,
) -> dict[str, Any]:
    processed = 0
    updated_count = 0
    failed_count = 0
    report: list[dict[str, Any]] = []

    for idx, row in enumerate(rows, start=1):
        processed += 1
        item_id = int(row["item_id"])
        payload: dict[str, Any] = {}
        for key in ("category", "url", "description"):
            if key not in row:
                continue
            value = row.get(key)
            if isinstance(value, str):
                value = value.strip()
            payload[key] = value if value != "" else None
        if not payload:
            failed_count += 1
            report.append(
                {
                    "row": idx,
                    "status": "error",
                    "item_id": item_id,
                    "code": "INVALID_METADATA_UPDATE",
                    "error": "at least one metadata field is required",
                }
            )
            if not continue_on_error:
                break
            continue

        try:
            updated = update_item(conn, item_id, payload)
            updated_count += 1
            report.append(
                {
                    "row": idx,
                    "status": "updated",
                    "item_id": item_id,
                    "item_number": updated["item_number"],
                }
            )
        except AppError as exc:
            failed_count += 1
            report.append(
                {
                    "row": idx,
                    "status": "error",
                    "item_id": item_id,
                    "code": exc.code,
                    "error": exc.message,
                }
            )
            if not continue_on_error:
                break

    status = "ok" if failed_count == 0 else ("partial" if updated_count else "error")
    return {
        "status": status,
        "processed": processed,
        "updated_count": updated_count,
        "failed_count": failed_count,
        "rows": report,
    }


def delete_item(conn: sqlite3.Connection, item_id: int) -> None:
    item = get_item(conn, item_id)
    _assert_item_is_locally_managed(item)
    ref = _first_item_reference(conn, item_id)
    if ref is not None:
        raise AppError(
            code="ITEM_REFERENCED",
            message=f"Item cannot be deleted because it is referenced by {ref}",
            status_code=409,
        )
    try:
        conn.execute("DELETE FROM items_master WHERE item_id = ?", (item_id,))
    except sqlite3.IntegrityError as exc:
        ref = _item_reference_label_for_delete(conn, item_id)
        raise AppError(
            code="ITEM_REFERENCED",
            message=f"Item cannot be deleted because it is referenced by {ref}",
            status_code=409,
        ) from exc


def list_item_history(conn: sqlite3.Connection, item_id: int) -> list[dict[str, Any]]:
    _get_entity_or_404(
        conn,
        "items_master",
        "item_id",
        item_id,
        "ITEM_NOT_FOUND",
        f"Item with id {item_id} not found",
    )
    rows = conn.execute(
        """
        SELECT *
        FROM transaction_log
        WHERE item_id = ?
        ORDER BY timestamp DESC, log_id DESC
        """,
        (item_id,),
    ).fetchall()
    return _rows_to_dict(rows)


def _stock_delta_from_transaction(row: sqlite3.Row) -> int:
    op = str(row["operation_type"] or "")
    qty = int(row["quantity"] or 0)
    from_location = row["from_location"]
    to_location = row["to_location"]

    if op == "ARRIVAL":
        return qty
    if op == "CONSUME":
        return -qty if from_location == "STOCK" else 0
    if op == "RESERVE":
        # Reservation lifecycle logs are allocation-only events in the current
        # architecture and typically store NULL locations. Only legacy reserve
        # rows that explicitly touch STOCK should contribute to stock deltas.
        delta = 0
        if to_location == "STOCK":
            delta += qty
        if from_location == "STOCK":
            delta -= qty
        return delta
    if op == "MOVE":
        delta = 0
        if to_location == "STOCK":
            delta += qty
        if from_location == "STOCK":
            delta -= qty
        return delta
    if op == "ADJUST":
        delta = 0
        if to_location == "STOCK":
            delta += qty
        if from_location == "STOCK":
            delta -= qty
        return delta
    return 0


def get_item_flow_timeline(conn: sqlite3.Connection, item_id: int) -> dict[str, Any]:
    item = get_item(conn, item_id)

    events: list[dict[str, Any]] = []

    tx_rows = conn.execute(
        """
        SELECT log_id, timestamp, operation_type, quantity, from_location, to_location, note
        FROM transaction_log
        WHERE item_id = ?
        ORDER BY timestamp ASC, log_id ASC
        """,
        (item_id,),
    ).fetchall()
    for row in tx_rows:
        delta = _stock_delta_from_transaction(row)
        if delta == 0:
            continue
        events.append(
            {
                "event_at": row["timestamp"],
                "delta": delta,
                "quantity": int(row["quantity"]),
                "direction": "increase" if delta > 0 else "decrease",
                "source_type": "transaction",
                "source_ref": f"log#{int(row['log_id'])}",
                "reason": f"{row['operation_type']} ({row['from_location'] or '-'} -> {row['to_location'] or '-'})",
                "note": row["note"],
            }
        )

    order_rows = conn.execute(
        """
        SELECT
            o.order_id,
            o.order_amount,
            o.expected_arrival,
            q.quotation_number,
            s.name AS supplier_name
        FROM orders o
        JOIN purchase_orders po ON po.purchase_order_id = o.purchase_order_id
        JOIN suppliers s ON s.supplier_id = po.supplier_id
        LEFT JOIN quotations q ON q.quotation_id = o.quotation_id
        WHERE o.item_id = ?
          AND o.status <> 'Arrived'
          AND o.expected_arrival IS NOT NULL
        ORDER BY o.expected_arrival ASC, o.order_id ASC
        """,
        (item_id,),
    ).fetchall()
    for row in order_rows:
        events.append(
            {
                "event_at": row["expected_arrival"],
                "delta": int(row["order_amount"]),
                "quantity": int(row["order_amount"]),
                "direction": "increase",
                "source_type": "expected_arrival",
                "source_ref": f"order#{int(row['order_id'])}",
                "reason": (
                    f"Expected arrival from {row['supplier_name']} / {row['quotation_number']}"
                    if row["quotation_number"]
                    else f"Expected arrival from {row['supplier_name']}"
                ),
                "note": None,
            }
        )

    reservation_rows = conn.execute(
        """
        SELECT reservation_id, quantity, deadline, purpose, note
        FROM reservations
        WHERE item_id = ?
          AND status = 'ACTIVE'
          AND deadline IS NOT NULL
        ORDER BY deadline ASC, reservation_id ASC
        """,
        (item_id,),
    ).fetchall()
    for row in reservation_rows:
        events.append(
            {
                "event_at": row["deadline"],
                "delta": -int(row["quantity"]),
                "quantity": int(row["quantity"]),
                "direction": "decrease",
                "source_type": "reservation_deadline",
                "source_ref": f"reservation#{int(row['reservation_id'])}",
                "reason": f"Reserved demand: {row['purpose'] or 'N/A'}",
                "note": row["note"],
            }
        )

    events.sort(key=lambda row: (str(row["event_at"]), str(row["source_ref"])))

    current_stock_row = conn.execute(
        "SELECT COALESCE(SUM(quantity), 0) AS qty FROM inventory_ledger WHERE item_id = ? AND location = 'STOCK'",
        (item_id,),
    ).fetchone()

    return {
        "item_id": int(item["item_id"]),
        "item_number": item["item_number"],
        "manufacturer_name": item["manufacturer_name"],
        "current_stock": int(current_stock_row["qty"] if current_stock_row else 0),
        "events": events,
    }

def list_inventory(
    conn: sqlite3.Connection,
    *,
    item_id: int | None = None,
    location: str | None = None,
    page: int = 1,
    per_page: int = 50,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if item_id is not None:
        clauses.append("il.item_id = ?")
        params.append(item_id)
    if location is not None:
        clauses.append("il.location = ?")
        params.append(location)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"""
        SELECT
            il.ledger_id,
            il.item_id,
            im.item_number,
            il.location,
            il.quantity,
            il.last_updated,
            m.name AS manufacturer_name,
            COALESCE(ca.canonical_category, im.category) AS category
        FROM inventory_ledger il
        JOIN items_master im ON im.item_id = il.item_id
        JOIN manufacturers m ON m.manufacturer_id = im.manufacturer_id
        LEFT JOIN category_aliases ca ON ca.alias_category = im.category
        {where}
        ORDER BY il.location, im.item_number
    """
    rows, pagination = _paginate(conn, sql, tuple(params), page, per_page)
    return [_normalize_order_read_row(row) for row in rows], pagination


def move_inventory(
    conn: sqlite3.Connection,
    *,
    item_id: int,
    quantity: int,
    from_location: str,
    to_location: str,
    note: str | None = None,
    batch_id: str | None = None,
    operation_type: str = "MOVE",
) -> dict[str, Any]:
    require_positive_int(quantity, "quantity")
    if from_location == to_location:
        raise AppError(
            code="INVALID_LOCATION",
            message="from_location and to_location must differ",
            status_code=422,
        )
    _get_entity_or_404(
        conn,
        "items_master",
        "item_id",
        item_id,
        "ITEM_NOT_FOUND",
        f"Item with id {item_id} not found",
    )
    _lock_inventory_item_state(conn, item_id)
    _apply_inventory_delta(conn, item_id, from_location, -int(quantity))
    _apply_inventory_delta(conn, item_id, to_location, int(quantity))
    return _log_transaction(
        conn,
        operation_type=operation_type,
        item_id=item_id,
        quantity=int(quantity),
        from_location=from_location,
        to_location=to_location,
        note=note,
        batch_id=batch_id,
    )


def consume_inventory(
    conn: sqlite3.Connection,
    *,
    item_id: int,
    quantity: int,
    from_location: str,
    note: str | None = None,
    batch_id: str | None = None,
) -> dict[str, Any]:
    require_positive_int(quantity, "quantity")
    _get_entity_or_404(
        conn,
        "items_master",
        "item_id",
        item_id,
        "ITEM_NOT_FOUND",
        f"Item with id {item_id} not found",
    )
    _lock_inventory_item_state(conn, item_id)
    _apply_inventory_delta(conn, item_id, from_location, -int(quantity))
    return _log_transaction(
        conn,
        operation_type="CONSUME",
        item_id=item_id,
        quantity=int(quantity),
        from_location=from_location,
        to_location=None,
        note=note,
        batch_id=batch_id,
    )


def adjust_inventory(
    conn: sqlite3.Connection,
    *,
    item_id: int,
    quantity_delta: int,
    location: str,
    note: str | None = None,
    batch_id: str | None = None,
) -> dict[str, Any]:
    if quantity_delta == 0:
        raise AppError(
            code="INVALID_QUANTITY",
            message="quantity_delta cannot be 0",
            status_code=422,
        )
    _get_entity_or_404(
        conn,
        "items_master",
        "item_id",
        item_id,
        "ITEM_NOT_FOUND",
        f"Item with id {item_id} not found",
    )
    _lock_inventory_item_state(conn, item_id)
    _apply_inventory_delta(conn, item_id, location, int(quantity_delta))
    from_location = None if quantity_delta > 0 else location
    to_location = location if quantity_delta > 0 else None
    return _log_transaction(
        conn,
        operation_type="ADJUST",
        item_id=item_id,
        quantity=abs(int(quantity_delta)),
        from_location=from_location,
        to_location=to_location,
        note=note,
        batch_id=batch_id,
    )


def batch_inventory_operations(
    conn: sqlite3.Connection,
    operations: list[dict[str, Any]],
    batch_id: str | None = None,
) -> dict[str, Any]:
    working_batch_id = batch_id or uuid4().hex
    results: list[dict[str, Any]] = []
    for op in operations:
        op_type = op["operation_type"].upper()
        if op_type == "MOVE":
            results.append(
                move_inventory(
                    conn,
                    item_id=op["item_id"],
                    quantity=op["quantity"],
                    from_location=op["from_location"],
                    to_location=op["to_location"],
                    note=op.get("note"),
                    batch_id=working_batch_id,
                    operation_type="MOVE",
                )
            )
        elif op_type == "CONSUME":
            results.append(
                consume_inventory(
                    conn,
                    item_id=op["item_id"],
                    quantity=op["quantity"],
                    from_location=op["from_location"],
                    note=op.get("note"),
                    batch_id=working_batch_id,
                )
            )
        elif op_type == "RESERVE":
            results.append(
                move_inventory(
                    conn,
                    item_id=op["item_id"],
                    quantity=op["quantity"],
                    from_location=op["from_location"] or "STOCK",
                    to_location=op["to_location"] or "RESERVED",
                    note=op.get("note"),
                    batch_id=working_batch_id,
                    operation_type="RESERVE",
                )
            )
        elif op_type == "ADJUST":
            quantity_delta = op.get("quantity_delta")
            if quantity_delta is None:
                quantity_delta = op["quantity"]
            results.append(
                adjust_inventory(
                    conn,
                    item_id=op["item_id"],
                    quantity_delta=int(quantity_delta),
                    location=op.get("location") or op.get("to_location") or op.get("from_location"),
                    note=op.get("note"),
                    batch_id=working_batch_id,
                )
            )
        elif op_type == "ARRIVAL":
            _apply_inventory_delta(conn, op["item_id"], op.get("to_location") or "STOCK", op["quantity"])
            results.append(
                _log_transaction(
                    conn,
                    operation_type="ARRIVAL",
                    item_id=op["item_id"],
                    quantity=op["quantity"],
                    from_location=None,
                    to_location=op.get("to_location") or "STOCK",
                    note=op.get("note"),
                    batch_id=working_batch_id,
                )
            )
        else:
            raise AppError(
                code="INVALID_OPERATION",
                message=f"Unsupported batch operation_type: {op_type}",
                status_code=422,
            )
    return {"batch_id": working_batch_id, "operations": results}




def _normalize_inventory_csv_operation_type(value: str) -> str:
    normalized = str(value or "").strip().upper()
    if not normalized:
        raise AppError(code="INVALID_OPERATION", message="operation_type is required", status_code=422)
    aliases = {
        "TRANSFER": "MOVE",
    }
    return aliases.get(normalized, normalized)


def _parse_csv_int_field(*, value: Any, row_index: int, field_name: str, code: str) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise AppError(
            code=code,
            message=f"row {row_index}: {field_name} must be an integer",
            status_code=422,
        ) from exc


def _normalize_inventory_import_overrides(
    row_overrides: dict[str | int, Any] | None,
) -> dict[int, dict[str, int]]:
    normalized: dict[int, dict[str, int]] = {}
    override_payload = _require_json_object(
        row_overrides,
        code="INVALID_INVENTORY_IMPORT_OVERRIDE",
        label="Inventory import row_overrides",
    )
    for raw_row_number, raw_override in override_payload.items():
        try:
            row_number = int(raw_row_number)
        except Exception as exc:  # noqa: BLE001
            raise AppError(
                code="INVALID_INVENTORY_IMPORT_OVERRIDE",
                message=f"Inventory import override row '{raw_row_number}' is not a valid integer",
                status_code=422,
            ) from exc
        if row_number < 2:
            raise AppError(
                code="INVALID_INVENTORY_IMPORT_OVERRIDE",
                message=f"Inventory import override row '{row_number}' must be >= 2",
                status_code=422,
            )
        if not isinstance(raw_override, dict):
            raise AppError(
                code="INVALID_INVENTORY_IMPORT_OVERRIDE",
                message=f"Inventory import override for row {row_number} must be an object",
                status_code=422,
            )
        unexpected_fields = sorted(set(raw_override) - {"item_id"})
        if unexpected_fields:
            raise AppError(
                code="INVALID_INVENTORY_IMPORT_OVERRIDE",
                message=(
                    f"Inventory import override for row {row_number} has unsupported field(s): "
                    f"{', '.join(unexpected_fields)}"
                ),
                status_code=422,
            )
        if "item_id" not in raw_override or raw_override.get("item_id") in (None, ""):
            raise AppError(
                code="INVALID_INVENTORY_IMPORT_OVERRIDE",
                message=f"Inventory import override for row {row_number} requires item_id",
                status_code=422,
            )
        try:
            item_id = require_positive_int(
                int(raw_override["item_id"]),
                f"item_id override (row {row_number})",
            )
        except Exception as exc:  # noqa: BLE001
            raise AppError(
                code="INVALID_INVENTORY_IMPORT_OVERRIDE",
                message=f"item_id override must be an integer > 0 (row {row_number})",
                status_code=422,
            ) from exc
        normalized[row_number] = {"item_id": item_id}
    return normalized


def preview_inventory_movements_from_rows(
    conn: sqlite3.Connection,
    *,
    rows: list[dict[str, Any]],
    batch_id: str | None = None,
    source_name: str = "inventory_import.csv",
) -> dict[str, Any]:
    item_rows = _load_item_preview_catalog_rows(conn)
    item_by_id = {int(row["item_id"]): row for row in item_rows}
    balances: dict[tuple[int, str], int] = {
        (int(row["item_id"]), str(row["location"])): int(row["quantity"])
        for row in conn.execute(
            "SELECT item_id, location, quantity FROM inventory_ledger"
        ).fetchall()
    }
    preview_rows: list[dict[str, Any]] = []
    summary = {
        "total_rows": 0,
        "exact": 0,
        "high_confidence": 0,
        "needs_review": 0,
        "unresolved": 0,
    }
    blocking_errors: list[str] = []

    for idx, raw_row in enumerate(rows, start=2):
        if not any(str(value or "").strip() for value in raw_row.values()):
            continue
        operation_type_raw = str(raw_row.get("operation_type") or "")
        item_id_raw = raw_row.get("item_id")
        quantity_raw = raw_row.get("quantity")
        from_location = str(raw_row.get("from_location") or "").strip() or None
        to_location = str(raw_row.get("to_location") or "").strip() or None
        location = str(raw_row.get("location") or "").strip() or None
        note = str(raw_row.get("note") or "").strip() or None
        preview_row = {
            "row": idx,
            "operation_type": operation_type_raw,
            "item_id": str(item_id_raw or "").strip(),
            "quantity": str(quantity_raw or "").strip(),
            "from_location": from_location,
            "to_location": to_location,
            "location": location,
            "note": note,
            "status": "unresolved",
            "message": "",
            "blocking": False,
            "requires_user_selection": False,
            "allowed_entity_types": [],
            "suggested_match": None,
            "candidates": [],
            "batch_id": batch_id,
        }
        summary["total_rows"] += 1

        try:
            operation_type = _normalize_inventory_csv_operation_type(operation_type_raw)
            preview_row["operation_type"] = operation_type
        except AppError as exc:
            preview_row["message"] = exc.message
            preview_row["blocking"] = True
            preview_rows.append(preview_row)
            summary["unresolved"] += 1
            blocking_errors.append(f"row {idx}: {exc.message}")
            continue

        try:
            quantity = require_positive_int(
                _parse_csv_int_field(
                    value=quantity_raw,
                    row_index=idx,
                    field_name="quantity",
                    code="INVALID_QUANTITY",
                ),
                f"row {idx} quantity",
            )
        except AppError as exc:
            preview_row["message"] = exc.message
            preview_row["blocking"] = True
            preview_rows.append(preview_row)
            summary["unresolved"] += 1
            blocking_errors.append(f"row {idx}: {exc.message}")
            continue

        resolved_item_id: int | None = None
        if item_id_raw not in (None, ""):
            try:
                resolved_item_id = _parse_csv_int_field(
                    value=item_id_raw,
                    row_index=idx,
                    field_name="item_id",
                    code="INVALID_ITEM",
                )
            except AppError:
                resolved_item_id = None
        if resolved_item_id is None or resolved_item_id not in item_by_id:
            preview_row["message"] = f"row {idx}: choose a valid item for this movement row"
            preview_row["blocking"] = True
            preview_row["requires_user_selection"] = True
            preview_row["allowed_entity_types"] = ["item"]
            preview_rows.append(preview_row)
            summary["unresolved"] += 1
            blocking_errors.append(f"row {idx}: {preview_row['message']}")
            continue

        item_row = item_by_id[resolved_item_id]
        preview_row["suggested_match"] = _build_item_preview_match(item_row)
        preview_row["item_id"] = str(resolved_item_id)
        preview_row["quantity"] = str(quantity)

        if operation_type in {"MOVE", "CONSUME", "RESERVE"} and not from_location:
            preview_row["message"] = f"row {idx}: from_location is required for {operation_type}"
            preview_row["blocking"] = True
            preview_rows.append(preview_row)
            summary["unresolved"] += 1
            blocking_errors.append(f"row {idx}: {preview_row['message']}")
            continue
        if operation_type in {"MOVE", "ARRIVAL", "RESERVE"} and not to_location:
            preview_row["message"] = f"row {idx}: to_location is required for {operation_type}"
            preview_row["blocking"] = True
            preview_rows.append(preview_row)
            summary["unresolved"] += 1
            blocking_errors.append(f"row {idx}: {preview_row['message']}")
            continue
        if operation_type == "ADJUST":
            location = location or to_location or from_location
            preview_row["location"] = location
            if not location:
                preview_row["message"] = f"row {idx}: location is required for ADJUST"
                preview_row["blocking"] = True
                preview_rows.append(preview_row)
                summary["unresolved"] += 1
                blocking_errors.append(f"row {idx}: {preview_row['message']}")
                continue

        if operation_type == "MOVE":
            available = balances.get((resolved_item_id, str(from_location)), 0)
            if available < quantity:
                preview_row["status"] = "needs_review"
                preview_row["message"] = f"Not enough inventory at {from_location}"
                preview_row["blocking"] = True
                preview_rows.append(preview_row)
                summary["needs_review"] += 1
                blocking_errors.append(f"row {idx}: {preview_row['message']}")
                continue
            balances[(resolved_item_id, str(from_location))] = available - quantity
            balances[(resolved_item_id, str(to_location))] = balances.get((resolved_item_id, str(to_location)), 0) + quantity
            preview_row["status"] = "exact"
            preview_row["message"] = f"Move {quantity} from {from_location} to {to_location}."
        elif operation_type == "CONSUME":
            available = balances.get((resolved_item_id, str(from_location)), 0)
            if available < quantity:
                preview_row["status"] = "needs_review"
                preview_row["message"] = f"Not enough inventory at {from_location}"
                preview_row["blocking"] = True
                preview_rows.append(preview_row)
                summary["needs_review"] += 1
                blocking_errors.append(f"row {idx}: {preview_row['message']}")
                continue
            balances[(resolved_item_id, str(from_location))] = available - quantity
            preview_row["status"] = "exact"
            preview_row["message"] = f"Consume {quantity} from {from_location}."
        elif operation_type == "RESERVE":
            available = balances.get((resolved_item_id, str(from_location)), 0)
            if available < quantity:
                preview_row["status"] = "needs_review"
                preview_row["message"] = f"Not enough inventory at {from_location}"
                preview_row["blocking"] = True
                preview_rows.append(preview_row)
                summary["needs_review"] += 1
                blocking_errors.append(f"row {idx}: {preview_row['message']}")
                continue
            balances[(resolved_item_id, str(from_location))] = available - quantity
            balances[(resolved_item_id, str(to_location))] = balances.get((resolved_item_id, str(to_location)), 0) + quantity
            preview_row["status"] = "exact"
            preview_row["message"] = f"Reserve {quantity} from {from_location} to {to_location}."
        elif operation_type == "ADJUST":
            balances[(resolved_item_id, str(location))] = balances.get((resolved_item_id, str(location)), 0) + quantity
            preview_row["status"] = "exact"
            preview_row["message"] = f"Adjust +{quantity} at {location}."
        elif operation_type == "ARRIVAL":
            balances[(resolved_item_id, str(to_location))] = balances.get((resolved_item_id, str(to_location)), 0) + quantity
            preview_row["status"] = "exact"
            preview_row["message"] = f"Arrival +{quantity} to {to_location}."
        else:
            preview_row["message"] = f"Unsupported batch operation_type: {operation_type}"
            preview_row["blocking"] = True
            preview_rows.append(preview_row)
            summary["unresolved"] += 1
            blocking_errors.append(f"row {idx}: {preview_row['message']}")
            continue

        preview_rows.append(preview_row)
        summary["exact"] += 1

    return {
        "source_name": source_name,
        "summary": summary,
        "blocking_errors": blocking_errors,
        "can_auto_accept": summary["needs_review"] == 0 and summary["unresolved"] == 0,
        "rows": preview_rows,
    }


def import_inventory_movements_from_rows(
    conn: sqlite3.Connection,
    *,
    rows: list[dict[str, Any]],
    batch_id: str | None = None,
    row_overrides: dict[str | int, Any] | None = None,
) -> dict[str, Any]:
    operations: list[dict[str, Any]] = []
    normalized_overrides = _normalize_inventory_import_overrides(row_overrides)
    _validate_import_override_rows(
        normalized_overrides,
        valid_row_numbers=_valid_csv_row_numbers(rows),
        code="INVALID_INVENTORY_IMPORT_OVERRIDE",
        label="Inventory import row_overrides",
    )
    for idx, raw_row in enumerate(rows, start=2):
        row = dict(raw_row)
        override = normalized_overrides.get(idx, {})
        op_type = _normalize_inventory_csv_operation_type(row.get("operation_type", ""))
        item_id_raw = override.get("item_id", row.get("item_id"))
        if item_id_raw in (None, ""):
            raise AppError(code="INVALID_ITEM", message=f"row {idx}: item_id is required", status_code=422)
        quantity_raw = row.get("quantity")
        if quantity_raw in (None, ""):
            raise AppError(code="INVALID_QUANTITY", message=f"row {idx}: quantity is required", status_code=422)
        quantity = require_positive_int(
            _parse_csv_int_field(value=quantity_raw, row_index=idx, field_name="quantity", code="INVALID_QUANTITY"),
            f"row {idx} quantity",
        )
        operation: dict[str, Any] = {
            "operation_type": op_type,
            "item_id": _parse_csv_int_field(value=item_id_raw, row_index=idx, field_name="item_id", code="INVALID_ITEM"),
            "quantity": quantity,
            "from_location": str(row.get("from_location") or "").strip() or None,
            "to_location": str(row.get("to_location") or "").strip() or None,
            "location": str(row.get("location") or "").strip() or None,
            "note": str(row.get("note") or "").strip() or None,
        }
        if op_type in {"MOVE", "CONSUME", "RESERVE"} and not operation["from_location"]:
            raise AppError(code="INVALID_LOCATION", message=f"row {idx}: from_location is required for {op_type}", status_code=422)
        if op_type in {"MOVE", "ARRIVAL", "RESERVE"} and not operation["to_location"]:
            raise AppError(code="INVALID_LOCATION", message=f"row {idx}: to_location is required for {op_type}", status_code=422)
        if op_type == "ADJUST" and not operation["location"]:
            operation["location"] = operation["to_location"] or operation["from_location"]
            if not operation["location"]:
                raise AppError(code="INVALID_LOCATION", message=f"row {idx}: location is required for ADJUST", status_code=422)
        operations.append(operation)
    if not operations:
        raise AppError(code="EMPTY_CSV", message="No movement rows found in CSV", status_code=422)
    return batch_inventory_operations(conn, operations=operations, batch_id=batch_id)


def import_inventory_movements_from_content(
    conn: sqlite3.Connection,
    *,
    content: bytes,
    batch_id: str | None = None,
    row_overrides: dict[str | int, Any] | None = None,
) -> dict[str, Any]:
    rows = _load_csv_rows_from_content(content)
    return import_inventory_movements_from_rows(
        conn,
        rows=rows,
        batch_id=batch_id,
        row_overrides=row_overrides,
    )


def preview_inventory_movements_from_content(
    conn: sqlite3.Connection,
    *,
    content: bytes,
    batch_id: str | None = None,
    source_name: str = "inventory_import.csv",
) -> dict[str, Any]:
    rows = _load_csv_rows_from_content(content)
    return preview_inventory_movements_from_rows(
        conn,
        rows=rows,
        batch_id=batch_id,
        source_name=source_name,
    )


def _assembly_lookup_map(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute("SELECT assembly_id, name FROM assemblies").fetchall()
    result: dict[str, int] = {}
    for row in rows:
        result[str(row["assembly_id"]).casefold()] = int(row["assembly_id"])
        result[str(row["name"]).strip().casefold()] = int(row["assembly_id"])
    return result


def _load_assembly_preview_catalog_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
            a.assembly_id,
            a.name,
            a.description,
            COUNT(ac.item_id) AS component_count
        FROM assemblies a
        LEFT JOIN assembly_components ac ON ac.assembly_id = a.assembly_id
        GROUP BY a.assembly_id
        ORDER BY a.name, a.assembly_id
        """
    ).fetchall()
    return _rows_to_dict(rows)


def _build_assembly_preview_match(
    assembly_row: dict[str, Any],
    *,
    match_source: str = "name",
    confidence_score: int | None = None,
    match_reason: str | None = None,
) -> dict[str, Any]:
    summary = f"{int(assembly_row.get('component_count') or 0)} component(s) | #{int(assembly_row['assembly_id'])}"
    if assembly_row.get("description"):
        summary = f"{summary} | {assembly_row['description']}"
    return {
        "entity_type": "assembly",
        "entity_id": int(assembly_row["assembly_id"]),
        "value_text": str(assembly_row["name"]),
        "display_label": f"{assembly_row['name']} #{int(assembly_row['assembly_id'])}",
        "summary": summary,
        "match_source": match_source,
        "confidence_score": confidence_score,
        "match_reason": match_reason,
    }


def _rank_assembly_preview_candidates(
    assembly_rows: list[dict[str, Any]],
    raw_value: str,
    *,
    limit: int = ORDER_IMPORT_PREVIEW_CANDIDATE_LIMIT,
) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for assembly_row in assembly_rows:
        confidence_score, score_reason = _score_order_import_candidate(
            raw_value,
            str(assembly_row["name"]),
        )
        if confidence_score <= 0:
            continue
        ranked.append(
            _build_assembly_preview_match(
                assembly_row,
                confidence_score=confidence_score,
                match_reason=f"assembly_name_{score_reason}",
            )
        )
    ranked.sort(
        key=lambda entry: (
            -int(entry.get("confidence_score") or 0),
            str(entry["value_text"]).casefold(),
            int(entry["entity_id"]),
        )
    )
    return ranked[:limit]


def _normalize_reservations_import_overrides(
    row_overrides: dict[str | int, Any] | None,
) -> dict[int, dict[str, int]]:
    normalized: dict[int, dict[str, int]] = {}
    override_payload = _require_json_object(
        row_overrides,
        code="INVALID_RESERVATION_IMPORT_OVERRIDE",
        label="Reservation import row_overrides",
    )
    for raw_row_number, raw_override in override_payload.items():
        try:
            row_number = int(raw_row_number)
        except Exception as exc:  # noqa: BLE001
            raise AppError(
                code="INVALID_RESERVATION_IMPORT_OVERRIDE",
                message=f"Reservation import override row '{raw_row_number}' is not a valid integer",
                status_code=422,
            ) from exc
        if row_number < 2:
            raise AppError(
                code="INVALID_RESERVATION_IMPORT_OVERRIDE",
                message=f"Reservation import override row '{row_number}' must be >= 2",
                status_code=422,
            )
        if not isinstance(raw_override, dict):
            raise AppError(
                code="INVALID_RESERVATION_IMPORT_OVERRIDE",
                message=f"Reservation import override for row {row_number} must be an object",
                status_code=422,
            )
        unexpected_fields = sorted(set(raw_override) - {"item_id", "assembly_id"})
        if unexpected_fields:
            raise AppError(
                code="INVALID_RESERVATION_IMPORT_OVERRIDE",
                message=(
                    f"Reservation import override for row {row_number} has unsupported field(s): "
                    f"{', '.join(unexpected_fields)}"
                ),
                status_code=422,
            )
        if not raw_override:
            raise AppError(
                code="INVALID_RESERVATION_IMPORT_OVERRIDE",
                message=(
                    f"Reservation import override for row {row_number} must include "
                    "item_id or assembly_id"
                ),
                status_code=422,
            )
        override: dict[str, int] = {}
        if "item_id" in raw_override:
            if raw_override.get("item_id") in (None, ""):
                raise AppError(
                    code="INVALID_RESERVATION_IMPORT_OVERRIDE",
                    message=f"item_id override must be an integer > 0 (row {row_number})",
                    status_code=422,
                )
            try:
                override["item_id"] = require_positive_int(
                    int(raw_override["item_id"]),
                    f"item_id override (row {row_number})",
                )
            except Exception as exc:  # noqa: BLE001
                raise AppError(
                    code="INVALID_RESERVATION_IMPORT_OVERRIDE",
                    message=f"item_id override must be an integer > 0 (row {row_number})",
                    status_code=422,
                ) from exc
        if "assembly_id" in raw_override:
            if raw_override.get("assembly_id") in (None, ""):
                raise AppError(
                    code="INVALID_RESERVATION_IMPORT_OVERRIDE",
                    message=f"assembly_id override must be an integer > 0 (row {row_number})",
                    status_code=422,
                )
            try:
                override["assembly_id"] = require_positive_int(
                    int(raw_override["assembly_id"]),
                    f"assembly_id override (row {row_number})",
                )
            except Exception as exc:  # noqa: BLE001
                raise AppError(
                    code="INVALID_RESERVATION_IMPORT_OVERRIDE",
                    message=f"assembly_id override must be an integer > 0 (row {row_number})",
                    status_code=422,
                ) from exc
        if "item_id" in override and "assembly_id" in override:
            raise AppError(
                code="INVALID_RESERVATION_IMPORT_OVERRIDE",
                message=f"Reservation import override row {row_number} must choose item_id or assembly_id, not both",
                status_code=422,
            )
        if override:
            normalized[row_number] = override
    return normalized


def preview_reservations_from_rows(
    conn: sqlite3.Connection,
    *,
    rows: list[dict[str, Any]],
    source_name: str = "reservations_import.csv",
) -> dict[str, Any]:
    item_rows = _load_item_preview_catalog_rows(conn)
    assembly_rows = _load_assembly_preview_catalog_rows(conn)
    item_by_id = {int(row["item_id"]): row for row in item_rows}
    assembly_by_id = {int(row["assembly_id"]): row for row in assembly_rows}
    assembly_lookup = _assembly_lookup_map(conn)
    available_by_item = {
        int(row["item_id"]): _get_total_available_inventory(conn, int(row["item_id"]))
        for row in item_rows
    }
    preview_rows: list[dict[str, Any]] = []
    summary = {
        "total_rows": 0,
        "exact": 0,
        "high_confidence": 0,
        "needs_review": 0,
        "unresolved": 0,
    }
    blocking_errors: list[str] = []

    for idx, raw_row in enumerate(rows, start=2):
        if not any(str(value or "").strip() for value in raw_row.values()):
            continue
        qty_raw = raw_row.get("quantity")
        purpose = str(raw_row.get("purpose") or "").strip() or None
        note = str(raw_row.get("note") or "").strip() or None
        assembly_ref = str(raw_row.get("assembly") or raw_row.get("assembly_name") or "").strip()
        assembly_qty_raw = raw_row.get("assembly_quantity")
        item_id_raw = raw_row.get("item_id")
        preview_row = {
            "row": idx,
            "quantity": str(qty_raw or "").strip(),
            "item_id": str(item_id_raw or "").strip(),
            "assembly": assembly_ref,
            "assembly_quantity": str(assembly_qty_raw or "").strip() or "1",
            "purpose": purpose,
            "deadline": str(raw_row.get("deadline") or "").strip() or None,
            "note": note,
            "project_id": str(raw_row.get("project_id") or "").strip() or None,
            "status": "unresolved",
            "message": "",
            "blocking": False,
            "requires_user_selection": False,
            "allowed_entity_types": [],
            "suggested_match": None,
            "candidates": [],
            "generated_reservations": [],
        }
        summary["total_rows"] += 1

        try:
            quantity = require_positive_int(
                _parse_csv_int_field(
                    value=qty_raw,
                    row_index=idx,
                    field_name="quantity",
                    code="INVALID_QUANTITY",
                ),
                f"row {idx} quantity",
            )
        except AppError as exc:
            preview_row["message"] = exc.message
            preview_row["blocking"] = True
            preview_rows.append(preview_row)
            summary["unresolved"] += 1
            blocking_errors.append(f"row {idx}: {exc.message}")
            continue

        try:
            deadline = normalize_optional_date((raw_row.get("deadline") or None), "deadline")
            preview_row["deadline"] = deadline
        except AppError as exc:
            preview_row["message"] = exc.message
            preview_row["blocking"] = True
            preview_rows.append(preview_row)
            summary["unresolved"] += 1
            blocking_errors.append(f"row {idx}: {exc.message}")
            continue

        project_id: int | None = None
        project_id_raw = raw_row.get("project_id")
        if project_id_raw not in (None, ""):
            try:
                project_id = _parse_csv_int_field(
                    value=project_id_raw,
                    row_index=idx,
                    field_name="project_id",
                    code="INVALID_PROJECT",
                )
                _get_entity_or_404(
                    conn,
                    "projects",
                    "project_id",
                    project_id,
                    "PROJECT_NOT_FOUND",
                    f"Project with id {project_id} not found",
                )
            except AppError as exc:
                preview_row["message"] = exc.message
                preview_row["blocking"] = True
                preview_rows.append(preview_row)
                summary["unresolved"] += 1
                blocking_errors.append(f"row {idx}: {exc.message}")
                continue

        assembly_quantity = 1
        if assembly_qty_raw not in (None, ""):
            try:
                assembly_quantity = require_positive_int(
                    _parse_csv_int_field(
                        value=assembly_qty_raw,
                        row_index=idx,
                        field_name="assembly_quantity",
                        code="INVALID_QUANTITY",
                    ),
                    f"row {idx} assembly_quantity",
                )
            except AppError as exc:
                preview_row["message"] = exc.message
                preview_row["blocking"] = True
                preview_rows.append(preview_row)
                summary["unresolved"] += 1
                blocking_errors.append(f"row {idx}: {exc.message}")
                continue

        generated_rows: list[dict[str, Any]] = []
        if item_id_raw not in (None, ""):
            try:
                item_id = _parse_csv_int_field(
                    value=item_id_raw,
                    row_index=idx,
                    field_name="item_id",
                    code="INVALID_ITEM",
                )
            except AppError:
                item_id = None
            if item_id is None or item_id not in item_by_id:
                preview_row["message"] = f"row {idx}: choose a valid item for this reservation row"
                preview_row["blocking"] = True
                preview_row["requires_user_selection"] = True
                preview_row["allowed_entity_types"] = ["item"]
                preview_rows.append(preview_row)
                summary["unresolved"] += 1
                blocking_errors.append(f"row {idx}: {preview_row['message']}")
                continue
            item_row = item_by_id[item_id]
            preview_row["suggested_match"] = _build_item_preview_match(item_row)
            generated_rows.append(
                {
                    "item_id": item_id,
                    "item_number": item_row["item_number"],
                    "manufacturer_name": item_row["manufacturer_name"],
                    "quantity": quantity,
                }
            )
        elif assembly_ref:
            assembly_id = assembly_lookup.get(assembly_ref.casefold())
            if assembly_id is None or assembly_id not in assembly_by_id:
                preview_row["message"] = f"row {idx}: choose a valid item or assembly for this reservation row"
                preview_row["blocking"] = True
                preview_row["requires_user_selection"] = True
                preview_row["allowed_entity_types"] = ["item", "assembly"]
                candidates = _rank_assembly_preview_candidates(assembly_rows, assembly_ref)
                preview_row["candidates"] = candidates
                preview_row["suggested_match"] = candidates[0] if candidates else None
                preview_rows.append(preview_row)
                summary["unresolved"] += 1
                blocking_errors.append(f"row {idx}: {preview_row['message']}")
                continue
            preview_row["suggested_match"] = _build_assembly_preview_match(assembly_by_id[assembly_id])
            component_rows = conn.execute(
                """
                SELECT
                    ac.item_id,
                    ac.quantity,
                    im.item_number,
                    m.name AS manufacturer_name
                FROM assembly_components ac
                JOIN items_master im ON im.item_id = ac.item_id
                JOIN manufacturers m ON m.manufacturer_id = im.manufacturer_id
                WHERE ac.assembly_id = ?
                ORDER BY im.item_number, ac.item_id
                """,
                (assembly_id,),
            ).fetchall()
            for component in component_rows:
                generated_rows.append(
                    {
                        "item_id": int(component["item_id"]),
                        "item_number": component["item_number"],
                        "manufacturer_name": component["manufacturer_name"],
                        "quantity": quantity * assembly_quantity * int(component["quantity"]),
                    }
                )
        else:
            preview_row["message"] = f"row {idx}: item_id or assembly is required"
            preview_row["blocking"] = True
            preview_row["requires_user_selection"] = True
            preview_row["allowed_entity_types"] = ["item", "assembly"]
            preview_rows.append(preview_row)
            summary["unresolved"] += 1
            blocking_errors.append(f"row {idx}: {preview_row['message']}")
            continue

        shortages = [
            generated
            for generated in generated_rows
            if available_by_item.get(int(generated["item_id"]), 0) < int(generated["quantity"])
        ]
        if shortages:
            preview_row["status"] = "needs_review"
            preview_row["message"] = "Not enough available inventory for reservation."
            preview_row["blocking"] = True
            preview_row["generated_reservations"] = generated_rows
            preview_rows.append(preview_row)
            summary["needs_review"] += 1
            blocking_errors.append(f"row {idx}: {preview_row['message']}")
            continue

        for generated in generated_rows:
            available_by_item[int(generated["item_id"])] = available_by_item.get(int(generated["item_id"]), 0) - int(
                generated["quantity"]
            )
        preview_row["status"] = "exact"
        preview_row["message"] = "Ready to create reservation row."
        preview_row["generated_reservations"] = generated_rows
        preview_rows.append(preview_row)
        summary["exact"] += 1

    return {
        "source_name": source_name,
        "summary": summary,
        "blocking_errors": blocking_errors,
        "can_auto_accept": summary["needs_review"] == 0 and summary["unresolved"] == 0,
        "rows": preview_rows,
    }


def import_reservations_from_rows(
    conn: sqlite3.Connection,
    *,
    rows: list[dict[str, Any]],
    row_overrides: dict[str | int, Any] | None = None,
) -> list[dict[str, Any]]:
    created: list[dict[str, Any]] = []
    normalized_overrides = _normalize_reservations_import_overrides(row_overrides)
    _validate_import_override_rows(
        normalized_overrides,
        valid_row_numbers=_valid_csv_row_numbers(rows),
        code="INVALID_RESERVATION_IMPORT_OVERRIDE",
        label="Reservation import row_overrides",
    )
    for idx, raw_row in enumerate(rows, start=2):
        row = dict(raw_row)
        qty_raw = row.get("quantity")
        if qty_raw in (None, ""):
            raise AppError(code="INVALID_QUANTITY", message=f"row {idx}: quantity is required", status_code=422)
        quantity = require_positive_int(
            _parse_csv_int_field(value=qty_raw, row_index=idx, field_name="quantity", code="INVALID_QUANTITY"),
            f"row {idx} quantity",
        )
        purpose = str(row.get("purpose") or "").strip() or None
        deadline = normalize_optional_date((row.get("deadline") or None), "deadline")
        note = str(row.get("note") or "").strip() or None
        project_id_raw = row.get("project_id")
        project_id = (
            _parse_csv_int_field(value=project_id_raw, row_index=idx, field_name="project_id", code="INVALID_PROJECT")
            if project_id_raw not in (None, "")
            else None
        )

        override = normalized_overrides.get(idx, {})
        item_id_override = override.get("item_id")
        assembly_id_override = override.get("assembly_id")
        item_id_raw = (
            None
            if assembly_id_override is not None
            else (item_id_override if item_id_override is not None else row.get("item_id"))
        )
        if item_id_raw not in (None, ""):
            created.append(
                create_reservation(
                    conn,
                    {
                        "item_id": _parse_csv_int_field(value=item_id_raw, row_index=idx, field_name="item_id", code="INVALID_ITEM"),
                        "quantity": quantity,
                        "purpose": purpose,
                        "deadline": deadline,
                        "note": note,
                        "project_id": project_id,
                    },
                )
            )
            continue
        assembly_ref = assembly_id_override if assembly_id_override is not None else row.get("assembly") or row.get("assembly_name")
        if assembly_ref not in (None, ""):
            assembly_quantity_raw = row.get("assembly_quantity")
            assembly_quantity = (
                require_positive_int(
                    _parse_csv_int_field(
                        value=assembly_quantity_raw,
                        row_index=idx,
                        field_name="assembly_quantity",
                        code="INVALID_QUANTITY",
                    ),
                    f"row {idx} assembly_quantity",
                )
                if assembly_quantity_raw not in (None, "")
                else 1
            )
            assembly_id = (
                int(assembly_ref)
                if assembly_id_override is not None
                else _assembly_lookup_map(conn).get(str(assembly_ref).strip().casefold())
            )
            if assembly_id is None:
                raise AppError(
                    code="ASSEMBLY_NOT_FOUND",
                    message=f"row {idx}: assembly '{assembly_ref}' not found",
                    status_code=422,
                )
            component_rows = conn.execute(
                """
                SELECT item_id, quantity
                FROM assembly_components
                WHERE assembly_id = ?
                ORDER BY item_id
                """,
                (assembly_id,),
            ).fetchall()
            for component in component_rows:
                created.append(
                    create_reservation(
                        conn,
                        {
                            "item_id": int(component["item_id"]),
                            "quantity": quantity * assembly_quantity * int(component["quantity"]),
                            "purpose": purpose,
                            "deadline": deadline,
                            "note": note,
                            "project_id": project_id,
                        },
                    )
                )
            continue
        raise AppError(
            code="INVALID_ITEM",
            message=f"row {idx}: item_id or assembly is required",
            status_code=422,
        )
    if not rows:
        raise AppError(code="EMPTY_CSV", message="No reservation rows found in CSV", status_code=422)
    return created


def import_reservations_from_content(
    conn: sqlite3.Connection,
    *,
    content: bytes,
    row_overrides: dict[str | int, Any] | None = None,
) -> list[dict[str, Any]]:
    rows = _load_csv_rows_from_content(content)
    return import_reservations_from_rows(conn, rows=rows, row_overrides=row_overrides)


def preview_reservations_from_content(
    conn: sqlite3.Connection,
    *,
    content: bytes,
    source_name: str = "reservations_import.csv",
) -> dict[str, Any]:
    rows = _load_csv_rows_from_content(content)
    return preview_reservations_from_rows(
        conn,
        rows=rows,
        source_name=source_name,
    )
def list_orders(
    conn: sqlite3.Connection,
    *,
    status: str | None = None,
    supplier: str | None = None,
    item_id: int | None = None,
    project_id: int | None = None,
    include_arrived: bool = True,
    page: int = 1,
    per_page: int = 50,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if status:
        clauses.append("o.status = ?")
        params.append(status)
    if supplier:
        clauses.append("s.name = ?")
        params.append(supplier)
    if item_id is not None:
        clauses.append("o.item_id = ?")
        params.append(int(item_id))
    if project_id is not None:
        clauses.append("o.project_id = ?")
        params.append(int(project_id))
    if not include_arrived:
        clauses.append("o.status <> 'Arrived'")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"""
        SELECT
            {_order_read_select_columns()}
        {_order_read_joins()}
        {where}
        ORDER BY o.order_date DESC, o.order_id DESC
    """
    return _paginate(conn, sql, tuple(params), page, per_page)


def list_arrival_schedule(
    conn: sqlite3.Connection,
    *,
    supplier: str | None = None,
    item_id: int | None = None,
    project_id: int | None = None,
    bucket: str | None = None,
    page: int = 1,
    per_page: int = 50,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    today_str = today_jst()
    valid_buckets = {"overdue", "scheduled", "no_eta"}
    normalized_bucket = bucket.strip().lower() if bucket else None
    if normalized_bucket and normalized_bucket not in valid_buckets:
        raise AppError(
            code="INVALID_ARRIVAL_BUCKET",
            message="bucket must be one of overdue, scheduled, or no_eta",
            status_code=422,
        )

    clauses = ["o.status = 'Ordered'"]
    params: list[Any] = []
    if supplier:
        clauses.append("s.name = ?")
        params.append(supplier)
    if item_id is not None:
        clauses.append("o.item_id = ?")
        params.append(int(item_id))
    if project_id is not None:
        clauses.append("o.project_id = ?")
        params.append(int(project_id))
    if normalized_bucket == "overdue":
        clauses.append("o.expected_arrival IS NOT NULL")
        clauses.append("date(o.expected_arrival) < date(?)")
        params.append(today_str)
    elif normalized_bucket == "scheduled":
        clauses.append("o.expected_arrival IS NOT NULL")
        clauses.append("date(o.expected_arrival) >= date(?)")
        params.append(today_str)
    elif normalized_bucket == "no_eta":
        clauses.append("o.expected_arrival IS NULL")

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"""
        SELECT
            {_order_read_select_columns()}
        {_order_read_joins()}
        {where}
        ORDER BY
            CASE
                WHEN o.expected_arrival IS NULL THEN 2
                WHEN date(o.expected_arrival) < date(?) THEN 0
                ELSE 1
            END,
            o.expected_arrival ASC,
            o.order_date DESC,
            o.order_id DESC
    """
    rows, pagination = _paginate(conn, sql, (*params, today_str), page, per_page)
    today = datetime.strptime(today_str, "%Y-%m-%d").date()
    enriched: list[dict[str, Any]] = []
    for raw_row in rows:
        row = _normalize_order_read_row(raw_row)
        expected_arrival = row.get("expected_arrival")
        arrival_bucket = "no_eta"
        overdue_days: int | None = None
        days_until_expected: int | None = None
        if expected_arrival:
            eta_date = datetime.strptime(str(expected_arrival), "%Y-%m-%d").date()
            days_delta = (eta_date - today).days
            days_until_expected = days_delta
            if days_delta < 0:
                arrival_bucket = "overdue"
                overdue_days = abs(days_delta)
            else:
                arrival_bucket = "scheduled"
        enriched.append(
            {
                **row,
                "arrival_bucket": arrival_bucket,
                "overdue_days": overdue_days,
                "days_until_expected": days_until_expected,
            }
        )
    return enriched, pagination


def get_order(conn: sqlite3.Connection, order_id: int) -> dict[str, Any]:
    row = conn.execute(
        f"""
        SELECT
            {_order_read_select_columns()}
        {_order_read_joins()}
        WHERE o.order_id = ?
        """,
        (order_id,),
    ).fetchone()
    if row is None:
        raise AppError(
            code="ORDER_NOT_FOUND",
            message=f"Order with id {order_id} not found",
            status_code=404,
        )
    return _normalize_order_read_row(row)


def _record_order_lineage_event(
    conn: sqlite3.Connection,
    *,
    event_type: str,
    source_purchase_order_line_id: int,
    target_purchase_order_line_id: int | None = None,
    quantity: int | None = None,
    previous_expected_arrival: str | None = None,
    new_expected_arrival: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    cur = conn.execute(
        """
        INSERT INTO order_lineage_events (
            event_type, source_purchase_order_line_id, target_purchase_order_line_id, quantity,
            previous_expected_arrival, new_expected_arrival, note, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event_type,
            source_purchase_order_line_id,
            target_purchase_order_line_id,
            quantity,
            previous_expected_arrival,
            new_expected_arrival,
            note,
            now_jst_iso(),
        ),
    )
    event_id = int(cur.lastrowid)
    row = conn.execute(
        "SELECT * FROM order_lineage_events WHERE event_id = ?",
        (event_id,),
    ).fetchone()
    return dict(row) if row else {"event_id": event_id}


def _record_local_order_split(
    conn: sqlite3.Connection,
    *,
    split_type: str,
    root_order_id: int,
    child_order_id: int,
    split_quantity: int,
    root_expected_arrival: str | None,
    child_expected_arrival: str | None,
    is_manual_override: bool = False,
    manual_override_fields: list[str] | None = None,
) -> dict[str, Any]:
    normalized_manual_fields = sorted({str(field).strip() for field in (manual_override_fields or []) if str(field).strip()})
    cur = conn.execute(
        """
        INSERT INTO local_order_splits (
            split_type,
            root_order_id,
            child_order_id,
            split_quantity,
            root_expected_arrival,
            child_expected_arrival,
            reconciliation_mode,
            is_manual_override,
            manual_override_fields,
            last_manual_override_at,
            created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            split_type,
            root_order_id,
            child_order_id,
            split_quantity,
            root_expected_arrival,
            child_expected_arrival,
            LOCAL_SPLIT_RECONCILIATION_MODE,
            bool(is_manual_override),
            json.dumps(normalized_manual_fields) if normalized_manual_fields else None,
            now_jst_iso() if is_manual_override else None,
            now_jst_iso(),
        ),
    )
    split_id = int(cur.lastrowid)
    row = conn.execute(
        "SELECT * FROM local_order_splits WHERE split_id = ?",
        (split_id,),
    ).fetchone()
    return dict(row) if row else {"split_id": split_id}


def _mark_local_order_split_manual_override(
    conn: sqlite3.Connection,
    *,
    child_order_id: int,
    fields: list[str],
) -> None:
    normalized_fields = sorted({str(field).strip() for field in fields if str(field).strip()})
    if not normalized_fields:
        return
    row = conn.execute(
        """
        SELECT manual_override_fields
        FROM local_order_splits
        WHERE child_order_id = ?
        """,
        (child_order_id,),
    ).fetchone()
    if row is None:
        return
    raw_existing = row.get("manual_override_fields") if isinstance(row, dict) else row["manual_override_fields"]
    existing_fields = _decode_manual_override_fields(raw_existing, order_id=child_order_id) or []
    merged_fields = sorted(set(existing_fields) | set(normalized_fields))
    conn.execute(
        """
        UPDATE local_order_splits
        SET is_manual_override = TRUE,
            manual_override_fields = ?,
            last_manual_override_at = ?
        WHERE child_order_id = ?
        """,
        (json.dumps(merged_fields), now_jst_iso(), child_order_id),
    )


def record_external_order_mirror_conflict(
    conn: sqlite3.Connection,
    *,
    source_system: str,
    external_order_id: str,
    conflict_code: str,
    conflict_message: str,
    local_order_id: int | None = None,
) -> dict[str, Any]:
    normalized_source_system = require_non_empty(source_system, "source_system")
    normalized_external_order_id = require_non_empty(external_order_id, "external_order_id")
    normalized_conflict_code = require_non_empty(conflict_code, "conflict_code")
    normalized_conflict_message = require_non_empty(conflict_message, "conflict_message")
    detected_at = now_jst_iso()
    conn.execute(
        """
        INSERT INTO external_order_mirrors (
            source_system,
            external_order_id,
            local_order_id,
            sync_state,
            conflict_code,
            conflict_message,
            conflict_detected_at,
            created_at
        ) VALUES (?, ?, ?, 'conflict', ?, ?, ?, ?)
        ON CONFLICT (source_system, external_order_id)
        DO UPDATE SET
            local_order_id = COALESCE(EXCLUDED.local_order_id, external_order_mirrors.local_order_id),
            sync_state = 'conflict',
            conflict_code = EXCLUDED.conflict_code,
            conflict_message = EXCLUDED.conflict_message,
            conflict_detected_at = EXCLUDED.conflict_detected_at
        """,
        (
            normalized_source_system,
            normalized_external_order_id,
            local_order_id,
            normalized_conflict_code,
            normalized_conflict_message,
            detected_at,
            detected_at,
        ),
    )
    row = conn.execute(
        """
        SELECT *
        FROM external_order_mirrors
        WHERE source_system = ? AND external_order_id = ?
        """,
        (normalized_source_system, normalized_external_order_id),
    ).fetchone()
    return dict(row) if row else {}


def list_order_lineage_events(
    conn: sqlite3.Connection,
    *,
    order_id: int,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT event_id, event_type, source_purchase_order_line_id, target_purchase_order_line_id, quantity,
               previous_expected_arrival, new_expected_arrival, note, created_at
        FROM order_lineage_events
        WHERE source_purchase_order_line_id = ? OR target_purchase_order_line_id = ?
        ORDER BY event_id ASC
        """,
        (order_id, order_id),
    ).fetchall()
    return _rows_to_dict(rows)


def update_order(conn: sqlite3.Connection, order_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    current = get_order(conn, order_id)
    _assert_order_is_locally_managed(current)
    if current["status"] == "Arrived":
        raise AppError(
            code="ORDER_ALREADY_ARRIVED",
            message="Arrived orders cannot be updated",
            status_code=409,
        )
    expected_arrival = (
        normalize_optional_date(payload.get("expected_arrival"), "expected_arrival")
        if "expected_arrival" in payload
        else current.get("expected_arrival")
    )
    next_purchase_order_document_url = (
        normalize_document_reference(payload.get("purchase_order_document_url"), "purchase_order_document_url")
        if "purchase_order_document_url" in payload
        else current.get("purchase_order_document_url")
    )
    status = payload.get("status")
    if status and status != "Ordered":
        raise AppError(
            code="INVALID_ORDER_STATUS",
            message="update_order only supports status='Ordered' for open orders",
            status_code=422,
        )
    project_id = payload.get("project_id") if "project_id" in payload else None
    if project_id is not None:
        project_id = int(project_id)
        _get_entity_or_404(
            conn,
            "projects",
            "project_id",
            project_id,
            "PROJECT_NOT_FOUND",
            f"Project with id {project_id} not found",
        )
    rfq_project_id: int | None = None
    if "project_id" in payload:
        procurement_project_id = _ordered_procurement_project_for_order(conn, order_id)
        rfq_project_id = _ordered_rfq_project_for_order(conn, order_id)
        managed_project_id = procurement_project_id if procurement_project_id is not None else rfq_project_id
        if managed_project_id is not None and project_id != managed_project_id:
            raise AppError(
                code=(
                    "ORDER_PROJECT_MANAGED_BY_PROCUREMENT"
                    if procurement_project_id is not None
                    else "ORDER_PROJECT_MANAGED_BY_RFQ"
                ),
                message=(
                    "project_id is managed by the ORDERED procurement line linked to this order"
                    if procurement_project_id is not None
                    else "project_id is managed by the ORDERED RFQ line linked to this order"
                ),
                status_code=409,
            )

    split_quantity_raw = payload.get("split_quantity")
    split_quantity: int | None
    if split_quantity_raw is None:
        split_quantity = None
    else:
        try:
            split_quantity = int(split_quantity_raw)
        except Exception as exc:  # noqa: BLE001
            raise AppError(
                code="INVALID_SPLIT_QUANTITY",
                message="split_quantity must be an integer",
                status_code=422,
            ) from exc

    if split_quantity is None:
        updates = ["expected_arrival = ?", "status = COALESCE(?, status)"]
        params: list[Any] = [expected_arrival, status]
        if "purchase_order_document_url" in payload:
            purchase_order_id = _get_or_create_purchase_order(
                conn,
                int(current["supplier_id"]),
                current.get("purchase_order_number"),
                next_purchase_order_document_url,
                current_purchase_order_id=int(current["purchase_order_id"]),
            )
            updates.append("purchase_order_id = ?")
            params.append(purchase_order_id)
        if "project_id" in payload:
            updates.append("project_id = ?")
            params.append(project_id)
            updates.append("project_id_manual = ?")
            params.append(1 if project_id is not None else 0)
        params.append(order_id)
        conn.execute(
            f"UPDATE orders SET {', '.join(updates)} WHERE order_id = ?",
            tuple(params),
        )
        updated = get_order(conn, order_id)
        if (
            "purchase_order_document_url" in payload
            and int(updated["purchase_order_id"]) != int(current["purchase_order_id"])
        ):
            _delete_purchase_order_if_orphaned(conn, int(current["purchase_order_id"]))
        if current.get("expected_arrival") != updated.get("expected_arrival"):
            _record_order_lineage_event(
                conn,
                event_type="ETA_UPDATE",
                source_purchase_order_line_id=order_id,
                target_purchase_order_line_id=order_id,
                quantity=int(updated.get("order_amount") or 0),
                previous_expected_arrival=current.get("expected_arrival"),
                new_expected_arrival=updated.get("expected_arrival"),
                note="full-order eta update",
            )
            if bool(current.get("is_split_child")):
                _mark_local_order_split_manual_override(
                    conn,
                    child_order_id=order_id,
                    fields=["expected_arrival"],
                )
        return updated

    require_positive_int(split_quantity, "split_quantity")
    order_amount = int(current["order_amount"])
    if split_quantity >= order_amount:
        raise AppError(
            code="INVALID_SPLIT_QUANTITY",
            message="split_quantity must be less than current order_amount",
            status_code=422,
        )
    if expected_arrival is None:
        raise AppError(
            code="EXPECTED_ARRIVAL_REQUIRED",
            message="expected_arrival is required when split_quantity is provided",
            status_code=422,
        )

    original_ordered_qty = int(current["ordered_quantity"] or order_amount)
    split_ordered = original_ordered_qty * split_quantity
    if split_ordered % order_amount != 0:
        raise AppError(
            code="PARTIAL_SPLIT_NOT_INTEGER_SAFE",
            message="Cannot split traceability quantities without fractional values",
            status_code=409,
        )
    split_ordered //= order_amount
    remaining_ordered = original_ordered_qty - split_ordered
    remaining_order_amount = order_amount - split_quantity
    if split_ordered <= 0 or remaining_ordered <= 0 or remaining_order_amount <= 0:
        raise AppError(
            code="INVALID_PARTIAL_SPLIT",
            message="Split would produce invalid quantities",
            status_code=409,
        )
    if rfq_project_id is None:
        rfq_project_id = _ordered_rfq_project_for_order(conn, order_id)
    if rfq_project_id is None:
        rfq_project_id = _ordered_procurement_project_for_order(conn, order_id)

    split_updates = ["order_amount = ?", "ordered_quantity = ?", "status = COALESCE(?, status)"]
    split_params: list[Any] = [remaining_order_amount, remaining_ordered, status]
    split_purchase_order_id = int(current["purchase_order_id"])
    if "purchase_order_document_url" in payload:
        split_purchase_order_id = _get_or_create_purchase_order(
            conn,
            int(current["supplier_id"]),
            current.get("purchase_order_number"),
            next_purchase_order_document_url,
            current_purchase_order_id=int(current["purchase_order_id"]),
        )
        split_updates.append("purchase_order_id = ?")
        split_params.append(split_purchase_order_id)
    if "project_id" in payload:
        split_updates.append("project_id = ?")
        split_params.append(project_id)
        split_updates.append("project_id_manual = ?")
        split_params.append(1 if project_id is not None else 0)
    split_params.append(order_id)
    conn.execute(
        f"UPDATE orders SET {', '.join(split_updates)} WHERE order_id = ?",
        tuple(split_params),
    )
    # RFQ ownership stays on the linked order only; the split sibling remains generic
    # until an ORDERED RFQ line explicitly points at it.
    split_child_project_id = (
        None
        if rfq_project_id is not None
        else (project_id if "project_id" in payload else current.get("project_id"))
    )
    is_rfq_derived = rfq_project_id is not None
    is_manual_update = not is_rfq_derived and "project_id" in payload
    if is_rfq_derived:
        split_child_project_id_manual = 0
    elif is_manual_update:
        split_child_project_id_manual = 1 if project_id is not None else 0
    else:
        split_child_project_id_manual = int(current.get("project_id_manual") or 0)
    cur = conn.execute(
        """
        INSERT INTO orders (
            item_id, quotation_id, purchase_order_id, project_id, project_id_manual, order_amount, ordered_quantity,
            ordered_item_number, order_date, expected_arrival, arrival_date, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 'Ordered')
        """,
        (
            current["item_id"],
            current["quotation_id"],
            split_purchase_order_id,
            split_child_project_id,
            split_child_project_id_manual,
            split_quantity,
            split_ordered,
            current["ordered_item_number"],
            current["order_date"],
            expected_arrival,
        ),
    )
    split_order_id = int(cur.lastrowid)

    split_order = get_order(conn, split_order_id)
    if (
        "purchase_order_document_url" in payload
        and split_purchase_order_id != int(current["purchase_order_id"])
    ):
        _delete_purchase_order_if_orphaned(conn, int(current["purchase_order_id"]))
    _record_order_lineage_event(
        conn,
        event_type="ETA_SPLIT",
        source_purchase_order_line_id=order_id,
        target_purchase_order_line_id=split_order_id,
        quantity=split_quantity,
        previous_expected_arrival=current.get("expected_arrival"),
        new_expected_arrival=expected_arrival,
        note="partial eta postponement split",
    )
    _record_local_order_split(
        conn,
        split_type="ETA_SPLIT",
        root_order_id=int(current.get("split_root_order_id") or order_id),
        child_order_id=split_order_id,
        split_quantity=split_quantity,
        root_expected_arrival=current.get("expected_arrival"),
        child_expected_arrival=expected_arrival,
        is_manual_override=True,
        manual_override_fields=["expected_arrival", "quantity"],
    )

    return {
        "order_id": order_id,
        "split_order_id": split_order_id,
        "updated_order": get_order(conn, order_id),
        "created_order": get_order(conn, split_order_id),
    }


def delete_order(conn: sqlite3.Connection, order_id: int) -> dict[str, Any]:
    order = get_order(conn, order_id)
    _assert_order_is_locally_managed(order)
    if order["status"] == "Arrived":
        raise AppError(
            code="ORDER_ALREADY_ARRIVED",
            message="Arrived orders cannot be deleted",
            status_code=409,
        )

    conn.execute("DELETE FROM orders WHERE order_id = ?", (order_id,))
    purchase_order_deleted = _delete_purchase_order_if_orphaned(conn, int(order["purchase_order_id"]))

    quotation_deleted = False
    if order["quotation_id"] is not None:
        remaining = conn.execute(
            "SELECT COUNT(*) AS c FROM orders WHERE quotation_id = ?",
            (order["quotation_id"],),
        ).fetchone()
        if int(remaining["c"]) == 0:
            conn.execute("DELETE FROM quotations WHERE quotation_id = ?", (order["quotation_id"],))
            quotation_deleted = True
    return {
        "deleted": True,
        "order_id": order_id,
        "quotation_deleted": quotation_deleted,
        "purchase_order_deleted": purchase_order_deleted,
        "csv_sync": _csv_archive_sync_disabled_result(),
    }


def merge_open_orders(
    conn: sqlite3.Connection,
    *,
    source_purchase_order_line_id: int,
    target_purchase_order_line_id: int,
    expected_arrival: str | None = None,
) -> dict[str, Any]:
    if source_purchase_order_line_id == target_purchase_order_line_id:
        raise AppError(
            code="INVALID_MERGE_PAIR",
            message="source_purchase_order_line_id and target_purchase_order_line_id must differ",
            status_code=422,
        )

    source = get_order(conn, source_purchase_order_line_id)
    target = get_order(conn, target_purchase_order_line_id)
    _assert_order_is_locally_managed(source)
    _assert_order_is_locally_managed(target)
    if source["status"] == "Arrived" or target["status"] == "Arrived":
        raise AppError(
            code="ORDER_ALREADY_ARRIVED",
            message="Arrived orders cannot be merged",
            status_code=409,
        )

    merge_keys = ("item_id", "quotation_id", "purchase_order_id", "ordered_item_number", "project_id")
    if any(source[key] != target[key] for key in merge_keys):
        raise AppError(
            code="ORDER_MERGE_SCOPE_MISMATCH",
            message=(
                "Orders can be merged only when item_id, quotation_id, "
                "purchase_order_id, ordered_item_number, and project_id match"
            ),
            status_code=422,
        )

    normalized_eta = normalize_optional_date(expected_arrival, "expected_arrival")
    final_eta = normalized_eta if normalized_eta is not None else (target.get("expected_arrival") or source.get("expected_arrival"))

    target_amount = int(target["order_amount"])
    source_amount = int(source["order_amount"])
    target_ordered = int(target["ordered_quantity"] or target_amount)
    source_ordered = int(source["ordered_quantity"] or source_amount)

    conn.execute(
        """
        UPDATE orders
        SET order_amount = ?,
            ordered_quantity = ?,
            expected_arrival = ?,
            status = 'Ordered'
        WHERE order_id = ?
        """,
        (target_amount + source_amount, target_ordered + source_ordered, final_eta, target_purchase_order_line_id),
    )
    conn.execute("DELETE FROM orders WHERE order_id = ?", (source_purchase_order_line_id,))

    event = _record_order_lineage_event(
        conn,
        event_type="ETA_MERGE",
        source_purchase_order_line_id=source_purchase_order_line_id,
        target_purchase_order_line_id=target_purchase_order_line_id,
        quantity=source_amount,
        previous_expected_arrival=source.get("expected_arrival"),
        new_expected_arrival=final_eta,
        note="merged open orders",
    )

    return {
        "merged": True,
        "source_purchase_order_line_id": source_purchase_order_line_id,
        "target_purchase_order_line_id": target_purchase_order_line_id,
        "target_order": get_order(conn, target_purchase_order_line_id),
        "lineage_event": event,
    }


def _normalize_required_quotation_document_url(
    value: str | None,
    *,
    row_index: int,
) -> str:
    normalized = normalize_document_reference(
        value,
        f"quotation_document_url (row {row_index})",
        required=True,
    )
    assert normalized is not None
    return normalized


def _resolve_import_quotation_document_url(
    row: dict[str, Any],
    *,
    row_index: int,
) -> str | None:
    raw_value = row.get("quotation_document_url")
    return _normalize_required_quotation_document_url(raw_value, row_index=row_index)


def _normalize_optional_purchase_order_number(
    value: Any,
    field_name: str = "purchase_order_number",
) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return require_non_empty(text, field_name)


def _normalize_required_purchase_order_number(
    value: Any,
    *,
    field_name: str = "purchase_order_number",
    code: str = "INVALID_CSV",
) -> str:
    normalized = _normalize_optional_purchase_order_number(value, field_name)
    if normalized is not None:
        return normalized
    raise AppError(
        code=code,
        message=f"{field_name} is required",
        status_code=422,
    )


def _order_import_duplicate_quotation_numbers(
    conn: sqlite3.Connection,
    supplier_id: int,
    quotation_numbers: list[str],
) -> list[str]:
    normalized_numbers = sorted(
        {
            str(quotation_number).strip()
            for quotation_number in quotation_numbers
            if str(quotation_number).strip()
        }
    )
    if not normalized_numbers:
        return []
    placeholders = ",".join("?" for _ in normalized_numbers)
    duplicate_rows = conn.execute(
        f"""
        SELECT q.quotation_number
        FROM quotations q
        WHERE q.supplier_id = ?
          AND q.quotation_number IN ({placeholders})
          AND EXISTS (
            SELECT 1
            FROM orders o
            WHERE o.quotation_id = q.quotation_id
          )
        ORDER BY q.quotation_number
        """,
        (supplier_id, *normalized_numbers),
    ).fetchall()
    return [str(row["quotation_number"]) for row in duplicate_rows]


def _normalize_order_import_overrides(
    row_overrides: dict[str | int, Any] | None,
) -> dict[int, dict[str, int]]:
    normalized: dict[int, dict[str, int]] = {}
    override_payload = _require_json_object(
        row_overrides,
        code="INVALID_ORDER_IMPORT_OVERRIDE",
        label="Order import row_overrides",
    )
    for raw_row_number, raw_override in override_payload.items():
        try:
            row_number = int(raw_row_number)
        except Exception as exc:  # noqa: BLE001
            raise AppError(
                code="INVALID_ORDER_IMPORT_OVERRIDE",
                message=f"Order import override row '{raw_row_number}' is not a valid integer",
                status_code=422,
            ) from exc
        if row_number < 2:
            raise AppError(
                code="INVALID_ORDER_IMPORT_OVERRIDE",
                message=f"Order import override row '{row_number}' must be >= 2",
                status_code=422,
            )
        if not isinstance(raw_override, dict):
            raise AppError(
                code="INVALID_ORDER_IMPORT_OVERRIDE",
                message=f"Order import override for row {row_number} must be an object",
                status_code=422,
            )
        override: dict[str, int] = {}
        unexpected_fields = sorted(set(raw_override) - {"item_id", "units_per_order"})
        if unexpected_fields:
            raise AppError(
                code="INVALID_ORDER_IMPORT_OVERRIDE",
                message=(
                    f"Order import override for row {row_number} has unsupported field(s): "
                    f"{', '.join(unexpected_fields)}"
                ),
                status_code=422,
            )
        if "item_id" in raw_override:
            if raw_override.get("item_id") in (None, ""):
                raise AppError(
                    code="INVALID_ORDER_IMPORT_OVERRIDE",
                    message=f"item_id override must be an integer > 0 (row {row_number})",
                    status_code=422,
                )
            try:
                override["item_id"] = require_positive_int(
                    int(raw_override["item_id"]),
                    f"item_id override (row {row_number})",
                )
            except Exception as exc:  # noqa: BLE001
                raise AppError(
                    code="INVALID_ORDER_IMPORT_OVERRIDE",
                    message=f"item_id override must be an integer > 0 (row {row_number})",
                    status_code=422,
                ) from exc
        if "units_per_order" in raw_override:
            if raw_override.get("units_per_order") in (None, ""):
                raise AppError(
                    code="INVALID_ORDER_IMPORT_OVERRIDE",
                    message=f"units_per_order override must be an integer > 0 (row {row_number})",
                    status_code=422,
                )
            try:
                override["units_per_order"] = require_positive_int(
                    int(raw_override["units_per_order"]),
                    f"units_per_order override (row {row_number})",
                )
            except Exception as exc:  # noqa: BLE001
                raise AppError(
                    code="INVALID_ORDER_IMPORT_OVERRIDE",
                    message=f"units_per_order override must be an integer > 0 (row {row_number})",
                    status_code=422,
                ) from exc
        if not override:
            raise AppError(
                code="INVALID_ORDER_IMPORT_OVERRIDE",
                message=(
                    f"Order import override for row {row_number} must include "
                    "item_id or units_per_order"
                ),
                status_code=422,
            )
        normalized[row_number] = override
    return normalized


def _normalize_order_import_alias_saves(
    alias_saves: list[dict[str, Any]] | None,
    *,
    default_supplier_name: str | None = None,
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    alias_payload = _require_json_array(
        alias_saves,
        code="INVALID_ORDER_IMPORT_ALIAS",
        label="Order import alias_saves",
    )
    for idx, raw_alias in enumerate(alias_payload, start=1):
        if not isinstance(raw_alias, dict):
            raise AppError(
                code="INVALID_ORDER_IMPORT_ALIAS",
                message=f"Alias save entry #{idx} must be an object",
                status_code=422,
            )
        unexpected_fields = sorted(
            set(raw_alias) - {"supplier_name", "ordered_item_number", "item_id", "units_per_order"}
        )
        if unexpected_fields:
            raise AppError(
                code="INVALID_ORDER_IMPORT_ALIAS",
                message=f"Alias save entry #{idx} has unsupported field(s): {', '.join(unexpected_fields)}",
                status_code=422,
            )
        ordered_item_number = require_non_empty(
            str(raw_alias.get("ordered_item_number", "")),
            f"ordered_item_number (alias save #{idx})",
        )
        supplier_name = str(raw_alias.get("supplier_name") or default_supplier_name or "").strip()
        supplier_name = require_non_empty(supplier_name, f"supplier_name (alias save #{idx})")
        if raw_alias.get("item_id") in (None, ""):
            raise AppError(
                code="INVALID_ORDER_IMPORT_ALIAS",
                message=f"Alias save entry #{idx} requires item_id",
                status_code=422,
            )
        try:
            item_id = require_positive_int(
                int(raw_alias["item_id"]),
                f"item_id (alias save #{idx})",
            )
        except Exception as exc:  # noqa: BLE001
            raise AppError(
                code="INVALID_ORDER_IMPORT_ALIAS",
                message=f"Alias save item_id must be an integer > 0 (entry #{idx})",
                status_code=422,
            ) from exc
        units_raw = raw_alias.get("units_per_order", 1)
        try:
            units_per_order = require_positive_int(
                int(units_raw),
                f"units_per_order (alias save #{idx})",
            )
        except Exception as exc:  # noqa: BLE001
            raise AppError(
                code="INVALID_ORDER_IMPORT_ALIAS",
                message=f"Alias save units_per_order must be an integer > 0 (entry #{idx})",
                status_code=422,
            ) from exc
        normalized.append(
            {
                "supplier_name": supplier_name,
                "ordered_item_number": ordered_item_number,
                "item_id": item_id,
                "units_per_order": units_per_order,
            }
        )
    return normalized


def _normalize_order_import_unlock_purchase_orders(
    conn: sqlite3.Connection,
    unlock_purchase_orders: list[dict[str, Any]] | None,
    *,
    default_supplier_id: int | None = None,
    default_supplier_name: str | None = None,
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    unlock_payload = _require_json_array(
        unlock_purchase_orders,
        code="INVALID_ORDER_IMPORT_UNLOCK",
        label="Order import unlock_purchase_orders",
    )
    for idx, raw_unlock in enumerate(unlock_payload, start=1):
        if not isinstance(raw_unlock, dict):
            raise AppError(
                code="INVALID_ORDER_IMPORT_UNLOCK",
                message=f"Unlock entry #{idx} must be an object",
                status_code=422,
            )
        unexpected_fields = sorted(set(raw_unlock) - {"supplier_id", "supplier_name", "purchase_order_number"})
        if unexpected_fields:
            raise AppError(
                code="INVALID_ORDER_IMPORT_UNLOCK",
                message=f"Unlock entry #{idx} has unsupported field(s): {', '.join(unexpected_fields)}",
                status_code=422,
            )
        supplier_id_value = raw_unlock.get("supplier_id")
        supplier_id = int(supplier_id_value) if supplier_id_value not in (None, "") else default_supplier_id
        supplier_name = str(raw_unlock.get("supplier_name") or "").strip() or default_supplier_name
        supplier_context = _resolve_order_import_supplier_context(
            conn,
            supplier_id=supplier_id,
            supplier_name=supplier_name,
        )
        resolved_supplier_id = supplier_context.get("supplier_id")
        if resolved_supplier_id is None:
            raise AppError(
                code="INVALID_ORDER_IMPORT_UNLOCK",
                message=f"Unlock entry #{idx} references a supplier that does not exist",
                status_code=422,
            )
        normalized.append(
            {
                "supplier_id": int(resolved_supplier_id),
                "supplier_name": str(supplier_context["supplier_name"]),
                "purchase_order_number": _normalize_required_purchase_order_number(
                    raw_unlock.get("purchase_order_number"),
                    field_name=f"purchase_order_number (unlock entry #{idx})",
                    code="INVALID_ORDER_IMPORT_UNLOCK",
                ),
            }
        )
    return normalized


def _get_locked_purchase_orders_by_numbers(
    conn: sqlite3.Connection,
    supplier_id: int,
    purchase_order_numbers: list[str],
) -> list[dict[str, Any]]:
    normalized_numbers = sorted(
        {
            str(purchase_order_number).strip()
            for purchase_order_number in purchase_order_numbers
            if str(purchase_order_number).strip()
        }
    )
    if not normalized_numbers:
        return []
    placeholders = ",".join("?" for _ in normalized_numbers)
    rows = conn.execute(
        f"""
        SELECT
            po.purchase_order_id,
            po.supplier_id,
            s.name AS supplier_name,
            po.purchase_order_number,
            po.purchase_order_document_url,
            po.import_locked
        FROM purchase_orders po
        JOIN suppliers s ON s.supplier_id = po.supplier_id
        WHERE po.supplier_id = ?
          AND po.import_locked = TRUE
          AND po.purchase_order_number IN ({placeholders})
        ORDER BY po.purchase_order_number
        """,
        (int(supplier_id), *normalized_numbers),
    ).fetchall()
    return _rows_to_dict(rows)

def _apply_order_import_alias_saves(
    conn: sqlite3.Connection,
    *,
    alias_saves: list[dict[str, Any]],
    import_job_id: int | None = None,
    row_number_by_alias_key: dict[tuple[str, str], int] | None = None,
) -> int:
    deduped: dict[tuple[str, str], dict[str, Any]] = {}
    for alias in alias_saves:
        deduped[
            (
                str(alias["supplier_name"]).casefold(),
                str(alias["ordered_item_number"]).casefold(),
            )
        ] = alias

    saved_count = 0
    for alias in deduped.values():
        supplier_id = _get_or_create_supplier(conn, str(alias["supplier_name"]))
        ordered_item_number = str(alias["ordered_item_number"])
        if _resolve_item_by_number(conn, ordered_item_number) is not None:
            continue
        before_alias = _alias_row_by_supplier_and_ordered(
            conn,
            supplier_id=supplier_id,
            ordered_item_number=ordered_item_number,
        )
        upsert_supplier_item_alias(
            conn,
            supplier_id=supplier_id,
            ordered_item_number=ordered_item_number,
            canonical_item_id=int(alias["item_id"]),
            units_per_order=int(alias["units_per_order"]),
        )
        after_alias = _alias_row_by_supplier_and_ordered(
            conn,
            supplier_id=supplier_id,
            ordered_item_number=ordered_item_number,
        )
        if import_job_id is not None and after_alias is not None and before_alias != after_alias:
            alias_key = (str(alias["supplier_name"]).casefold(), ordered_item_number.casefold())
            _record_import_job_effect(
                conn,
                import_job_id=import_job_id,
                row_number=(row_number_by_alias_key or {}).get(alias_key, 1),
                status="created",
                entry_type="alias",
                effect_type="alias_updated" if before_alias is not None else "alias_created",
                alias_id=int(after_alias["alias_id"]),
                item_id=int(after_alias["canonical_item_id"]),
                supplier_id=int(after_alias["supplier_id"]),
                supplier_name=str(after_alias["supplier_name"]),
                item_number=str(after_alias["ordered_item_number"]),
                canonical_item_number=str(after_alias["canonical_item_number"]),
                units_per_order=int(after_alias["units_per_order"]),
                before_state=before_alias,
                after_state=after_alias,
            )
        saved_count += 1
    return saved_count


def _load_order_import_preview_candidates(
    conn: sqlite3.Connection,
    supplier_id: int | None,
) -> list[dict[str, Any]]:
    direct_rows = conn.execute(
        """
        SELECT
            im.item_id,
            im.item_number AS canonical_item_number,
            m.name AS manufacturer_name
        FROM items_master im
        JOIN manufacturers m ON m.manufacturer_id = im.manufacturer_id
        ORDER BY im.item_number, im.item_id
        """
    ).fetchall()
    candidates: list[dict[str, Any]] = [
        {
            "item_id": int(row["item_id"]),
            "canonical_item_number": str(row["canonical_item_number"]),
            "manufacturer_name": str(row["manufacturer_name"]),
            "units_per_order": 1,
            "candidate_text": str(row["canonical_item_number"]),
            "match_source": "item_number",
            "summary": f"{row['manufacturer_name']} | direct item number",
        }
        for row in direct_rows
    ]
    if supplier_id is None:
        return candidates

    alias_rows = conn.execute(
        """
        SELECT
            a.ordered_item_number,
            a.units_per_order,
            im.item_id,
            im.item_number AS canonical_item_number,
            m.name AS manufacturer_name
        FROM supplier_item_aliases a
        JOIN items_master im ON im.item_id = a.canonical_item_id
        JOIN manufacturers m ON m.manufacturer_id = im.manufacturer_id
        WHERE a.supplier_id = ?
        ORDER BY a.ordered_item_number, a.alias_id
        """,
        (supplier_id,),
    ).fetchall()
    candidates.extend(
        {
            "item_id": int(row["item_id"]),
            "canonical_item_number": str(row["canonical_item_number"]),
            "manufacturer_name": str(row["manufacturer_name"]),
            "units_per_order": int(row["units_per_order"]),
            "candidate_text": str(row["ordered_item_number"]),
            "match_source": "supplier_item_alias",
            "summary": (
                f"{row['manufacturer_name']} | alias {row['ordered_item_number']} | "
                f"units/order {int(row['units_per_order'])}"
            ),
        }
        for row in alias_rows
    )
    return candidates


def _load_supplier_preview_catalog_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT supplier_id, name
        FROM suppliers
        ORDER BY name, supplier_id
        """
    ).fetchall()
    return _rows_to_dict(rows)


def _build_supplier_preview_match(
    supplier_row: dict[str, Any],
    *,
    confidence_score: int | None = None,
    match_reason: str | None = None,
) -> dict[str, Any]:
    supplier_id = int(supplier_row["supplier_id"])
    supplier_name = str(supplier_row["name"])
    return {
        "entity_type": "supplier",
        "entity_id": supplier_id,
        "value_text": supplier_name,
        "display_label": supplier_name,
        "summary": f"Supplier #{supplier_id}",
        "match_source": "name",
        "confidence_score": confidence_score,
        "match_reason": match_reason,
    }


def _rank_supplier_preview_candidates(
    supplier_rows: list[dict[str, Any]],
    raw_value: str,
    *,
    limit: int = ORDER_IMPORT_PREVIEW_CANDIDATE_LIMIT,
) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for supplier_row in supplier_rows:
        confidence_score, score_reason = _score_order_import_candidate(
            raw_value,
            str(supplier_row["name"]),
        )
        if confidence_score <= 0:
            continue
        ranked.append(
            _build_supplier_preview_match(
                supplier_row,
                confidence_score=confidence_score,
                match_reason=f"name_{score_reason}",
            )
        )
    ranked.sort(
        key=lambda entry: (
            -int(entry.get("confidence_score") or 0),
            str(entry["value_text"]).casefold(),
            int(entry["entity_id"]),
        )
    )
    return ranked[:limit]


def _rank_order_style_preview_candidates(
    raw_value: str,
    preview_candidates: list[dict[str, Any]],
    *,
    limit: int = ORDER_IMPORT_PREVIEW_CANDIDATE_LIMIT,
) -> list[dict[str, Any]]:
    ranked_candidates: list[dict[str, Any]] = []
    for candidate in preview_candidates:
        confidence_score, score_reason = _score_order_import_candidate(
            raw_value,
            str(candidate["candidate_text"]),
        )
        if confidence_score <= 0:
            continue
        ranked_candidates.append(
            {
                "item_id": int(candidate["item_id"]),
                "canonical_item_number": str(candidate["canonical_item_number"]),
                "manufacturer_name": str(candidate["manufacturer_name"]),
                "units_per_order": int(candidate["units_per_order"]),
                "display_label": (
                    f"{candidate['canonical_item_number']} "
                    f"({candidate['manufacturer_name']}) #{int(candidate['item_id'])}"
                ),
                "summary": str(candidate["summary"]),
                "match_source": str(candidate["match_source"]),
                "match_reason": f"{candidate['match_source']}_{score_reason}",
                "confidence_score": confidence_score,
            }
        )

    deduped_candidates: dict[tuple[int, int], dict[str, Any]] = {}
    for candidate in sorted(
        ranked_candidates,
        key=lambda entry: (
            -int(entry["confidence_score"]),
            0 if entry["match_source"] == "supplier_item_alias" else 1,
            str(entry["canonical_item_number"]).casefold(),
            int(entry["item_id"]),
        ),
    ):
        dedupe_key = (int(candidate["item_id"]), int(candidate["units_per_order"]))
        if dedupe_key not in deduped_candidates:
            deduped_candidates[dedupe_key] = candidate
    return list(deduped_candidates.values())[:limit]


def _build_bom_item_preview_match(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "entity_type": "item",
        "entity_id": int(candidate["item_id"]),
        "value_text": str(candidate["canonical_item_number"]),
        "display_label": str(candidate["display_label"]),
        "summary": str(candidate["summary"]),
        "match_source": str(candidate["match_source"]),
        "confidence_score": int(candidate["confidence_score"]),
        "match_reason": str(candidate["match_reason"]),
        "canonical_item_number": str(candidate["canonical_item_number"]),
        "manufacturer_name": str(candidate["manufacturer_name"]),
        "units_per_order": int(candidate["units_per_order"]),
    }


def _resolve_bom_preview_supplier(
    supplier_rows: list[dict[str, Any]],
    raw_supplier: str,
) -> dict[str, Any]:
    supplier_name = str(raw_supplier or "").strip()
    if not supplier_name:
        return {
            "status": "unresolved",
            "message": "supplier is required",
            "requires_selection": True,
            "suggested_match": None,
            "candidates": [],
            "preview_supplier_id": None,
        }

    candidate_matches = _rank_supplier_preview_candidates(supplier_rows, supplier_name)
    exact_candidates = _exact_preview_candidates(candidate_matches)
    if len(exact_candidates) == 1:
        return {
            "status": "exact",
            "message": "Matched registered supplier.",
            "requires_selection": False,
            "suggested_match": exact_candidates[0],
            "candidates": candidate_matches,
            "preview_supplier_id": int(exact_candidates[0]["entity_id"]),
        }
    if len(exact_candidates) > 1:
        return {
            "status": "needs_review",
            "message": "Multiple registered suppliers match this name. Choose the correct supplier.",
            "requires_selection": True,
            "suggested_match": None,
            "candidates": exact_candidates,
            "preview_supplier_id": None,
        }

    best_candidate = candidate_matches[0] if candidate_matches else None
    status = _classify_ranked_preview_status(
        confidence_score=int(best_candidate["confidence_score"]) if best_candidate else None,
        match_reason=str(best_candidate["match_reason"]) if best_candidate else None,
    )
    if status == "high_confidence":
        message = "High-confidence supplier match found."
    elif status == "needs_review":
        message = "Review the suggested supplier before continuing."
    else:
        message = "No registered supplier matched this row."
    return {
        "status": status,
        "message": message,
        "requires_selection": status in {"needs_review", "unresolved"},
        "suggested_match": best_candidate if status != "unresolved" else None,
        "candidates": candidate_matches,
        "preview_supplier_id": (
            int(best_candidate["entity_id"])
            if best_candidate is not None and status != "unresolved"
            else None
        ),
    }


def _resolve_bom_preview_item(
    raw_item_number: str,
    preview_candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    item_number = str(raw_item_number or "").strip()
    if not item_number:
        return {
            "status": "unresolved",
            "message": "item_number is required",
            "requires_selection": True,
            "suggested_match": None,
            "candidates": [],
        }

    candidate_matches = [
        _build_bom_item_preview_match(candidate)
        for candidate in _rank_order_style_preview_candidates(item_number, preview_candidates)
    ]
    exact_candidates = _exact_preview_candidates(candidate_matches)
    if len(exact_candidates) == 1:
        exact_match = exact_candidates[0]
        return {
            "status": "exact",
            "message": (
                "Matched supplier alias to a canonical item."
                if str(exact_match.get("match_source") or "") == "supplier_item_alias"
                else "Matched registered item."
            ),
            "requires_selection": False,
            "suggested_match": exact_match,
            "candidates": candidate_matches,
        }
    if len(exact_candidates) > 1:
        return {
            "status": "needs_review",
            "message": "Multiple registered items match this row. Choose the correct item.",
            "requires_selection": True,
            "suggested_match": None,
            "candidates": exact_candidates,
        }

    best_candidate = candidate_matches[0] if candidate_matches else None
    status = _classify_ranked_preview_status(
        confidence_score=int(best_candidate["confidence_score"]) if best_candidate else None,
        match_reason=str(best_candidate["match_reason"]) if best_candidate else None,
    )
    if status == "high_confidence":
        message = "High-confidence item match found."
    elif status == "needs_review":
        message = "Review the suggested item before continuing."
    else:
        message = "No reliable registered item matched this row."
    return {
        "status": status,
        "message": message,
        "requires_selection": status in {"needs_review", "unresolved"},
        "suggested_match": best_candidate if status != "unresolved" else None,
        "candidates": candidate_matches,
    }


def _score_order_import_candidate(raw_value: str, candidate_text: str) -> tuple[int, str]:
    raw_text = str(raw_value or "").strip()
    match_text = str(candidate_text or "").strip()
    if not raw_text or not match_text:
        return 0, "none"
    if raw_text == match_text:
        return 100, "exact"
    if raw_text.casefold() == match_text.casefold():
        return 99, "casefold_exact"
    normalized_raw = _normalize_item_number_for_lookup(raw_text)
    normalized_match = _normalize_item_number_for_lookup(match_text)
    if normalized_raw and normalized_raw == normalized_match:
        return 97, "normalized_exact"
    compare_left = normalized_raw or raw_text.casefold()
    compare_right = normalized_match or match_text.casefold()
    score = int(round(SequenceMatcher(None, compare_left, compare_right).ratio() * 100))
    if compare_left in compare_right or compare_right in compare_left:
        score = max(score, 88)
    if compare_left.startswith(compare_right) or compare_right.startswith(compare_left):
        score = max(score, 90)
    return score, "fuzzy"


def _classify_ranked_preview_status(
    *,
    confidence_score: int | None,
    match_reason: str | None,
) -> str:
    if confidence_score is None:
        return "unresolved"
    reason = str(match_reason or "")
    if reason.endswith("exact") or reason.endswith("casefold_exact") or reason.endswith("normalized_exact"):
        return "exact"
    if confidence_score >= ORDER_IMPORT_AUTO_ACCEPT_SCORE:
        return "high_confidence"
    if confidence_score >= ORDER_IMPORT_REVIEW_SCORE:
        return "needs_review"
    return "unresolved"


def _project_requirement_preview_should_export_to_items_csv(
    *,
    raw_target: str,
    status: str,
    suggested_match: dict[str, Any] | None,
) -> bool:
    if not str(raw_target or "").strip():
        return False
    if status == "unresolved":
        return True
    if status != "needs_review" or not isinstance(suggested_match, dict):
        return False
    confidence_score = suggested_match.get("confidence_score")
    normalized_confidence = int(confidence_score) if confidence_score is not None else None
    return (
        _classify_ranked_preview_status(
            confidence_score=normalized_confidence,
            match_reason=str(suggested_match.get("match_reason") or ""),
        )
        == "needs_review"
    )


def _project_requirement_preview_row_eligible_for_items_csv_export(row: dict[str, Any]) -> bool:
    explicit_flag = row.get("eligible_for_items_csv_export")
    if explicit_flag is not None:
        return bool(explicit_flag) and bool(str(row.get("raw_target") or "").strip())
    suggested_match = row.get("suggested_match")
    normalized_suggested_match = suggested_match if isinstance(suggested_match, dict) else None
    return _project_requirement_preview_should_export_to_items_csv(
        raw_target=str(row.get("raw_target") or ""),
        status=str(row.get("status") or ""),
        suggested_match=normalized_suggested_match,
    )


PREVIEW_STATUS_PRIORITY = {
    "exact": 0,
    "high_confidence": 1,
    "needs_review": 2,
    "unresolved": 3,
}


def _merge_preview_statuses(*statuses: str) -> str:
    return max(
        (str(status or "unresolved") for status in statuses),
        key=lambda value: PREVIEW_STATUS_PRIORITY.get(value, PREVIEW_STATUS_PRIORITY["unresolved"]),
    )


def _exact_preview_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    exact_candidates: list[dict[str, Any]] = []
    for candidate in candidates:
        if (
            _classify_ranked_preview_status(
                confidence_score=int(candidate.get("confidence_score") or 0),
                match_reason=str(candidate.get("match_reason") or ""),
            )
            == "exact"
        ):
            exact_candidates.append(candidate)
    return exact_candidates


def _classify_order_import_preview_status(
    *,
    confidence_score: int | None,
    match_reason: str | None,
) -> str:
    return _classify_ranked_preview_status(
        confidence_score=confidence_score,
        match_reason=match_reason,
    )


def preview_orders_import_from_rows(
    conn: sqlite3.Connection,
    *,
    supplier_id: int | None = None,
    supplier_name: str | None = None,
    rows: list[dict[str, str]],
    source_name: str = "order_import.csv",
) -> dict[str, Any]:
    default_supplier_context = None
    if supplier_id is not None or supplier_name is not None:
        default_supplier_context = _resolve_order_import_supplier_context(
            conn,
            supplier_id=supplier_id,
            supplier_name=supplier_name,
        )
    preview_rows: list[dict[str, Any]] = []
    row_supplier_contexts: list[dict[str, Any]] = []
    preview_candidate_cache: dict[int | None, list[dict[str, Any]]] = {}
    summary = {
        "total_rows": 0,
        "exact": 0,
        "high_confidence": 0,
        "needs_review": 0,
        "unresolved": 0,
    }

    for row_number, row in enumerate(rows, start=2):
        if not any(str(value or "").strip() for value in row.values()):
            continue

        supplier_context = _resolve_order_import_row_supplier_context(
            conn,
            row=row,
            row_number=row_number,
            default_supplier_id=(
                int(default_supplier_context["supplier_id"])
                if default_supplier_context and default_supplier_context.get("supplier_id") is not None
                else None
            ),
            default_supplier_name=(
                str(default_supplier_context["supplier_name"])
                if default_supplier_context is not None
                else None
            ),
        )
        row_supplier_contexts.append(supplier_context)
        preview_supplier_id = (
            int(supplier_context["supplier_id"])
            if supplier_context.get("supplier_id") is not None
            else None
        )
        if preview_supplier_id not in preview_candidate_cache:
            preview_candidate_cache[preview_supplier_id] = _load_order_import_preview_candidates(
                conn,
                preview_supplier_id,
            )
        preview_candidates = preview_candidate_cache[preview_supplier_id]
        item_number = require_non_empty(str(row.get("item_number", "")), f"item_number (row {row_number})")
        quantity_raw = row.get("quantity")
        try:
            ordered_quantity = require_positive_int(int(quantity_raw), f"quantity (row {row_number})")
        except Exception as exc:  # noqa: BLE001
            raise AppError(
                code="INVALID_CSV",
                message=f"quantity must be an integer > 0 (row {row_number})",
                status_code=422,
            ) from exc

        quotation_document_url = _resolve_import_quotation_document_url(
            row,
            row_index=row_number,
        )
        purchase_order_document_url = normalize_document_reference(
            row.get("purchase_order_document_url"),
            f"purchase_order_document_url (row {row_number})",
        )
        raw_purchase_order_number = _normalize_optional_purchase_order_number(
            row.get("purchase_order_number"),
            f"purchase_order_number (row {row_number})",
        )
        order_date = normalize_optional_date(row.get("order_date"), f"order_date (row {row_number})")
        if order_date is None:
            order_date = today_jst()
        expected_arrival = normalize_optional_date(
            row.get("expected_arrival"),
            f"expected_arrival (row {row_number})",
        )
        issue_date = normalize_optional_date(row.get("issue_date"), f"issue_date (row {row_number})")
        quotation_number = require_non_empty(
            str(row.get("quotation_number", "")),
            f"quotation_number (row {row_number})",
        )
        purchase_order_number = raw_purchase_order_number or quotation_number

        top_candidates = _rank_order_style_preview_candidates(item_number, preview_candidates)
        best_candidate = top_candidates[0] if top_candidates else None
        status = _classify_order_import_preview_status(
            confidence_score=int(best_candidate["confidence_score"]) if best_candidate else None,
            match_reason=str(best_candidate["match_reason"]) if best_candidate else None,
        )
        suggested_match = best_candidate if status != "unresolved" else None
        preview_row = {
            "row": row_number,
            "supplier_name": str(supplier_context["supplier_name"]),
            "supplier_id": preview_supplier_id,
            "item_number": item_number,
            "quantity": ordered_quantity,
            "quotation_number": quotation_number,
            "issue_date": issue_date,
            "order_date": order_date,
            "expected_arrival": expected_arrival,
            "quotation_document_url": quotation_document_url,
            "purchase_order_document_url": purchase_order_document_url,
            "purchase_order_number": purchase_order_number,
            "status": status,
            "confidence_score": int(best_candidate["confidence_score"]) if best_candidate else None,
            "suggested_match": suggested_match,
            "candidates": top_candidates,
            "warnings": [],
            "order_amount": (
                ordered_quantity * int(suggested_match["units_per_order"])
                if suggested_match is not None
                else None
            ),
            "supplier_exists": bool(supplier_context["exists"]),
        }
        preview_rows.append(preview_row)
        summary["total_rows"] += 1
        summary[status] += 1

    blocking_errors: list[str] = []
    duplicate_quotation_numbers: list[str] = []
    locked_purchase_orders: list[dict[str, Any]] = []
    lock_messages_seen: set[str] = set()
    rows_by_supplier_id: dict[int, list[dict[str, Any]]] = {}
    for preview_row in preview_rows:
        supplier_row_id = preview_row.get("supplier_id")
        if supplier_row_id is None:
            continue
        rows_by_supplier_id.setdefault(int(supplier_row_id), []).append(preview_row)
    for duplicate_supplier_id, supplier_rows in rows_by_supplier_id.items():
        supplier_locks = _get_locked_purchase_orders_by_numbers(
            conn,
            duplicate_supplier_id,
            [str(row["purchase_order_number"]) for row in supplier_rows],
        )
        if not supplier_locks:
            continue
        locked_purchase_orders.extend(supplier_locks)
        duplicate_set = {str(lock_row["purchase_order_number"]) for lock_row in supplier_locks}
        supplier_name_value = str(supplier_rows[0]["supplier_name"])
        duplicate_message = (
            f"Purchase order import is locked for supplier '{supplier_name_value}': "
            + ", ".join(sorted(duplicate_set))
        )
        if duplicate_message not in lock_messages_seen:
            blocking_errors.append(duplicate_message)
            lock_messages_seen.add(duplicate_message)
        for preview_row in supplier_rows:
            if str(preview_row["purchase_order_number"]) in duplicate_set:
                preview_row["warnings"].append("Purchase order import is locked for this supplier.")

    return {
        "source_name": source_name,
        "supplier": _summarize_order_import_supplier_contexts(row_supplier_contexts),
        "thresholds": {
            "auto_accept": ORDER_IMPORT_AUTO_ACCEPT_SCORE,
            "review": ORDER_IMPORT_REVIEW_SCORE,
        },
        "summary": summary,
        "blocking_errors": blocking_errors,
        "duplicate_quotation_numbers": duplicate_quotation_numbers,
        "locked_purchase_orders": locked_purchase_orders,
        "can_auto_accept": (
            not blocking_errors
            and summary["total_rows"] > 0
            and summary["needs_review"] == 0
            and summary["unresolved"] == 0
        ),
        "rows": preview_rows,
    }


def _process_order_rows_for_import(
    conn: sqlite3.Connection,
    *,
    supplier_id: int | None = None,
    supplier_name: str | None = None,
    rows: list[dict[str, str]],
    row_overrides: dict[int, dict[str, int]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    resolved: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    seen_missing: set[tuple[str, str]] = set()
    default_supplier_context = None
    if supplier_id is not None or supplier_name is not None:
        default_supplier_context = _resolve_order_import_supplier_context(
            conn,
            supplier_id=supplier_id,
            supplier_name=supplier_name,
        )
    for idx, row in enumerate(rows, start=2):
        if not any(str(value or "").strip() for value in row.values()):
            continue
        supplier_context = _resolve_order_import_row_supplier_context(
            conn,
            row=row,
            row_number=idx,
            default_supplier_id=(
                int(default_supplier_context["supplier_id"])
                if default_supplier_context and default_supplier_context.get("supplier_id") is not None
                else None
            ),
            default_supplier_name=(
                str(default_supplier_context["supplier_name"])
                if default_supplier_context is not None
                else None
            ),
        )
        row_supplier_id = (
            int(supplier_context["supplier_id"])
            if supplier_context.get("supplier_id") is not None
            else _get_or_create_supplier(conn, str(supplier_context["supplier_name"]))
        )
        row_supplier_name = str(supplier_context["supplier_name"])
        item_number = require_non_empty(str(row.get("item_number", "")), f"item_number (row {idx})")
        quantity_raw = row.get("quantity")
        try:
            ordered_quantity = require_positive_int(int(quantity_raw), f"quantity (row {idx})")
        except Exception as exc:  # noqa: BLE001
            raise AppError(
                code="INVALID_CSV",
                message=f"quantity must be an integer > 0 (row {idx})",
                status_code=422,
            ) from exc
        quotation_document_url = _resolve_import_quotation_document_url(
            row,
            row_index=idx,
        )
        purchase_order_document_url = normalize_document_reference(
            row.get("purchase_order_document_url"),
            f"purchase_order_document_url (row {idx})",
        )
        raw_purchase_order_number = _normalize_optional_purchase_order_number(
            row.get("purchase_order_number"),
            f"purchase_order_number (row {idx})",
        )
        item_id, units_per_order = _resolve_order_item(conn, row_supplier_id, item_number)
        override = (row_overrides or {}).get(idx, {})
        override_item_id = override.get("item_id")
        override_units = override.get("units_per_order")
        if override_item_id is not None:
            _get_entity_or_404(
                conn,
                "items_master",
                "item_id",
                override_item_id,
                "ITEM_NOT_FOUND",
                f"Item with id {override_item_id} not found",
            )
            if item_id != override_item_id and override_units is None:
                units_per_order = 1
            item_id = override_item_id
        if override_units is not None:
            units_per_order = override_units
        if item_id is None:
            dedupe_key = (row_supplier_name.casefold(), item_number.casefold())
            if dedupe_key not in seen_missing:
                seen_missing.add(dedupe_key)
                missing.append(
                    {
                        "row": idx,
                        "item_number": item_number,
                        "supplier": row_supplier_name,
                        "manufacturer_name": "",
                        "resolution_type": "new_item",
                        "category": "",
                        "url": "",
                        "description": "",
                        "canonical_item_number": "",
                        "units_per_order": "",
                    }
                )
            continue
        order_date = normalize_optional_date(row.get("order_date"), f"order_date (row {idx})")
        if order_date is None:
            order_date = today_jst()
        quotation_number = require_non_empty(
            str(row.get("quotation_number", "")),
            f"quotation_number (row {idx})",
        )
        resolved.append(
            {
                "item_id": item_id,
                "supplier_id": row_supplier_id,
                "supplier_name": row_supplier_name,
                "row_number": idx,
                "quotation_number": quotation_number,
                "issue_date": normalize_optional_date(row.get("issue_date"), f"issue_date (row {idx})"),
                "quotation_document_url": quotation_document_url,
                "purchase_order_number": raw_purchase_order_number or quotation_number,
                "purchase_order_document_url": purchase_order_document_url,
                "order_amount": ordered_quantity * units_per_order,
                "ordered_quantity": ordered_quantity,
                "ordered_item_number": item_number,
                "order_date": order_date,
                "expected_arrival": normalize_optional_date(
                    row.get("expected_arrival"),
                    f"expected_arrival (row {idx})",
                ),
            }
        )
    return resolved, missing


def import_orders_from_rows(
    conn: sqlite3.Connection,
    *,
    supplier_id: int | None = None,
    supplier_name: str | None = None,
    rows: list[dict[str, str]],
    source_name: str = "order_import.csv",
    missing_output_dir: str | Path | None = None,
    row_overrides: dict[str | int, Any] | None = None,
    alias_saves: list[dict[str, Any]] | None = None,
    unlock_purchase_orders: list[dict[str, Any]] | None = None,
    import_job_id: int | None = None,
) -> dict[str, Any]:
    normalized_overrides = _normalize_order_import_overrides(row_overrides)
    normalized_alias_saves = _normalize_order_import_alias_saves(
        alias_saves,
        default_supplier_name=supplier_name,
    )
    normalized_unlock_purchase_orders = _normalize_order_import_unlock_purchase_orders(
        conn,
        unlock_purchase_orders,
        default_supplier_id=supplier_id,
        default_supplier_name=supplier_name,
    )
    _validate_import_override_rows(
        normalized_overrides,
        valid_row_numbers=_valid_csv_row_numbers(rows, skip_blank_rows=True),
        code="INVALID_ORDER_IMPORT_OVERRIDE",
        label="Order import row_overrides",
    )
    resolved, missing = _process_order_rows_for_import(
        conn,
        supplier_id=supplier_id,
        supplier_name=supplier_name,
        rows=rows,
        row_overrides=normalized_overrides,
    )
    if missing:
        missing_csv = _write_missing_items_csv(
            missing,
            source_name=source_name,
            output_dir=missing_output_dir,
        )
        if import_job_id is not None:
            for row in missing:
                _record_import_job_effect(
                    conn,
                    import_job_id=import_job_id,
                    row_number=int(row["row"]),
                    status="error",
                    effect_type="order_missing_item",
                    item_number=str(row.get("item_number") or ""),
                    supplier_name=str(row.get("supplier") or ""),
                    message="Ordered item number is not yet registered in the catalog",
                    code="ORDER_ITEM_NOT_FOUND",
                )
        return {
            "status": "missing_items",
            "missing_count": len(missing),
            "missing_csv_path": str(missing_csv.path),
            "missing_storage_ref": missing_csv.storage_ref,
            "missing_artifact": _build_generated_artifact_from_stored_object(
                conn,
                missing_csv,
                source_job_type="orders" if import_job_id is not None else None,
                source_job_id=str(import_job_id) if import_job_id is not None else None,
            ),
            "rows": missing,
        }

    unlocked_purchase_order_keys = {
        (int(entry["supplier_id"]), str(entry["purchase_order_number"]))
        for entry in normalized_unlock_purchase_orders
    }
    row_purchase_order_keys = {
        (int(row["supplier_id"]), str(row["purchase_order_number"]))
        for row in resolved
    }
    invalid_unlock_keys = unlocked_purchase_order_keys - row_purchase_order_keys
    if invalid_unlock_keys:
        raise AppError(
            code="INVALID_ORDER_IMPORT_UNLOCK",
            message="unlock_purchase_orders includes purchase orders that are not present in this import",
            status_code=422,
        )
    for unlock_supplier_id, unlock_purchase_order_number in sorted(unlocked_purchase_order_keys):
        _set_purchase_order_import_locked(
            conn,
            supplier_id=unlock_supplier_id,
            purchase_order_number=unlock_purchase_order_number,
            import_locked=False,
        )

    duplicate_details: list[dict[str, Any]] = []
    duplicate_messages: list[str] = []
    rows_by_supplier_id: dict[int, list[dict[str, Any]]] = {}
    for row in resolved:
        rows_by_supplier_id.setdefault(int(row["supplier_id"]), []).append(row)
    for duplicate_supplier_id, supplier_rows in rows_by_supplier_id.items():
        supplier_duplicates = _get_locked_purchase_orders_by_numbers(
            conn,
            duplicate_supplier_id,
            [str(row["purchase_order_number"]) for row in supplier_rows],
        )
        if not supplier_duplicates:
            continue
        duplicate_set = {str(entry["purchase_order_number"]) for entry in supplier_duplicates}
        duplicate_details.extend(
            {
                "supplier_id": duplicate_supplier_id,
                "supplier_name": str(supplier_rows[0]["supplier_name"]),
                "purchase_order_id": int(duplicate_row["purchase_order_id"]),
                "purchase_order_number": str(duplicate_row["purchase_order_number"]),
            }
            for duplicate_row in supplier_duplicates
        )
        duplicate_messages.append(
            "Purchase order import is locked for supplier "
            f"'{supplier_rows[0]['supplier_name']}': {', '.join(sorted(duplicate_set))}"
        )
        if import_job_id is not None:
            for row in resolved:
                if int(row["supplier_id"]) != duplicate_supplier_id:
                    continue
                if str(row["purchase_order_number"]) not in duplicate_set:
                    continue
                _record_import_job_effect(
                    conn,
                    import_job_id=import_job_id,
                    row_number=int(row["row_number"]),
                    status="duplicate",
                    effect_type="order_locked_purchase_order",
                    item_id=int(row["item_id"]),
                    supplier_id=int(row["supplier_id"]),
                    supplier_name=str(row["supplier_name"]),
                    item_number=str(row.get("ordered_item_number") or ""),
                    message=(
                        "Purchase order import is locked for this supplier: "
                        f"{', '.join(sorted(duplicate_set))}"
                    ),
                    code="PURCHASE_ORDER_IMPORT_LOCKED",
                )
    if duplicate_messages:
        raise AppError(
            code="PURCHASE_ORDER_IMPORT_LOCKED",
            message="; ".join(duplicate_messages),
            status_code=409,
            details={
                "purchase_order_numbers": [detail["purchase_order_number"] for detail in duplicate_details],
                "purchase_orders_by_supplier": duplicate_details,
            },
        )

    saved_alias_count = _apply_order_import_alias_saves(
        conn,
        alias_saves=normalized_alias_saves,
        import_job_id=import_job_id,
        row_number_by_alias_key={
            (str(row["supplier_name"]).casefold(), str(row["ordered_item_number"]).casefold()): int(row["row_number"])
            for row in resolved
        },
    )

    order_ids: list[int] = []
    quotation_ids_by_key: dict[tuple[int, str], int] = {}
    recorded_quotation_keys: set[tuple[int, str]] = set()
    purchase_order_ids_by_key: dict[tuple[int, str], int] = {}
    for row in resolved:
        quotation_key = (int(row["supplier_id"]), str(row["quotation_number"]))
        quotation_id = quotation_ids_by_key.get(quotation_key)
        if quotation_id is None:
            existing_before = conn.execute(
                """
                SELECT quotation_id
                FROM quotations
                WHERE supplier_id = ? AND quotation_number = ?
                """,
                (int(row["supplier_id"]), row["quotation_number"]),
            ).fetchone()
            before_state = (
                _get_quotation_row_by_id(conn, int(existing_before["quotation_id"]))
                if existing_before is not None
                else None
            )
            quotation_id = _get_or_create_quotation(
                conn,
                int(row["supplier_id"]),
                row["quotation_number"],
                row["issue_date"],
                row["quotation_document_url"],
            )
            quotation_ids_by_key[quotation_key] = quotation_id
            if import_job_id is not None and quotation_key not in recorded_quotation_keys:
                after_state = _get_quotation_row_by_id(conn, quotation_id)
                if after_state is not None and before_state != after_state:
                    _record_import_job_effect(
                        conn,
                        import_job_id=import_job_id,
                        row_number=int(row["row_number"]),
                        status="created",
                        effect_type="quotation_updated" if before_state is not None else "quotation_created",
                        supplier_id=int(after_state["supplier_id"]),
                        supplier_name=str(after_state["supplier_name"]),
                        before_state=before_state,
                        after_state=after_state,
                    )
                recorded_quotation_keys.add(quotation_key)
        purchase_order_document_url = row["purchase_order_document_url"]
        purchase_order_number = str(row["purchase_order_number"])
        purchase_order_before_state: dict[str, Any] | None = None
        purchase_order_key = (int(row["supplier_id"]), purchase_order_number)
        purchase_order_id = purchase_order_ids_by_key.get(purchase_order_key, 0)
        if purchase_order_id == 0:
            _lock_purchase_order_number_state(conn, int(row["supplier_id"]), purchase_order_number)
            purchase_order_before_state = _find_purchase_order_row(
                conn,
                supplier_id=int(row["supplier_id"]),
                purchase_order_number=purchase_order_number,
            )
            purchase_order_id = _get_or_create_purchase_order(
                conn,
                int(row["supplier_id"]),
                purchase_order_number,
                purchase_order_document_url,
            )
            purchase_order_ids_by_key[purchase_order_key] = purchase_order_id
            if import_job_id is not None:
                purchase_order_after_state = _get_purchase_order_row_by_id(conn, purchase_order_id)
                if purchase_order_after_state is not None and purchase_order_before_state != purchase_order_after_state:
                    _record_import_job_effect(
                        conn,
                        import_job_id=import_job_id,
                        row_number=int(row["row_number"]),
                        status="created",
                        effect_type=(
                            "purchase_order_updated"
                            if purchase_order_before_state is not None
                            else "purchase_order_created"
                        ),
                        supplier_id=int(purchase_order_after_state["supplier_id"]),
                        supplier_name=str(purchase_order_after_state["supplier_name"]),
                        before_state=purchase_order_before_state,
                        after_state=purchase_order_after_state,
                    )
        cur = conn.execute(
            """
            INSERT INTO orders (
                item_id,
                quotation_id,
                purchase_order_id,
                order_amount,
                ordered_quantity,
                ordered_item_number,
                order_date,
                expected_arrival,
                status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Ordered')
            """,
            (
                row["item_id"],
                quotation_id,
                purchase_order_id,
                row["order_amount"],
                row["ordered_quantity"],
                row["ordered_item_number"],
                row["order_date"],
                row["expected_arrival"],
            ),
        )
        order_id = int(cur.lastrowid)
        order_ids.append(order_id)
        if import_job_id is not None:
            order_snapshot = get_order(conn, order_id)
            _record_import_job_effect(
                conn,
                import_job_id=import_job_id,
                row_number=int(row["row_number"]),
                status="created",
                effect_type="order_created",
                item_id=int(row["item_id"]),
                item_number=str(row.get("ordered_item_number") or ""),
                supplier_id=int(row["supplier_id"]),
                supplier_name=str(row["supplier_name"]),
                after_state={
                    "order_id": int(order_snapshot["order_id"]),
                    "item_id": int(order_snapshot["item_id"]),
                    "quotation_id": int(order_snapshot["quotation_id"]),
                    "order_amount": int(order_snapshot["order_amount"]),
                    "ordered_quantity": int(order_snapshot["ordered_quantity"]),
                    "ordered_item_number": str(order_snapshot["ordered_item_number"]),
                    "order_date": order_snapshot["order_date"],
                    "expected_arrival": order_snapshot["expected_arrival"],
                    "purchase_order_id": int(order_snapshot["purchase_order_id"]),
                    "purchase_order_number": str(order_snapshot["purchase_order_number"]),
                    "status": str(order_snapshot["status"]),
                    "project_id": order_snapshot.get("project_id"),
                    "quotation_number": str(order_snapshot["quotation_number"]),
                    "quotation_document_url": order_snapshot["quotation_document_url"],
                    "purchase_order_document_url": order_snapshot["purchase_order_document_url"],
                    "supplier_id": int(order_snapshot["supplier_id"]),
                    "supplier_name": str(order_snapshot["supplier_name"]),
                },
            )
    suggested_procurement_links: list[dict[str, Any]] = []
    if order_ids:
        placeholders = ",".join("?" for _ in order_ids)
        imported_orders = conn.execute(
            f"""
            SELECT o.order_id, o.item_id, o.quotation_id, im.item_number, q.quotation_number
            FROM orders o
            JOIN items_master im ON im.item_id = o.item_id
            LEFT JOIN quotations q ON q.quotation_id = o.quotation_id
            WHERE o.order_id IN ({placeholders})
            """,
            tuple(order_ids),
        ).fetchall()
        for order in imported_orders:
            candidate_rows = conn.execute(
                """
                SELECT
                    pl.line_id,
                    pl.batch_id,
                    pb.title AS batch_title,
                    pl.status,
                    pl.source_project_id
                FROM procurement_lines pl
                JOIN procurement_batches pb ON pb.batch_id = pl.batch_id
                WHERE pl.item_id = ?
                  AND pl.status IN ('SENT', 'QUOTED')
                  AND pl.linked_order_id IS NULL
                ORDER BY
                    CASE pl.status WHEN 'QUOTED' THEN 0 ELSE 1 END,
                    pl.updated_at DESC,
                    pl.line_id DESC
                """,
                (int(order["item_id"]),),
            ).fetchall()
            for candidate in candidate_rows:
                suggested_procurement_links.append(
                    {
                        "order_id": int(order["order_id"]),
                        "quotation_id": int(order["quotation_id"]),
                        "quotation_number": order["quotation_number"],
                        "item_id": int(order["item_id"]),
                        "item_number": order["item_number"],
                        "line_id": int(candidate["line_id"]),
                        "batch_id": int(candidate["batch_id"]),
                        "batch_title": candidate["batch_title"],
                        "line_status": candidate["status"],
                        "source_project_id": candidate["source_project_id"],
                        "default_selected": True,
                    }
                )
    return {
        "status": "ok",
        "imported_count": len(order_ids),
        "order_ids": order_ids,
        "saved_alias_count": saved_alias_count,
        "suggested_procurement_links": suggested_procurement_links,
    }


def import_orders_from_content(
    conn: sqlite3.Connection,
    *,
    supplier_id: int | None = None,
    supplier_name: str | None = None,
    content: bytes,
    source_name: str = "order_import.csv",
    missing_output_dir: str | Path | None = None,
    row_overrides: dict[str | int, Any] | None = None,
    alias_saves: list[dict[str, Any]] | None = None,
    unlock_purchase_orders: list[dict[str, Any]] | None = None,
    import_job_id: int | None = None,
) -> dict[str, Any]:
    rows = _load_csv_rows_from_content(content)
    return import_orders_from_rows(
        conn,
        supplier_id=supplier_id,
        supplier_name=supplier_name,
        rows=rows,
        source_name=source_name,
        missing_output_dir=missing_output_dir,
        row_overrides=row_overrides,
        alias_saves=alias_saves,
        unlock_purchase_orders=unlock_purchase_orders,
        import_job_id=import_job_id,
    )


def import_orders_from_content_with_job(
    conn: sqlite3.Connection,
    *,
    supplier_id: int | None = None,
    supplier_name: str | None = None,
    content: bytes,
    source_name: str = "order_import.csv",
    missing_output_dir: str | Path | None = None,
    row_overrides: dict[str | int, Any] | None = None,
    alias_saves: list[dict[str, Any]] | None = None,
    unlock_purchase_orders: list[dict[str, Any]] | None = None,
    redo_of_job_id: int | None = None,
) -> dict[str, Any]:
    source_text = _read_import_job_source_text(content)
    import_job_id = _record_import_job(
        conn,
        import_type="orders",
        source_name=source_name,
        source_content=source_text,
        continue_on_error=False,
        redo_of_job_id=redo_of_job_id,
        request_metadata={
            "supplier_id": supplier_id,
            "supplier_name": supplier_name,
            "row_overrides": row_overrides or None,
            "alias_saves": alias_saves or None,
            "unlock_purchase_orders": unlock_purchase_orders or None,
        },
    )
    conn.execute("SAVEPOINT order_import_job")
    try:
        result = import_orders_from_content(
            conn,
            supplier_id=supplier_id,
            supplier_name=supplier_name,
            content=content,
            source_name=source_name,
            missing_output_dir=missing_output_dir,
            row_overrides=row_overrides,
            alias_saves=alias_saves,
            unlock_purchase_orders=unlock_purchase_orders,
            import_job_id=import_job_id,
        )
    except Exception:
        conn.execute("ROLLBACK TO SAVEPOINT order_import_job")
        conn.execute("RELEASE SAVEPOINT order_import_job")
        _finalize_import_job(
            conn,
            import_job_id=import_job_id,
            result={"status": "error", "processed": 0, "created_count": 0, "duplicate_count": 0, "failed_count": 1},
        )
        raise
    conn.execute("RELEASE SAVEPOINT order_import_job")
    _finalize_import_job(
        conn,
        import_job_id=import_job_id,
        result={
            "status": result["status"],
            "processed": result.get("imported_count", 0) + result.get("missing_count", 0),
            "created_count": result.get("imported_count", 0),
            "duplicate_count": 0,
            "failed_count": result.get("missing_count", 0),
        },
    )
    return {**result, "import_job_id": import_job_id}


def _get_order_import_job_row(conn: sqlite3.Connection, import_job_id: int) -> sqlite3.Row:
    row = conn.execute(
        """
        SELECT
            import_job_id,
            import_type,
            source_name,
            source_content,
            request_metadata,
            continue_on_error,
            status,
            processed,
            created_count,
            duplicate_count,
            failed_count,
            lifecycle_state,
            created_at,
            undone_at,
            redo_of_job_id,
            last_redo_job_id
        FROM import_jobs
        WHERE import_job_id = ? AND import_type = 'orders'
        """,
        (import_job_id,),
    ).fetchone()
    if row is None:
        raise AppError(
            code="IMPORT_JOB_NOT_FOUND",
            message=f"Order import job {import_job_id} not found",
            status_code=404,
        )
    return row


def list_order_import_jobs(
    conn: sqlite3.Connection,
    *,
    page: int = 1,
    per_page: int = 50,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    sql = """
        SELECT
            import_job_id,
            import_type,
            source_name,
            request_metadata,
            continue_on_error,
            status,
            processed,
            created_count,
            duplicate_count,
            failed_count,
            lifecycle_state,
            created_at,
            undone_at,
            redo_of_job_id,
            last_redo_job_id
        FROM import_jobs
        WHERE import_type = 'orders'
        ORDER BY created_at DESC, import_job_id DESC
    """
    rows, pagination = _paginate(conn, sql, tuple(), page, per_page)
    return [_normalize_import_job_row(row) for row in rows], pagination


def get_order_import_job(conn: sqlite3.Connection, import_job_id: int) -> dict[str, Any]:
    job = _normalize_import_job_row(_get_order_import_job_row(conn, import_job_id))
    effects = conn.execute(
        """
        SELECT
            effect_id,
            import_job_id,
            row_number,
            status,
            entry_type,
            effect_type,
            item_id,
            alias_id,
            supplier_id,
            item_number,
            supplier_name,
            canonical_item_number,
            units_per_order,
            message,
            code,
            before_state,
            after_state,
            created_at
        FROM import_job_effects
        WHERE import_job_id = ?
        ORDER BY row_number, effect_id
        """,
        (import_job_id,),
    ).fetchall()
    return {
        "job": job,
        "effects": [_normalize_import_job_effect_row(row) for row in effects],
    }


def undo_orders_import_job(conn: sqlite3.Connection, import_job_id: int) -> dict[str, Any]:
    job_row = _get_order_import_job_row(conn, import_job_id)
    job = _normalize_import_job_row(job_row)
    if job["lifecycle_state"] == "undone":
        raise AppError(
            code="IMPORT_JOB_ALREADY_UNDONE",
            message=f"Order import job {import_job_id} has already been undone",
            status_code=409,
        )

    effects = conn.execute(
        """
        SELECT
            effect_id,
            row_number,
            status,
            entry_type,
            effect_type,
            item_id,
            alias_id,
            supplier_id,
            item_number,
            supplier_name,
            canonical_item_number,
            units_per_order,
            message,
            code,
            before_state,
            after_state
        FROM import_job_effects
        WHERE import_job_id = ? AND status = 'created'
        ORDER BY effect_id DESC
        """,
        (import_job_id,),
    ).fetchall()
    effect_rows = [_normalize_import_job_effect_row(row) for row in effects]
    order_effects = [row for row in effect_rows if row["effect_type"] == "order_created"]
    quotation_effects = [row for row in effect_rows if row["effect_type"] in {"quotation_created", "quotation_updated"}]
    purchase_order_effects = [
        row for row in effect_rows if row["effect_type"] in {"purchase_order_created", "purchase_order_updated"}
    ]
    alias_effects = [row for row in effect_rows if row["effect_type"] in {"alias_created", "alias_updated"}]

    savepoint = f"sp_undo_orders_import_{uuid4().hex}"
    conn.execute(f"SAVEPOINT {savepoint}")
    removed_orders = 0
    removed_quotations = 0
    restored_quotations = 0
    removed_aliases = 0
    restored_aliases = 0
    try:
        for effect in order_effects:
            effect_id = int(effect["effect_id"])
            row_number = int(effect["row_number"])
            after_state = effect.get("after_state")
            if not isinstance(after_state, dict):
                _raise_import_undo_conflict(
                    "Missing order after_state snapshot for undo",
                    effect_id=effect_id,
                    row_number=row_number,
                )
            order_id = int(after_state["order_id"])
            current_row = conn.execute(
                """
                SELECT
                    order_id,
                    item_id,
                    quotation_id,
                    purchase_order_id,
                    order_amount,
                    ordered_quantity,
                    ordered_item_number,
                    order_date,
                    expected_arrival,
                    status,
                    project_id
                FROM orders
                WHERE order_id = ?
                """,
                (order_id,),
            ).fetchone()
            current_order = dict(current_row) if current_row is not None else None
            if not _import_job_matches_state(
                current_order,
                after_state,
                (
                    "order_id",
                    "item_id",
                    "quotation_id",
                    "purchase_order_id",
                    "order_amount",
                    "ordered_quantity",
                    "ordered_item_number",
                    "order_date",
                    "expected_arrival",
                    "status",
                    "project_id",
                ),
            ):
                _raise_import_undo_conflict(
                    f"Order was modified after import; cannot safely undo row {row_number}",
                    effect_id=effect_id,
                    row_number=row_number,
                )

            lineage_row = conn.execute(
                """
                SELECT COUNT(*) AS c
                FROM order_lineage_events
                WHERE source_purchase_order_line_id = ? OR target_purchase_order_line_id = ?
                """,
                (order_id, order_id),
            ).fetchone()
            if int(lineage_row["c"] or 0) > 0:
                _raise_import_undo_conflict(
                    f"Order has lineage history and cannot be safely undone (row {row_number})",
                    effect_id=effect_id,
                    row_number=row_number,
                )

            procurement_row = conn.execute(
                "SELECT COUNT(*) AS c FROM procurement_lines WHERE linked_order_id = ?",
                (order_id,),
            ).fetchone()
            if int(procurement_row["c"] or 0) > 0:
                _raise_import_undo_conflict(
                    f"Order is linked to procurement workflow and cannot be safely undone (row {row_number})",
                    effect_id=effect_id,
                    row_number=row_number,
                )

            rfq_row = conn.execute(
                "SELECT COUNT(*) AS c FROM rfq_lines WHERE linked_order_id = ?",
                (order_id,),
            ).fetchone()
            if int(rfq_row["c"] or 0) > 0:
                _raise_import_undo_conflict(
                    f"Order is linked to RFQ workflow and cannot be safely undone (row {row_number})",
                    effect_id=effect_id,
                    row_number=row_number,
                )

            conn.execute("DELETE FROM orders WHERE order_id = ?", (order_id,))
            removed_orders += 1

        for effect in quotation_effects:
            effect_id = int(effect["effect_id"])
            row_number = int(effect["row_number"])
            effect_type = str(effect["effect_type"])
            after_state = effect.get("after_state")
            if not isinstance(after_state, dict):
                _raise_import_undo_conflict(
                    "Missing quotation after_state snapshot for undo",
                    effect_id=effect_id,
                    row_number=row_number,
                )
            quotation_id = int(after_state["quotation_id"])
            current_quotation = _get_quotation_row_by_id(conn, quotation_id)
            if not _import_job_matches_state(
                current_quotation,
                after_state,
                ("quotation_id", "supplier_id", "quotation_number", "issue_date", "quotation_document_url"),
            ):
                _raise_import_undo_conflict(
                    f"Quotation was modified after import; cannot safely undo row {row_number}",
                    effect_id=effect_id,
                    row_number=row_number,
                )

            remaining_orders = conn.execute(
                "SELECT COUNT(*) AS c FROM orders WHERE quotation_id = ?",
                (quotation_id,),
            ).fetchone()
            if int(remaining_orders["c"] or 0) > 0:
                _raise_import_undo_conflict(
                    f"Quotation is now referenced by orders outside the import job and cannot be safely undone (row {row_number})",
                    effect_id=effect_id,
                    row_number=row_number,
                )

            if effect_type == "quotation_created":
                conn.execute("DELETE FROM quotations WHERE quotation_id = ?", (quotation_id,))
                removed_quotations += 1
                continue

            before_state = effect.get("before_state")
            if not isinstance(before_state, dict):
                _raise_import_undo_conflict(
                    "Missing quotation before_state snapshot for undo",
                    effect_id=effect_id,
                    row_number=row_number,
                )
            conn.execute(
                """
                UPDATE quotations
                SET issue_date = ?, quotation_document_url = ?
                WHERE quotation_id = ?
                """,
                (
                    before_state.get("issue_date"),
                    before_state.get("quotation_document_url"),
                    quotation_id,
                ),
            )
            restored_quotations += 1

        for effect in purchase_order_effects:
            effect_id = int(effect["effect_id"])
            row_number = int(effect["row_number"])
            effect_type = str(effect["effect_type"])
            after_state = effect.get("after_state")
            if not isinstance(after_state, dict):
                _raise_import_undo_conflict(
                    "Missing purchase order after_state snapshot for undo",
                    effect_id=effect_id,
                    row_number=row_number,
                )
            purchase_order_id = int(after_state["purchase_order_id"])
            current_purchase_order = _get_purchase_order_row_by_id(conn, purchase_order_id)
            if not _import_job_matches_state(
                current_purchase_order,
                after_state,
                (
                    "purchase_order_id",
                    "supplier_id",
                    "purchase_order_number",
                    "purchase_order_document_url",
                    "import_locked",
                ),
            ):
                _raise_import_undo_conflict(
                    f"Purchase order was modified after import; cannot safely undo row {row_number}",
                    effect_id=effect_id,
                    row_number=row_number,
                )

            remaining_orders = conn.execute(
                "SELECT COUNT(*) AS c FROM orders WHERE purchase_order_id = ?",
                (purchase_order_id,),
            ).fetchone()
            if int(remaining_orders["c"] or 0) > 0:
                _raise_import_undo_conflict(
                    (
                        "Purchase order is now referenced by order lines outside the import job "
                        f"and cannot be safely undone (row {row_number})"
                    ),
                    effect_id=effect_id,
                    row_number=row_number,
                )

            if effect_type == "purchase_order_created":
                conn.execute("DELETE FROM purchase_orders WHERE purchase_order_id = ?", (purchase_order_id,))
                removed_quotations += 0
                continue

            before_state = effect.get("before_state")
            if not isinstance(before_state, dict):
                _raise_import_undo_conflict(
                    "Missing purchase order before_state snapshot for undo",
                    effect_id=effect_id,
                    row_number=row_number,
                )
            conn.execute(
                """
                UPDATE purchase_orders
                SET purchase_order_number = ?,
                    purchase_order_document_url = ?,
                    import_locked = ?
                WHERE purchase_order_id = ?
                """,
                (
                    before_state.get("purchase_order_number"),
                    before_state.get("purchase_order_document_url"),
                    bool(before_state.get("import_locked", True)),
                    purchase_order_id,
                ),
            )

        for effect in alias_effects:
            effect_id = int(effect["effect_id"])
            row_number = int(effect["row_number"])
            effect_type = str(effect["effect_type"])
            after_state = effect.get("after_state")
            if not isinstance(after_state, dict):
                _raise_import_undo_conflict(
                    "Missing alias after_state snapshot for undo",
                    effect_id=effect_id,
                    row_number=row_number,
                )
            supplier_id = int(after_state["supplier_id"])
            ordered_item_number = str(after_state["ordered_item_number"])
            current_alias = _alias_row_by_supplier_and_ordered(
                conn,
                supplier_id=supplier_id,
                ordered_item_number=ordered_item_number,
            )
            if effect_type == "alias_created":
                if not _import_job_matches_state(
                    current_alias,
                    after_state,
                    (
                        "alias_id",
                        "supplier_id",
                        "ordered_item_number",
                        "canonical_item_id",
                        "units_per_order",
                    ),
                ):
                    _raise_import_undo_conflict(
                        f"Alias no longer matches imported state; cannot safely undo row {row_number}",
                        effect_id=effect_id,
                        row_number=row_number,
                    )
                delete_supplier_item_alias(conn, int(current_alias["alias_id"]))
                removed_aliases += 1
                continue

            before_state = effect.get("before_state")
            if not isinstance(before_state, dict):
                _raise_import_undo_conflict(
                    "Missing alias before_state snapshot for undo",
                    effect_id=effect_id,
                    row_number=row_number,
                )
            if not _import_job_matches_state(
                current_alias,
                after_state,
                (
                    "alias_id",
                    "supplier_id",
                    "ordered_item_number",
                    "canonical_item_id",
                    "units_per_order",
                ),
            ):
                _raise_import_undo_conflict(
                    f"Alias was modified after import; cannot safely undo row {row_number}",
                    effect_id=effect_id,
                    row_number=row_number,
                )
            upsert_supplier_item_alias(
                conn,
                supplier_id=int(before_state["supplier_id"]),
                ordered_item_number=str(before_state["ordered_item_number"]),
                canonical_item_id=int(before_state["canonical_item_id"]),
                units_per_order=int(before_state["units_per_order"]),
            )
            restored_aliases += 1

        undone_at = now_jst_iso()
        conn.execute(
            """
            UPDATE import_jobs
            SET lifecycle_state = 'undone', undone_at = ?
            WHERE import_job_id = ?
            """,
            (undone_at, import_job_id),
        )
        conn.execute(f"RELEASE {savepoint}")
        return {
            "import_job_id": import_job_id,
            "status": "undone",
            "undone_at": undone_at,
            "removed_orders": removed_orders,
            "removed_quotations": removed_quotations,
            "restored_quotations": restored_quotations,
            "removed_aliases": removed_aliases,
            "restored_aliases": restored_aliases,
        }
    except Exception:
        conn.execute(f"ROLLBACK TO {savepoint}")
        conn.execute(f"RELEASE {savepoint}")
        raise


def redo_orders_import_job(conn: sqlite3.Connection, import_job_id: int) -> dict[str, Any]:
    job_row = _get_order_import_job_row(conn, import_job_id)
    job = _normalize_import_job_row(job_row)
    if job["lifecycle_state"] != "undone":
        raise AppError(
            code="IMPORT_JOB_REDO_REQUIRES_UNDONE",
            message=f"Order import job {import_job_id} must be undone before redo",
            status_code=409,
        )
    source_text = str(job_row["source_content"] or "")
    if not source_text:
        raise AppError(
            code="IMPORT_JOB_SOURCE_MISSING",
            message=f"Order import job {import_job_id} does not have source content to redo",
            status_code=422,
        )
    request_metadata = job.get("request_metadata") or {}
    result = import_orders_from_content_with_job(
        conn,
        supplier_id=request_metadata.get("supplier_id"),
        supplier_name=request_metadata.get("supplier_name"),
        content=source_text.encode("utf-8"),
        source_name=str(job_row["source_name"]),
        missing_output_dir=None,
        row_overrides=request_metadata.get("row_overrides"),
        alias_saves=request_metadata.get("alias_saves"),
        unlock_purchase_orders=request_metadata.get("unlock_purchase_orders"),
        redo_of_job_id=import_job_id,
    )
    redo_job_id = int(result["import_job_id"])
    conn.execute(
        "UPDATE import_jobs SET last_redo_job_id = ? WHERE import_job_id = ?",
        (redo_job_id, import_job_id),
    )
    return {
        "source_job_id": import_job_id,
        "redo_job_id": redo_job_id,
        "import_result": result,
    }


def preview_orders_import_from_content(
    conn: sqlite3.Connection,
    *,
    supplier_id: int | None = None,
    supplier_name: str | None = None,
    content: bytes,
    source_name: str = "order_import.csv",
) -> dict[str, Any]:
    rows = _load_csv_rows_from_content(content)
    return preview_orders_import_from_rows(
        conn,
        supplier_id=supplier_id,
        supplier_name=supplier_name,
        rows=rows,
        source_name=source_name,
    )


def import_orders_from_csv_path(
    conn: sqlite3.Connection,
    *,
    supplier_name: str,
    csv_path: str | Path,
    missing_output_dir: str | Path | None = None,
) -> dict[str, Any]:
    rows = _load_csv_rows_from_path(csv_path)
    return import_orders_from_rows(
        conn,
        supplier_name=supplier_name,
        rows=rows,
        source_name=Path(csv_path).name,
        missing_output_dir=missing_output_dir,
    )


def _import_unregistered_order_csv_file(
    conn: sqlite3.Connection,
    *,
    roots: OrderImportRoots,
    csv_path: Path,
    supplier_name: str,
    items_unregistered_root: Path | None = None,
) -> dict[str, Any]:
    unregistered_items_root = items_unregistered_root if items_unregistered_root else ITEMS_IMPORT_UNREGISTERED_ROOT
    fieldnames, rows = _load_csv_rows_with_fieldnames_from_path(csv_path)
    result = import_orders_from_rows(
        conn,
        supplier_name=supplier_name,
        rows=rows,
        source_name=f"{_safe_filename_component(supplier_name)}__{csv_path.name}",
        missing_output_dir=unregistered_items_root,
    )
    file_warnings: list[str] = []
    file_normalizations: list[dict[str, str]] = []

    if result["status"] == "missing_items":
        return {
            "file": str(csv_path),
            "supplier": supplier_name,
            "status": "missing_items",
            "missing_count": result.get("missing_count", 0),
            "missing_csv_path": result.get("missing_csv_path"),
            "missing_artifact": result.get("missing_artifact"),
            "missing_rows": result.get("rows", []),
            "warnings": file_warnings,
            "normalizations": file_normalizations,
        }

    use_storage_registered_roots = (
        not is_local_storage_backend()
        or (
            roots.registered_csv_root.resolve() == ORDERS_IMPORT_REGISTERED_CSV_ROOT.resolve()
            and roots.registered_pdf_root.resolve() == ORDERS_IMPORT_REGISTERED_PDF_ROOT.resolve()
        )
    )

    csv_source = csv_path.resolve()
    if use_storage_registered_roots:
        rollback_storage_refs: list[str] = []
        csv_dest_display: str | None = None
        try:
            stored_csv = move_file_to_storage(
                bucket=ORDERS_REGISTERED_CSV_BUCKET,
                source_path=csv_source,
                subdir=supplier_name,
            )
            rollback_storage_refs.append(stored_csv.storage_ref)
            csv_dest = stored_csv.path
            csv_dest_display = stored_csv.storage_ref if stored_csv.path is None else str(stored_csv.path)
        except Exception:
            for storage_ref in reversed(rollback_storage_refs):
                delete_storage_ref(storage_ref)
            raise
    else:
        csv_dest, _ = _predict_move_target(
            csv_source,
            registered_csv_supplier_dir(roots, supplier_name).resolve(),
            set(),
        )
        _execute_planned_file_moves([(csv_source, csv_dest.resolve())])
        csv_dest_display = str(csv_dest)
    return {
        "file": str(csv_path),
        "supplier": supplier_name,
        "status": "ok",
        "moved_to": csv_dest_display,
        "imported_count": result.get("imported_count", 0),
        "moved_pdf_files": [],
        "warnings": file_warnings,
        "normalizations": file_normalizations,
    }


def _predict_move_target(src: Path, dst_dir: Path, reserved_targets: set[str]) -> tuple[Path, bool]:
    target = dst_dir / src.name
    target_key = str(target).casefold()
    if target_key not in reserved_targets and not target.exists():
        return target, False

    stem = src.stem
    suffix = src.suffix
    idx = 1
    while True:
        candidate = dst_dir / f"{stem}_{idx}{suffix}"
        candidate_key = str(candidate).casefold()
        if candidate_key not in reserved_targets and not candidate.exists():
            return candidate, True
        idx += 1

def process_order_arrival(
    conn: sqlite3.Connection,
    *,
    order_id: int,
    quantity: int | None = None,
) -> dict[str, Any]:
    order = get_order(conn, order_id)
    _lock_order_item_state(conn, order_id, int(order["item_id"]))
    order = get_order(conn, order_id)
    # Validate the ownership boundary against the serialized post-lock state.
    _assert_order_is_locally_managed(order)
    if order["status"] == "Arrived":
        raise AppError(
            code="ORDER_ALREADY_ARRIVED",
            message=f"Order {order_id} is already arrived",
            status_code=409,
        )
    order_amount = int(order["order_amount"])
    arrived_qty = order_amount if quantity is None else int(quantity)
    require_positive_int(arrived_qty, "quantity")
    if arrived_qty > order_amount:
        raise AppError(
            code="INVALID_ARRIVAL_QUANTITY",
            message="Arrival quantity cannot exceed open order_amount",
            status_code=422,
        )
    split_order_id: int | None = None
    if arrived_qty == order_amount:
        conn.execute(
            """
            UPDATE orders
            SET status = 'Arrived', arrival_date = ?
            WHERE order_id = ?
            """,
            (today_jst(), order_id),
        )
    else:
        original_ordered_qty = int(order["ordered_quantity"] or order_amount)
        arrived_ordered = original_ordered_qty * arrived_qty
        if arrived_ordered % order_amount != 0:
            raise AppError(
                code="PARTIAL_SPLIT_NOT_INTEGER_SAFE",
                message="Cannot split traceability quantities without fractional values",
                status_code=409,
            )
        arrived_ordered //= order_amount
        remaining_ordered = original_ordered_qty - arrived_ordered
        remaining_order_amount = order_amount - arrived_qty
        if arrived_ordered <= 0 or remaining_ordered <= 0 or remaining_order_amount <= 0:
            raise AppError(
                code="INVALID_PARTIAL_SPLIT",
                message="Partial arrival split would produce invalid quantities",
                status_code=409,
            )
        conn.execute(
            """
            UPDATE orders
            SET order_amount = ?, ordered_quantity = ?, status = 'Arrived', arrival_date = ?
            WHERE order_id = ?
            """,
            (arrived_qty, arrived_ordered, today_jst(), order_id),
        )
        cur = conn.execute(
            """
            INSERT INTO orders (
                item_id, quotation_id, purchase_order_id, project_id, project_id_manual, order_amount, ordered_quantity,
                ordered_item_number, order_date, expected_arrival, arrival_date, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 'Ordered')
            """,
            (
                order["item_id"],
                order["quotation_id"],
                order["purchase_order_id"],
                order.get("project_id"),
                order.get("project_id_manual") or 0,
                remaining_order_amount,
                remaining_ordered,
                order["ordered_item_number"],
                order["order_date"],
                order["expected_arrival"],
            ),
        )
        split_order_id = int(cur.lastrowid)
        _record_order_lineage_event(
            conn,
            event_type="ARRIVAL_SPLIT",
            source_purchase_order_line_id=order_id,
            target_purchase_order_line_id=split_order_id,
            quantity=arrived_qty,
            previous_expected_arrival=order.get("expected_arrival"),
            new_expected_arrival=order.get("expected_arrival"),
            note="partial arrival split",
        )
        _record_local_order_split(
            conn,
            split_type="ARRIVAL_SPLIT",
            root_order_id=int(order.get("split_root_order_id") or order_id),
            child_order_id=split_order_id,
            split_quantity=remaining_order_amount,
            root_expected_arrival=order.get("expected_arrival"),
            child_expected_arrival=order.get("expected_arrival"),
        )

    _apply_inventory_delta(conn, int(order["item_id"]), "STOCK", arrived_qty)
    log = _log_transaction(
        conn,
        operation_type="ARRIVAL",
        item_id=int(order["item_id"]),
        quantity=arrived_qty,
        from_location=None,
        to_location="STOCK",
        note=f"order_id={order_id}",
        batch_id=f"arrival-{order_id}",
    )
    return {
        "order_id": order_id,
        "arrived_quantity": arrived_qty,
        "split_order_id": split_order_id,
        "transaction": log,
    }


def list_quotations(
    conn: sqlite3.Connection,
    *,
    supplier: str | None = None,
    page: int = 1,
    per_page: int = 50,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if supplier:
        clauses.append("s.name = ?")
        params.append(supplier)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"""
        SELECT q.*, s.name AS supplier_name
        FROM quotations q
        JOIN suppliers s ON s.supplier_id = q.supplier_id
        {where}
        ORDER BY q.issue_date DESC, q.quotation_id DESC
    """
    return _paginate(conn, sql, tuple(params), page, per_page)


def list_purchase_orders(
    conn: sqlite3.Connection,
    *,
    supplier: str | None = None,
    page: int = 1,
    per_page: int = 50,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if supplier:
        clauses.append("s.name = ?")
        params.append(supplier)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"""
        SELECT
            po.purchase_order_id,
            po.supplier_id,
            s.name AS supplier_name,
            po.purchase_order_number,
            po.purchase_order_document_url,
            po.import_locked,
            COUNT(o.order_id) AS line_count,
            MIN(o.order_date) AS first_order_date,
            MAX(o.order_date) AS last_order_date
        FROM purchase_orders po
        JOIN suppliers s ON s.supplier_id = po.supplier_id
        LEFT JOIN orders o ON o.purchase_order_id = po.purchase_order_id
        {where}
        GROUP BY
            po.purchase_order_id,
            po.supplier_id,
            s.name,
            po.purchase_order_number,
            po.purchase_order_document_url,
            po.import_locked
        ORDER BY COALESCE(MAX(o.order_date), '0001-01-01') DESC, po.purchase_order_id DESC
    """
    return _paginate(conn, sql, tuple(params), page, per_page)


def update_quotation(conn: sqlite3.Connection, quotation_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    _get_entity_or_404(
        conn,
        "quotations",
        "quotation_id",
        quotation_id,
        "QUOTATION_NOT_FOUND",
        f"Quotation with id {quotation_id} not found",
    )
    next_issue_date = normalize_optional_date(payload.get("issue_date"), "issue_date")
    next_document_url = (
        normalize_document_reference(payload.get("quotation_document_url"), "quotation_document_url")
        if "quotation_document_url" in payload
        else None
    )
    conn.execute(
        """
        UPDATE quotations
        SET issue_date = COALESCE(?, issue_date),
            quotation_document_url = COALESCE(?, quotation_document_url)
        WHERE quotation_id = ?
        """,
        (
            next_issue_date,
            next_document_url,
            quotation_id,
        ),
    )
    row = conn.execute(
        """
        SELECT q.*, s.name AS supplier_name
        FROM quotations q
        JOIN suppliers s ON s.supplier_id = q.supplier_id
        WHERE q.quotation_id = ?
        """,
        (quotation_id,),
    ).fetchone()
    updated = dict(row)

    return updated


def update_purchase_order(conn: sqlite3.Connection, purchase_order_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    _get_entity_or_404(
        conn,
        "purchase_orders",
        "purchase_order_id",
        purchase_order_id,
        "PURCHASE_ORDER_NOT_FOUND",
        f"Purchase order with id {purchase_order_id} not found",
    )
    current = _get_purchase_order_row_by_id(conn, purchase_order_id)
    if current is None:
        raise AppError(
            code="PURCHASE_ORDER_NOT_FOUND",
            message=f"Purchase order with id {purchase_order_id} not found",
            status_code=404,
        )
    next_purchase_order_number = (
        _normalize_required_purchase_order_number(
            payload.get("purchase_order_number"),
            field_name="purchase_order_number",
            code="INVALID_PURCHASE_ORDER",
        )
        if "purchase_order_number" in payload
        else current.get("purchase_order_number")
    )
    next_document_url = (
        normalize_document_reference(payload.get("purchase_order_document_url"), "purchase_order_document_url")
        if "purchase_order_document_url" in payload
        else current.get("purchase_order_document_url")
    )
    next_import_locked = (
        bool(payload.get("import_locked"))
        if "import_locked" in payload
        else bool(current.get("import_locked"))
    )
    if next_purchase_order_number is not None:
        _lock_purchase_order_number_state(conn, int(current["supplier_id"]), next_purchase_order_number)
    duplicate_number = _find_purchase_order_row(
        conn,
        supplier_id=int(current["supplier_id"]),
        purchase_order_number=next_purchase_order_number,
    )
    if duplicate_number is not None and int(duplicate_number["purchase_order_id"]) != purchase_order_id:
        raise AppError(
            code="PURCHASE_ORDER_ALREADY_EXISTS",
            message="Another purchase order already uses this purchase order number for the same supplier",
            status_code=409,
        )
    duplicate_document = _find_purchase_order_row_by_document_url(
        conn,
        supplier_id=int(current["supplier_id"]),
        purchase_order_document_url=next_document_url,
    )
    if duplicate_document is not None and int(duplicate_document["purchase_order_id"]) != purchase_order_id:
        raise AppError(
            code="PURCHASE_ORDER_ALREADY_EXISTS",
            message="Another purchase order already uses this document URL for the same supplier",
            status_code=409,
        )
    conn.execute(
        """
        UPDATE purchase_orders
        SET purchase_order_number = ?,
            purchase_order_document_url = ?,
            import_locked = ?
        WHERE purchase_order_id = ?
        """,
        (next_purchase_order_number, next_document_url, next_import_locked, purchase_order_id),
    )
    updated = _get_purchase_order_row_by_id(conn, purchase_order_id)
    return updated if updated is not None else {"purchase_order_id": purchase_order_id}


def delete_quotation(conn: sqlite3.Connection, quotation_id: int) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT q.*, s.name AS supplier_name
        FROM quotations q
        JOIN suppliers s ON s.supplier_id = q.supplier_id
        WHERE q.quotation_id = ?
        """,
        (quotation_id,),
    ).fetchone()
    if row is None:
        raise AppError(
            code="QUOTATION_NOT_FOUND",
            message=f"Quotation with id {quotation_id} not found",
            status_code=404,
        )

    arrived_count_row = conn.execute(
        "SELECT COUNT(*) AS c FROM orders WHERE quotation_id = ? AND status = 'Arrived'",
        (quotation_id,),
    ).fetchone()
    if int(arrived_count_row["c"] or 0) > 0:
        raise AppError(
            code="QUOTATION_HAS_ARRIVED_ORDERS",
            message="Quotations linked to arrived orders cannot be deleted",
            status_code=409,
        )

    linked_purchase_order_rows = conn.execute(
        "SELECT DISTINCT purchase_order_id FROM orders WHERE quotation_id = ?",
        (quotation_id,),
    ).fetchall()
    conn.execute("DELETE FROM orders WHERE quotation_id = ?", (quotation_id,))
    try:
        conn.execute("DELETE FROM quotations WHERE quotation_id = ?", (quotation_id,))
    except sqlite3.IntegrityError as exc:
        raise AppError(
            code="QUOTATION_REFERENCED",
            message="Quotation cannot be deleted because it is referenced by one or more orders",
            status_code=409,
        ) from exc
    deleted_purchase_orders = 0
    for purchase_order_row in linked_purchase_order_rows:
        if _delete_purchase_order_if_orphaned(conn, int(purchase_order_row["purchase_order_id"])):
            deleted_purchase_orders += 1

    return {
        "deleted": True,
        "quotation_id": quotation_id,
        "deleted_purchase_orders": deleted_purchase_orders,
        "csv_sync": _csv_archive_sync_disabled_result(),
    }


def delete_purchase_order(conn: sqlite3.Connection, purchase_order_id: int) -> dict[str, Any]:
    row = _get_purchase_order_row_by_id(conn, purchase_order_id)
    if row is None:
        raise AppError(
            code="PURCHASE_ORDER_NOT_FOUND",
            message=f"Purchase order with id {purchase_order_id} not found",
            status_code=404,
        )

    arrived_count_row = conn.execute(
        "SELECT COUNT(*) AS c FROM orders WHERE purchase_order_id = ? AND status = 'Arrived'",
        (purchase_order_id,),
    ).fetchone()
    if int(arrived_count_row["c"] or 0) > 0:
        raise AppError(
            code="PURCHASE_ORDER_HAS_ARRIVED_LINES",
            message="Purchase orders linked to arrived lines cannot be deleted",
            status_code=409,
        )

    linked_quotation_rows = conn.execute(
        "SELECT DISTINCT quotation_id FROM orders WHERE purchase_order_id = ?",
        (purchase_order_id,),
    ).fetchall()
    conn.execute("DELETE FROM orders WHERE purchase_order_id = ?", (purchase_order_id,))
    try:
        conn.execute("DELETE FROM purchase_orders WHERE purchase_order_id = ?", (purchase_order_id,))
    except sqlite3.IntegrityError as exc:
        raise AppError(
            code="PURCHASE_ORDER_REFERENCED",
            message="Purchase order cannot be deleted because it is referenced by one or more lines",
            status_code=409,
        ) from exc
    deleted_quotations = 0
    for quotation_row in linked_quotation_rows:
        remaining = conn.execute(
            "SELECT COUNT(*) AS c FROM orders WHERE quotation_id = ?",
            (int(quotation_row["quotation_id"]),),
        ).fetchone()
        if int(remaining["c"] or 0) == 0:
            conn.execute("DELETE FROM quotations WHERE quotation_id = ?", (int(quotation_row["quotation_id"]),))
            deleted_quotations += 1
    return {
        "deleted": True,
        "purchase_order_id": purchase_order_id,
        "deleted_quotations": deleted_quotations,
        "csv_sync": _csv_archive_sync_disabled_result(),
    }


def list_reservations(
    conn: sqlite3.Connection,
    *,
    status: str | None = None,
    item_id: int | None = None,
    page: int = 1,
    per_page: int = 50,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if status:
        clauses.append("r.status = ?")
        params.append(status)
    if item_id:
        clauses.append("r.item_id = ?")
        params.append(item_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"""
        SELECT
            r.*,
            im.item_number,
            p.name AS project_name
        FROM reservations r
        JOIN items_master im ON im.item_id = r.item_id
        LEFT JOIN projects p ON p.project_id = r.project_id
        {where}
        ORDER BY r.created_at DESC, r.reservation_id DESC
    """
    return _paginate(conn, sql, tuple(params), page, per_page)


def get_reservation(conn: sqlite3.Connection, reservation_id: int) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT r.*, im.item_number, p.name AS project_name
        FROM reservations r
        JOIN items_master im ON im.item_id = r.item_id
        LEFT JOIN projects p ON p.project_id = r.project_id
        WHERE r.reservation_id = ?
        """,
        (reservation_id,),
    ).fetchone()
    if row is None:
        raise AppError(
            code="RESERVATION_NOT_FOUND",
            message=f"Reservation with id {reservation_id} not found",
            status_code=404,
        )
    return dict(row)


def create_reservation(conn: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    item_id = int(payload["item_id"])
    quantity = require_positive_int(int(payload["quantity"]), "quantity")
    project_id = payload.get("project_id")
    if project_id is not None:
        project_id = int(project_id)
        _get_entity_or_404(
            conn,
            "projects",
            "project_id",
            project_id,
            "PROJECT_NOT_FOUND",
            f"Project with id {project_id} not found",
        )
    _get_entity_or_404(
        conn,
        "items_master",
        "item_id",
        item_id,
        "ITEM_NOT_FOUND",
        f"Item with id {item_id} not found",
    )
    _lock_inventory_item_state(conn, item_id)
    available_rows = _list_item_available_inventory(conn, item_id)
    total_available = sum(qty for _, qty in available_rows)
    if total_available < quantity:
        raise AppError(
            code="INSUFFICIENT_STOCK",
            message="Not enough available inventory for reservation",
            status_code=409,
            details={
                "item_id": item_id,
                "requested": quantity,
                "available": total_available,
            },
        )
    cur = conn.execute(
        """
        INSERT INTO reservations (
            item_id, quantity, purpose, deadline, created_at, status, note, project_id
        ) VALUES (?, ?, ?, ?, ?, 'ACTIVE', ?, ?)
        """,
        (
            item_id,
            quantity,
            payload.get("purpose"),
            normalize_optional_date(payload.get("deadline"), "deadline"),
            now_jst_iso(),
            payload.get("note"),
            project_id,
        ),
    )
    _log_transaction(
        conn,
        operation_type="RESERVE",
        item_id=item_id,
        quantity=quantity,
        from_location=None,
        to_location=None,
        note=payload.get("note") or payload.get("purpose"),
        batch_id=f"reservation-{cur.lastrowid}",
    )
    remaining_to_allocate = quantity
    for location, available in available_rows:
        if remaining_to_allocate <= 0:
            break
        allocated = min(available, remaining_to_allocate)
        conn.execute(
            """
            INSERT INTO reservation_allocations (
                reservation_id,
                item_id,
                location,
                quantity,
                status,
                created_at,
                note
            ) VALUES (?, ?, ?, ?, 'ACTIVE', ?, ?)
            """,
            (
                int(cur.lastrowid),
                item_id,
                location,
                allocated,
                now_jst_iso(),
                payload.get("note") or payload.get("purpose"),
            ),
        )
        remaining_to_allocate -= allocated
    return get_reservation(conn, int(cur.lastrowid))


def update_reservation(conn: sqlite3.Connection, reservation_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    reservation = get_reservation(conn, reservation_id)
    if reservation["status"] != "ACTIVE":
        raise AppError(
            code="RESERVATION_NOT_ACTIVE",
            message="Only ACTIVE reservations can be updated",
            status_code=409,
        )
    conn.execute(
        """
        UPDATE reservations
        SET purpose = COALESCE(?, purpose),
            deadline = COALESCE(?, deadline),
            note = COALESCE(?, note)
        WHERE reservation_id = ?
        """,
        (
            payload.get("purpose"),
            normalize_optional_date(payload.get("deadline"), "deadline"),
            payload.get("note"),
            reservation_id,
        ),
    )
    return get_reservation(conn, reservation_id)


def release_reservation(
    conn: sqlite3.Connection,
    reservation_id: int,
    *,
    quantity: int | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    reservation = get_reservation(conn, reservation_id)
    _lock_reservation_item_state(conn, reservation_id, int(reservation["item_id"]))
    reservation = get_reservation(conn, reservation_id)
    if reservation["status"] != "ACTIVE":
        raise AppError(
            code="RESERVATION_NOT_ACTIVE",
            message="Only ACTIVE reservations can be released",
            status_code=409,
        )
    reserved_quantity = int(reservation["quantity"])
    release_quantity = reserved_quantity if quantity is None else require_positive_int(int(quantity), "quantity")
    if release_quantity > reserved_quantity:
        raise AppError(
            code="INVALID_RESERVATION_QUANTITY",
            message="Release quantity cannot exceed remaining reservation quantity",
            status_code=422,
            details={
                "reservation_id": reservation_id,
                "requested": release_quantity,
                "remaining": reserved_quantity,
            },
        )
    item_id = int(reservation["item_id"])
    allocations = conn.execute(
        """
        SELECT allocation_id, location, quantity, note
        FROM reservation_allocations
        WHERE reservation_id = ? AND status = 'ACTIVE'
        ORDER BY allocation_id
        """,
        (reservation_id,),
    ).fetchall()
    allocatable_quantity = sum(int(alloc["quantity"]) for alloc in allocations)
    if allocatable_quantity < release_quantity:
        raise AppError(
            code="RESERVATION_ALLOCATION_INCONSISTENT",
            message="Active allocation quantity is insufficient to release requested amount",
            status_code=409,
            details={
                "reservation_id": reservation_id,
                "requested": release_quantity,
                "active_allocation_quantity": allocatable_quantity,
            },
        )
    log = _log_transaction(
        conn,
        operation_type="RESERVE",
        item_id=item_id,
        quantity=release_quantity,
        from_location=None,
        to_location=None,
        note=note or (
            f"release reservation {reservation_id}"
            if reserved_quantity == release_quantity
            else f"partial release reservation {reservation_id} ({release_quantity}/{reserved_quantity})"
        ),
        batch_id=f"reservation-release-{reservation_id}",
    )
    log_id = int(log["log_id"])
    _set_transaction_batch_id(conn, log_id, f"reservation-release-{reservation_id}-log-{log_id}")
    remaining_to_release = release_quantity
    for alloc in allocations:
        if remaining_to_release <= 0:
            break
        alloc_qty = int(alloc["quantity"])
        consume_alloc = min(alloc_qty, remaining_to_release)
        left_qty = alloc_qty - consume_alloc
        allocation_note = _reservation_event_note(note, alloc["note"], log_id)
        if left_qty == 0:
            conn.execute(
                """
                UPDATE reservation_allocations
                SET status = 'RELEASED', released_at = ?, note = ?
                WHERE allocation_id = ?
                """,
                (log["timestamp"], allocation_note, int(alloc["allocation_id"])),
            )
        else:
            conn.execute(
                "UPDATE reservation_allocations SET quantity = ? WHERE allocation_id = ?",
                (left_qty, int(alloc["allocation_id"])),
            )
            conn.execute(
                """
                INSERT INTO reservation_allocations (
                    reservation_id, item_id, location, quantity, status, created_at, released_at, note
                )
                SELECT reservation_id, item_id, location, ?, 'RELEASED', ?, ?, ?
                FROM reservation_allocations
                WHERE allocation_id = ?
                """,
                (
                    consume_alloc,
                    log["timestamp"],
                    log["timestamp"],
                    allocation_note,
                    int(alloc["allocation_id"]),
                ),
            )
        remaining_to_release -= consume_alloc

    remaining = reserved_quantity - release_quantity
    if remaining == 0:
        conn.execute(
            """
            UPDATE reservations
            SET status = 'RELEASED', released_at = ?
            WHERE reservation_id = ?
            """,
            (log["timestamp"], reservation_id),
        )
    else:
        conn.execute(
            """
            UPDATE reservations
            SET quantity = ?
            WHERE reservation_id = ?
            """,
            (remaining, reservation_id),
        )
    return get_reservation(conn, reservation_id)


def consume_reservation(
    conn: sqlite3.Connection,
    reservation_id: int,
    *,
    quantity: int | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    reservation = get_reservation(conn, reservation_id)
    _lock_reservation_item_state(conn, reservation_id, int(reservation["item_id"]))
    reservation = get_reservation(conn, reservation_id)
    if reservation["status"] != "ACTIVE":
        raise AppError(
            code="RESERVATION_NOT_ACTIVE",
            message="Only ACTIVE reservations can be consumed",
            status_code=409,
        )
    reserved_quantity = int(reservation["quantity"])
    consume_quantity = reserved_quantity if quantity is None else require_positive_int(int(quantity), "quantity")
    if consume_quantity > reserved_quantity:
        raise AppError(
            code="INVALID_RESERVATION_QUANTITY",
            message="Consume quantity cannot exceed remaining reservation quantity",
            status_code=422,
            details={
                "reservation_id": reservation_id,
                "requested": consume_quantity,
                "remaining": reserved_quantity,
            },
        )
    item_id = int(reservation["item_id"])
    allocations = conn.execute(
        """
        SELECT allocation_id, location, quantity, note
        FROM reservation_allocations
        WHERE reservation_id = ? AND status = 'ACTIVE'
        ORDER BY allocation_id
        """,
        (reservation_id,),
    ).fetchall()
    allocatable_quantity = sum(int(alloc["quantity"]) for alloc in allocations)
    if allocatable_quantity < consume_quantity:
        raise AppError(
            code="RESERVATION_ALLOCATION_INCONSISTENT",
            message="Active allocation quantity is insufficient to consume requested amount",
            status_code=409,
            details={
                "reservation_id": reservation_id,
                "requested": consume_quantity,
                "active_allocation_quantity": allocatable_quantity,
            },
        )
    log = _log_transaction(
        conn,
        operation_type="CONSUME",
        item_id=item_id,
        quantity=consume_quantity,
        from_location=None,
        to_location=None,
        note=note or (
            f"consume reservation {reservation_id}"
            if reserved_quantity == consume_quantity
            else f"partial consume reservation {reservation_id} ({consume_quantity}/{reserved_quantity})"
        ),
        batch_id=f"reservation-consume-{reservation_id}",
    )
    log_id = int(log["log_id"])
    _set_transaction_batch_id(conn, log_id, f"reservation-consume-{reservation_id}-log-{log_id}")
    remaining_to_consume = consume_quantity
    for alloc in allocations:
        if remaining_to_consume <= 0:
            break
        alloc_qty = int(alloc["quantity"])
        use_qty = min(alloc_qty, remaining_to_consume)
        _apply_inventory_delta(conn, item_id, str(alloc["location"]), -use_qty)
        left_qty = alloc_qty - use_qty
        allocation_note = _reservation_event_note(note, alloc["note"], log_id)
        if left_qty == 0:
            conn.execute(
                """
                UPDATE reservation_allocations
                SET status = 'CONSUMED', released_at = ?, note = ?
                WHERE allocation_id = ?
                """,
                (log["timestamp"], allocation_note, int(alloc["allocation_id"])),
            )
        else:
            conn.execute(
                "UPDATE reservation_allocations SET quantity = ? WHERE allocation_id = ?",
                (left_qty, int(alloc["allocation_id"])),
            )
            conn.execute(
                """
                INSERT INTO reservation_allocations (
                    reservation_id, item_id, location, quantity, status, created_at, released_at, note
                )
                SELECT reservation_id, item_id, location, ?, 'CONSUMED', ?, ?, ?
                FROM reservation_allocations
                WHERE allocation_id = ?
                """,
                (
                    use_qty,
                    log["timestamp"],
                    log["timestamp"],
                    allocation_note,
                    int(alloc["allocation_id"]),
                ),
            )
        remaining_to_consume -= use_qty

    remaining = reserved_quantity - consume_quantity
    if remaining == 0:
        conn.execute(
            """
            UPDATE reservations
            SET status = 'CONSUMED', released_at = ?
            WHERE reservation_id = ?
            """,
            (log["timestamp"], reservation_id),
        )
    else:
        conn.execute(
            """
            UPDATE reservations
            SET quantity = ?
            WHERE reservation_id = ?
            """,
            (remaining, reservation_id),
        )
    return get_reservation(conn, reservation_id)


def batch_create_reservations(
    conn: sqlite3.Connection, reservations: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    created: list[dict[str, Any]] = []
    for payload in reservations:
        created.append(create_reservation(conn, payload))
    return created


def list_assemblies(
    conn: sqlite3.Connection, *, page: int = 1, per_page: int = 50
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    sql = """
        SELECT
            a.*,
            COUNT(ac.item_id) AS component_count
        FROM assemblies a
        LEFT JOIN assembly_components ac ON ac.assembly_id = a.assembly_id
        GROUP BY a.assembly_id
        ORDER BY a.name
    """
    return _paginate(conn, sql, (), page, per_page)


def get_assembly(conn: sqlite3.Connection, assembly_id: int) -> dict[str, Any]:
    assembly = _get_entity_or_404(
        conn,
        "assemblies",
        "assembly_id",
        assembly_id,
        "ASSEMBLY_NOT_FOUND",
        f"Assembly with id {assembly_id} not found",
    )
    components = conn.execute(
        """
        SELECT
            ac.assembly_id,
            ac.item_id,
            ac.quantity,
            im.item_number
        FROM assembly_components ac
        JOIN items_master im ON im.item_id = ac.item_id
        WHERE ac.assembly_id = ?
        ORDER BY im.item_number
        """,
        (assembly_id,),
    ).fetchall()
    data = dict(assembly)
    data["components"] = _rows_to_dict(components)
    return data


def create_assembly(conn: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    cur = conn.execute(
        """
        INSERT INTO assemblies (name, description, created_at)
        VALUES (?, ?, ?)
        """,
        (
            require_non_empty(payload["name"], "name"),
            payload.get("description"),
            now_jst_iso(),
        ),
    )
    assembly_id = int(cur.lastrowid)
    for component in payload.get("components", []):
        conn.execute(
            """
            INSERT INTO assembly_components (assembly_id, item_id, quantity)
            VALUES (?, ?, ?)
            """,
            (
                assembly_id,
                int(component["item_id"]),
                require_positive_int(int(component["quantity"]), "quantity"),
            ),
        )
    return get_assembly(conn, assembly_id)


def update_assembly(conn: sqlite3.Connection, assembly_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    _get_entity_or_404(
        conn,
        "assemblies",
        "assembly_id",
        assembly_id,
        "ASSEMBLY_NOT_FOUND",
        f"Assembly with id {assembly_id} not found",
    )
    updates: list[str] = []
    params: list[Any] = []
    if payload.get("name") is not None:
        updates.append("name = ?")
        params.append(require_non_empty(payload["name"], "name"))
    if "description" in payload:
        updates.append("description = ?")
        params.append(payload.get("description"))
    if updates:
        conn.execute(
            f"UPDATE assemblies SET {', '.join(updates)} WHERE assembly_id = ?",
            (*params, assembly_id),
        )
    if "components" in payload and payload["components"] is not None:
        conn.execute("DELETE FROM assembly_components WHERE assembly_id = ?", (assembly_id,))
        for component in payload["components"]:
            conn.execute(
                """
                INSERT INTO assembly_components (assembly_id, item_id, quantity)
                VALUES (?, ?, ?)
                """,
                (
                    assembly_id,
                    int(component["item_id"]),
                    require_positive_int(int(component["quantity"]), "quantity"),
                ),
            )
    return get_assembly(conn, assembly_id)


def delete_assembly(conn: sqlite3.Connection, assembly_id: int) -> None:
    _get_entity_or_404(
        conn,
        "assemblies",
        "assembly_id",
        assembly_id,
        "ASSEMBLY_NOT_FOUND",
        f"Assembly with id {assembly_id} not found",
    )
    conn.execute("DELETE FROM assemblies WHERE assembly_id = ?", (assembly_id,))


def get_assembly_locations(conn: sqlite3.Connection, assembly_id: int) -> list[dict[str, Any]]:
    _get_entity_or_404(
        conn,
        "assemblies",
        "assembly_id",
        assembly_id,
        "ASSEMBLY_NOT_FOUND",
        f"Assembly with id {assembly_id} not found",
    )
    rows = conn.execute(
        """
        SELECT *
        FROM location_assembly_usage
        WHERE assembly_id = ?
        ORDER BY location
        """,
        (assembly_id,),
    ).fetchall()
    return _rows_to_dict(rows)


def set_location_assemblies(
    conn: sqlite3.Connection,
    *,
    location: str,
    assignments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    normalized_location = require_non_empty(location, "location")
    conn.execute(
        "DELETE FROM location_assembly_usage WHERE location = ?",
        (normalized_location,),
    )
    for assignment in assignments:
        _get_entity_or_404(
            conn,
            "assemblies",
            "assembly_id",
            assignment["assembly_id"],
            "ASSEMBLY_NOT_FOUND",
            f"Assembly with id {assignment['assembly_id']} not found",
        )
        conn.execute(
            """
            INSERT INTO location_assembly_usage (
                location, assembly_id, quantity, note, updated_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                normalized_location,
                int(assignment["assembly_id"]),
                require_positive_int(int(assignment["quantity"]), "quantity"),
                assignment.get("note"),
                now_jst_iso(),
            ),
        )
    rows = conn.execute(
        """
        SELECT lau.*, a.name AS assembly_name
        FROM location_assembly_usage lau
        JOIN assemblies a ON a.assembly_id = lau.assembly_id
        WHERE lau.location = ?
        ORDER BY a.name
        """,
        (normalized_location,),
    ).fetchall()
    return _rows_to_dict(rows)


def list_locations(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT location, COUNT(*) AS item_count, SUM(quantity) AS total_quantity
        FROM inventory_ledger
        GROUP BY location
        ORDER BY location
        """
    ).fetchall()
    return _rows_to_dict(rows)


def inspect_location(conn: sqlite3.Connection, location: str) -> dict[str, Any]:
    normalized_location = require_non_empty(location, "location")
    inventory_rows = conn.execute(
        """
        SELECT
            il.item_id,
            im.item_number,
            il.location,
            il.quantity
        FROM inventory_ledger il
        JOIN items_master im ON im.item_id = il.item_id
        WHERE il.location = ?
        ORDER BY im.item_number
        """,
        (normalized_location,),
    ).fetchall()
    assembly_rows = conn.execute(
        """
        SELECT
            lau.assembly_id,
            a.name AS assembly_name,
            lau.quantity,
            lau.note,
            lau.updated_at
        FROM location_assembly_usage lau
        JOIN assemblies a ON a.assembly_id = lau.assembly_id
        WHERE lau.location = ?
        ORDER BY a.name
        """,
        (normalized_location,),
    ).fetchall()
    advisory_rows = conn.execute(
        """
        SELECT
            ac.item_id,
            im.item_number,
            SUM(lau.quantity * ac.quantity) AS advisory_quantity
        FROM location_assembly_usage lau
        JOIN assembly_components ac ON ac.assembly_id = lau.assembly_id
        JOIN items_master im ON im.item_id = ac.item_id
        WHERE lau.location = ?
        GROUP BY ac.item_id, im.item_number
        ORDER BY im.item_number
        """,
        (normalized_location,),
    ).fetchall()
    return {
        "location": normalized_location,
        "inventory": _rows_to_dict(inventory_rows),
        "assemblies": _rows_to_dict(assembly_rows),
        "advisory_components": _rows_to_dict(advisory_rows),
    }


def disassemble_location(conn: sqlite3.Connection, location: str) -> dict[str, Any]:
    normalized_location = require_non_empty(location, "location")
    moved: list[dict[str, Any]] = []
    if normalized_location != "STOCK":
        rows = conn.execute(
            """
            SELECT item_id, quantity
            FROM inventory_ledger
            WHERE location = ?
            """,
            (normalized_location,),
        ).fetchall()
        for row in rows:
            log = move_inventory(
                conn,
                item_id=int(row["item_id"]),
                quantity=int(row["quantity"]),
                from_location=normalized_location,
                to_location="STOCK",
                note=f"disassemble location {normalized_location}",
                batch_id=f"location-disassemble-{normalized_location}",
            )
            moved.append(log)
    deleted_usage = conn.execute(
        "DELETE FROM location_assembly_usage WHERE location = ?",
        (normalized_location,),
    ).rowcount
    return {
        "location": normalized_location,
        "moved_transactions": moved,
        "deleted_assembly_assignments": deleted_usage,
    }


def list_projects(
    conn: sqlite3.Connection, *, page: int = 1, per_page: int = 50
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    sql = """
        SELECT p.*, COUNT(pr.requirement_id) AS requirement_count
        FROM projects p
        LEFT JOIN project_requirements pr ON pr.project_id = p.project_id
        GROUP BY p.project_id
        ORDER BY p.created_at DESC
    """
    return _paginate(conn, sql, (), page, per_page)


def _list_project_requirements(conn: sqlite3.Connection, project_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
            pr.*,
            im.item_number,
            a.name AS assembly_name
        FROM project_requirements pr
        LEFT JOIN items_master im ON im.item_id = pr.item_id
        LEFT JOIN assemblies a ON a.assembly_id = pr.assembly_id
        WHERE pr.project_id = ?
        ORDER BY pr.requirement_id
        """,
        (project_id,),
    ).fetchall()
    return _rows_to_dict(rows)


def _load_legacy_assembly_project_requirements(
    conn: sqlite3.Connection,
    project_id: int,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT assembly_id, quantity, requirement_type, note, created_at
        FROM project_requirements
        WHERE project_id = ?
          AND assembly_id IS NOT NULL
          AND item_id IS NULL
        ORDER BY requirement_id
        """,
        (project_id,),
    ).fetchall()
    return _rows_to_dict(rows)


def get_project(conn: sqlite3.Connection, project_id: int) -> dict[str, Any]:
    project = _get_entity_or_404(
        conn,
        "projects",
        "project_id",
        project_id,
        "PROJECT_NOT_FOUND",
        f"Project with id {project_id} not found",
    )
    data = dict(project)
    data["requirements"] = _list_project_requirements(conn, project_id)
    return data


def _replace_project_requirements(
    conn: sqlite3.Connection,
    project_id: int,
    requirements: list[dict[str, Any]],
    *,
    preserve_legacy_assembly_rows: bool = False,
) -> None:
    legacy_assembly_rows = (
        _load_legacy_assembly_project_requirements(conn, project_id)
        if preserve_legacy_assembly_rows
        else []
    )
    conn.execute("DELETE FROM project_requirements WHERE project_id = ?", (project_id,))
    for req in requirements:
        item_id = req.get("item_id")
        assembly_id = req.get("assembly_id")
        if item_id is None and assembly_id is None:
            continue
        conn.execute(
            """
            INSERT INTO project_requirements (
                project_id, assembly_id, item_id, quantity, requirement_type, note, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                assembly_id,
                item_id,
                require_positive_int(int(req["quantity"]), "quantity"),
                req.get("requirement_type", "INITIAL"),
                req.get("note"),
                now_jst_iso(),
            ),
        )
    for req in legacy_assembly_rows:
        conn.execute(
            """
            INSERT INTO project_requirements (
                project_id, assembly_id, item_id, quantity, requirement_type, note, created_at
            ) VALUES (?, ?, NULL, ?, ?, ?, ?)
            """,
            (
                project_id,
                int(req["assembly_id"]),
                require_positive_int(int(req["quantity"]), "quantity"),
                req.get("requirement_type", "INITIAL"),
                req.get("note"),
                req.get("created_at") or now_jst_iso(),
            ),
        )


def create_project(conn: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    cur = conn.execute(
        """
        INSERT INTO projects (name, description, status, planned_start, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            require_non_empty(payload["name"], "name"),
            payload.get("description"),
            payload.get("status", "PLANNING"),
            normalize_optional_date(payload.get("planned_start"), "planned_start"),
            now_jst_iso(),
            now_jst_iso(),
        ),
    )
    project_id = int(cur.lastrowid)
    if payload.get("requirements"):
        _replace_project_requirements(conn, project_id, payload["requirements"])
    return get_project(conn, project_id)


def update_project(conn: sqlite3.Connection, project_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    _get_entity_or_404(
        conn,
        "projects",
        "project_id",
        project_id,
        "PROJECT_NOT_FOUND",
        f"Project with id {project_id} not found",
    )
    updates: list[str] = []
    params: list[Any] = []
    for key in ("name", "description", "status"):
        if key in payload and payload[key] is not None:
            updates.append(f"{key} = ?")
            params.append(payload[key])
    if "planned_start" in payload:
        updates.append("planned_start = ?")
        params.append(normalize_optional_date(payload.get("planned_start"), "planned_start"))
    if updates:
        updates.append("updated_at = ?")
        params.append(now_jst_iso())
        conn.execute(
            f"UPDATE projects SET {', '.join(updates)} WHERE project_id = ?",
            (*params, project_id),
        )
    if "requirements" in payload and payload["requirements"] is not None:
        preserve_legacy_assembly_rows = not any(
            req.get("assembly_id") is not None and req.get("item_id") is None
            for req in payload["requirements"]
        )
        _replace_project_requirements(
            conn,
            project_id,
            payload["requirements"],
            preserve_legacy_assembly_rows=preserve_legacy_assembly_rows,
        )
    return get_project(conn, project_id)


def preview_project_requirement_bulk_text(
    conn: sqlite3.Connection,
    *,
    text: str,
) -> dict[str, Any]:
    item_catalog_rows = _load_item_preview_catalog_rows(conn)
    preview_rows: list[dict[str, Any]] = []
    summary = {
        "total_rows": 0,
        "exact": 0,
        "high_confidence": 0,
        "needs_review": 0,
        "unresolved": 0,
    }

    for line_number, raw_line in enumerate(str(text or "").splitlines(), start=1):
        stripped_line = raw_line.strip()
        if not stripped_line:
            continue

        parts = [part.strip() for part in stripped_line.split(",")]
        raw_target = parts[0] if parts else ""
        quantity_raw = parts[1] if len(parts) > 1 else "1"
        quantity = 1
        quantity_defaulted = False
        try:
            quantity = require_positive_int(int(quantity_raw or "1"), f"quantity (line {line_number})")
        except Exception:  # noqa: BLE001
            quantity = 1
            quantity_defaulted = True

        candidate_matches = _rank_item_preview_candidates(item_catalog_rows, raw_target)
        exact_candidates = [
            candidate
            for candidate in candidate_matches
            if _classify_ranked_preview_status(
                confidence_score=int(candidate.get("confidence_score") or 0),
                match_reason=str(candidate.get("match_reason") or ""),
            )
            == "exact"
        ]
        suggested_match = exact_candidates[0] if len(exact_candidates) == 1 else candidate_matches[0] if candidate_matches else None
        status = "unresolved"
        message = "No registered item matched this line."
        requires_user_selection = True

        if raw_target:
            if len(exact_candidates) == 1:
                status = "exact"
                message = "Matched registered item."
                requires_user_selection = False
            elif len(exact_candidates) > 1:
                status = "needs_review"
                suggested_match = None
                message = "Multiple registered items share this item number. Choose the correct item."
                candidate_matches = exact_candidates
            elif suggested_match is not None:
                status = _classify_ranked_preview_status(
                    confidence_score=int(suggested_match.get("confidence_score") or 0),
                    match_reason=str(suggested_match.get("match_reason") or ""),
                )
                if status == "high_confidence":
                    message = "High-confidence match found."
                    requires_user_selection = False
                elif status == "needs_review":
                    message = "Review the suggested item before applying."
                else:
                    message = "No reliable item match found. Choose the correct item."
            else:
                message = "No registered item matched this line."
        else:
            message = "item_number is required"

        if quantity_defaulted:
            if status in {"exact", "high_confidence"}:
                status = "needs_review"
            message = f"{message} Quantity was invalid and defaulted to 1."

        eligible_for_items_csv_export = _project_requirement_preview_should_export_to_items_csv(
            raw_target=raw_target,
            status=status,
            suggested_match=suggested_match,
        )
        preview_row = {
            "row": line_number,
            "raw_line": stripped_line,
            "raw_target": raw_target,
            "quantity": str(quantity),
            "quantity_raw": quantity_raw,
            "quantity_defaulted": quantity_defaulted,
            "status": status,
            "message": message,
            "requires_user_selection": requires_user_selection,
            "allowed_entity_types": ["item"] if status != "exact" else [],
            "suggested_match": suggested_match,
            "candidates": candidate_matches,
            "eligible_for_items_csv_export": eligible_for_items_csv_export,
        }
        preview_rows.append(preview_row)
        summary[status] += 1
        summary["total_rows"] += 1

    return {
        "summary": summary,
        "can_auto_accept": summary["total_rows"] > 0 and summary["needs_review"] == 0 and summary["unresolved"] == 0,
        "rows": preview_rows,
    }


def export_project_requirement_unresolved_items_csv(
    conn: sqlite3.Connection,
    *,
    text: str = "",
    rows: list[dict[str, Any]] | None = None,
) -> tuple[str, bytes]:
    preview_rows = rows if rows is not None and len(rows) > 0 else preview_project_requirement_bulk_text(conn, text=text)["rows"]
    export_rows: list[dict[str, Any]] = []
    seen_item_numbers: set[str] = set()

    for row in preview_rows:
        if not _project_requirement_preview_row_eligible_for_items_csv_export(row):
            continue
        item_number = str(row.get("raw_target") or "").strip()
        if not item_number:
            continue
        normalized_key = item_number.casefold()
        if normalized_key in seen_item_numbers:
            continue
        seen_item_numbers.add(normalized_key)
        export_rows.append(
            {
                "row_type": "item",
                "item_number": item_number,
                "manufacturer_name": "UNKNOWN",
                "category": "",
                "url": "",
                "description": "",
                "supplier": "",
                "canonical_item_number": "",
                "units_per_order": "1",
            }
        )

    if not export_rows:
        raise AppError(
            code="NO_UNRESOLVED_PROJECT_ITEMS",
            message="No exportable project preview items are available to export.",
            status_code=400,
        )

    spec = IMPORT_TEMPLATE_SPECS["items"]
    filename = "project_requirements_unresolved_items_import.csv"
    content = _csv_bytes(spec["fieldnames"], export_rows)
    return filename, content


def delete_project(conn: sqlite3.Connection, project_id: int) -> None:
    _get_entity_or_404(
        conn,
        "projects",
        "project_id",
        project_id,
        "PROJECT_NOT_FOUND",
        f"Project with id {project_id} not found",
    )
    conn.execute("DELETE FROM projects WHERE project_id = ?", (project_id,))
PLANNING_COMMITTED_PROJECT_STATUSES = {"CONFIRMED", "ACTIVE"}
RFQ_BATCH_STATUSES = {"OPEN", "CLOSED", "CANCELLED"}
RFQ_LINE_STATUSES = {"DRAFT", "QUOTED", "ORDERED", "CANCELLED"}
PROCUREMENT_BATCH_STATUSES = {"DRAFT", "SENT", "QUOTED", "ORDERED", "CLOSED", "CANCELLED"}
PROCUREMENT_LINE_STATUSES = {"DRAFT", "SENT", "QUOTED", "ORDERED", "CANCELLED"}


def _validate_rfq_batch_status(value: str) -> str:
    normalized = require_non_empty(value, "status").upper()
    if normalized not in RFQ_BATCH_STATUSES:
        raise AppError(
            code="INVALID_RFQ_BATCH_STATUS",
            message=f"status must be one of: {', '.join(sorted(RFQ_BATCH_STATUSES))}",
            status_code=422,
        )
    return normalized


def _validate_rfq_line_status(value: str) -> str:
    normalized = require_non_empty(value, "status").upper()
    if normalized not in RFQ_LINE_STATUSES:
        raise AppError(
            code="INVALID_RFQ_LINE_STATUS",
            message=f"status must be one of: {', '.join(sorted(RFQ_LINE_STATUSES))}",
            status_code=422,
        )
    return normalized


def _validate_procurement_batch_status(value: str) -> str:
    normalized = require_non_empty(value, "status").upper()
    if normalized not in PROCUREMENT_BATCH_STATUSES:
        raise AppError(
            code="INVALID_PROCUREMENT_BATCH_STATUS",
            message=f"status must be one of: {', '.join(sorted(PROCUREMENT_BATCH_STATUSES))}",
            status_code=422,
        )
    return normalized


def _validate_procurement_line_status(value: str) -> str:
    normalized = require_non_empty(value, "status").upper()
    if normalized not in PROCUREMENT_LINE_STATUSES:
        raise AppError(
            code="INVALID_PROCUREMENT_LINE_STATUS",
            message=f"status must be one of: {', '.join(sorted(PROCUREMENT_LINE_STATUSES))}",
            status_code=422,
        )
    return normalized


def _aggregate_project_required_by_item(
    conn: sqlite3.Connection,
    project: dict[str, Any],
    *,
    focus_item_id: int | None = None,
) -> dict[int, int]:
    required_by_item: dict[int, int] = {}
    assembly_ids = sorted(
        {
            int(requirement["assembly_id"])
            for requirement in project["requirements"]
            if requirement.get("assembly_id") is not None and requirement.get("item_id") is None
        }
    )
    assembly_components_by_assembly: dict[int, list[dict[str, int]]] = {}
    if assembly_ids:
        placeholders = ",".join("?" for _ in assembly_ids)
        component_rows = conn.execute(
            f"""
            SELECT assembly_id, item_id, quantity
            FROM assembly_components
            WHERE assembly_id IN ({placeholders})
            ORDER BY assembly_id, item_id
            """,
            tuple(assembly_ids),
        ).fetchall()
        for row in component_rows:
            assembly_id = int(row["assembly_id"])
            assembly_components_by_assembly.setdefault(assembly_id, []).append(
                {
                    "item_id": int(row["item_id"]),
                    "quantity": int(row["quantity"]),
                }
            )

    for requirement in project["requirements"]:
        requirement_qty = int(requirement["quantity"])
        item_id_raw = requirement.get("item_id")
        if item_id_raw is not None:
            item_id = int(item_id_raw)
            if focus_item_id is not None and item_id != focus_item_id:
                continue
            required_by_item[item_id] = required_by_item.get(item_id, 0) + requirement_qty
            continue

        assembly_id_raw = requirement.get("assembly_id")
        if assembly_id_raw is None:
            continue
        for component in assembly_components_by_assembly.get(int(assembly_id_raw), []):
            component_item_id = int(component["item_id"])
            if focus_item_id is not None and component_item_id != focus_item_id:
                continue
            component_qty = requirement_qty * int(component["quantity"])
            required_by_item[component_item_id] = required_by_item.get(component_item_id, 0) + component_qty
    return required_by_item


def _load_projects_with_requirements(
    conn: sqlite3.Connection,
    project_ids: list[int],
) -> list[dict[str, Any]]:
    if not project_ids:
        return []
    placeholders = ",".join("?" for _ in project_ids)
    project_rows = conn.execute(
        f"SELECT * FROM projects WHERE project_id IN ({placeholders})",
        tuple(project_ids),
    ).fetchall()
    project_lookup = {int(row["project_id"]): {**dict(row), "requirements": []} for row in project_rows}
    requirement_rows = conn.execute(
        f"""
        SELECT
            pr.*,
            im.item_number,
            a.name AS assembly_name
        FROM project_requirements pr
        LEFT JOIN items_master im ON im.item_id = pr.item_id
        LEFT JOIN assemblies a ON a.assembly_id = pr.assembly_id
        WHERE pr.project_id IN ({placeholders})
        ORDER BY pr.project_id, pr.requirement_id
        """,
        tuple(project_ids),
    ).fetchall()
    for row in requirement_rows:
        project_lookup[int(row["project_id"])]["requirements"].append(dict(row))
    return [project_lookup[project_id] for project_id in project_ids if project_id in project_lookup]


def _normalize_project_planning_date(
    project: dict[str, Any],
    *,
    target_date: str | None = None,
) -> str:
    if target_date is not None:
        normalized_target = _normalize_future_target_date(target_date, field_name="target_date")
        if normalized_target is None:
            raise AppError(
                code="PROJECT_PLANNING_DATE_REQUIRED",
                message="target_date is required for project planning analysis",
                status_code=422,
            )
        return normalized_target
    normalized_start = normalize_optional_date(project.get("planned_start"), "planned_start")
    if normalized_start is not None:
        return normalized_start
    return today_jst()


def _load_item_planning_metadata(
    conn: sqlite3.Connection, item_ids: list[int]
) -> dict[int, dict[str, Any]]:
    if not item_ids:
        return {}
    placeholders = ",".join("?" for _ in item_ids)
    rows = conn.execute(
        f"""
        SELECT
            im.item_id,
            im.item_number,
            m.name AS manufacturer_name
        FROM items_master im
        JOIN manufacturers m ON m.manufacturer_id = im.manufacturer_id
        WHERE im.item_id IN ({placeholders})
        """,
        tuple(item_ids),
    ).fetchall()
    return {int(row["item_id"]): dict(row) for row in rows}


def _load_total_available_inventory_by_item(
    conn: sqlite3.Connection,
    item_ids: list[int],
) -> dict[int, int]:
    if not item_ids:
        return {}
    placeholders = ",".join("?" for _ in item_ids)
    inventory_rows = conn.execute(
        f"""
        SELECT item_id, location, quantity
        FROM inventory_ledger
        WHERE item_id IN ({placeholders})
          AND quantity > 0
          AND location <> 'RESERVED'
        """,
        tuple(item_ids),
    ).fetchall()
    allocation_rows = conn.execute(
        f"""
        SELECT item_id, location, COALESCE(SUM(quantity), 0) AS quantity
        FROM reservation_allocations
        WHERE status = 'ACTIVE'
          AND item_id IN ({placeholders})
        GROUP BY item_id, location
        """,
        tuple(item_ids),
    ).fetchall()
    allocated_by_key = {
        (int(row["item_id"]), str(row["location"])): int(row["quantity"] or 0)
        for row in allocation_rows
    }
    totals = {item_id: 0 for item_id in item_ids}
    for row in inventory_rows:
        item_id = int(row["item_id"])
        location = str(row["location"])
        available = max(0, int(row["quantity"]) - allocated_by_key.get((item_id, location), 0))
        if available > 0:
            totals[item_id] = totals.get(item_id, 0) + available
    return totals


def _planning_source_signature(source: dict[str, Any]) -> tuple[Any, ...]:
    return (
        source.get("source_type"),
        source.get("ref_id"),
        source.get("project_id"),
        source.get("date"),
        source.get("status"),
        source.get("label"),
    )


def _append_planning_source(target: list[dict[str, Any]], source: dict[str, Any]) -> None:
    quantity = int(source.get("quantity") or 0)
    if quantity <= 0:
        return
    signature = _planning_source_signature(source)
    for existing in target:
        if _planning_source_signature(existing) == signature:
            existing["quantity"] = int(existing.get("quantity") or 0) + quantity
            return
    normalized = dict(source)
    normalized["quantity"] = quantity
    target.append(normalized)


def _consume_planning_sources(
    sources: list[dict[str, Any]],
    quantity: int,
) -> list[dict[str, Any]]:
    remaining = int(quantity)
    consumed: list[dict[str, Any]] = []
    index = 0
    while remaining > 0 and index < len(sources):
        available = int(sources[index].get("quantity") or 0)
        if available <= 0:
            index += 1
            continue
        used = min(available, remaining)
        consumed_source = dict(sources[index])
        consumed_source["quantity"] = used
        _append_planning_source(consumed, consumed_source)
        sources[index]["quantity"] = available - used
        remaining -= used
        if int(sources[index].get("quantity") or 0) <= 0:
            index += 1
    sources[:] = [source for source in sources if int(source.get("quantity") or 0) > 0]
    return consumed


def _sum_planning_sources(sources: list[dict[str, Any]]) -> int:
    return sum(int(source.get("quantity") or 0) for source in sources)


def _build_planning_source(
    source_type: str,
    *,
    quantity: int,
    label: str,
    ref_id: int | None = None,
    project_id: int | None = None,
    date: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    return {
        "source_type": source_type,
        "quantity": int(quantity),
        "label": label,
        "ref_id": ref_id,
        "project_id": project_id,
        "date": date,
        "status": status,
    }


def _build_project_planning_snapshot(
    conn: sqlite3.Connection,
    *,
    project_id: int | None = None,
    target_date: str | None = None,
    focus_item_id: int | None = None,
) -> dict[str, Any]:
    selected_project: dict[str, Any] | None = None
    selected_target_date: str | None = None
    if project_id is not None:
        selected_project = get_project(conn, project_id)
        if selected_project["status"] in {"COMPLETED", "CANCELLED"}:
            raise AppError(
                code="PROJECT_NOT_PLANNABLE",
                message="Completed or cancelled projects are excluded from planning pipeline analysis",
                status_code=409,
            )
        selected_target_date = _normalize_project_planning_date(
            selected_project,
            target_date=target_date,
        )

    committed_sql = """
        SELECT project_id
        FROM projects
        WHERE status IN ('CONFIRMED', 'ACTIVE')
    """
    committed_params: list[Any] = []
    if project_id is not None:
        committed_sql += "\n          AND project_id <> ?"
        committed_params.append(project_id)
    committed_sql += "\n        ORDER BY COALESCE(planned_start, ?) ASC, project_id ASC"
    committed_params.append(today_jst())
    committed_rows = conn.execute(committed_sql, tuple(committed_params)).fetchall()

    committed_project_ids = [int(row["project_id"]) for row in committed_rows]
    planning_projects = _load_projects_with_requirements(conn, committed_project_ids)
    for project in planning_projects:
        project["effective_planned_start"] = _normalize_project_planning_date(project)

    if selected_project is not None:
        preview_project = dict(selected_project)
        preview_project["effective_planned_start"] = selected_target_date
        preview_project["is_planning_preview"] = (
            preview_project["status"] not in PLANNING_COMMITTED_PROJECT_STATUSES
        )
        planning_projects.append(preview_project)

    planning_projects.sort(
        key=lambda row: (str(row["effective_planned_start"]), int(row["project_id"]))
    )
    project_sequence = [int(project["project_id"]) for project in planning_projects]
    project_rank = {project_id: idx for idx, project_id in enumerate(project_sequence)}

    required_by_project: dict[int, dict[int, int]] = {}
    item_ids: set[int] = set()
    for project in planning_projects:
        project_required = _aggregate_project_required_by_item(
            conn,
            project,
            focus_item_id=focus_item_id,
        )
        required_by_project[int(project["project_id"])] = project_required
        item_ids.update(project_required.keys())

    item_ids_sorted = sorted(item_ids)
    item_metadata = _load_item_planning_metadata(conn, item_ids_sorted)
    available_inventory_by_item = _load_total_available_inventory_by_item(conn, item_ids_sorted)

    generic_order_events: dict[int, list[dict[str, Any]]] = {item_id: [] for item_id in item_ids_sorted}
    project_order_events: dict[int, list[dict[str, Any]]] = {item_id: [] for item_id in item_ids_sorted}
    procurement_supply_events: dict[int, list[dict[str, Any]]] = {item_id: [] for item_id in item_ids_sorted}

    if item_ids_sorted:
        item_placeholders = ",".join("?" for _ in item_ids_sorted)

        generic_rows = conn.execute(
            f"""
            SELECT order_id, item_id, order_amount AS quantity, expected_arrival
            FROM orders
            WHERE project_id IS NULL
              AND status <> 'Arrived'
              AND expected_arrival IS NOT NULL
              AND item_id IN ({item_placeholders})
            ORDER BY expected_arrival ASC, order_id ASC
            """,
            tuple(item_ids_sorted),
        ).fetchall()
        for row in generic_rows:
            generic_order_events[int(row["item_id"])].append(
                {
                    "ref_id": int(row["order_id"]),
                    "date": str(row["expected_arrival"]),
                    "quantity": int(row["quantity"]),
                }
            )

        if project_sequence:
            project_placeholders = ",".join("?" for _ in project_sequence)
            project_rows = conn.execute(
                f"""
                SELECT order_id, item_id, project_id, order_amount AS quantity, expected_arrival
                FROM orders
                WHERE project_id IN ({project_placeholders})
                  AND status <> 'Arrived'
                  AND expected_arrival IS NOT NULL
                  AND item_id IN ({item_placeholders})
                ORDER BY expected_arrival ASC, order_id ASC
                """,
                tuple(project_sequence) + tuple(item_ids_sorted),
            ).fetchall()
            for row in project_rows:
                project_order_events[int(row["item_id"])].append(
                    {
                        "ref_id": int(row["order_id"]),
                        "date": str(row["expected_arrival"]),
                        "quantity": int(row["quantity"]),
                        "project_id": int(row["project_id"]),
                    }
                )

            procurement_rows = conn.execute(
                f"""
                SELECT
                    pl.line_id,
                    pl.item_id,
                    pl.source_project_id AS project_id,
                    pl.finalized_quantity AS quantity,
                    pl.expected_arrival
                FROM procurement_lines pl
                JOIN procurement_batches pb ON pb.batch_id = pl.batch_id
                WHERE pb.status <> 'CANCELLED'
                  AND pl.status = 'QUOTED'
                  AND pl.linked_order_id IS NULL
                  AND pl.expected_arrival IS NOT NULL
                  AND pl.item_id IN ({item_placeholders})
                  AND (pl.source_project_id IS NULL OR pl.source_project_id IN ({project_placeholders}))
                ORDER BY pl.expected_arrival ASC, pl.line_id ASC
                """,
                tuple(item_ids_sorted) + tuple(project_sequence),
            ).fetchall()
            for row in procurement_rows:
                procurement_supply_events[int(row["item_id"])].append(
                    {
                        "ref_id": int(row["line_id"]),
                        "date": str(row["expected_arrival"]),
                        "quantity": int(row["quantity"]),
                        "project_id": int(row["project_id"]) if row["project_id"] is not None else None,
                        "source_type": "quoted_procurement",
                    }
                )
            legacy_rfq_rows = conn.execute(
                f"""
                SELECT
                    rl.line_id,
                    rl.item_id,
                    rb.project_id,
                    COALESCE(rl.finalized_quantity, rl.requested_quantity) AS quantity,
                    rl.expected_arrival
                FROM rfq_lines rl
                JOIN rfq_batches rb ON rb.rfq_id = rl.rfq_id
                WHERE rb.status <> 'CANCELLED'
                  AND rl.status = 'QUOTED'
                  AND rl.linked_order_id IS NULL
                  AND rl.expected_arrival IS NOT NULL
                  AND rl.item_id IN ({item_placeholders})
                  AND rb.project_id IN ({project_placeholders})
                ORDER BY rl.expected_arrival ASC, rl.line_id ASC
                """,
                tuple(item_ids_sorted) + tuple(project_sequence),
            ).fetchall()
            for row in legacy_rfq_rows:
                procurement_supply_events[int(row["item_id"])].append(
                    {
                        "ref_id": int(row["line_id"]),
                        "date": str(row["expected_arrival"]),
                        "quantity": int(row["quantity"]),
                        "project_id": int(row["project_id"]),
                        "source_type": "quoted_rfq",
                    }
                )

    metrics: dict[int, dict[int, dict[str, Any]]] = {}
    for project in planning_projects:
        pid = int(project["project_id"])
        metrics[pid] = {}
        for item_id, required_qty in required_by_project.get(pid, {}).items():
            metrics[pid][item_id] = {
                "required_quantity": int(required_qty),
                "dedicated_supply_by_start": 0,
                "generic_available_at_start": 0,
                "generic_allocated_quantity": 0,
                "covered_on_time_quantity": 0,
                "shortage_at_start": 0,
                "future_generic_recovery_quantity": 0,
                "future_dedicated_recovery_quantity": 0,
                "recovered_after_start_quantity": 0,
                "pending_backlog_quantity": 0,
                "supply_sources_by_start": [],
                "recovery_sources_after_start": [],
            }

    for item_id in item_ids_sorted:
        generic_pool_sources: list[dict[str, Any]] = []
        current_stock = int(available_inventory_by_item.get(item_id, 0))
        if current_stock > 0:
            generic_pool_sources.append(
                _build_planning_source(
                    "stock",
                    quantity=current_stock,
                    label="Current stock",
                )
            )
        dedicated_ready_sources: dict[int, list[dict[str, Any]]] = {
            pid: [] for pid in project_sequence
        }
        events: list[dict[str, Any]] = []

        for row in generic_order_events.get(item_id, []):
            events.append(
                {
                    "kind": "generic_supply",
                    "date": row["date"],
                    "priority": 1,
                    "source": _build_planning_source(
                        "generic_order",
                        quantity=int(row["quantity"]),
                        label=f"Order #{int(row['ref_id'])}",
                        ref_id=int(row["ref_id"]),
                        date=str(row["date"]),
                    ),
                    "ref_id": row["ref_id"],
                    "project_rank": -1,
                }
            )
        for row in project_order_events.get(item_id, []):
            events.append(
                {
                    "kind": "dedicated_supply",
                    "date": row["date"],
                    "priority": 0,
                    "source": _build_planning_source(
                        "dedicated_order",
                        quantity=int(row["quantity"]),
                        label=f"Order #{int(row['ref_id'])}",
                        ref_id=int(row["ref_id"]),
                        project_id=int(row["project_id"]),
                        date=str(row["date"]),
                    ),
                    "project_id": row["project_id"],
                    "ref_id": row["ref_id"],
                    "project_rank": project_rank.get(int(row["project_id"]), 0),
                }
            )
        for row in procurement_supply_events.get(item_id, []):
            events.append(
                {
                    "kind": "generic_supply" if row.get("project_id") is None else "dedicated_supply",
                    "date": row["date"],
                    "priority": 1 if row.get("project_id") is None else 0,
                    "source": _build_planning_source(
                        str(row.get("source_type") or "quoted_procurement"),
                        quantity=int(row["quantity"]),
                        label=(
                            f"RFQ Line #{int(row['ref_id'])} [QUOTED]"
                            if row.get("source_type") == "quoted_rfq"
                            else f"Procurement Line #{int(row['ref_id'])} [QUOTED]"
                        ),
                        ref_id=int(row["ref_id"]),
                        project_id=int(row["project_id"]) if row.get("project_id") is not None else None,
                        date=str(row["date"]),
                        status="QUOTED",
                    ),
                    "project_id": row["project_id"],
                    "ref_id": row["ref_id"],
                    "project_rank": project_rank.get(int(row["project_id"]), 0) if row.get("project_id") is not None else -1,
                }
            )
        for project in planning_projects:
            pid = int(project["project_id"])
            required_qty = required_by_project.get(pid, {}).get(item_id)
            if not required_qty:
                continue
            events.append(
                {
                    "kind": "demand",
                    "date": str(project["effective_planned_start"]),
                    "priority": 2,
                    "quantity": int(required_qty),
                    "project_id": pid,
                    "ref_id": pid,
                    "project_rank": project_rank[pid],
                }
            )

        events.sort(
            key=lambda event: (
                str(event["date"]),
                int(event["priority"]),
                int(event["project_rank"]),
                int(event["ref_id"]),
            )
        )

        for event in events:
            if event["kind"] == "dedicated_supply":
                project_metric = metrics[int(event["project_id"])][item_id]
                remaining_sources = [dict(event["source"])]
                backlog_qty = int(project_metric["pending_backlog_quantity"])
                if backlog_qty > 0:
                    recovered_sources = _consume_planning_sources(
                        remaining_sources,
                        backlog_qty,
                    )
                    recovered_qty = _sum_planning_sources(recovered_sources)
                    project_metric["pending_backlog_quantity"] = backlog_qty - recovered_qty
                    project_metric["recovered_after_start_quantity"] += recovered_qty
                    project_metric["future_dedicated_recovery_quantity"] += recovered_qty
                    for source in recovered_sources:
                        _append_planning_source(
                            project_metric["recovery_sources_after_start"],
                            source,
                        )
                for source in remaining_sources:
                    _append_planning_source(
                        dedicated_ready_sources[int(event["project_id"])],
                        source,
                    )
                continue

            if event["kind"] == "generic_supply":
                remaining_sources = [dict(event["source"])]
                for pid in project_sequence:
                    project_metric = metrics.get(pid, {}).get(item_id)
                    if project_metric is None:
                        continue
                    backlog_qty = int(project_metric["pending_backlog_quantity"])
                    if backlog_qty <= 0:
                        continue
                    recovered_sources = _consume_planning_sources(
                        remaining_sources,
                        backlog_qty,
                    )
                    recovered_qty = _sum_planning_sources(recovered_sources)
                    project_metric["pending_backlog_quantity"] = backlog_qty - recovered_qty
                    project_metric["recovered_after_start_quantity"] += recovered_qty
                    project_metric["future_generic_recovery_quantity"] += recovered_qty
                    for source in recovered_sources:
                        _append_planning_source(
                            project_metric["recovery_sources_after_start"],
                            source,
                        )
                    if _sum_planning_sources(remaining_sources) <= 0:
                        break
                for source in remaining_sources:
                    _append_planning_source(generic_pool_sources, source)
                continue

            pid = int(event["project_id"])
            project_metric = metrics[pid][item_id]
            project_metric["generic_available_at_start"] = _sum_planning_sources(generic_pool_sources)
            required_qty = int(project_metric["required_quantity"])
            dedicated_sources = _consume_planning_sources(
                dedicated_ready_sources.get(pid, []),
                required_qty,
            )
            dedicated_qty = _sum_planning_sources(dedicated_sources)
            remaining_qty = required_qty - dedicated_qty
            generic_sources = _consume_planning_sources(generic_pool_sources, remaining_qty)
            generic_qty = _sum_planning_sources(generic_sources)
            shortage_qty = remaining_qty - generic_qty
            project_metric["dedicated_supply_by_start"] = dedicated_qty
            project_metric["generic_allocated_quantity"] = generic_qty
            project_metric["covered_on_time_quantity"] = dedicated_qty + generic_qty
            project_metric["shortage_at_start"] = shortage_qty
            project_metric["pending_backlog_quantity"] = shortage_qty
            for source in dedicated_sources + generic_sources:
                _append_planning_source(project_metric["supply_sources_by_start"], source)

    project_rows: dict[int, list[dict[str, Any]]] = {}
    project_summaries: list[dict[str, Any]] = []
    cumulative_generic_consumed = 0
    for project in planning_projects:
        pid = int(project["project_id"])
        rows: list[dict[str, Any]] = []
        for item_id, project_metric in metrics.get(pid, {}).items():
            item_meta = item_metadata.get(item_id)
            pending_backlog = int(project_metric.pop("pending_backlog_quantity"))
            row = {
                "item_id": item_id,
                "item_number": item_meta.get("item_number") if item_meta else None,
                "manufacturer_name": item_meta.get("manufacturer_name") if item_meta else None,
                **project_metric,
                "remaining_shortage_quantity": pending_backlog,
            }
            rows.append(row)
        rows.sort(
            key=lambda row: (
                -int(row["shortage_at_start"]),
                -int(row["remaining_shortage_quantity"]),
                str(row["item_number"] or ""),
            )
        )
        project_rows[pid] = rows
        generic_committed_total = sum(
            int(row["generic_allocated_quantity"]) + int(row["future_generic_recovery_quantity"])
            for row in rows
        )
        project_summaries.append(
            {
                "project_id": pid,
                "name": project["name"],
                "status": project["status"],
                "planned_start": str(project["effective_planned_start"]),
                "is_planning_preview": bool(project.get("is_planning_preview")),
                "item_count": len(rows),
                "required_total": sum(int(row["required_quantity"]) for row in rows),
                "covered_on_time_total": sum(int(row["covered_on_time_quantity"]) for row in rows),
                "shortage_at_start_total": sum(int(row["shortage_at_start"]) for row in rows),
                "remaining_shortage_total": sum(
                    int(row["remaining_shortage_quantity"]) for row in rows
                ),
                "generic_committed_total": generic_committed_total,
                "cumulative_generic_consumed_before_total": cumulative_generic_consumed,
            }
        )
        cumulative_generic_consumed += generic_committed_total

    return {
        "project_summaries": project_summaries,
        "project_rows": project_rows,
        "project_lookup": {int(project["project_id"]): project for project in planning_projects},
        "selected_project_id": project_id,
        "selected_target_date": selected_target_date,
    }


def _project_allocation_snapshot_signature(
    *,
    project_id: int,
    target_date: str | None,
    rows: list[dict[str, Any]],
) -> str:
    normalized_rows = []
    for row in rows:
        normalized_rows.append(
            {
                "item_id": int(row["item_id"]),
                "required_quantity": int(row["required_quantity"]),
                "covered_on_time_quantity": int(row["covered_on_time_quantity"]),
                "shortage_at_start": int(row["shortage_at_start"]),
                "remaining_shortage_quantity": int(row["remaining_shortage_quantity"]),
                "supply_sources_by_start": [
                    {
                        "source_type": source.get("source_type"),
                        "quantity": int(source.get("quantity") or 0),
                        "ref_id": source.get("ref_id"),
                        "project_id": source.get("project_id"),
                        "date": source.get("date"),
                        "status": source.get("status"),
                        "label": source.get("label"),
                    }
                    for source in list(row.get("supply_sources_by_start") or [])
                ],
            }
        )
    normalized_rows.sort(key=lambda row: int(row["item_id"]))
    payload = {
        "project_id": int(project_id),
        "target_date": target_date,
        "rows": normalized_rows,
    }
    return json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def confirm_project_allocation(
    conn: sqlite3.Connection,
    project_id: int,
    *,
    target_date: str | None = None,
    dry_run: bool = True,
    expected_snapshot_signature: str | None = None,
) -> dict[str, Any]:
    snapshot = _build_project_planning_snapshot(
        conn,
        project_id=project_id,
        target_date=target_date,
    )
    project = snapshot["project_lookup"].get(project_id)
    if project is None:
        raise AppError(
            code="PROJECT_NOT_IN_PLANNING_PIPELINE",
            message="Project is not present in the planning pipeline",
            status_code=404,
        )

    rows = list(snapshot["project_rows"].get(project_id, []))
    effective_target_date = snapshot["selected_target_date"]
    snapshot_signature = _project_allocation_snapshot_signature(
        project_id=project_id,
        target_date=effective_target_date,
        rows=rows,
    )
    if expected_snapshot_signature is not None and expected_snapshot_signature != snapshot_signature:
        raise AppError(
            code="PLANNING_SNAPSHOT_CHANGED",
            message="Planning snapshot changed. Refresh the board preview and try again.",
            status_code=409,
        )

    summary = next(
        (row for row in snapshot["project_summaries"] if int(row["project_id"]) == int(project_id)),
        None,
    )
    if summary is None:
        raise AppError(
            code="PROJECT_NOT_IN_PLANNING_PIPELINE",
            message="Project is not present in the planning pipeline",
            status_code=404,
        )
    project_status = str(project.get("status") or "").upper()
    if not dry_run and project_status not in PLANNING_COMMITTED_PROJECT_STATUSES:
        raise AppError(
            code="PROJECT_CONFIRMATION_REQUIRED",
            message="Project must be CONFIRMED or ACTIVE before allocation can be persisted",
            status_code=409,
        )

    reservations_created: list[dict[str, Any]] = []
    orders_assigned: list[dict[str, Any]] = []
    orders_split: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    reservation_purpose = f"Confirmed allocation for project {project['name']}"
    reservation_note = f"Workspace confirm allocation ({effective_target_date or 'no target date'})"

    for row in rows:
        item_id = int(row["item_id"])
        for source in list(row.get("supply_sources_by_start") or []):
            source_type = str(source.get("source_type") or "")
            quantity = int(source.get("quantity") or 0)
            ref_id = source.get("ref_id")
            if quantity <= 0:
                continue

            if source_type == "stock":
                preview_entry = {
                    "reservation_id": None,
                    "item_id": item_id,
                    "quantity": quantity,
                }
                if dry_run:
                    reservations_created.append(preview_entry)
                    continue
                reservation = create_reservation(
                    conn,
                    {
                        "item_id": item_id,
                        "quantity": quantity,
                        "purpose": reservation_purpose,
                        "deadline": effective_target_date,
                        "note": reservation_note,
                        "project_id": project_id,
                    },
                )
                reservations_created.append(
                    {
                        "reservation_id": int(reservation["reservation_id"]),
                        "item_id": item_id,
                        "quantity": quantity,
                    }
                )
                continue

            if source_type == "generic_order":
                if ref_id is None:
                    skipped.append(
                        {
                            "item_id": item_id,
                            "reason": "generic order source is missing an order reference",
                        }
                    )
                    continue
                order_id = int(ref_id)
                has_ordered_procurement_link = conn.execute(
                    """
                    SELECT 1
                    FROM procurement_lines
                    WHERE linked_order_id = ?
                      AND status = 'ORDERED'
                    LIMIT 1
                    """,
                    (order_id,),
                ).fetchone() is not None
                has_ordered_rfq_link = conn.execute(
                    """
                    SELECT 1
                    FROM rfq_lines
                    WHERE linked_order_id = ?
                      AND status = 'ORDERED'
                    LIMIT 1
                    """,
                    (order_id,),
                ).fetchone() is not None
                if has_ordered_procurement_link or has_ordered_rfq_link:
                    skipped.append(
                        {
                            "item_id": item_id,
                            "order_id": order_id,
                            "reason": (
                                "order is already managed by an ORDERED procurement line"
                                if has_ordered_procurement_link
                                else "order is already managed by an ORDERED RFQ line"
                            ),
                        }
                    )
                    continue

                order = get_order(conn, order_id)
                order_amount = int(order["order_amount"])
                if quantity > order_amount:
                    skipped.append(
                        {
                            "item_id": item_id,
                            "order_id": order_id,
                            "reason": "allocation quantity exceeds current open order quantity",
                        }
                    )
                    continue

                if quantity == order_amount:
                    preview_entry = {
                        "order_id": order_id,
                        "item_id": item_id,
                        "quantity": quantity,
                        "action": "assign",
                    }
                    if dry_run:
                        orders_assigned.append(preview_entry)
                        continue
                    update_order(conn, order_id, {"project_id": project_id})
                    orders_assigned.append(preview_entry)
                    continue

                if not order.get("expected_arrival"):
                    skipped.append(
                        {
                            "item_id": item_id,
                            "order_id": order_id,
                            "reason": "partial allocation requires an expected_arrival on the source order",
                        }
                    )
                    continue

                preview_entry = {
                    "original_order_id": order_id,
                    "new_order_id": None,
                    "item_id": item_id,
                    "assigned_quantity": quantity,
                    "remaining_quantity": order_amount - quantity,
                }
                if dry_run:
                    orders_split.append(preview_entry)
                    continue
                split_result = update_order(
                    conn,
                    order_id,
                    {
                        "expected_arrival": order["expected_arrival"],
                        "split_quantity": quantity,
                    },
                )
                created_order_id = int(split_result["created_order"]["order_id"])
                update_order(conn, created_order_id, {"project_id": project_id})
                preview_entry["new_order_id"] = created_order_id
                orders_split.append(preview_entry)
                continue

            skipped.append(
                {
                    "item_id": item_id,
                    "ref_id": ref_id,
                    "reason": (
                        "already dedicated"
                        if source_type in {"dedicated_order", "quoted_procurement", "quoted_rfq"}
                        else f"unsupported allocation source type '{source_type}'"
                    ),
                }
            )

    return {
        "project_id": int(project_id),
        "project_name": str(project["name"]),
        "target_date": effective_target_date,
        "dry_run": bool(dry_run),
        "snapshot_signature": snapshot_signature,
        "summary": summary,
        "orders_assigned": orders_assigned,
        "orders_split": orders_split,
        "reservations_created": reservations_created,
        "skipped": skipped,
    }


def _load_project_procurement_summary(conn: sqlite3.Connection) -> dict[int, dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
            p.project_id,
            COUNT(DISTINCT pb.batch_id) AS total_batches,
            COUNT(DISTINCT CASE WHEN pb.status IN ('DRAFT', 'SENT', 'QUOTED', 'ORDERED') THEN pb.batch_id END) AS open_batch_count,
            COUNT(DISTINCT CASE WHEN pb.status = 'CLOSED' THEN pb.batch_id END) AS closed_batch_count,
            COUNT(DISTINCT CASE WHEN pb.status = 'CANCELLED' THEN pb.batch_id END) AS cancelled_batch_count,
            COALESCE(SUM(CASE WHEN pl.status = 'DRAFT' THEN 1 ELSE 0 END), 0) AS draft_line_count,
            COALESCE(SUM(CASE WHEN pl.status = 'SENT' THEN 1 ELSE 0 END), 0) AS sent_line_count,
            COALESCE(SUM(CASE WHEN pl.status = 'QUOTED' THEN 1 ELSE 0 END), 0) AS quoted_line_count,
            COALESCE(SUM(CASE WHEN pl.status = 'ORDERED' THEN 1 ELSE 0 END), 0) AS ordered_line_count,
            MAX(pl.expected_arrival) AS latest_target_date
        FROM projects p
        LEFT JOIN procurement_lines pl ON pl.source_project_id = p.project_id
        LEFT JOIN procurement_batches pb ON pb.batch_id = pl.batch_id
        GROUP BY p.project_id
        """
    ).fetchall()
    return {
        int(row["project_id"]): {
            "total_batches": int(row["total_batches"] or 0),
            "open_batch_count": int(row["open_batch_count"] or 0),
            "closed_batch_count": int(row["closed_batch_count"] or 0),
            "cancelled_batch_count": int(row["cancelled_batch_count"] or 0),
            "draft_line_count": int(row["draft_line_count"] or 0),
            "sent_line_count": int(row["sent_line_count"] or 0),
            "quoted_line_count": int(row["quoted_line_count"] or 0),
            "ordered_line_count": int(row["ordered_line_count"] or 0),
            "latest_target_date": row["latest_target_date"],
        }
        for row in rows
    }


def get_workspace_summary(conn: sqlite3.Connection) -> dict[str, Any]:
    project_rows = conn.execute(
        """
        SELECT
            p.project_id,
            p.name,
            p.description,
            p.status,
            p.planned_start,
            p.created_at,
            p.updated_at,
            COUNT(pr.requirement_id) AS requirement_count
        FROM projects p
        LEFT JOIN project_requirements pr ON pr.project_id = p.project_id
        GROUP BY p.project_id
        ORDER BY
            CASE p.status
                WHEN 'ACTIVE' THEN 0
                WHEN 'CONFIRMED' THEN 1
                WHEN 'PLANNING' THEN 2
                WHEN 'COMPLETED' THEN 3
                ELSE 4
            END,
            COALESCE(p.planned_start, '9999-12-31') ASC,
            p.project_id DESC
        """
    ).fetchall()
    pipeline = list_planning_pipeline(conn)
    pipeline_lookup = {int(row["project_id"]): row for row in pipeline}
    procurement_lookup = _load_project_procurement_summary(conn)

    projects: list[dict[str, Any]] = []
    for row in project_rows:
        project_id_value = int(row["project_id"])
        planning_summary = pipeline_lookup.get(project_id_value)
        status = str(row["status"])
        if status in PLANNING_COMMITTED_PROJECT_STATUSES:
            summary_mode = "authoritative"
            summary_message = "Committed pipeline metrics are live."
        elif status == "PLANNING":
            summary_mode = "preview_required"
            summary_message = "Draft project does not consume pipeline capacity until previewed or confirmed."
        else:
            summary_mode = "not_plannable"
            summary_message = "Completed and cancelled projects are excluded from planning analysis."
        procurement_summary = procurement_lookup.get(
            project_id_value,
            {
                "total_batches": 0,
                "open_batch_count": 0,
                "closed_batch_count": 0,
                "cancelled_batch_count": 0,
                "draft_line_count": 0,
                "sent_line_count": 0,
                "quoted_line_count": 0,
                "ordered_line_count": 0,
                "latest_target_date": None,
            },
        )
        legacy_rfq_row = conn.execute(
            """
            SELECT
                COUNT(DISTINCT rb.rfq_id) AS total_batches,
                COUNT(DISTINCT CASE WHEN rb.status = 'OPEN' THEN rb.rfq_id END) AS open_batch_count,
                COUNT(DISTINCT CASE WHEN rb.status = 'CLOSED' THEN rb.rfq_id END) AS closed_batch_count,
                COUNT(DISTINCT CASE WHEN rb.status = 'CANCELLED' THEN rb.rfq_id END) AS cancelled_batch_count,
                COALESCE(SUM(CASE WHEN rl.status = 'DRAFT' THEN 1 ELSE 0 END), 0) AS draft_line_count,
                COALESCE(SUM(CASE WHEN rl.status = 'QUOTED' THEN 1 ELSE 0 END), 0) AS quoted_line_count,
                COALESCE(SUM(CASE WHEN rl.status = 'ORDERED' THEN 1 ELSE 0 END), 0) AS ordered_line_count,
                MAX(rb.target_date) AS latest_target_date
            FROM rfq_batches rb
            LEFT JOIN rfq_lines rl ON rl.rfq_id = rb.rfq_id
            WHERE rb.project_id = ?
            """,
            (project_id_value,),
        ).fetchone()
        rfq_summary = procurement_summary
        if legacy_rfq_row is not None and int(legacy_rfq_row["total_batches"] or 0) > 0:
            rfq_summary = {
                "total_batches": int(legacy_rfq_row["total_batches"] or 0),
                "open_batch_count": int(legacy_rfq_row["open_batch_count"] or 0),
                "closed_batch_count": int(legacy_rfq_row["closed_batch_count"] or 0),
                "cancelled_batch_count": int(legacy_rfq_row["cancelled_batch_count"] or 0),
                "draft_line_count": int(legacy_rfq_row["draft_line_count"] or 0),
                "sent_line_count": 0,
                "quoted_line_count": int(legacy_rfq_row["quoted_line_count"] or 0),
                "ordered_line_count": int(legacy_rfq_row["ordered_line_count"] or 0),
                "latest_target_date": legacy_rfq_row["latest_target_date"],
            }
        projects.append(
            {
                "project_id": project_id_value,
                "name": row["name"],
                "description": row["description"],
                "status": status,
                "planned_start": row["planned_start"],
                "requirement_count": int(row["requirement_count"] or 0),
                "summary_mode": summary_mode,
                "summary_message": summary_message,
                "planning_summary": planning_summary,
                "procurement_summary": procurement_summary,
                "rfq_summary": rfq_summary,
            }
        )

    return {
        "generated_at": now_jst_iso(),
        "projects": projects,
        "pipeline": pipeline,
    }


def get_item_planning_context(
    conn: sqlite3.Connection,
    item_id: int,
    *,
    preview_project_id: int | None = None,
    target_date: str | None = None,
) -> dict[str, Any]:
    item = get_item(conn, item_id)
    snapshot = _build_project_planning_snapshot(
        conn,
        project_id=preview_project_id,
        target_date=target_date,
        focus_item_id=item_id,
    )
    project_rows: list[dict[str, Any]] = []
    for summary in snapshot["project_summaries"]:
        project_id_value = int(summary["project_id"])
        row = next(
            (
                candidate
                for candidate in snapshot["project_rows"].get(project_id_value, [])
                if int(candidate["item_id"]) == item_id
            ),
            None,
        )
        if row is None:
            continue
        project_rows.append(
            {
                "project_id": project_id_value,
                "project_name": summary["name"],
                "project_status": summary["status"],
                "planned_start": summary["planned_start"],
                "is_planning_preview": bool(summary["is_planning_preview"]),
                "required_quantity": int(row["required_quantity"]),
                "dedicated_supply_by_start": int(row["dedicated_supply_by_start"]),
                "generic_available_at_start": int(row["generic_available_at_start"]),
                "generic_allocated_quantity": int(row["generic_allocated_quantity"]),
                "covered_on_time_quantity": int(row["covered_on_time_quantity"]),
                "shortage_at_start": int(row["shortage_at_start"]),
                "future_generic_recovery_quantity": int(row["future_generic_recovery_quantity"]),
                "future_dedicated_recovery_quantity": int(row["future_dedicated_recovery_quantity"]),
                "recovered_after_start_quantity": int(row["recovered_after_start_quantity"]),
                "remaining_shortage_quantity": int(row["remaining_shortage_quantity"]),
                "supply_sources_by_start": list(row.get("supply_sources_by_start") or []),
                "recovery_sources_after_start": list(row.get("recovery_sources_after_start") or []),
            }
        )

    return {
        "item_id": int(item["item_id"]),
        "item_number": item["item_number"],
        "manufacturer_name": item["manufacturer_name"],
        "preview_project_id": preview_project_id,
        "target_date": snapshot["selected_target_date"],
        "projects": project_rows,
    }


def _format_planning_source_list(sources: list[dict[str, Any]]) -> str:
    return " | ".join(
        f"{int(source.get('quantity') or 0)} {str(source.get('label') or '').strip()}".strip()
        for source in sources
        if int(source.get("quantity") or 0) > 0
    )


def export_workspace_planning_csv(
    conn: sqlite3.Connection,
    *,
    project_id: int,
    target_date: str | None = None,
) -> tuple[str, bytes]:
    analysis = project_planning_analysis(conn, project_id, target_date=target_date)
    procurement_lookup = _load_project_procurement_summary(conn)
    fieldnames = [
        "section",
        "project_id",
        "project_name",
        "project_status",
        "planned_start",
        "target_date",
        "procurement_open_batches",
        "procurement_quoted_lines",
        "procurement_ordered_lines",
        "item_id",
        "item_number",
        "manufacturer_name",
        "required_quantity",
        "covered_on_time_quantity",
        "shortage_at_start",
        "recovered_after_start_quantity",
        "remaining_shortage_quantity",
        "dedicated_supply_by_start",
        "generic_allocated_quantity",
        "generic_committed_total",
        "cumulative_generic_consumed_before_total",
        "coverage_sources",
        "recovery_sources",
    ]
    rows: list[dict[str, Any]] = []

    selected_procurement = procurement_lookup.get(int(analysis["project"]["project_id"]), {})
    selected_recovered_total = sum(
        int(row["recovered_after_start_quantity"]) for row in analysis["rows"]
    )
    rows.append(
        {
            "section": "selected_project_summary",
            "project_id": int(analysis["project"]["project_id"]),
            "project_name": analysis["project"]["name"],
            "project_status": analysis["project"]["status"],
            "planned_start": analysis["project"]["planned_start"],
            "target_date": analysis["target_date"],
            "procurement_open_batches": int(selected_procurement.get("open_batch_count") or 0),
            "procurement_quoted_lines": int(selected_procurement.get("quoted_line_count") or 0),
            "procurement_ordered_lines": int(selected_procurement.get("ordered_line_count") or 0),
            "item_id": "",
            "item_number": "",
            "manufacturer_name": "",
            "required_quantity": int(analysis["summary"]["required_total"]),
            "covered_on_time_quantity": int(analysis["summary"]["covered_on_time_total"]),
            "shortage_at_start": int(analysis["summary"]["shortage_at_start_total"]),
            "recovered_after_start_quantity": selected_recovered_total,
            "remaining_shortage_quantity": int(analysis["summary"]["remaining_shortage_total"]),
            "dedicated_supply_by_start": "",
            "generic_allocated_quantity": "",
            "generic_committed_total": int(analysis["summary"]["generic_committed_total"]),
            "cumulative_generic_consumed_before_total": int(
                analysis["summary"]["cumulative_generic_consumed_before_total"]
            ),
            "coverage_sources": "",
            "recovery_sources": "",
        }
    )

    for summary in analysis["pipeline"]:
        procurement_summary = procurement_lookup.get(int(summary["project_id"]), {})
        rows.append(
            {
                "section": "pipeline",
                "project_id": int(summary["project_id"]),
                "project_name": summary["name"],
                "project_status": summary["status"],
                "planned_start": summary["planned_start"],
                "target_date": analysis["target_date"],
                "procurement_open_batches": int(procurement_summary.get("open_batch_count") or 0),
                "procurement_quoted_lines": int(procurement_summary.get("quoted_line_count") or 0),
                "procurement_ordered_lines": int(procurement_summary.get("ordered_line_count") or 0),
                "item_id": "",
                "item_number": "",
                "manufacturer_name": "",
                "required_quantity": int(summary["required_total"]),
                "covered_on_time_quantity": int(summary["covered_on_time_total"]),
                "shortage_at_start": int(summary["shortage_at_start_total"]),
                "recovered_after_start_quantity": "",
                "remaining_shortage_quantity": int(summary["remaining_shortage_total"]),
                "dedicated_supply_by_start": "",
                "generic_allocated_quantity": "",
                "generic_committed_total": int(summary["generic_committed_total"]),
                "cumulative_generic_consumed_before_total": int(
                    summary["cumulative_generic_consumed_before_total"]
                ),
                "coverage_sources": "",
                "recovery_sources": "",
            }
        )

    for row in analysis["rows"]:
        rows.append(
            {
                "section": "selected_project_item",
                "project_id": int(analysis["project"]["project_id"]),
                "project_name": analysis["project"]["name"],
                "project_status": analysis["project"]["status"],
                "planned_start": analysis["project"]["planned_start"],
                "target_date": analysis["target_date"],
                "procurement_open_batches": int(selected_procurement.get("open_batch_count") or 0),
                "procurement_quoted_lines": int(selected_procurement.get("quoted_line_count") or 0),
                "procurement_ordered_lines": int(selected_procurement.get("ordered_line_count") or 0),
                "item_id": int(row["item_id"]),
                "item_number": row["item_number"],
                "manufacturer_name": row["manufacturer_name"],
                "required_quantity": int(row["required_quantity"]),
                "covered_on_time_quantity": int(row["covered_on_time_quantity"]),
                "shortage_at_start": int(row["shortage_at_start"]),
                "recovered_after_start_quantity": int(row["recovered_after_start_quantity"]),
                "remaining_shortage_quantity": int(row["remaining_shortage_quantity"]),
                "dedicated_supply_by_start": int(row["dedicated_supply_by_start"]),
                "generic_allocated_quantity": int(row["generic_allocated_quantity"]),
                "generic_committed_total": "",
                "cumulative_generic_consumed_before_total": "",
                "coverage_sources": _format_planning_source_list(
                    list(row.get("supply_sources_by_start") or [])
                ),
                "recovery_sources": _format_planning_source_list(
                    list(row.get("recovery_sources_after_start") or [])
                ),
            }
        )

    filename = (
        f"workspace_planning_project_{int(analysis['project']['project_id'])}_{analysis['target_date']}.csv"
    )
    return filename, _csv_bytes(fieldnames, rows)


def export_workspace_planning_multi_csv(
    conn: sqlite3.Connection,
    *,
    project_id: int | None = None,
    target_date: str | None = None,
) -> tuple[str, bytes]:
    snapshot = _build_project_planning_snapshot(
        conn,
        project_id=project_id,
        target_date=target_date,
    )
    procurement_lookup = _load_project_procurement_summary(conn)
    export_target_date = snapshot["selected_target_date"] or ""
    fieldnames = [
        "section",
        "project_rank",
        "project_id",
        "project_name",
        "project_status",
        "is_planning_preview",
        "planned_start",
        "target_date",
        "procurement_open_batches",
        "procurement_quoted_lines",
        "procurement_ordered_lines",
        "item_id",
        "item_number",
        "manufacturer_name",
        "required_quantity",
        "covered_on_time_quantity",
        "shortage_at_start",
        "recovered_after_start_quantity",
        "remaining_shortage_quantity",
        "dedicated_supply_by_start",
        "generic_allocated_quantity",
        "generic_committed_total",
        "cumulative_generic_consumed_before_total",
        "coverage_sources",
        "recovery_sources",
    ]
    rows: list[dict[str, Any]] = []

    for project_rank, summary in enumerate(snapshot["project_summaries"], start=1):
        pid = int(summary["project_id"])
        project_rows = snapshot["project_rows"].get(pid, [])
        procurement_summary = procurement_lookup.get(pid, {})
        recovered_total = sum(
            int(row["recovered_after_start_quantity"]) for row in project_rows
        )
        rows.append(
            {
                "section": "project_summary",
                "project_rank": project_rank,
                "project_id": pid,
                "project_name": summary["name"],
                "project_status": summary["status"],
                "is_planning_preview": bool(summary["is_planning_preview"]),
                "planned_start": summary["planned_start"],
                "target_date": export_target_date,
                "procurement_open_batches": int(procurement_summary.get("open_batch_count") or 0),
                "procurement_quoted_lines": int(procurement_summary.get("quoted_line_count") or 0),
                "procurement_ordered_lines": int(procurement_summary.get("ordered_line_count") or 0),
                "item_id": "",
                "item_number": "",
                "manufacturer_name": "",
                "required_quantity": int(summary["required_total"]),
                "covered_on_time_quantity": int(summary["covered_on_time_total"]),
                "shortage_at_start": int(summary["shortage_at_start_total"]),
                "recovered_after_start_quantity": recovered_total,
                "remaining_shortage_quantity": int(summary["remaining_shortage_total"]),
                "dedicated_supply_by_start": "",
                "generic_allocated_quantity": "",
                "generic_committed_total": int(summary["generic_committed_total"]),
                "cumulative_generic_consumed_before_total": int(
                    summary["cumulative_generic_consumed_before_total"]
                ),
                "coverage_sources": "",
                "recovery_sources": "",
            }
        )
        for row in project_rows:
            rows.append(
                {
                    "section": "project_item",
                    "project_rank": project_rank,
                    "project_id": pid,
                    "project_name": summary["name"],
                    "project_status": summary["status"],
                    "is_planning_preview": bool(summary["is_planning_preview"]),
                    "planned_start": summary["planned_start"],
                    "target_date": export_target_date,
                    "procurement_open_batches": int(procurement_summary.get("open_batch_count") or 0),
                    "procurement_quoted_lines": int(procurement_summary.get("quoted_line_count") or 0),
                    "procurement_ordered_lines": int(procurement_summary.get("ordered_line_count") or 0),
                    "item_id": int(row["item_id"]),
                    "item_number": row["item_number"],
                    "manufacturer_name": row["manufacturer_name"],
                    "required_quantity": int(row["required_quantity"]),
                    "covered_on_time_quantity": int(row["covered_on_time_quantity"]),
                    "shortage_at_start": int(row["shortage_at_start"]),
                    "recovered_after_start_quantity": int(
                        row["recovered_after_start_quantity"]
                    ),
                    "remaining_shortage_quantity": int(
                        row["remaining_shortage_quantity"]
                    ),
                    "dedicated_supply_by_start": int(row["dedicated_supply_by_start"]),
                    "generic_allocated_quantity": int(
                        row["generic_allocated_quantity"]
                    ),
                    "generic_committed_total": "",
                    "cumulative_generic_consumed_before_total": "",
                    "coverage_sources": _format_planning_source_list(
                        list(row.get("supply_sources_by_start") or [])
                    ),
                    "recovery_sources": _format_planning_source_list(
                        list(row.get("recovery_sources_after_start") or [])
                    ),
                }
            )

    if project_id is not None and snapshot["selected_target_date"] is not None:
        filename = (
            "workspace_planning_pipeline_"
            f"project_{project_id}_{snapshot['selected_target_date']}.csv"
        )
    else:
        filename = f"workspace_planning_pipeline_{today_jst()}.csv"
    return filename, _csv_bytes(fieldnames, rows)


def list_planning_pipeline(
    conn: sqlite3.Connection,
    *,
    preview_project_id: int | None = None,
    target_date: str | None = None,
) -> list[dict[str, Any]]:
    snapshot = _build_project_planning_snapshot(
        conn,
        project_id=preview_project_id,
        target_date=target_date,
    )
    return snapshot["project_summaries"]


def project_planning_analysis(
    conn: sqlite3.Connection,
    project_id: int,
    *,
    target_date: str | None = None,
) -> dict[str, Any]:
    snapshot = _build_project_planning_snapshot(
        conn,
        project_id=project_id,
        target_date=target_date,
    )
    project = get_project(conn, project_id)
    target = snapshot["selected_target_date"]
    if target is None:
        target = _normalize_project_planning_date(project)
    summary = next(
        (row for row in snapshot["project_summaries"] if int(row["project_id"]) == project_id),
        None,
    )
    if summary is None:
        raise AppError(
            code="PROJECT_NOT_IN_PLANNING_PIPELINE",
            message="Project is not present in the planning pipeline",
            status_code=404,
        )
    project = dict(project)
    project["planned_start"] = target
    return {
        "project": project,
        "target_date": target,
        "summary": summary,
        "rows": snapshot["project_rows"].get(project_id, []),
        "pipeline": snapshot["project_summaries"],
    }


def project_gap_analysis(
    conn: sqlite3.Connection, project_id: int, *, target_date: str | None = None
) -> dict[str, Any]:
    if target_date is None:
        project = get_project(conn, project_id)
        effective_date = today_jst()
        project = dict(project)
        project["planned_start"] = effective_date
        required_by_item = _aggregate_project_required_by_item(conn, project)
        rows: list[dict[str, Any]] = []
        required_total = 0
        covered_total = 0
        shortage_total = 0
        for item_id in sorted(required_by_item):
            item = get_item(conn, item_id)
            required_quantity = int(required_by_item[item_id])
            available_stock = _get_total_available_inventory(conn, item_id)
            shortage = max(0, required_quantity - available_stock)
            covered = min(required_quantity, available_stock)
            rows.append(
                {
                    "item_id": item_id,
                    "item_number": item["item_number"],
                    "required_quantity": required_quantity,
                    "available_stock": available_stock,
                    "shortage": shortage,
                    "dedicated_supply_by_start": 0,
                    "generic_allocated_quantity": covered,
                    "remaining_shortage_quantity": shortage,
                }
            )
            required_total += required_quantity
            covered_total += covered
            shortage_total += shortage
        return {
            "project": project,
            "target_date": effective_date,
            "summary": {
                "project_id": int(project["project_id"]),
                "name": project["name"],
                "status": project["status"],
                "planned_start": project.get("planned_start"),
                "is_planning_preview": bool(project.get("status") not in PLANNING_COMMITTED_PROJECT_STATUSES),
                "item_count": len(rows),
                "required_total": required_total,
                "covered_on_time_total": covered_total,
                "shortage_at_start_total": shortage_total,
                "remaining_shortage_total": shortage_total,
                "generic_committed_total": covered_total,
                "cumulative_generic_consumed_before_total": 0,
            },
            "rows": rows,
        }
    planning = project_planning_analysis(conn, project_id, target_date=target_date)
    rows = [
        {
            "item_id": row["item_id"],
            "item_number": row["item_number"],
            "required_quantity": row["required_quantity"],
            "available_stock": int(row["generic_available_at_start"])
            + int(row["dedicated_supply_by_start"]),
            "shortage": row["shortage_at_start"],
            "dedicated_supply_by_start": row["dedicated_supply_by_start"],
            "generic_allocated_quantity": row["generic_allocated_quantity"],
            "remaining_shortage_quantity": row["remaining_shortage_quantity"],
        }
        for row in planning["rows"]
    ]
    return {
        "project": planning["project"],
        "target_date": planning["target_date"],
        "summary": planning["summary"],
        "rows": rows,
    }


def confirm_project_for_procurement(
    conn: sqlite3.Connection,
    project_id: int,
    *,
    target_date: str | None = None,
) -> dict[str, Any]:
    project = get_project(conn, project_id)
    if str(project["status"]) != "PLANNING":
        return project
    effective_target_date = _normalize_project_planning_date(project, target_date=target_date)
    now = now_jst_iso()
    conn.execute(
        """
        UPDATE projects
        SET status = 'CONFIRMED',
            planned_start = ?,
            updated_at = ?
        WHERE project_id = ?
        """,
        (effective_target_date, now, project_id),
    )
    return get_project(conn, project_id)


def reserve_project_requirements(conn: sqlite3.Connection, project_id: int) -> dict[str, Any]:
    project = get_project(conn, project_id)
    created: list[dict[str, Any]] = []
    required_by_item = _aggregate_project_required_by_item(conn, project)
    for item_id, required_qty in sorted(required_by_item.items()):
        reserve_qty = min(required_qty, _get_total_available_inventory(conn, item_id))
        if reserve_qty <= 0:
            continue
        created.append(
            create_reservation(
                conn,
                {
                    "item_id": item_id,
                    "quantity": reserve_qty,
                    "purpose": f"Project:{project['name']}",
                    "note": "Project requirement reservation",
                    "project_id": project_id,
                },
            )
        )
    return {"project_id": project_id, "created_reservations": created}


def _rfq_batch_row(conn: sqlite3.Connection, rfq_id: int) -> sqlite3.Row:
    row = conn.execute(
        """
        SELECT
            rb.*,
            p.name AS project_name,
            COUNT(rl.line_id) AS line_count,
            COALESCE(SUM(rl.finalized_quantity), 0) AS finalized_quantity_total,
            COALESCE(SUM(CASE WHEN rl.status = 'QUOTED' THEN 1 ELSE 0 END), 0) AS quoted_line_count,
            COALESCE(SUM(CASE WHEN rl.status = 'ORDERED' THEN 1 ELSE 0 END), 0) AS ordered_line_count
        FROM rfq_batches rb
        JOIN projects p ON p.project_id = rb.project_id
        LEFT JOIN rfq_lines rl ON rl.rfq_id = rb.rfq_id
        WHERE rb.rfq_id = ?
        GROUP BY rb.rfq_id, p.name
        """,
        (rfq_id,),
    ).fetchone()
    if row is None:
        raise AppError(
            code="RFQ_BATCH_NOT_FOUND",
            message=f"RFQ batch with id {rfq_id} not found",
            status_code=404,
        )
    return row


def _rfq_line_detail_rows(conn: sqlite3.Connection, rfq_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
            rl.*,
            im.item_number,
            m.name AS manufacturer_name,
            rl.linked_order_id AS linked_purchase_order_line_id,
            o.project_id AS linked_purchase_order_line_project_id,
            o.expected_arrival AS linked_purchase_order_line_expected_arrival,
            q.quotation_number AS linked_quotation_number,
            s.name AS linked_purchase_order_line_supplier_name
        FROM rfq_lines rl
        JOIN items_master im ON im.item_id = rl.item_id
        JOIN manufacturers m ON m.manufacturer_id = im.manufacturer_id
        LEFT JOIN orders o ON o.order_id = rl.linked_order_id
        LEFT JOIN quotations q ON q.quotation_id = o.quotation_id
        LEFT JOIN suppliers s ON s.supplier_id = q.supplier_id
        WHERE rl.rfq_id = ?
        ORDER BY rl.line_id ASC
        """,
        (rfq_id,),
    ).fetchall()
    return _rows_to_dict(rows)


def get_rfq_batch(conn: sqlite3.Connection, rfq_id: int) -> dict[str, Any]:
    data = dict(_rfq_batch_row(conn, rfq_id))
    data["lines"] = _rfq_line_detail_rows(conn, rfq_id)
    return data


def list_rfq_batches(
    conn: sqlite3.Connection,
    *,
    status: str | None = None,
    project_id: int | None = None,
    page: int = 1,
    per_page: int = 50,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if status:
        clauses.append("rb.status = ?")
        params.append(_validate_rfq_batch_status(status))
    if project_id is not None:
        clauses.append("rb.project_id = ?")
        params.append(project_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"""
        SELECT
            rb.*,
            p.name AS project_name,
            COUNT(rl.line_id) AS line_count,
            COALESCE(SUM(rl.finalized_quantity), 0) AS finalized_quantity_total,
            COALESCE(SUM(CASE WHEN rl.status = 'QUOTED' THEN 1 ELSE 0 END), 0) AS quoted_line_count,
            COALESCE(SUM(CASE WHEN rl.status = 'ORDERED' THEN 1 ELSE 0 END), 0) AS ordered_line_count
        FROM rfq_batches rb
        JOIN projects p ON p.project_id = rb.project_id
        LEFT JOIN rfq_lines rl ON rl.rfq_id = rb.rfq_id
        {where}
        GROUP BY rb.rfq_id, p.name
        ORDER BY rb.updated_at DESC, rb.rfq_id DESC
    """
    return _paginate(conn, sql, tuple(params), page, per_page)


def create_project_rfq_batch_from_analysis(
    conn: sqlite3.Connection,
    project_id: int,
    *,
    title: str | None = None,
    note: str | None = None,
    target_date: str | None = None,
) -> dict[str, Any]:
    analysis = project_planning_analysis(conn, project_id, target_date=target_date)
    project = analysis["project"]
    shortage_rows = [row for row in analysis["rows"] if int(row["shortage_at_start"]) > 0]
    if not shortage_rows:
        raise AppError(
            code="RFQ_NOT_REQUIRED",
            message="Project has no uncovered on-time shortage rows to convert into RFQ lines",
            status_code=409,
        )
    now = now_jst_iso()
    resolved_title = (title or "").strip() or f"{project['name']} RFQ ({analysis['target_date']})"
    cur = conn.execute(
        """
        INSERT INTO rfq_batches (
            project_id, title, target_date, status, note, created_at, updated_at
        ) VALUES (?, ?, ?, 'OPEN', ?, ?, ?)
        """,
        (
            project_id,
            resolved_title,
            analysis["target_date"],
            note,
            now,
            now,
        ),
    )
    rfq_id = int(cur.lastrowid)
    for row in shortage_rows:
        shortage_qty = int(row["shortage_at_start"])
        conn.execute(
            """
            INSERT INTO rfq_lines (
                rfq_id,
                item_id,
                requested_quantity,
                finalized_quantity,
                status,
                note,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, 'DRAFT', ?, ?, ?)
            """,
            (
                rfq_id,
                int(row["item_id"]),
                shortage_qty,
                shortage_qty,
                f"Created from planning shortage at {analysis['target_date']}",
                now,
                now,
            ),
        )
    if project["status"] == "PLANNING":
        confirm_project_for_procurement(conn, project_id, target_date=analysis["target_date"])
    return get_rfq_batch(conn, rfq_id)


def update_rfq_batch(
    conn: sqlite3.Connection,
    rfq_id: int,
    payload: dict[str, Any],
) -> dict[str, Any]:
    _rfq_batch_row(conn, rfq_id)
    updates: list[str] = []
    params: list[Any] = []
    if "title" in payload:
        updates.append("title = ?")
        params.append(require_non_empty(str(payload.get("title") or ""), "title"))
    if "status" in payload and payload.get("status") is not None:
        updates.append("status = ?")
        params.append(_validate_rfq_batch_status(str(payload["status"])))
    if "note" in payload:
        updates.append("note = ?")
        params.append(payload.get("note"))
    if updates:
        updates.append("updated_at = ?")
        params.append(now_jst_iso())
        conn.execute(
            f"UPDATE rfq_batches SET {', '.join(updates)} WHERE rfq_id = ?",
            (*params, rfq_id),
        )
    return get_rfq_batch(conn, rfq_id)


def _rfq_line_row(conn: sqlite3.Connection, line_id: int) -> sqlite3.Row:
    row = conn.execute(
        """
        SELECT
            rl.*,
            rb.project_id,
            rb.status AS batch_status
        FROM rfq_lines rl
        JOIN rfq_batches rb ON rb.rfq_id = rl.rfq_id
        WHERE rl.line_id = ?
        """,
        (line_id,),
    ).fetchone()
    if row is None:
        raise AppError(
            code="RFQ_LINE_NOT_FOUND",
            message=f"RFQ line with id {line_id} not found",
            status_code=404,
        )
    return row


def _ordered_rfq_project_for_order(conn: sqlite3.Connection, order_id: int) -> int | None:
    rows = conn.execute(
        """
        SELECT DISTINCT rb.project_id
        FROM rfq_lines rl
        JOIN rfq_batches rb ON rb.rfq_id = rl.rfq_id
        WHERE rl.linked_order_id = ?
          AND rl.status = 'ORDERED'
        """,
        (order_id,),
    ).fetchall()
    if not rows:
        return None
    project_ids = {int(row["project_id"]) for row in rows}
    if len(project_ids) > 1:
        raise AppError(
            code="RFQ_ORDER_PROJECT_CONFLICT",
            message="Linked order is attached to multiple projects via ordered RFQ lines",
            status_code=409,
        )
    return next(iter(project_ids))


def _sync_order_project_assignment_from_rfq(conn: sqlite3.Connection, order_id: int) -> None:
    project_id = _ordered_rfq_project_for_order(conn, order_id)
    if project_id is not None:
        conn.execute(
            "UPDATE orders SET project_id = ? WHERE order_id = ?",
            (project_id, order_id),
        )
    else:
        conn.execute(
            "UPDATE orders SET project_id = NULL"
            " WHERE order_id = ? AND project_id_manual = 0",
            (order_id,),
        )


def update_rfq_line(
    conn: sqlite3.Connection,
    line_id: int,
    payload: dict[str, Any],
) -> dict[str, Any]:
    current = _rfq_line_row(conn, line_id)
    batch_project_id = int(current["project_id"])
    current_linked_order_id = (
        int(current["linked_order_id"]) if current["linked_order_id"] is not None else None
    )
    updates: list[str] = []
    params: list[Any] = []

    if "requested_quantity" in payload and payload.get("requested_quantity") is not None:
        updates.append("requested_quantity = ?")
        params.append(require_positive_int(int(payload["requested_quantity"]), "requested_quantity"))
    if "finalized_quantity" in payload and payload.get("finalized_quantity") is not None:
        updates.append("finalized_quantity = ?")
        params.append(require_positive_int(int(payload["finalized_quantity"]), "finalized_quantity"))
    if "supplier_name" in payload:
        supplier_name = payload.get("supplier_name")
        updates.append("supplier_name = ?")
        params.append(require_non_empty(str(supplier_name), "supplier_name") if supplier_name else None)
    if "lead_time_days" in payload:
        lead_time_days = payload.get("lead_time_days")
        updates.append("lead_time_days = ?")
        params.append(None if lead_time_days is None else int(lead_time_days))
    normalized_expected_arrival = (
        normalize_optional_date(payload.get("expected_arrival"), "expected_arrival")
        if "expected_arrival" in payload
        else current["expected_arrival"]
    )
    if "expected_arrival" in payload:
        updates.append("expected_arrival = ?")
        params.append(normalized_expected_arrival)

    final_status = str(current["status"])
    if "status" in payload:
        final_status = _validate_rfq_line_status(str(payload["status"]))

    final_linked_order_id = current_linked_order_id
    linked_purchase_order_line_key_present = "linked_purchase_order_line_id" in payload
    if linked_purchase_order_line_key_present:
        final_linked_order_id = payload.get("linked_purchase_order_line_id")
        final_linked_order_id = None if final_linked_order_id is None else int(final_linked_order_id)
    if linked_purchase_order_line_key_present and final_linked_order_id is not None and "status" not in payload:
        final_status = "ORDERED"
    if final_status != "ORDERED":
        final_linked_order_id = None

    if final_status == "QUOTED" and normalized_expected_arrival is None:
        raise AppError(
            code="RFQ_EXPECTED_ARRIVAL_REQUIRED",
            message="expected_arrival is required before an RFQ line can be marked QUOTED",
            status_code=422,
        )
    if final_status == "ORDERED" and final_linked_order_id is None:
        raise AppError(
            code="RFQ_LINKED_ORDER_REQUIRED",
            message="linked_purchase_order_line_id is required before an RFQ line can be marked ORDERED",
            status_code=422,
        )
    if final_status == "ORDERED":
        order = get_order(conn, final_linked_order_id)
        if int(order["item_id"]) != int(current["item_id"]):
            raise AppError(
                code="RFQ_ORDER_ITEM_MISMATCH",
                message="Linked order item_id must match RFQ line item_id",
                status_code=409,
            )
        existing_order_project_id = order.get("project_id")
        if existing_order_project_id is not None and int(existing_order_project_id) != batch_project_id:
            raise AppError(
                code="RFQ_ORDER_PROJECT_CONFLICT",
                message="Linked order already belongs to another project",
                status_code=409,
            )
        linked_rfq_project_id = _ordered_rfq_project_for_order(conn, final_linked_order_id)
        if linked_rfq_project_id is not None and linked_rfq_project_id != batch_project_id:
            raise AppError(
                code="RFQ_ORDER_PROJECT_CONFLICT",
                message="Linked order already belongs to another project",
                status_code=409,
            )
        if order.get("expected_arrival") is None:
            raise AppError(
                code="ORDER_EXPECTED_ARRIVAL_REQUIRED",
                message="Linked order must have expected_arrival before it can drive project planning",
                status_code=409,
            )

    if final_linked_order_id != current_linked_order_id:
        updates.append("linked_order_id = ?")
        params.append(final_linked_order_id)
    if final_status != str(current["status"]):
        updates.append("status = ?")
        params.append(final_status)

    should_sync_orders = (
        final_linked_order_id != current_linked_order_id
        or final_status != str(current["status"])
    )
    impacted_order_ids = {
        order_id
        for order_id in (current_linked_order_id, final_linked_order_id)
        if order_id is not None
    }

    if updates:
        updates.append("updated_at = ?")
        params.append(now_jst_iso())
        conn.execute(
            f"UPDATE rfq_lines SET {', '.join(updates)} WHERE line_id = ?",
            (*params, line_id),
        )
        if should_sync_orders:
            for impacted_order_id in sorted(impacted_order_ids):
                _sync_order_project_assignment_from_rfq(conn, impacted_order_id)

    updated_row = _rfq_line_row(conn, line_id)
    return {
        "batch": dict(_rfq_batch_row(conn, int(updated_row["rfq_id"]))),
        "line": next(
            row for row in _rfq_line_detail_rows(conn, int(updated_row["rfq_id"])) if int(row["line_id"]) == line_id
        ),
    }


def _procurement_batch_row(conn: sqlite3.Connection, batch_id: int) -> sqlite3.Row:
    row = conn.execute(
        """
        SELECT
            pb.*,
            COUNT(pl.line_id) AS line_count,
            COALESCE(SUM(pl.finalized_quantity), 0) AS finalized_quantity_total,
            COALESCE(SUM(CASE WHEN pl.status = 'QUOTED' THEN 1 ELSE 0 END), 0) AS quoted_line_count,
            COALESCE(SUM(CASE WHEN pl.status = 'ORDERED' THEN 1 ELSE 0 END), 0) AS ordered_line_count
        FROM procurement_batches pb
        LEFT JOIN procurement_lines pl ON pl.batch_id = pb.batch_id
        WHERE pb.batch_id = ?
        GROUP BY pb.batch_id
        """,
        (batch_id,),
    ).fetchone()
    if row is None:
        raise AppError(
            code="PROCUREMENT_BATCH_NOT_FOUND",
            message=f"Procurement batch with id {batch_id} not found",
            status_code=404,
        )
    return row


def _procurement_line_detail_rows(conn: sqlite3.Connection, batch_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
            pl.*,
            im.item_number,
            im.category,
            im.description,
            m.name AS manufacturer_name,
            p.name AS source_project_name,
            pl.linked_order_id AS linked_purchase_order_line_id,
            o.project_id AS linked_purchase_order_line_project_id,
            o.expected_arrival AS linked_purchase_order_line_expected_arrival,
            q.quotation_number AS linked_quotation_number,
            s.name AS linked_purchase_order_line_supplier_name
        FROM procurement_lines pl
        JOIN items_master im ON im.item_id = pl.item_id
        JOIN manufacturers m ON m.manufacturer_id = im.manufacturer_id
        LEFT JOIN projects p ON p.project_id = pl.source_project_id
        LEFT JOIN orders o ON o.order_id = pl.linked_order_id
        LEFT JOIN quotations q ON q.quotation_id = COALESCE(pl.linked_quotation_id, o.quotation_id)
        LEFT JOIN suppliers s ON s.supplier_id = q.supplier_id
        WHERE pl.batch_id = ?
        ORDER BY
            CASE pl.status
                WHEN 'ORDERED' THEN 0
                WHEN 'QUOTED' THEN 1
                WHEN 'SENT' THEN 2
                ELSE 3
            END,
            pl.line_id
        """,
        (batch_id,),
    ).fetchall()
    return _rows_to_dict(rows)


def get_procurement_batch(conn: sqlite3.Connection, batch_id: int) -> dict[str, Any]:
    data = dict(_procurement_batch_row(conn, batch_id))
    data["lines"] = _procurement_line_detail_rows(conn, batch_id)
    return data


def list_procurement_batches(
    conn: sqlite3.Connection,
    *,
    status: str | None = None,
    item_id: int | None = None,
    project_id: int | None = None,
    page: int = 1,
    per_page: int = 50,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if status:
        clauses.append("pb.status = ?")
        params.append(_validate_procurement_batch_status(status))
    if item_id is not None:
        clauses.append("pl.item_id = ?")
        params.append(int(item_id))
    if project_id is not None:
        clauses.append("pl.source_project_id = ?")
        params.append(int(project_id))
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"""
        SELECT
            pb.*,
            COUNT(pl.line_id) AS line_count,
            COALESCE(SUM(pl.finalized_quantity), 0) AS finalized_quantity_total,
            COALESCE(SUM(CASE WHEN pl.status = 'QUOTED' THEN 1 ELSE 0 END), 0) AS quoted_line_count,
            COALESCE(SUM(CASE WHEN pl.status = 'ORDERED' THEN 1 ELSE 0 END), 0) AS ordered_line_count
        FROM procurement_batches pb
        LEFT JOIN procurement_lines pl ON pl.batch_id = pb.batch_id
        {where}
        GROUP BY pb.batch_id
        ORDER BY pb.updated_at DESC, pb.batch_id DESC
    """
    return _paginate(conn, sql, tuple(params), page, per_page)


def create_procurement_batch(conn: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    now = now_jst_iso()
    cur = conn.execute(
        """
        INSERT INTO procurement_batches (title, status, note, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            require_non_empty(str(payload.get("title") or ""), "title"),
            _validate_procurement_batch_status(str(payload.get("status") or "DRAFT")),
            payload.get("note"),
            now,
            now,
        ),
    )
    return get_procurement_batch(conn, int(cur.lastrowid))


def update_procurement_batch(conn: sqlite3.Connection, batch_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    _procurement_batch_row(conn, batch_id)
    updates: list[str] = []
    params: list[Any] = []
    if "title" in payload:
        updates.append("title = ?")
        params.append(require_non_empty(str(payload.get("title") or ""), "title"))
    if "status" in payload and payload.get("status") is not None:
        updates.append("status = ?")
        params.append(_validate_procurement_batch_status(str(payload["status"])))
    if "note" in payload:
        updates.append("note = ?")
        params.append(payload.get("note"))
    if updates:
        updates.append("updated_at = ?")
        params.append(now_jst_iso())
        conn.execute(
            f"UPDATE procurement_batches SET {', '.join(updates)} WHERE batch_id = ?",
            (*params, batch_id),
        )
    return get_procurement_batch(conn, batch_id)


def delete_procurement_batch(conn: sqlite3.Connection, batch_id: int) -> dict[str, Any]:
    batch = dict(_procurement_batch_row(conn, batch_id))
    if str(batch["status"]) != "DRAFT":
        raise AppError(
            code="PROCUREMENT_BATCH_NOT_DRAFT",
            message="Only DRAFT procurement batches can be deleted",
            status_code=409,
        )
    conn.execute("DELETE FROM procurement_batches WHERE batch_id = ?", (batch_id,))
    return {"deleted": True, "batch_id": batch_id}


def _ordered_procurement_project_for_order(conn: sqlite3.Connection, order_id: int) -> int | None:
    rows = conn.execute(
        """
        SELECT DISTINCT source_project_id AS project_id
        FROM procurement_lines
        WHERE linked_order_id = ?
          AND status = 'ORDERED'
          AND source_project_id IS NOT NULL
        """,
        (order_id,),
    ).fetchall()
    if not rows:
        return None
    project_ids = {int(row["project_id"]) for row in rows}
    if len(project_ids) > 1:
        raise AppError(
            code="PROCUREMENT_ORDER_PROJECT_CONFLICT",
            message="Linked order is attached to multiple projects via ordered procurement lines",
            status_code=409,
        )
    return next(iter(project_ids))


def _sync_order_project_assignment_from_procurement(conn: sqlite3.Connection, order_id: int) -> None:
    project_id = _ordered_procurement_project_for_order(conn, order_id)
    if project_id is not None:
        conn.execute("UPDATE orders SET project_id = ? WHERE order_id = ?", (project_id, order_id))
    else:
        rfq_project_id = _ordered_rfq_project_for_order(conn, order_id)
        if rfq_project_id is not None:
            conn.execute("UPDATE orders SET project_id = ? WHERE order_id = ?", (rfq_project_id, order_id))
            return
        conn.execute(
            "UPDATE orders SET project_id = NULL WHERE order_id = ? AND project_id_manual = 0",
            (order_id,),
        )


def add_procurement_lines(
    conn: sqlite3.Connection,
    *,
    batch_id: int,
    lines: list[dict[str, Any]],
) -> dict[str, Any]:
    _procurement_batch_row(conn, batch_id)
    now = now_jst_iso()
    for line in lines:
        requested_quantity = require_positive_int(int(line["requested_quantity"]), "requested_quantity")
        finalized_quantity = require_positive_int(
            int(line.get("finalized_quantity") or requested_quantity),
            "finalized_quantity",
        )
        conn.execute(
            """
            INSERT INTO procurement_lines (
                batch_id, item_id, source_type, source_project_id, requested_quantity, finalized_quantity,
                supplier_name, expected_arrival, linked_order_id, linked_quotation_id, status, note, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                batch_id,
                int(line["item_id"]),
                str(line.get("source_type") or "ADHOC").upper(),
                line.get("source_project_id"),
                requested_quantity,
                finalized_quantity,
                line.get("supplier_name"),
                normalize_optional_date(line.get("expected_arrival"), "expected_arrival"),
                line.get("linked_purchase_order_line_id"),
                line.get("linked_quotation_id"),
                _validate_procurement_line_status(str(line.get("status") or "DRAFT")),
                line.get("note"),
                now,
                now,
            ),
        )
    conn.execute("UPDATE procurement_batches SET updated_at = ? WHERE batch_id = ?", (now, batch_id))
    return get_procurement_batch(conn, batch_id)


def _procurement_line_row(conn: sqlite3.Connection, line_id: int) -> sqlite3.Row:
    row = conn.execute(
        """
        SELECT pl.*, pb.status AS batch_status
        FROM procurement_lines pl
        JOIN procurement_batches pb ON pb.batch_id = pl.batch_id
        WHERE pl.line_id = ?
        """,
        (line_id,),
    ).fetchone()
    if row is None:
        raise AppError(
            code="PROCUREMENT_LINE_NOT_FOUND",
            message=f"Procurement line with id {line_id} not found",
            status_code=404,
        )
    return row


def update_procurement_line(conn: sqlite3.Connection, line_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    current = _procurement_line_row(conn, line_id)
    current_linked_order_id = int(current["linked_order_id"]) if current["linked_order_id"] is not None else None
    updates: list[str] = []
    params: list[Any] = []

    if "requested_quantity" in payload and payload.get("requested_quantity") is not None:
        updates.append("requested_quantity = ?")
        params.append(require_positive_int(int(payload["requested_quantity"]), "requested_quantity"))
    if "finalized_quantity" in payload and payload.get("finalized_quantity") is not None:
        updates.append("finalized_quantity = ?")
        params.append(require_positive_int(int(payload["finalized_quantity"]), "finalized_quantity"))
    if "supplier_name" in payload:
        supplier_name = payload.get("supplier_name")
        updates.append("supplier_name = ?")
        params.append(require_non_empty(str(supplier_name), "supplier_name") if supplier_name else None)
    normalized_expected_arrival = (
        normalize_optional_date(payload.get("expected_arrival"), "expected_arrival")
        if "expected_arrival" in payload
        else current["expected_arrival"]
    )
    if "expected_arrival" in payload:
        updates.append("expected_arrival = ?")
        params.append(normalized_expected_arrival)

    final_status = str(current["status"])
    if "status" in payload:
        final_status = _validate_procurement_line_status(str(payload["status"]))

    final_linked_order_id = current_linked_order_id
    linked_purchase_order_line_key_present = "linked_purchase_order_line_id" in payload
    if linked_purchase_order_line_key_present:
        final_linked_order_id = payload.get("linked_purchase_order_line_id")
        final_linked_order_id = None if final_linked_order_id is None else int(final_linked_order_id)
    if linked_purchase_order_line_key_present and final_linked_order_id is not None and "status" not in payload:
        final_status = "ORDERED"
    if final_status != "ORDERED":
        final_linked_order_id = None

    if final_status == "QUOTED" and normalized_expected_arrival is None:
        raise AppError(
            code="PROCUREMENT_EXPECTED_ARRIVAL_REQUIRED",
            message="expected_arrival is required before a procurement line can be marked QUOTED",
            status_code=422,
        )
    if final_status == "ORDERED" and final_linked_order_id is None:
        raise AppError(
            code="PROCUREMENT_LINKED_ORDER_REQUIRED",
            message="linked_purchase_order_line_id is required before a procurement line can be marked ORDERED",
            status_code=422,
        )
    if final_status == "ORDERED":
        order = get_order(conn, final_linked_order_id)
        if int(order["item_id"]) != int(current["item_id"]):
            raise AppError(
                code="PROCUREMENT_ORDER_ITEM_MISMATCH",
                message="Linked order item_id must match procurement line item_id",
                status_code=409,
            )
        source_project_id = int(current["source_project_id"]) if current["source_project_id"] is not None else None
        linked_project_id = _ordered_procurement_project_for_order(conn, final_linked_order_id)
        if source_project_id is not None and linked_project_id is not None and linked_project_id != source_project_id:
            raise AppError(
                code="PROCUREMENT_ORDER_PROJECT_CONFLICT",
                message="Linked order already belongs to another project",
                status_code=409,
            )
        if source_project_id is not None and order.get("project_id") is not None and int(order["project_id"]) != source_project_id:
            raise AppError(
                code="PROCUREMENT_ORDER_PROJECT_CONFLICT",
                message="Linked order already belongs to another project",
                status_code=409,
            )

    if "linked_quotation_id" in payload:
        updates.append("linked_quotation_id = ?")
        params.append(payload.get("linked_quotation_id"))
    if final_linked_order_id != current_linked_order_id:
        updates.append("linked_order_id = ?")
        params.append(final_linked_order_id)
    if final_status != str(current["status"]):
        updates.append("status = ?")
        params.append(final_status)
    if "note" in payload:
        updates.append("note = ?")
        params.append(payload.get("note"))

    should_sync_orders = final_linked_order_id != current_linked_order_id or final_status != str(current["status"])
    impacted_order_ids = {order_id for order_id in (current_linked_order_id, final_linked_order_id) if order_id is not None}
    if updates:
        now = now_jst_iso()
        updates.append("updated_at = ?")
        params.append(now)
        conn.execute(f"UPDATE procurement_lines SET {', '.join(updates)} WHERE line_id = ?", (*params, line_id))
        conn.execute("UPDATE procurement_batches SET updated_at = ? WHERE batch_id = ?", (now, int(current["batch_id"])))
        if should_sync_orders:
            for impacted_order_id in sorted(impacted_order_ids):
                _sync_order_project_assignment_from_procurement(conn, impacted_order_id)

    updated_row = _procurement_line_row(conn, line_id)
    return {
        "batch": dict(_procurement_batch_row(conn, int(updated_row["batch_id"]))),
        "line": next(
            row
            for row in _procurement_line_detail_rows(conn, int(updated_row["batch_id"]))
            if int(row["line_id"]) == line_id
        ),
    }


def delete_procurement_line(conn: sqlite3.Connection, line_id: int) -> dict[str, Any]:
    current = _procurement_line_row(conn, line_id)
    if str(current["status"]) != "DRAFT":
        raise AppError(
            code="PROCUREMENT_LINE_NOT_DRAFT",
            message="Only DRAFT procurement lines can be deleted",
            status_code=409,
        )
    batch_id = int(current["batch_id"])
    conn.execute("DELETE FROM procurement_lines WHERE line_id = ?", (line_id,))
    conn.execute("UPDATE procurement_batches SET updated_at = ? WHERE batch_id = ?", (now_jst_iso(), batch_id))
    return {"deleted": True, "line_id": line_id, "batch_id": batch_id}


def export_procurement_batch_csv(conn: sqlite3.Connection, batch_id: int) -> tuple[str, bytes]:
    batch = get_procurement_batch(conn, batch_id)
    fieldnames = [
        "batch_title",
        "item_id",
        "item_number",
        "manufacturer",
        "description",
        "category",
        "supplier_name",
        "finalized_quantity",
        "expected_arrival",
        "source_type",
        "source_project_name",
        "note",
    ]
    rows = [
        {
            "batch_title": batch["title"],
            "item_id": line["item_id"],
            "item_number": line["item_number"],
            "manufacturer": line["manufacturer_name"],
            "description": line.get("description") or "",
            "category": line.get("category") or "",
            "supplier_name": line.get("supplier_name") or "",
            "finalized_quantity": line["finalized_quantity"],
            "expected_arrival": line.get("expected_arrival") or "",
            "source_type": line["source_type"],
            "source_project_name": line.get("source_project_name") or "",
            "note": line.get("note") or "",
        }
        for line in batch["lines"]
    ]
    return f"procurement_batch_{batch_id}.csv", _csv_bytes(fieldnames, rows)


def add_shortages_to_procurement(
    conn: sqlite3.Connection,
    *,
    batch_id: int | None,
    create_batch_title: str | None,
    create_batch_note: str | None,
    confirm_project_id: int | None = None,
    confirm_target_date: str | None = None,
    lines: list[dict[str, Any]],
) -> dict[str, Any]:
    target_batch_id = batch_id
    if target_batch_id is None:
        created = create_procurement_batch(
            conn,
            {
                "title": (create_batch_title or "").strip() or f"Procurement Batch {today_jst()}",
                "note": create_batch_note,
                "status": "DRAFT",
            },
        )
        target_batch_id = int(created["batch_id"])
    batch = add_procurement_lines(conn, batch_id=target_batch_id, lines=lines)
    if confirm_project_id is not None:
        confirm_project_for_procurement(
            conn,
            int(confirm_project_id),
            target_date=confirm_target_date,
        )
    return batch


def get_shortage_inbox(conn: sqlite3.Connection) -> dict[str, Any]:
    snapshot = _build_project_planning_snapshot(conn)
    rows: list[dict[str, Any]] = []
    for summary in snapshot["project_summaries"]:
        pid = int(summary["project_id"])
        for row in snapshot["project_rows"].get(pid, []):
            shortage = int(row["shortage_at_start"])
            if shortage <= 0:
                continue
            rows.append(
                {
                    "item_id": int(row["item_id"]),
                    "item_number": row["item_number"],
                    "manufacturer_name": row["manufacturer_name"],
                    "requested_quantity": shortage,
                    "source_type": "PROJECT",
                    "source_project_id": pid,
                    "source_project_name": summary["name"],
                    "suggested_supplier": None,
                    "expected_arrival": summary["planned_start"],
                    "note": f"Shortage at project start {summary['planned_start']}",
                }
            )
    rows.sort(key=lambda row: (-int(row["requested_quantity"]), str(row["item_number"] or "")))
    return {"generated_at": now_jst_iso(), "rows": rows}


def confirm_procurement_links(conn: sqlite3.Connection, *, links: list[dict[str, Any]]) -> dict[str, Any]:
    confirmed_count = 0
    for link in links:
        if not link.get("confirmed", True):
            continue
        update_procurement_line(
            conn,
            int(link["line_id"]),
            {"linked_purchase_order_line_id": int(link["purchase_order_line_id"]), "status": "ORDERED"},
        )
        confirmed_count += 1
    return {"confirmed_count": confirmed_count}


def preview_bom_rows(
    conn: sqlite3.Connection,
    rows: list[dict[str, Any]],
    *,
    target_date: str | None = None,
) -> dict[str, Any]:
    normalized_target_date = _normalize_future_target_date(
        target_date,
        field_name="target_date",
    )
    supplier_rows = _load_supplier_preview_catalog_rows(conn)
    preview_candidate_cache: dict[int | None, list[dict[str, Any]]] = {}
    preview_rows: list[dict[str, Any]] = []
    summary = {
        "total_rows": 0,
        "exact": 0,
        "high_confidence": 0,
        "needs_review": 0,
        "unresolved": 0,
    }

    for row_number, row in enumerate(rows, start=1):
        supplier_name = str(row.get("supplier") or "").strip()
        item_number = str(row.get("item_number") or "").strip()
        required_quantity = int(row.get("required_quantity") or 0)
        if required_quantity < 0:
            raise AppError(
                code="INVALID_QUANTITY",
                message="required_quantity must be >= 0",
                status_code=422,
            )

        supplier_resolution = _resolve_bom_preview_supplier(supplier_rows, supplier_name)
        preview_supplier_id = supplier_resolution["preview_supplier_id"]
        if preview_supplier_id not in preview_candidate_cache:
            preview_candidate_cache[preview_supplier_id] = _load_order_import_preview_candidates(
                conn,
                preview_supplier_id,
            )
        item_resolution = _resolve_bom_preview_item(
            item_number,
            preview_candidate_cache[preview_supplier_id],
        )
        status = _merge_preview_statuses(
            str(supplier_resolution["status"]),
            str(item_resolution["status"]),
        )

        canonical_item_number: str | None = None
        units_per_order: int | None = None
        canonical_required_quantity: int | None = None
        available_stock: int | None = None
        shortage: int | None = None
        suggested_match = item_resolution["suggested_match"]
        if suggested_match is not None and str(item_resolution["status"]) in {"exact", "high_confidence"}:
            units_per_order = int(suggested_match.get("units_per_order") or 1)
            canonical_item_number = str(
                suggested_match.get("canonical_item_number") or suggested_match["value_text"]
            )
            canonical_required_quantity = required_quantity * units_per_order
            available_stock = _get_projected_available_inventory(
                conn,
                int(suggested_match["entity_id"]),
                target_date=normalized_target_date,
            )
            shortage = max(0, canonical_required_quantity - available_stock)

        message_parts: list[str] = []
        if status == "exact":
            if str((suggested_match or {}).get("match_source") or "") == "supplier_item_alias":
                message_parts.append("Matched supplier alias to a canonical item.")
            else:
                message_parts.append("Matched registered supplier and item.")
        elif status == "high_confidence":
            message_parts.append("High-confidence BOM row match found.")
        else:
            for resolution in (supplier_resolution, item_resolution):
                resolution_status = str(resolution["status"])
                if resolution_status in {"needs_review", "unresolved"}:
                    message_parts.append(str(resolution["message"]))
            if not message_parts:
                for resolution in (supplier_resolution, item_resolution):
                    resolution_status = str(resolution["status"])
                    if resolution_status == "high_confidence":
                        message_parts.append(str(resolution["message"]))
        if not message_parts:
            message_parts.append("Review this row before continuing.")

        preview_row = {
            "row": row_number,
            "supplier": supplier_name,
            "item_number": item_number,
            "required_quantity": required_quantity,
            "supplier_status": supplier_resolution["status"],
            "item_status": item_resolution["status"],
            "status": status,
            "message": " ".join(dict.fromkeys(message_parts)),
            "requires_supplier_selection": supplier_resolution["requires_selection"],
            "requires_item_selection": item_resolution["requires_selection"],
            "suggested_supplier": supplier_resolution["suggested_match"],
            "supplier_candidates": supplier_resolution["candidates"],
            "suggested_match": suggested_match,
            "candidates": item_resolution["candidates"],
            "canonical_item_number": canonical_item_number,
            "units_per_order": units_per_order,
            "canonical_required_quantity": canonical_required_quantity,
            "available_stock": available_stock,
            "shortage": shortage,
        }
        preview_rows.append(preview_row)
        summary["total_rows"] += 1
        summary[status] += 1

    return {
        "target_date": normalized_target_date,
        "summary": summary,
        "can_auto_accept": (
            summary["total_rows"] > 0
            and summary["needs_review"] == 0
            and summary["unresolved"] == 0
        ),
        "rows": preview_rows,
    }


def analyze_bom_rows(
    conn: sqlite3.Connection,
    rows: list[dict[str, Any]],
    *,
    target_date: str | None = None,
) -> dict[str, Any]:
    normalized_target_date = _normalize_future_target_date(
        target_date,
        field_name="target_date",
    )
    results: list[dict[str, Any]] = []
    for row in rows:
        supplier_name = require_non_empty(row["supplier"], "supplier")
        supplier_context = _resolve_order_import_supplier_context(
            conn,
            supplier_name=supplier_name,
        )
        item_number = require_non_empty(row["item_number"], "item_number")
        required_quantity = int(row["required_quantity"])
        if required_quantity < 0:
            raise AppError(
                code="INVALID_QUANTITY",
                message="required_quantity must be >= 0",
                status_code=422,
            )
        item_id, units = _resolve_order_item(conn, supplier_context["supplier_id"], item_number)
        if item_id is None:
            results.append(
                {
                    "supplier": supplier_name,
                    "item_number": item_number,
                    "required_quantity": required_quantity,
                    "status": "missing_item",
                }
            )
            continue
        canonical_required = required_quantity * units
        available = _get_projected_available_inventory(
            conn,
            item_id,
            target_date=normalized_target_date,
        )
        shortage = max(0, canonical_required - available)
        item = get_item(conn, item_id)
        results.append(
            {
                "supplier": supplier_name,
                "ordered_item_number": item_number,
                "item_id": item_id,
                "canonical_item_number": item["item_number"],
                "required_quantity": canonical_required,
                "available_stock": available,
                "shortage": shortage,
                "status": "ok",
            }
        )
    return {"rows": results, "target_date": normalized_target_date}


def reserve_bom_rows(
    conn: sqlite3.Connection,
    rows: list[dict[str, Any]],
    *,
    purpose: str | None = "BOM reserve",
    deadline: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    analysis = analyze_bom_rows(conn, rows)
    created: list[dict[str, Any]] = []
    for row in analysis["rows"]:
        if row.get("status") != "ok":
            continue
        reserve_qty = min(int(row["required_quantity"]), int(row["available_stock"]))
        if reserve_qty <= 0:
            continue
        created.append(
            create_reservation(
                conn,
                {
                    "item_id": row["item_id"],
                    "quantity": reserve_qty,
                    "purpose": purpose,
                    "deadline": deadline,
                    "note": note or "BOM reservation",
                },
            )
        )
    return {"analysis": analysis["rows"], "created_reservations": created}


PURCHASE_CANDIDATE_STATUSES = {"OPEN", "ORDERING", "ORDERED", "CANCELLED"}
PURCHASE_CANDIDATE_SOURCE_TYPES = {"BOM", "PROJECT"}


def _validate_purchase_candidate_status(value: str) -> str:
    normalized = require_non_empty(value, "status").upper()
    if normalized not in PURCHASE_CANDIDATE_STATUSES:
        raise AppError(
            code="INVALID_PURCHASE_CANDIDATE_STATUS",
            message=f"status must be one of: {', '.join(sorted(PURCHASE_CANDIDATE_STATUSES))}",
            status_code=422,
        )
    return normalized


def _validate_purchase_candidate_source_type(value: str) -> str:
    normalized = require_non_empty(value, "source_type").upper()
    if normalized not in PURCHASE_CANDIDATE_SOURCE_TYPES:
        raise AppError(
            code="INVALID_PURCHASE_CANDIDATE_SOURCE_TYPE",
            message=f"source_type must be one of: {', '.join(sorted(PURCHASE_CANDIDATE_SOURCE_TYPES))}",
            status_code=422,
        )
    return normalized


def _purchase_candidate_row(conn: sqlite3.Connection, candidate_id: int) -> sqlite3.Row:
    row = conn.execute(
        """
        SELECT
            pc.*,
            p.name AS project_name,
            im.item_number AS item_number,
            m.name AS manufacturer_name
        FROM purchase_candidates pc
        LEFT JOIN projects p ON p.project_id = pc.project_id
        LEFT JOIN items_master im ON im.item_id = pc.item_id
        LEFT JOIN manufacturers m ON m.manufacturer_id = im.manufacturer_id
        WHERE pc.candidate_id = ?
        """,
        (candidate_id,),
    ).fetchone()
    if row is None:
        raise AppError(
            code="PURCHASE_CANDIDATE_NOT_FOUND",
            message=f"Purchase candidate with id {candidate_id} not found",
            status_code=404,
        )
    return row


def get_purchase_candidate(conn: sqlite3.Connection, candidate_id: int) -> dict[str, Any]:
    return dict(_purchase_candidate_row(conn, candidate_id))


def list_purchase_candidates(
    conn: sqlite3.Connection,
    *,
    status: str | None = None,
    source_type: str | None = None,
    project_id: int | None = None,
    target_date: str | None = None,
    page: int = 1,
    per_page: int = 50,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if status:
        clauses.append("pc.status = ?")
        params.append(_validate_purchase_candidate_status(status))
    if source_type:
        clauses.append("pc.source_type = ?")
        params.append(_validate_purchase_candidate_source_type(source_type))
    if project_id is not None:
        clauses.append("pc.project_id = ?")
        params.append(int(project_id))
    if target_date:
        clauses.append("pc.target_date = ?")
        params.append(normalize_optional_date(target_date, "target_date"))
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"""
        SELECT
            pc.*,
            p.name AS project_name,
            im.item_number AS item_number,
            m.name AS manufacturer_name
        FROM purchase_candidates pc
        LEFT JOIN projects p ON p.project_id = pc.project_id
        LEFT JOIN items_master im ON im.item_id = pc.item_id
        LEFT JOIN manufacturers m ON m.manufacturer_id = im.manufacturer_id
        {where}
        ORDER BY
            CASE pc.status
                WHEN 'OPEN' THEN 0
                WHEN 'ORDERING' THEN 1
                WHEN 'ORDERED' THEN 2
                ELSE 3
            END,
            COALESCE(pc.target_date, '9999-12-31') ASC,
            pc.updated_at DESC,
            pc.candidate_id DESC
    """
    return _paginate(conn, sql, tuple(params), page, per_page)


def _insert_purchase_candidate(
    conn: sqlite3.Connection,
    *,
    source_type: str,
    project_id: int | None,
    item_id: int | None,
    supplier_name: str | None,
    ordered_item_number: str | None,
    canonical_item_number: str | None,
    required_quantity: int,
    available_stock: int,
    shortage_quantity: int,
    target_date: str | None,
    note: str | None = None,
) -> dict[str, Any]:
    normalized_source_type = _validate_purchase_candidate_source_type(source_type)
    normalized_target_date = _normalize_future_target_date(target_date, field_name="target_date")
    if required_quantity < 0 or available_stock < 0 or shortage_quantity < 0:
        raise AppError(
            code="INVALID_QUANTITY",
            message="required_quantity, available_stock, and shortage_quantity must be >= 0",
            status_code=422,
        )
    now = now_jst_iso()
    cur = conn.execute(
        """
        INSERT INTO purchase_candidates (
            source_type,
            project_id,
            item_id,
            supplier_name,
            ordered_item_number,
            canonical_item_number,
            required_quantity,
            available_stock,
            shortage_quantity,
            target_date,
            status,
            note,
            created_at,
            updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN', ?, ?, ?)
        """,
        (
            normalized_source_type,
            project_id,
            item_id,
            supplier_name,
            ordered_item_number,
            canonical_item_number,
            int(required_quantity),
            int(available_stock),
            int(shortage_quantity),
            normalized_target_date,
            note,
            now,
            now,
        ),
    )
    return get_purchase_candidate(conn, int(cur.lastrowid))


def create_purchase_candidates_from_bom(
    conn: sqlite3.Connection,
    *,
    rows: list[dict[str, Any]],
    target_date: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    analysis = analyze_bom_rows(conn, rows, target_date=target_date)
    created: list[dict[str, Any]] = []
    for row in analysis["rows"]:
        status = str(row.get("status") or "")
        if status == "ok":
            shortage = int(row.get("shortage") or 0)
            if shortage <= 0:
                continue
            created.append(
                _insert_purchase_candidate(
                    conn,
                    source_type="BOM",
                    project_id=None,
                    item_id=int(row["item_id"]),
                    supplier_name=str(row.get("supplier") or ""),
                    ordered_item_number=str(row.get("ordered_item_number") or ""),
                    canonical_item_number=str(row.get("canonical_item_number") or ""),
                    required_quantity=int(row.get("required_quantity") or 0),
                    available_stock=int(row.get("available_stock") or 0),
                    shortage_quantity=shortage,
                    target_date=analysis.get("target_date"),
                    note=note or "BOM shortage before purchase order",
                )
            )
            continue
        if status == "missing_item":
            required_quantity = int(row.get("required_quantity") or 0)
            if required_quantity <= 0:
                continue
            created.append(
                _insert_purchase_candidate(
                    conn,
                    source_type="BOM",
                    project_id=None,
                    item_id=None,
                    supplier_name=str(row.get("supplier") or ""),
                    ordered_item_number=str(row.get("item_number") or ""),
                    canonical_item_number=None,
                    required_quantity=required_quantity,
                    available_stock=0,
                    shortage_quantity=required_quantity,
                    target_date=analysis.get("target_date"),
                    note=note or "BOM missing item before purchase order",
                )
            )
    return {
        "target_date": analysis.get("target_date"),
        "analysis": analysis["rows"],
        "created_count": len(created),
        "created": created,
    }


def create_purchase_candidates_from_project_gap(
    conn: sqlite3.Connection,
    project_id: int,
    *,
    target_date: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    analysis = project_gap_analysis(conn, project_id, target_date=target_date)
    project = analysis["project"]
    created: list[dict[str, Any]] = []
    for row in analysis["rows"]:
        shortage = int(row.get("shortage") or 0)
        if shortage <= 0:
            continue
        created.append(
            _insert_purchase_candidate(
                conn,
                source_type="PROJECT",
                project_id=project_id,
                item_id=int(row["item_id"]),
                supplier_name=None,
                ordered_item_number=str(row.get("item_number") or ""),
                canonical_item_number=str(row.get("item_number") or ""),
                required_quantity=int(row.get("required_quantity") or 0),
                available_stock=int(row.get("available_stock") or 0),
                shortage_quantity=shortage,
                target_date=analysis.get("target_date"),
                note=note or f"Project shortage before purchase order: {project['name']}",
            )
        )
    return {
        "project": project,
        "target_date": analysis.get("target_date"),
        "analysis": analysis["rows"],
        "created_count": len(created),
        "created": created,
    }


def update_purchase_candidate(
    conn: sqlite3.Connection, candidate_id: int, payload: dict[str, Any]
) -> dict[str, Any]:
    _purchase_candidate_row(conn, candidate_id)
    updates: list[str] = []
    params: list[Any] = []
    if "status" in payload and payload.get("status") is not None:
        updates.append("status = ?")
        params.append(_validate_purchase_candidate_status(str(payload["status"])))
    if "note" in payload:
        updates.append("note = ?")
        params.append(payload.get("note"))
    if updates:
        updates.append("updated_at = ?")
        params.append(now_jst_iso())
        conn.execute(
            f"UPDATE purchase_candidates SET {', '.join(updates)} WHERE candidate_id = ?",
            (*params, candidate_id),
        )
    return get_purchase_candidate(conn, candidate_id)


def list_transactions(
    conn: sqlite3.Connection,
    *,
    item_id: int | None = None,
    batch_id: str | None = None,
    page: int = 1,
    per_page: int = 50,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if item_id is not None:
        clauses.append("t.item_id = ?")
        params.append(item_id)
    if batch_id is not None:
        clauses.append("t.batch_id = ?")
        params.append(batch_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"""
        SELECT
            t.*,
            im.item_number
        FROM transaction_log t
        JOIN items_master im ON im.item_id = t.item_id
        {where}
        ORDER BY t.timestamp DESC, t.log_id DESC
    """
    return _paginate(conn, sql, tuple(params), page, per_page)


def get_transaction(conn: sqlite3.Connection, log_id: int) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT
            t.*,
            im.item_number
        FROM transaction_log t
        JOIN items_master im ON im.item_id = t.item_id
        WHERE t.log_id = ?
        """,
        (log_id,),
    ).fetchone()
    if row is None:
        raise AppError(
            code="TRANSACTION_NOT_FOUND",
            message=f"Transaction {log_id} not found",
            status_code=404,
        )
    return dict(row)


def _find_reservation_transaction_context(batch_id: Any) -> tuple[str | None, int | None, int | None]:
    normalized = str(batch_id or "").strip()
    match = _RESERVATION_RELEASE_BATCH_RE.match(normalized)
    if match:
        return "release", int(match.group(1)), int(match.group(2))
    match = _RESERVATION_CONSUME_BATCH_RE.match(normalized)
    if match:
        return "consume", int(match.group(1)), int(match.group(2))
    match = _RESERVATION_CREATE_BATCH_RE.match(normalized)
    if match:
        return "create", int(match.group(1)), None
    return None, None, None


def _get_reservation_undo_rows(
    conn: sqlite3.Connection,
    *,
    reservation_id: int,
    target_status: str,
    log_id: int,
) -> list[dict[str, Any]]:
    marker = f"%[[tx:{int(log_id)}]]"
    rows = conn.execute(
        """
        SELECT allocation_id, location, quantity, note
        FROM reservation_allocations
        WHERE reservation_id = ? AND status = ? AND note LIKE ?
        ORDER BY allocation_id
        """,
        (reservation_id, target_status, marker),
    ).fetchall()
    return [dict(row) for row in rows]


def _restore_reservation_allocation_rows(
    conn: sqlite3.Connection,
    *,
    reservation_id: int,
    rows: list[dict[str, Any]],
    log_id: int,
) -> None:
    for row in rows:
        active_row = conn.execute(
            """
            SELECT allocation_id, quantity
            FROM reservation_allocations
            WHERE reservation_id = ? AND status = 'ACTIVE' AND location = ?
            ORDER BY allocation_id
            LIMIT 1
            """,
            (reservation_id, str(row["location"])),
        ).fetchone()
        if active_row is not None:
            conn.execute(
                "UPDATE reservation_allocations SET quantity = ? WHERE allocation_id = ?",
                (int(active_row["quantity"]) + int(row["quantity"]), int(active_row["allocation_id"])),
            )
            conn.execute("DELETE FROM reservation_allocations WHERE allocation_id = ?", (int(row["allocation_id"]),))
            continue
        conn.execute(
            """
            UPDATE reservation_allocations
            SET status = 'ACTIVE', released_at = NULL, note = ?
            WHERE allocation_id = ?
            """,
            (_remove_reservation_tx_marker(row.get("note"), log_id), int(row["allocation_id"])),
        )


def _undo_reservation_release(
    conn: sqlite3.Connection,
    *,
    reservation_id: int,
    log_id: int,
    item_id: int,
    qty: int,
    undo_note: str,
) -> dict[str, Any]:
    _lock_reservation_item_state(conn, reservation_id, item_id)
    reservation = get_reservation(conn, reservation_id)
    if reservation["status"] == "CONSUMED":
        raise AppError(
            code="UNDO_NOT_POSSIBLE",
            message="Reservation was consumed after this release and cannot be safely undone",
            status_code=409,
        )
    released_rows = _get_reservation_undo_rows(
        conn,
        reservation_id=reservation_id,
        target_status="RELEASED",
        log_id=log_id,
    )
    released_qty = sum(int(row["quantity"]) for row in released_rows)
    if released_qty != qty:
        raise AppError(
            code="UNDO_NOT_POSSIBLE",
            message="Reservation release state no longer matches the transaction being undone",
            status_code=409,
        )
    _restore_reservation_allocation_rows(conn, reservation_id=reservation_id, rows=released_rows, log_id=log_id)
    conn.execute(
        """
        UPDATE reservations
        SET quantity = ?, status = 'ACTIVE', released_at = NULL
        WHERE reservation_id = ?
        """,
        (int(reservation["quantity"]) + qty, reservation_id),
    )
    return _log_transaction(
        conn,
        operation_type="RESERVE",
        item_id=item_id,
        quantity=qty,
        from_location=None,
        to_location=None,
        note=undo_note,
        batch_id=f"undo-{log_id}",
        undo_of_log_id=log_id,
    )


def _undo_reservation_consume(
    conn: sqlite3.Connection,
    *,
    reservation_id: int,
    log_id: int,
    item_id: int,
    qty: int,
    undo_note: str,
) -> dict[str, Any]:
    _lock_reservation_item_state(conn, reservation_id, item_id)
    reservation = get_reservation(conn, reservation_id)
    consumed_rows = _get_reservation_undo_rows(
        conn,
        reservation_id=reservation_id,
        target_status="CONSUMED",
        log_id=log_id,
    )
    consumed_qty = sum(int(row["quantity"]) for row in consumed_rows)
    if consumed_qty != qty:
        raise AppError(
            code="UNDO_NOT_POSSIBLE",
            message="Reservation consume state no longer matches the transaction being undone",
            status_code=409,
        )
    for row in consumed_rows:
        _apply_inventory_delta(conn, item_id, str(row["location"]), int(row["quantity"]))
    _restore_reservation_allocation_rows(conn, reservation_id=reservation_id, rows=consumed_rows, log_id=log_id)
    conn.execute(
        """
        UPDATE reservations
        SET quantity = ?, status = 'ACTIVE', released_at = NULL
        WHERE reservation_id = ?
        """,
        (int(reservation["quantity"]) + qty, reservation_id),
    )
    return _log_transaction(
        conn,
        operation_type="CONSUME",
        item_id=item_id,
        quantity=qty,
        from_location=None,
        to_location=None,
        note=undo_note,
        batch_id=f"undo-{log_id}",
        undo_of_log_id=log_id,
    )


def undo_transaction(conn: sqlite3.Connection, log_id: int, note: str | None = None) -> dict[str, Any]:
    _lock_transaction_state(conn, log_id)
    original = get_transaction(conn, log_id)
    if int(original["is_undone"]) == 1:
        raise AppError(
            code="ALREADY_UNDONE",
            message=f"Transaction {log_id} has already been undone",
            status_code=409,
        )
    op_type = original["operation_type"]
    item_id = int(original["item_id"])
    qty = int(original["quantity"])
    applied_qty = qty
    undo_note = note or f"undo log_id={log_id}"
    reservation_action, reservation_id, reservation_log_id = _find_reservation_transaction_context(original.get("batch_id"))

    if op_type == "MOVE":
        _lock_inventory_item_state(conn, item_id)
        available = _get_inventory_quantity(conn, item_id, original["to_location"])
        if available <= 0:
            raise AppError(
                code="UNDO_NOT_POSSIBLE",
                message="No quantity available at destination for MOVE undo",
                status_code=409,
            )
        applied_qty = min(qty, available)
        _apply_inventory_delta(conn, item_id, original["to_location"], -applied_qty)
        _apply_inventory_delta(conn, item_id, original["from_location"], applied_qty)
        undo_log = _log_transaction(
            conn,
            operation_type="MOVE",
            item_id=item_id,
            quantity=applied_qty,
            from_location=original["to_location"],
            to_location=original["from_location"],
            note=undo_note,
            batch_id=f"undo-{log_id}",
            undo_of_log_id=log_id,
        )
    elif op_type == "ARRIVAL":
        _lock_inventory_item_state(conn, item_id)
        available = _get_inventory_quantity(conn, item_id, "STOCK")
        if available <= 0:
            raise AppError(
                code="UNDO_NOT_POSSIBLE",
                message="No quantity available in STOCK for ARRIVAL undo",
                status_code=409,
            )
        applied_qty = min(qty, available)
        _apply_inventory_delta(conn, item_id, "STOCK", -applied_qty)
        undo_log = _log_transaction(
            conn,
            operation_type="CONSUME",
            item_id=item_id,
            quantity=applied_qty,
            from_location="STOCK",
            to_location=None,
            note=undo_note,
            batch_id=f"undo-{log_id}",
            undo_of_log_id=log_id,
        )
    elif op_type == "CONSUME" and reservation_action == "consume" and reservation_id is not None and reservation_log_id is not None:
        undo_log = _undo_reservation_consume(
            conn,
            reservation_id=reservation_id,
            log_id=reservation_log_id,
            item_id=item_id,
            qty=qty,
            undo_note=undo_note,
        )
    elif op_type == "CONSUME":
        _lock_inventory_item_state(conn, item_id)
        target = original["from_location"] or "STOCK"
        _apply_inventory_delta(conn, item_id, target, qty)
        undo_log = _log_transaction(
            conn,
            operation_type="ADJUST",
            item_id=item_id,
            quantity=qty,
            from_location=None,
            to_location=target,
            note=undo_note,
            batch_id=f"undo-{log_id}",
            undo_of_log_id=log_id,
        )
    elif op_type == "ADJUST":
        _lock_inventory_item_state(conn, item_id)
        if original["to_location"] and not original["from_location"]:
            available = _get_inventory_quantity(conn, item_id, original["to_location"])
            if available <= 0:
                raise AppError(
                    code="UNDO_NOT_POSSIBLE",
                    message="No quantity available for ADJUST undo",
                    status_code=409,
                )
            applied_qty = min(qty, available)
            _apply_inventory_delta(conn, item_id, original["to_location"], -applied_qty)
            undo_log = _log_transaction(
                conn,
                operation_type="ADJUST",
                item_id=item_id,
                quantity=applied_qty,
                from_location=original["to_location"],
                to_location=None,
                note=undo_note,
                batch_id=f"undo-{log_id}",
                undo_of_log_id=log_id,
            )
        elif original["from_location"] and not original["to_location"]:
            _apply_inventory_delta(conn, item_id, original["from_location"], qty)
            undo_log = _log_transaction(
                conn,
                operation_type="ADJUST",
                item_id=item_id,
                quantity=qty,
                from_location=None,
                to_location=original["from_location"],
                note=undo_note,
                batch_id=f"undo-{log_id}",
                undo_of_log_id=log_id,
            )
        else:
            available = _get_inventory_quantity(conn, item_id, original["to_location"])
            if available <= 0:
                raise AppError(
                    code="UNDO_NOT_POSSIBLE",
                    message="No quantity available for ADJUST undo",
                    status_code=409,
                )
            applied_qty = min(qty, available)
            _apply_inventory_delta(conn, item_id, original["to_location"], -applied_qty)
            _apply_inventory_delta(conn, item_id, original["from_location"], applied_qty)
            undo_log = _log_transaction(
                conn,
                operation_type="MOVE",
                item_id=item_id,
                quantity=applied_qty,
                from_location=original["to_location"],
                to_location=original["from_location"],
                note=undo_note,
                batch_id=f"undo-{log_id}",
                undo_of_log_id=log_id,
            )
    elif op_type == "RESERVE" and reservation_action == "release" and reservation_id is not None and reservation_log_id is not None:
        undo_log = _undo_reservation_release(
            conn,
            reservation_id=reservation_id,
            log_id=reservation_log_id,
            item_id=item_id,
            qty=qty,
            undo_note=undo_note,
        )
    elif op_type == "RESERVE":
        if reservation_action != "create" or reservation_id is None:
            raise AppError(
                code="UNDO_NOT_POSSIBLE",
                message="Unable to resolve reservation for RESERVE undo",
                status_code=409,
            )
        _lock_reservation_item_state(conn, reservation_id, item_id)
        reservation = get_reservation(conn, reservation_id)
        if reservation["status"] != "ACTIVE":
            raise AppError(
                code="UNDO_NOT_POSSIBLE",
                message="Reservation is no longer ACTIVE for RESERVE undo",
                status_code=409,
            )
        conn.execute(
            """
            UPDATE reservation_allocations
            SET status = 'RELEASED', released_at = ?, note = ?
            WHERE reservation_id = ? AND status = 'ACTIVE'
            """,
            (now_jst_iso(), undo_note, reservation_id),
        )
        conn.execute(
            """
            UPDATE reservations
            SET status = 'RELEASED', released_at = ?
            WHERE reservation_id = ?
            """,
            (now_jst_iso(), reservation_id),
        )
        undo_log = _log_transaction(
            conn,
            operation_type="RESERVE",
            item_id=item_id,
            quantity=qty,
            from_location=None,
            to_location=None,
            note=undo_note,
            batch_id=f"undo-{log_id}",
            undo_of_log_id=log_id,
        )
    else:
        raise AppError(
            code="UNDO_NOT_SUPPORTED",
            message=f"Undo is not supported for operation_type={op_type}",
            status_code=422,
        )

    conn.execute(
        "UPDATE transaction_log SET is_undone = 1 WHERE log_id = ?",
        (log_id,),
    )
    return {"original_log_id": log_id, "undo_log": undo_log, "applied_quantity": applied_qty}


def get_operational_integrity_summary(conn: sqlite3.Connection) -> dict[str, Any]:
    checked_at = now_jst_iso()
    active_reservation_mismatch_row = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM (
            SELECT
                r.reservation_id
            FROM reservations r
            LEFT JOIN (
                SELECT reservation_id, COALESCE(SUM(quantity), 0) AS active_quantity
                FROM reservation_allocations
                WHERE status = 'ACTIVE'
                GROUP BY reservation_id
            ) active ON active.reservation_id = r.reservation_id
            WHERE r.status = 'ACTIVE'
              AND COALESCE(active.active_quantity, 0) <> r.quantity
        ) mismatches
        """
    ).fetchone()
    terminal_reservation_active_alloc_row = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM (
            SELECT
                r.reservation_id
            FROM reservations r
            JOIN reservation_allocations ra ON ra.reservation_id = r.reservation_id
            WHERE r.status IN ('RELEASED', 'CONSUMED')
              AND ra.status = 'ACTIVE'
            GROUP BY r.reservation_id
        ) leaked
        """
    ).fetchone()
    allocation_item_mismatch_row = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM reservation_allocations ra
        JOIN reservations r ON r.reservation_id = ra.reservation_id
        WHERE ra.item_id <> r.item_id
        """
    ).fetchone()
    duplicate_undo_row = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM (
            SELECT undo_of_log_id
            FROM transaction_log
            WHERE undo_of_log_id IS NOT NULL
            GROUP BY undo_of_log_id
            HAVING COUNT(*) > 1
        ) duplicates
        """
    ).fetchone()
    marked_undone_without_compensation_row = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM transaction_log original
        WHERE original.is_undone = 1
          AND NOT EXISTS (
              SELECT 1
              FROM transaction_log undo_log
              WHERE undo_log.undo_of_log_id = original.log_id
          )
        """
    ).fetchone()
    pending_undo_age_row = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM transaction_log original
        WHERE original.is_undone = 0
          AND EXISTS (
              SELECT 1
              FROM transaction_log undo_log
              WHERE undo_log.undo_of_log_id = original.log_id
          )
        """
    ).fetchone()
    checks = {
        "active_reservation_quantity_mismatches": int(active_reservation_mismatch_row["count"] or 0),
        "terminal_reservations_with_active_allocations": int(terminal_reservation_active_alloc_row["count"] or 0),
        "reservation_allocation_item_mismatches": int(allocation_item_mismatch_row["count"] or 0),
        "duplicate_undo_logs": int(duplicate_undo_row["count"] or 0),
        "marked_undone_without_compensating_log": int(marked_undone_without_compensation_row["count"] or 0),
        "compensating_log_without_marked_original": int(pending_undo_age_row["count"] or 0),
    }
    ok = all(count == 0 for count in checks.values())
    return {
        "ok": ok,
        "checked_at": checked_at,
        "checks": checks,
    }


def dashboard_summary(conn: sqlite3.Connection, low_stock_threshold: int = 5) -> dict[str, Any]:
    today = today_jst()
    next_week = (datetime.fromisoformat(today) + timedelta(days=7)).date().isoformat()
    overdue_orders = _rows_to_dict(
        conn.execute(
            """
            SELECT
                o.order_id,
                o.expected_arrival,
                o.order_amount,
                im.item_number,
                s.name AS supplier_name
            FROM orders o
            JOIN items_master im ON im.item_id = o.item_id
            JOIN purchase_orders po ON po.purchase_order_id = o.purchase_order_id
            JOIN suppliers s ON s.supplier_id = po.supplier_id
            LEFT JOIN quotations q ON q.quotation_id = o.quotation_id
            WHERE o.status = 'Ordered'
              AND o.expected_arrival IS NOT NULL
              AND o.expected_arrival < ?
            ORDER BY o.expected_arrival ASC
            LIMIT 50
            """,
            (today,),
        ).fetchall()
    )
    expiring_reservations = _rows_to_dict(
        conn.execute(
            """
            SELECT
                r.reservation_id,
                r.deadline,
                r.quantity,
                im.item_number
            FROM reservations r
            JOIN items_master im ON im.item_id = r.item_id
            WHERE r.status = 'ACTIVE'
              AND r.deadline IS NOT NULL
              AND r.deadline <= ?
            ORDER BY r.deadline ASC
            LIMIT 50
            """,
            (next_week,),
        ).fetchall()
    )
    low_stock = _rows_to_dict(
        conn.execute(
            """
            SELECT
                il.item_id,
                im.item_number,
                il.quantity
            FROM inventory_ledger il
            JOIN items_master im ON im.item_id = il.item_id
            WHERE il.location = 'STOCK' AND il.quantity <= ?
            ORDER BY il.quantity ASC, im.item_number
            LIMIT 100
            """,
            (int(low_stock_threshold),),
        ).fetchall()
    )
    recent_activity = _rows_to_dict(
        conn.execute(
            """
            SELECT
                t.*,
                im.item_number
            FROM transaction_log t
            JOIN items_master im ON im.item_id = t.item_id
            ORDER BY t.timestamp DESC, t.log_id DESC
            LIMIT 20
            """
        ).fetchall()
    )
    pending_registration_requests = int(
        conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM registration_requests
            WHERE status = 'pending'
            """
        ).fetchone()["count"]
    )
    return {
        "overdue_orders": overdue_orders,
        "expiring_reservations": expiring_reservations,
        "low_stock_alerts": low_stock,
        "recent_activity": recent_activity,
        "pending_registration_requests": pending_registration_requests,
    }


def _build_inventory_state(conn: sqlite3.Connection) -> dict[tuple[int, str], int]:
    rows = conn.execute(
        "SELECT item_id, location, quantity FROM inventory_ledger"
    ).fetchall()
    return {(int(r["item_id"]), str(r["location"])): int(r["quantity"]) for r in rows}


def _state_apply(state: dict[tuple[int, str], int], key: tuple[int, str], delta: int) -> None:
    current = state.get(key, 0)
    updated = current + delta
    if updated <= 0:
        state.pop(key, None)
    else:
        state[key] = updated


def get_inventory_snapshot(
    conn: sqlite3.Connection,
    *,
    target_date: str | None = None,
    mode: str | None = None,
    basis: str | None = None,
) -> dict[str, Any]:
    if target_date is None:
        target_date = today_jst()
    normalized_target = normalize_optional_date(target_date, "date")
    if normalized_target is None:
        normalized_target = today_jst()
    today = today_jst()
    effective_mode = mode or ("past" if normalized_target < today else "future")
    if effective_mode not in {"past", "future"}:
        raise AppError(
            code="INVALID_SNAPSHOT_MODE",
            message="mode must be one of: past, future",
            status_code=422,
        )
    effective_basis = basis or "raw"
    if effective_basis not in {"raw", "net_available"}:
        raise AppError(
            code="INVALID_SNAPSHOT_BASIS",
            message="basis must be one of: raw, net_available",
            status_code=422,
        )
    if effective_basis == "net_available" and effective_mode == "past":
        raise AppError(
            code="SNAPSHOT_BASIS_MODE_UNSUPPORTED",
            message="basis=net_available is only supported for current/future snapshots",
            status_code=422,
        )

    state = _build_inventory_state(conn)
    if effective_mode == "past":
        rows = conn.execute(
            """
            SELECT *
            FROM transaction_log
            WHERE date(timestamp) > date(?)
            ORDER BY timestamp DESC, log_id DESC
            """,
            (normalized_target,),
        ).fetchall()
        for row in rows:
            item_id = int(row["item_id"])
            quantity = int(row["quantity"])
            op = row["operation_type"]
            from_location = row["from_location"]
            to_location = row["to_location"]
            if op == "MOVE":
                if to_location:
                    _state_apply(state, (item_id, to_location), -quantity)
                if from_location:
                    _state_apply(state, (item_id, from_location), quantity)
            elif op == "CONSUME":
                if from_location:
                    _state_apply(state, (item_id, from_location), quantity)
            elif op == "RESERVE":
                _state_apply(state, (item_id, "RESERVED"), -quantity)
                _state_apply(state, (item_id, "STOCK"), quantity)
            elif op == "ARRIVAL":
                _state_apply(state, (item_id, "STOCK"), -quantity)
            elif op == "ADJUST":
                if to_location and not from_location:
                    _state_apply(state, (item_id, to_location), -quantity)
                elif from_location and not to_location:
                    _state_apply(state, (item_id, from_location), quantity)
                elif to_location and from_location:
                    _state_apply(state, (item_id, to_location), -quantity)
                    _state_apply(state, (item_id, from_location), quantity)
    else:
        if effective_basis == "net_available":
            available_state: dict[tuple[int, str], int] = {}
            for (item_id, location), quantity in state.items():
                if quantity <= 0 or location == "RESERVED":
                    continue
                available_qty = _get_available_inventory_quantity(conn, item_id, location)
                if available_qty > 0:
                    available_state[(item_id, location)] = available_qty
            state = available_state
        pending_orders = conn.execute(
            """
            SELECT item_id, SUM(order_amount) AS qty
            FROM orders
            WHERE status <> 'Arrived'
              AND expected_arrival IS NOT NULL
              AND date(expected_arrival) <= date(?)
            GROUP BY item_id
            """,
            (normalized_target,),
        ).fetchall()
        for row in pending_orders:
            _state_apply(state, (int(row["item_id"]), "STOCK"), int(row["qty"]))
        if effective_basis == "raw":
            pending_consumption = conn.execute(
                """
                SELECT item_id, SUM(quantity) AS qty
                FROM reservations
                WHERE status = 'ACTIVE'
                  AND deadline IS NOT NULL
                  AND date(deadline) <= date(?)
                GROUP BY item_id
                """,
                (normalized_target,),
            ).fetchall()
            for row in pending_consumption:
                _state_apply(state, (int(row["item_id"]), "RESERVED"), -int(row["qty"]))

    if not state:
        return {"date": normalized_target, "mode": effective_mode, "basis": effective_basis, "rows": []}

    item_ids = sorted({item_id for item_id, _ in state.keys()})
    placeholder = ",".join("?" for _ in item_ids)
    item_map_rows = conn.execute(
        f"""
        SELECT
            im.item_id,
            im.item_number,
            m.name AS manufacturer_name,
            COALESCE(ca.canonical_category, im.category) AS category,
            im.description
        FROM items_master im
        JOIN manufacturers m ON m.manufacturer_id = im.manufacturer_id
        LEFT JOIN category_aliases ca ON ca.alias_category = im.category
        WHERE im.item_id IN ({placeholder})
        """,
        tuple(item_ids),
    ).fetchall()
    item_map = {int(row["item_id"]): dict(row) for row in item_map_rows}
    allocation_summary: dict[tuple[int, str], dict[str, Any]] = {}
    if effective_basis == "net_available":
        allocation_summary = _get_active_allocation_summary_by_item_location(conn, item_ids)

    rows: list[dict[str, Any]] = []
    for (item_id, location), quantity in sorted(state.items(), key=lambda r: (r[0][1], r[0][0])):
        if quantity <= 0:
            continue
        item = item_map.get(item_id)
        allocation = allocation_summary.get((item_id, location))
        rows.append(
            {
                "item_id": item_id,
                "item_number": item["item_number"] if item else None,
                "manufacturer_name": item["manufacturer_name"] if item else None,
                "category": item["category"] if item else None,
                "description": item["description"] if item else None,
                "location": location,
                "quantity": quantity,
                "allocated_quantity": int(allocation["allocated_quantity"]) if allocation else 0,
                "active_reservation_count": int(allocation["active_reservation_count"]) if allocation else 0,
                "allocated_project_names": list(allocation["allocated_project_names"]) if allocation else [],
            }
        )
    return {"date": normalized_target, "mode": effective_mode, "basis": effective_basis, "rows": rows}


def export_inventory_snapshot_csv(
    conn: sqlite3.Connection,
    *,
    target_date: str | None = None,
    mode: str | None = None,
    basis: str | None = None,
) -> tuple[str, bytes]:
    snapshot = get_inventory_snapshot(
        conn,
        target_date=target_date,
        mode=mode,
        basis=basis,
    )
    fieldnames = [
        "date",
        "mode",
        "basis",
        "item_id",
        "item_number",
        "manufacturer_name",
        "category",
        "description",
        "location",
        "quantity",
        "allocated_quantity",
        "active_reservation_count",
        "allocated_project_names",
    ]
    rows = [
        {
            "date": snapshot["date"],
            "mode": snapshot["mode"],
            "basis": snapshot["basis"],
            "item_id": row.get("item_id"),
            "item_number": row.get("item_number"),
            "manufacturer_name": row.get("manufacturer_name"),
            "category": row.get("category"),
            "description": row.get("description"),
            "location": row.get("location"),
            "quantity": row.get("quantity"),
            "allocated_quantity": row.get("allocated_quantity"),
            "active_reservation_count": row.get("active_reservation_count"),
            "allocated_project_names": " | ".join(row.get("allocated_project_names") or []),
        }
        for row in snapshot["rows"]
    ]
    filename = (
        f"inventory_snapshot_{snapshot['date']}_{snapshot['mode']}_{snapshot['basis']}.csv"
    )
    return filename, _csv_bytes(fieldnames, rows)


def list_manufacturers(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT manufacturer_id, name FROM manufacturers ORDER BY name"
    ).fetchall()
    return _rows_to_dict(rows)


def create_manufacturer(conn: sqlite3.Connection, name: str) -> dict[str, Any]:
    normalized = require_non_empty(name, "name")
    try:
        cur = conn.execute("INSERT INTO manufacturers (name) VALUES (?)", (normalized,))
    except sqlite3.IntegrityError as exc:
        _raise_manufacturer_already_exists(normalized, exc=exc)
    return to_dict(
        conn.execute(
            "SELECT manufacturer_id, name FROM manufacturers WHERE manufacturer_id = ?",
            (cur.lastrowid,),
        ).fetchone()
    ) or {}


def list_suppliers(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT supplier_id, name FROM suppliers ORDER BY name").fetchall()
    return _rows_to_dict(rows)


CATALOG_ENTITY_TYPES = {"item", "assembly", "supplier", "project"}


def _catalog_rank_text(query: str, *values: Any) -> tuple[int, str | None]:
    normalized_query = _normalize_search_text(query)
    query_terms = _split_search_terms(query)
    if not normalized_query or not query_terms:
        return 999, None
    best_rank = 999
    best_source: str | None = None
    matched_terms: set[str] = set()
    first_term_source: str | None = None
    for idx, value in enumerate(values):
        if value is None:
            continue
        normalized_value = _normalize_search_text(value)
        if not normalized_value:
            continue
        local_matches = [term for term in query_terms if term in normalized_value]
        if local_matches:
            matched_terms.update(local_matches)
            if first_term_source is None and query_terms[0] in local_matches:
                first_term_source = str(idx)
        if normalized_value == normalized_query:
            rank = 0
        elif normalized_value.startswith(normalized_query):
            rank = 1
        elif normalized_query in normalized_value:
            rank = 2
        elif len(local_matches) == len(query_terms):
            rank = 3
        else:
            continue
        if rank < best_rank:
            best_rank = rank
            best_source = str(idx)
    if best_rank != 999:
        return best_rank, best_source
    if len(matched_terms) == len(query_terms):
        return 4, first_term_source
    return best_rank, best_source


def catalog_search(
    conn: sqlite3.Connection,
    *,
    q: str,
    entity_types: list[str] | None = None,
    limit_per_type: int = 8,
) -> dict[str, Any]:
    raw_query = str(q or "").strip()
    normalized_query = _normalize_search_text(raw_query)
    search_terms = _split_search_terms(raw_query)
    if not normalized_query or not search_terms:
        return {"query": "", "results": []}

    requested_types = entity_types or sorted(CATALOG_ENTITY_TYPES)
    invalid_types = [entity_type for entity_type in requested_types if entity_type not in CATALOG_ENTITY_TYPES]
    if invalid_types:
        raise AppError(
            code="INVALID_CATALOG_TYPE",
            message=f"Unsupported catalog type(s): {', '.join(sorted(set(invalid_types)))}",
            status_code=422,
        )

    results: list[dict[str, Any]] = []

    if "item" in requested_types:
        item_clauses: list[str] = []
        item_params: list[Any] = []
        _append_search_term_clauses(
            item_clauses,
            item_params,
            terms=search_terms,
            expressions=[
                "im.item_number",
                "m.name",
                "COALESCE(ca.canonical_category, im.category, '')",
                "im.description",
                "a.ordered_item_number",
                "s.name",
            ],
        )
        item_rows = conn.execute(
            """
            SELECT
                im.item_id,
                im.item_number,
                m.name AS manufacturer_name,
                COALESCE(ca.canonical_category, im.category) AS category,
                im.description,
                s.name AS alias_supplier_name,
                a.ordered_item_number
            FROM items_master im
            JOIN manufacturers m ON m.manufacturer_id = im.manufacturer_id
            LEFT JOIN category_aliases ca ON ca.alias_category = im.category
            LEFT JOIN supplier_item_aliases a ON a.canonical_item_id = im.item_id
            LEFT JOIN suppliers s ON s.supplier_id = a.supplier_id
            WHERE """
            + " AND ".join(item_clauses)
            + """
            ORDER BY im.item_number, im.item_id
            """,
            tuple(item_params),
        ).fetchall()
        item_candidates: dict[int, dict[str, Any]] = {}
        for row in item_rows:
            score, source_idx = _catalog_rank_text(
                raw_query,
                row["item_number"],
                row["manufacturer_name"],
                row["category"],
                row["description"],
                row["ordered_item_number"],
                row["alias_supplier_name"],
            )
            if score == 999:
                continue
            source_map = {
                "0": "item_number",
                "1": "manufacturer_name",
                "2": "category",
                "3": "description",
                "4": "supplier_item_alias",
                "5": "alias_supplier_name",
            }
            match_source = source_map.get(source_idx or "", "item_number")
            summary_bits = _build_item_catalog_summary_bits(dict(row))
            if match_source == "supplier_item_alias" and row["ordered_item_number"]:
                summary_bits.append(
                    f"alias {row['ordered_item_number']} @ {row['alias_supplier_name'] or 'supplier'}"
                )
            candidate = {
                "entity_type": "item",
                "entity_id": int(row["item_id"]),
                "value_text": str(row["item_number"]),
                "display_label": f"{row['item_number']} ({row['manufacturer_name']}) #{int(row['item_id'])}",
                "summary": " | ".join(summary_bits),
                "match_source": match_source,
                "_score": score,
            }
            existing = item_candidates.get(int(row["item_id"]))
            if existing is None or (candidate["_score"], candidate["display_label"]) < (
                existing["_score"],
                existing["display_label"],
            ):
                item_candidates[int(row["item_id"])] = candidate
        results.extend(
            sorted(item_candidates.values(), key=lambda row: (int(row["_score"]), str(row["display_label"]).casefold()))[
                :limit_per_type
            ]
        )

    if "supplier" in requested_types:
        supplier_clauses: list[str] = []
        supplier_params: list[Any] = []
        _append_search_term_clauses(
            supplier_clauses,
            supplier_params,
            terms=search_terms,
            expressions=["s.name"],
        )
        supplier_rows = conn.execute(
            """
            SELECT
                s.supplier_id,
                s.name,
                COUNT(a.alias_id) AS alias_count
            FROM suppliers s
            LEFT JOIN supplier_item_aliases a ON a.supplier_id = s.supplier_id
            WHERE """
            + " AND ".join(supplier_clauses)
            + """
            GROUP BY s.supplier_id
            ORDER BY s.name, s.supplier_id
            """,
            tuple(supplier_params),
        ).fetchall()
        supplier_results: list[dict[str, Any]] = []
        for row in supplier_rows:
            score, _ = _catalog_rank_text(raw_query, row["name"])
            if score == 999:
                continue
            supplier_results.append(
                {
                    "entity_type": "supplier",
                    "entity_id": int(row["supplier_id"]),
                    "value_text": str(row["name"]),
                    "display_label": str(row["name"]),
                    "summary": f"{int(row['alias_count'])} alias mapping(s) | #{int(row['supplier_id'])}",
                    "match_source": "name",
                    "_score": score,
                }
            )
        results.extend(
            sorted(supplier_results, key=lambda row: (int(row["_score"]), str(row["display_label"]).casefold()))[
                :limit_per_type
            ]
        )

    if "assembly" in requested_types:
        assembly_results: list[dict[str, Any]] = []
        for row in _load_assembly_preview_catalog_rows(conn):
            score, source_idx = _catalog_rank_text(raw_query, row["name"], row["description"])
            if score == 999:
                continue
            assembly_results.append(
                {
                    "entity_type": "assembly",
                    "entity_id": int(row["assembly_id"]),
                    "value_text": str(row["name"]),
                    "display_label": f"{row['name']} #{int(row['assembly_id'])}",
                    "summary": " | ".join(
                        part
                        for part in [
                            f"{int(row.get('component_count') or 0)} component(s)",
                            str(row["description"]) if row.get("description") else "",
                        ]
                        if part
                    ),
                    "match_source": "name" if source_idx == "0" else "description",
                    "_score": score,
                }
            )
        results.extend(
            sorted(assembly_results, key=lambda row: (int(row["_score"]), str(row["display_label"]).casefold()))[
                :limit_per_type
            ]
        )

    if "project" in requested_types:
        project_clauses: list[str] = []
        project_params: list[Any] = []
        _append_search_term_clauses(
            project_clauses,
            project_params,
            terms=search_terms,
            expressions=["p.name", "p.description"],
        )
        project_rows = conn.execute(
            """
            SELECT
                p.project_id,
                p.name,
                p.description,
                p.status,
                p.planned_start,
                COUNT(pr.requirement_id) AS requirement_count
            FROM projects p
            LEFT JOIN project_requirements pr ON pr.project_id = p.project_id
            WHERE """
            + " AND ".join(project_clauses)
            + """
            GROUP BY p.project_id
            ORDER BY p.created_at DESC, p.project_id DESC
            """,
            tuple(project_params),
        ).fetchall()
        project_results: list[dict[str, Any]] = []
        for row in project_rows:
            score, source_idx = _catalog_rank_text(raw_query, row["name"], row["description"])
            if score == 999:
                continue
            match_source = "name" if source_idx == "0" else "description"
            summary_parts = [str(row["status"]), f"{int(row['requirement_count'])} requirement(s)"]
            if row["planned_start"]:
                summary_parts.append(f"start {row['planned_start']}")
            project_results.append(
                {
                    "entity_type": "project",
                    "entity_id": int(row["project_id"]),
                    "value_text": str(row["name"]),
                    "display_label": f"{row['name']} #{int(row['project_id'])}",
                    "summary": " | ".join(summary_parts),
                    "match_source": match_source,
                    "_score": score,
                }
            )
        results.extend(
            sorted(project_results, key=lambda row: (int(row["_score"]), str(row["display_label"]).casefold()))[
                :limit_per_type
            ]
        )

    for row in results:
        row.pop("_score", None)
    return {"query": raw_query, "results": results}


def create_supplier(conn: sqlite3.Connection, name: str) -> dict[str, Any]:
    normalized = require_non_empty(name, "name")
    try:
        cur = conn.execute("INSERT INTO suppliers (name) VALUES (?)", (normalized,))
    except sqlite3.IntegrityError as exc:
        exact = conn.execute("SELECT supplier_id FROM suppliers WHERE name = ?", (normalized,)).fetchone()
        if exact is None:
            casefold_rows = conn.execute(
                "SELECT supplier_id FROM suppliers WHERE lower(name) = lower(?) ORDER BY supplier_id",
                (normalized,),
            ).fetchall()
            if len(casefold_rows) > 1:
                raise AppError(
                    code="AMBIGUOUS_SUPPLIER_NAME",
                    message=(
                        f"Multiple suppliers match '{normalized}' case-insensitively. "
                        "Use supplier_id to disambiguate."
                    ),
                    status_code=409,
                ) from exc
        _raise_supplier_already_exists(normalized, exc=exc)
    return to_dict(
        conn.execute(
            "SELECT supplier_id, name FROM suppliers WHERE supplier_id = ?",
            (cur.lastrowid,),
        ).fetchone()
    ) or {}


def list_supplier_item_aliases(conn: sqlite3.Connection, supplier_id: int) -> list[dict[str, Any]]:
    _get_entity_or_404(
        conn,
        "suppliers",
        "supplier_id",
        supplier_id,
        "SUPPLIER_NOT_FOUND",
        f"Supplier with id {supplier_id} not found",
    )
    rows = conn.execute(
        """
        SELECT
            a.alias_id,
            a.supplier_id,
            s.name AS supplier_name,
            a.ordered_item_number,
            a.canonical_item_id,
            im.item_number AS canonical_item_number,
            a.units_per_order,
            a.created_at
        FROM supplier_item_aliases a
        JOIN suppliers s ON s.supplier_id = a.supplier_id
        JOIN items_master im ON im.item_id = a.canonical_item_id
        WHERE a.supplier_id = ?
        ORDER BY a.ordered_item_number
        """,
        (supplier_id,),
    ).fetchall()
    return _rows_to_dict(rows)


def upsert_supplier_item_alias(
    conn: sqlite3.Connection,
    *,
    supplier_id: int,
    ordered_item_number: str,
    canonical_item_id: int | None = None,
    canonical_item_number: str | None = None,
    units_per_order: int = 1,
) -> dict[str, Any]:
    _get_entity_or_404(
        conn,
        "suppliers",
        "supplier_id",
        supplier_id,
        "SUPPLIER_NOT_FOUND",
        f"Supplier with id {supplier_id} not found",
    )
    if canonical_item_id is None:
        if canonical_item_number is None:
            raise AppError(
                code="INVALID_ALIAS",
                message="canonical_item_id or canonical_item_number is required",
                status_code=422,
            )
        canonical_item_id = _resolve_item_by_number(conn, canonical_item_number)
        if canonical_item_id is None:
            raise AppError(
                code="ITEM_NOT_FOUND",
                message=f"Canonical item '{canonical_item_number}' not found",
                status_code=404,
            )
    _get_entity_or_404(
        conn,
        "items_master",
        "item_id",
        canonical_item_id,
        "ITEM_NOT_FOUND",
        f"Item with id {canonical_item_id} not found",
    )
    normalized_item_number = require_non_empty(ordered_item_number, "ordered_item_number")
    if _resolve_item_by_number(conn, normalized_item_number) is not None:
        raise AppError(
            code="ALIAS_CONFLICT_DIRECT_ITEM",
            message=(
                f"ordered_item_number '{normalized_item_number}' matches an existing direct item_number; "
                "alias would never be used"
            ),
            status_code=409,
        )
    units = require_positive_int(units_per_order, "units_per_order")
    conn.execute(
        """
        INSERT INTO supplier_item_aliases (
            supplier_id, ordered_item_number, canonical_item_id, units_per_order, created_at
        ) VALUES (?, ?, ?, ?, ?)
        ON CONFLICT (supplier_id, ordered_item_number)
        DO UPDATE SET
            canonical_item_id = excluded.canonical_item_id,
            units_per_order = excluded.units_per_order
        """,
        (supplier_id, normalized_item_number, canonical_item_id, units, now_jst_iso()),
    )
    row = conn.execute(
        """
        SELECT
            a.alias_id,
            a.supplier_id,
            s.name AS supplier_name,
            a.ordered_item_number,
            a.canonical_item_id,
            im.item_number AS canonical_item_number,
            a.units_per_order,
            a.created_at
        FROM supplier_item_aliases a
        JOIN suppliers s ON s.supplier_id = a.supplier_id
        JOIN items_master im ON im.item_id = a.canonical_item_id
        WHERE a.supplier_id = ? AND a.ordered_item_number = ?
        """,
        (supplier_id, normalized_item_number),
    ).fetchone()
    return dict(row)


def upsert_supplier_item_alias_by_name(
    conn: sqlite3.Connection,
    *,
    supplier_name: str,
    ordered_item_number: str,
    canonical_item_id: int | None = None,
    canonical_item_number: str | None = None,
    units_per_order: int = 1,
) -> dict[str, Any]:
    supplier_id = _get_or_create_supplier(conn, require_non_empty(supplier_name, "supplier_name"))
    return upsert_supplier_item_alias(
        conn,
        supplier_id=supplier_id,
        ordered_item_number=ordered_item_number,
        canonical_item_id=canonical_item_id,
        canonical_item_number=canonical_item_number,
        units_per_order=units_per_order,
    )


def delete_supplier_item_alias(conn: sqlite3.Connection, alias_id: int) -> None:
    row = conn.execute(
        "SELECT alias_id FROM supplier_item_aliases WHERE alias_id = ?",
        (alias_id,),
    ).fetchone()
    if row is None:
        raise AppError(
            code="ALIAS_NOT_FOUND",
            message=f"Alias with id {alias_id} not found",
            status_code=404,
        )
    conn.execute("DELETE FROM supplier_item_aliases WHERE alias_id = ?", (alias_id,))


def list_raw_categories(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        """
        SELECT DISTINCT category
        FROM items_master
        WHERE category IS NOT NULL AND trim(category) <> ''
        ORDER BY category
        """
    ).fetchall()
    return [str(row["category"]) for row in rows]


def list_category_aliases(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT alias_category, canonical_category, created_at, updated_at
        FROM category_aliases
        ORDER BY alias_category
        """
    ).fetchall()
    return _rows_to_dict(rows)


def list_categories(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        """
        SELECT DISTINCT COALESCE(ca.canonical_category, im.category) AS category
        FROM items_master im
        LEFT JOIN category_aliases ca ON ca.alias_category = im.category
        WHERE im.category IS NOT NULL AND trim(im.category) <> ''
        ORDER BY category
        """
    ).fetchall()
    return [str(row["category"]) for row in rows]


def get_category_usage(conn: sqlite3.Connection, category: str) -> dict[str, Any]:
    normalized = require_non_empty(category, "category")
    rows = conn.execute(
        """
        SELECT
            im.item_id,
            im.item_number,
            im.category AS raw_category,
            COALESCE(ca.canonical_category, im.category) AS effective_category
        FROM items_master im
        LEFT JOIN category_aliases ca ON ca.alias_category = im.category
        WHERE im.category = ? OR COALESCE(ca.canonical_category, im.category) = ?
        ORDER BY im.item_number
        """,
        (normalized, normalized),
    ).fetchall()
    return {"category": normalized, "items": _rows_to_dict(rows)}


def merge_category_alias(
    conn: sqlite3.Connection, source_category: str, target_category: str
) -> dict[str, Any]:
    source = require_non_empty(source_category, "alias_category")
    target = require_non_empty(target_category, "canonical_category")
    if source == target:
        raise AppError(
            code="INVALID_CATEGORY_ALIAS",
            message="alias_category and canonical_category must differ",
            status_code=422,
        )
    now = now_jst_iso()
    conn.execute(
        """
        INSERT INTO category_aliases (
            alias_category, canonical_category, created_at, updated_at
        ) VALUES (?, ?, ?, ?)
        ON CONFLICT (alias_category)
        DO UPDATE SET
            canonical_category = excluded.canonical_category,
            updated_at = excluded.updated_at
        """,
        (source, target, now, now),
    )
    row = conn.execute(
        """
        SELECT alias_category, canonical_category, created_at, updated_at
        FROM category_aliases
        WHERE alias_category = ?
        """,
        (source,),
    ).fetchone()
    return dict(row)


def remove_category_alias(conn: sqlite3.Connection, source_category: str) -> None:
    normalized = require_non_empty(source_category, "alias_category")
    row = conn.execute(
        "SELECT alias_category FROM category_aliases WHERE alias_category = ?",
        (normalized,),
    ).fetchone()
    if row is None:
        raise AppError(
            code="CATEGORY_ALIAS_NOT_FOUND",
            message=f"Category alias '{normalized}' not found",
            status_code=404,
        )
    conn.execute(
        "DELETE FROM category_aliases WHERE alias_category = ?",
        (normalized,),
    )


def rename_category(conn: sqlite3.Connection, source_category: str, target_category: str) -> dict[str, Any]:
    return merge_category_alias(conn, source_category, target_category)
