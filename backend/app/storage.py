from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re
from typing import Final
from uuid import uuid4

from . import config
from .errors import AppError

LOCAL_STORAGE_SCHEME: Final[str] = "local"
GENERATED_ARTIFACTS_BUCKET: Final[str] = "generated_artifacts"
ITEMS_REGISTERED_ARCHIVES_BUCKET: Final[str] = "items_registered_archives"
ITEMS_UNREGISTERED_BUCKET: Final[str] = "items_unregistered"
ORDERS_REGISTERED_CSV_BUCKET: Final[str] = "orders_registered_csv"
ORDERS_REGISTERED_PDF_BUCKET: Final[str] = "orders_registered_pdf"


@dataclass(frozen=True)
class StoredObject:
    storage_ref: str
    filename: str
    size_bytes: int
    created_at: str
    path: Path | None


def _safe_filename(filename: str, default: str) -> str:
    candidate = Path(filename or default).name.strip()
    candidate = re.sub(r"[^A-Za-z0-9._-]+", "_", candidate)
    candidate = candidate.strip("._")
    return candidate or default


def _root_for_bucket(bucket: str) -> Path:
    if config.get_storage_backend() != config.STORAGE_BACKEND_LOCAL:
        raise AppError(
            code="STORAGE_NOT_LOCAL",
            message="Local storage root access is not available for the configured storage backend",
            status_code=500,
        )
    if bucket == GENERATED_ARTIFACTS_BUCKET:
        return config.GENERATED_ARTIFACTS_ROOT
    if bucket == ITEMS_REGISTERED_ARCHIVES_BUCKET:
        return config.ITEMS_IMPORT_REGISTERED_ROOT
    if bucket == ITEMS_UNREGISTERED_BUCKET:
        return config.ITEMS_IMPORT_UNREGISTERED_ROOT
    if bucket == ORDERS_REGISTERED_CSV_BUCKET:
        return config.ORDERS_IMPORT_REGISTERED_CSV_ROOT
    if bucket == ORDERS_REGISTERED_PDF_BUCKET:
        return config.ORDERS_IMPORT_REGISTERED_PDF_ROOT
    raise AppError(
        code="STORAGE_NOT_CONFIGURED",
        message=f"Storage bucket '{bucket}' is not configured",
        status_code=500,
    )


def get_storage_root(bucket: str) -> Path:
    return _root_for_bucket(bucket)


def is_local_storage_backend() -> bool:
    return config.get_storage_backend() == config.STORAGE_BACKEND_LOCAL


def _object_class_for_bucket(bucket: str) -> str:
    if bucket == GENERATED_ARTIFACTS_BUCKET:
        return "artifacts"
    if bucket == ITEMS_UNREGISTERED_BUCKET:
        return "staging"
    if bucket in {
        ITEMS_REGISTERED_ARCHIVES_BUCKET,
        ORDERS_REGISTERED_CSV_BUCKET,
        ORDERS_REGISTERED_PDF_BUCKET,
    }:
        return "archives"
    raise AppError(
        code="STORAGE_NOT_CONFIGURED",
        message=f"Storage bucket '{bucket}' is not configured",
        status_code=500,
    )


def _object_bucket_prefix(bucket: str) -> str:
    bucket_name = {
        GENERATED_ARTIFACTS_BUCKET: "generated_artifacts",
        ITEMS_UNREGISTERED_BUCKET: "items_unregistered",
        ITEMS_REGISTERED_ARCHIVES_BUCKET: "items_registered",
        ORDERS_REGISTERED_CSV_BUCKET: "orders_registered_csv",
        ORDERS_REGISTERED_PDF_BUCKET: "orders_registered_pdf",
    }.get(bucket)
    if bucket_name is None:
        raise AppError(
            code="STORAGE_NOT_CONFIGURED",
            message=f"Storage bucket '{bucket}' is not configured",
            status_code=500,
        )
    return config.get_storage_prefix(_object_class_for_bucket(bucket), bucket_name)


def _object_name_for_bucket(bucket: str, relative_path: Path) -> str:
    prefix = _object_bucket_prefix(bucket)
    normalized = relative_path.as_posix().lstrip("/")
    if prefix:
        return f"{prefix}/{normalized}".strip("/")
    return normalized


def _build_gcs_storage_ref(bucket_name: str, object_name: str) -> str:
    return f"{config.STORAGE_BACKEND_GCS}://{bucket_name}/{object_name.lstrip('/')}"


def _get_gcs_client():
    if not config.GCS_BUCKET:
        raise AppError(
            code="STORAGE_NOT_CONFIGURED",
            message="GCS_BUCKET must be configured when STORAGE_BACKEND=gcs",
            status_code=500,
        )
    try:
        from google.cloud import storage as gcs_storage
    except ImportError as exc:
        raise AppError(
            code="STORAGE_NOT_CONFIGURED",
            message="google-cloud-storage must be installed to use STORAGE_BACKEND=gcs",
            status_code=500,
        ) from exc
    return gcs_storage.Client()


def _get_gcs_bucket(bucket_name: str | None = None):
    target_bucket = bucket_name or config.GCS_BUCKET
    if not target_bucket:
        raise AppError(
            code="STORAGE_NOT_CONFIGURED",
            message="GCS_BUCKET must be configured when STORAGE_BACKEND=gcs",
            status_code=500,
        )
    return _get_gcs_client().bucket(target_bucket)


def _get_gcs_bucket_for_ref(storage_ref: str, bucket_name: str):
    if bucket_name != config.GCS_BUCKET:
        raise AppError(
            code="ARTIFACT_NOT_FOUND",
            message=(
                f"Stored object '{storage_ref}' not found: "
                f"bucket '{bucket_name}' does not match configured GCS bucket"
            ),
            status_code=404,
        )
    return _get_gcs_bucket()


def get_storage_backend_summary() -> dict[str, object]:
    backend = config.get_storage_backend()
    object_prefixes = {
        "staging": config.get_storage_prefix("staging"),
        "artifacts": config.get_storage_prefix("artifacts"),
        "archives": config.get_storage_prefix("archives"),
        "exports": config.get_storage_prefix("exports"),
    }
    return {
        "backend": backend,
        "bucket": config.GCS_BUCKET or None,
        "object_prefix": config.GCS_OBJECT_PREFIX or None,
        "object_prefixes": object_prefixes,
        "cloud_run_ready": backend == config.STORAGE_BACKEND_GCS and bool(config.GCS_BUCKET),
        "implementation_status": "ready",
    }


def _build_storage_ref(bucket: str, relative_path: Path) -> str:
    normalized = relative_path.as_posix().lstrip("/")
    return f"{LOCAL_STORAGE_SCHEME}://{bucket}/{normalized}"


def _parse_storage_ref(storage_ref: str) -> tuple[str, str, Path]:
    text = str(storage_ref or "").strip()
    match = re.match(r"^(?P<scheme>[a-z0-9]+)://(?P<bucket>[^/]+)/(?P<path>.+)$", text, re.IGNORECASE)
    if not match:
        raise AppError(
            code="ARTIFACT_NOT_FOUND",
            message=f"Stored object '{storage_ref}' not found",
            status_code=404,
        )
    scheme = str(match.group("scheme")).lower()
    bucket = str(match.group("bucket"))
    relative_text = str(match.group("path"))
    if not bucket or not relative_text.strip():
        raise AppError(
            code="ARTIFACT_NOT_FOUND",
            message=f"Stored object '{storage_ref}' not found",
            status_code=404,
        )
    return scheme, bucket, Path(relative_text)


def resolve_storage_ref(storage_ref: str) -> Path:
    scheme, bucket, relative_path = _parse_storage_ref(storage_ref)
    if scheme != LOCAL_STORAGE_SCHEME:
        raise AppError(
            code="ARTIFACT_NOT_FOUND",
            message=f"Stored object '{storage_ref}' not found",
            status_code=404,
        )
    root = _root_for_bucket(bucket)
    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise AppError(
            code="ARTIFACT_NOT_FOUND",
            message=f"Stored object '{storage_ref}' not found",
            status_code=404,
        ) from exc
    return candidate


def try_resolve_storage_ref(storage_ref: str) -> Path | None:
    try:
        return resolve_storage_ref(storage_ref)
    except AppError:
        return None


def stat_storage_ref(storage_ref: str) -> StoredObject | None:
    scheme, bucket, relative_path = _parse_storage_ref(storage_ref)
    if scheme == LOCAL_STORAGE_SCHEME:
        path = try_resolve_storage_ref(storage_ref)
        if path is None or not path.is_file():
            return None
        stats = path.stat()
        return StoredObject(
            storage_ref=storage_ref,
            filename=path.name,
            size_bytes=int(stats.st_size),
            created_at=datetime.fromtimestamp(stats.st_mtime).isoformat(timespec="seconds"),
            path=path,
        )
    if scheme == config.STORAGE_BACKEND_GCS:
        blob = _get_gcs_bucket_for_ref(storage_ref, bucket).get_blob(relative_path.as_posix())
        if blob is None:
            return None
        updated = getattr(blob, "updated", None)
        created_at = (
            updated.isoformat(timespec="seconds")
            if hasattr(updated, "isoformat")
            else datetime.utcnow().isoformat(timespec="seconds")
        )
        return StoredObject(
            storage_ref=storage_ref,
            filename=Path(relative_path.as_posix()).name,
            size_bytes=int(getattr(blob, "size", 0) or 0),
            created_at=created_at,
            path=None,
        )
    raise AppError(
        code="ARTIFACT_NOT_FOUND",
        message=f"Stored object '{storage_ref}' not found",
        status_code=404,
    )


def read_storage_bytes(storage_ref: str) -> tuple[str, bytes]:
    stored = stat_storage_ref(storage_ref)
    if stored is None:
        raise AppError(
            code="ARTIFACT_NOT_FOUND",
            message=f"Stored object '{storage_ref}' not found",
            status_code=404,
        )
    if stored.path is not None:
        return stored.filename, stored.path.read_bytes()
    scheme, bucket, relative_path = _parse_storage_ref(storage_ref)
    if scheme == config.STORAGE_BACKEND_GCS:
        blob = _get_gcs_bucket_for_ref(storage_ref, bucket).blob(relative_path.as_posix())
        return stored.filename, blob.download_as_bytes()
    raise AppError(
        code="ARTIFACT_NOT_FOUND",
        message=f"Stored object '{storage_ref}' not found",
        status_code=404,
    )


def write_storage_bytes(
    *,
    bucket: str,
    filename: str,
    content: bytes,
    subdir: str | None = None,
) -> StoredObject:
    safe_filename = _safe_filename(filename, "artifact.bin")
    if is_local_storage_backend():
        root = _root_for_bucket(bucket)
        target_dir = root / Path(subdir) if subdir else root
        target_dir.mkdir(parents=True, exist_ok=True)

        stem = Path(safe_filename).stem
        suffix = Path(safe_filename).suffix
        target = target_dir / safe_filename
        if target.exists():
            index = 1
            while True:
                candidate = target_dir / f"{stem}_{index}{suffix}"
                if not candidate.exists():
                    target = candidate
                    break
                index += 1

        temp_path = target_dir / f".tmp_{target.name}.{uuid4().hex}"
        try:
            temp_path.write_bytes(content)
            temp_path.replace(target)
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise

        stats = target.stat()
        relative_path = target.relative_to(root)
        return StoredObject(
            storage_ref=_build_storage_ref(bucket, relative_path),
            filename=target.name,
            size_bytes=int(stats.st_size),
            created_at=datetime.fromtimestamp(stats.st_mtime).isoformat(timespec="seconds"),
            path=target,
        )

    bucket_client = _get_gcs_bucket()
    relative_dir = Path(subdir) if subdir else Path()
    stem = Path(safe_filename).stem
    suffix = Path(safe_filename).suffix
    relative_path = relative_dir / safe_filename
    object_name = _object_name_for_bucket(bucket, relative_path)
    blob = bucket_client.blob(object_name)
    if blob.exists():
        index = 1
        while True:
            candidate_relative = relative_dir / f"{stem}_{index}{suffix}"
            candidate_object_name = _object_name_for_bucket(bucket, candidate_relative)
            candidate_blob = bucket_client.blob(candidate_object_name)
            if not candidate_blob.exists():
                relative_path = candidate_relative
                object_name = candidate_object_name
                blob = candidate_blob
                break
            index += 1
    blob.upload_from_string(content)
    return stat_storage_ref(_build_gcs_storage_ref(config.GCS_BUCKET, object_name)) or StoredObject(
        storage_ref=_build_gcs_storage_ref(config.GCS_BUCKET, object_name),
        filename=Path(object_name).name,
        size_bytes=len(content),
        created_at=datetime.utcnow().isoformat(timespec="seconds"),
        path=None,
    )


def move_file_to_storage(
    *,
    bucket: str,
    source_path: str | Path,
    filename: str | None = None,
    subdir: str | None = None,
) -> StoredObject:
    source = Path(source_path).resolve()
    if not source.exists() or not source.is_file():
        raise AppError(
            code="STORAGE_SOURCE_NOT_FOUND",
            message=f"Storage source '{source_path}' not found",
            status_code=404,
        )

    safe_filename = _safe_filename(filename or source.name, source.name or "artifact.bin")
    if is_local_storage_backend():
        root = _root_for_bucket(bucket)
        target_dir = root / Path(subdir) if subdir else root
        target_dir.mkdir(parents=True, exist_ok=True)

        stem = Path(safe_filename).stem
        suffix = Path(safe_filename).suffix
        target = target_dir / safe_filename
        if target.exists():
            index = 1
            while True:
                candidate = target_dir / f"{stem}_{index}{suffix}"
                if not candidate.exists():
                    target = candidate
                    break
                index += 1

        source.replace(target)
        stats = target.stat()
        relative_path = target.relative_to(root)
        return StoredObject(
            storage_ref=_build_storage_ref(bucket, relative_path),
            filename=target.name,
            size_bytes=int(stats.st_size),
            created_at=datetime.fromtimestamp(stats.st_mtime).isoformat(timespec="seconds"),
            path=target,
        )

    content = source.read_bytes()
    stored = write_storage_bytes(
        bucket=bucket,
        filename=safe_filename,
        content=content,
        subdir=subdir,
    )
    source.unlink(missing_ok=True)
    return stored


def delete_storage_ref(storage_ref: str) -> None:
    scheme, bucket, relative_path = _parse_storage_ref(storage_ref)
    if scheme == LOCAL_STORAGE_SCHEME:
        path = try_resolve_storage_ref(storage_ref)
        if path is not None:
            path.unlink(missing_ok=True)
        return
    if scheme == config.STORAGE_BACKEND_GCS:
        blob = _get_gcs_bucket_for_ref(storage_ref, bucket).blob(relative_path.as_posix())
        blob.delete()
        return
    raise AppError(
        code="ARTIFACT_NOT_FOUND",
        message=f"Stored object '{storage_ref}' not found",
        status_code=404,
    )
