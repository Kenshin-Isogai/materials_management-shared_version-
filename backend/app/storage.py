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
    path: Path


def _safe_filename(filename: str, default: str) -> str:
    candidate = Path(filename or default).name.strip()
    candidate = re.sub(r"[^A-Za-z0-9._-]+", "_", candidate)
    candidate = candidate.strip("._")
    return candidate or default


def _root_for_bucket(bucket: str) -> Path:
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


def _build_storage_ref(bucket: str, relative_path: Path) -> str:
    normalized = relative_path.as_posix().lstrip("/")
    return f"{LOCAL_STORAGE_SCHEME}://{bucket}/{normalized}"


def _parse_storage_ref(storage_ref: str) -> tuple[str, Path]:
    text = str(storage_ref or "").strip()
    prefix = f"{LOCAL_STORAGE_SCHEME}://"
    if not text.startswith(prefix):
        raise AppError(
            code="ARTIFACT_NOT_FOUND",
            message=f"Stored object '{storage_ref}' not found",
            status_code=404,
        )
    remainder = text[len(prefix) :]
    bucket, _, relative_text = remainder.partition("/")
    if not bucket or not relative_text.strip():
        raise AppError(
            code="ARTIFACT_NOT_FOUND",
            message=f"Stored object '{storage_ref}' not found",
            status_code=404,
        )
    return bucket, Path(relative_text)


def resolve_storage_ref(storage_ref: str) -> Path:
    bucket, relative_path = _parse_storage_ref(storage_ref)
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


def read_storage_bytes(storage_ref: str) -> tuple[str, bytes]:
    stored = stat_storage_ref(storage_ref)
    if stored is None:
        raise AppError(
            code="ARTIFACT_NOT_FOUND",
            message=f"Stored object '{storage_ref}' not found",
            status_code=404,
        )
    return stored.filename, stored.path.read_bytes()


def write_storage_bytes(
    *,
    bucket: str,
    filename: str,
    content: bytes,
    subdir: str | None = None,
) -> StoredObject:
    root = _root_for_bucket(bucket)
    safe_filename = _safe_filename(filename, "artifact.bin")
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

    root = _root_for_bucket(bucket)
    safe_filename = _safe_filename(filename or source.name, source.name or "artifact.bin")
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
