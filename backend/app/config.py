from __future__ import annotations

import os
import shutil
import stat
import tempfile
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = Path(__file__).resolve().parents[1]

RUNTIME_TARGET_LOCAL = "local"
RUNTIME_TARGET_CLOUD_RUN = "cloud_run"


def get_runtime_target() -> str:
    explicit = (os.getenv("APP_RUNTIME_TARGET") or "").strip().lower()
    if explicit in {RUNTIME_TARGET_LOCAL, RUNTIME_TARGET_CLOUD_RUN}:
        return explicit
    if os.getenv("K_SERVICE"):
        return RUNTIME_TARGET_CLOUD_RUN
    return RUNTIME_TARGET_LOCAL


def is_cloud_run_runtime() -> bool:
    return get_runtime_target() == RUNTIME_TARGET_CLOUD_RUN


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return int(raw)


def _default_app_data_root() -> Path:
    if is_cloud_run_runtime():
        return Path(tempfile.gettempdir()) / "materials-management"
    return WORKSPACE_ROOT


APP_DATA_ROOT = Path(os.getenv("APP_DATA_ROOT", str(_default_app_data_root()))).expanduser().resolve()
IMPORTS_ROOT = Path(os.getenv("IMPORTS_ROOT", str(APP_DATA_ROOT / "imports"))).expanduser().resolve()
EXPORTS_ROOT = Path(os.getenv("EXPORTS_ROOT", str(APP_DATA_ROOT / "exports"))).expanduser().resolve()
DEFAULT_EXPORTS_DIR = EXPORTS_ROOT
GENERATED_ARTIFACTS_ROOT = APP_DATA_ROOT / "generated_artifacts"

ITEMS_IMPORT_ROOT = IMPORTS_ROOT / "items"
ITEMS_IMPORT_UNREGISTERED_ROOT = ITEMS_IMPORT_ROOT / "unregistered"
ITEMS_IMPORT_REGISTERED_ROOT = ITEMS_IMPORT_ROOT / "registered"

ORDERS_IMPORT_ROOT = IMPORTS_ROOT / "orders"
ORDERS_IMPORT_REGISTERED_ROOT = ORDERS_IMPORT_ROOT / "registered"
ORDERS_IMPORT_UNREGISTERED_ROOT = ORDERS_IMPORT_ROOT / "unregistered"
ORDERS_IMPORT_REGISTERED_CSV_ROOT = ORDERS_IMPORT_REGISTERED_ROOT / "csv_files"
ORDERS_IMPORT_REGISTERED_PDF_ROOT = ORDERS_IMPORT_REGISTERED_ROOT / "pdf_files"
ORDERS_IMPORT_UNREGISTERED_CSV_ROOT = ORDERS_IMPORT_UNREGISTERED_ROOT / "csv_files"
ORDERS_IMPORT_UNREGISTERED_PDF_ROOT = ORDERS_IMPORT_UNREGISTERED_ROOT / "pdf_files"

STAGING_IMPORT_ROOT = IMPORTS_ROOT / "staging"
ITEMS_IMPORT_STAGING_ROOT = STAGING_IMPORT_ROOT / "items"
ORDERS_IMPORT_STAGING_ROOT = STAGING_IMPORT_ROOT / "orders"

ITEMS_IMPORT_MAX_CONSOLIDATED_ROWS = int(os.getenv("ITEMS_IMPORT_MAX_CONSOLIDATED_ROWS", "5000"))

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://materials:materials@localhost:5432/materials_db",
)
APP_HOST = os.getenv("APP_HOST", "0.0.0.0")
APP_PORT = int(os.getenv("PORT") or os.getenv("APP_PORT", "8000"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "info")
WEB_CONCURRENCY = int(os.getenv("WEB_CONCURRENCY", "4"))
AUTO_MIGRATE_ON_STARTUP = _env_flag("AUTO_MIGRATE_ON_STARTUP", default=not is_cloud_run_runtime())
DB_POOL_SIZE = _env_int("DB_POOL_SIZE", 5)
DB_MAX_OVERFLOW = _env_int("DB_MAX_OVERFLOW", 10)
DB_POOL_TIMEOUT = _env_int("DB_POOL_TIMEOUT", 30)
DB_POOL_RECYCLE_SECONDS = _env_int("DB_POOL_RECYCLE_SECONDS", 1800 if is_cloud_run_runtime() else 0)

AUTH_MODE_NONE = "none"
AUTH_MODE_DRY_RUN = "rbac_dry_run"
AUTH_MODE_ENFORCED = "rbac_enforced"


def get_auth_mode() -> str:
    raw = (os.getenv("INVENTORY_AUTH_MODE") or AUTH_MODE_NONE).strip().lower()
    if raw not in {AUTH_MODE_NONE, AUTH_MODE_DRY_RUN, AUTH_MODE_ENFORCED}:
        return AUTH_MODE_NONE
    return raw


def get_cors_allowed_origins() -> list[str]:
    default = (
        ""
        if is_cloud_run_runtime()
        else "http://localhost,http://127.0.0.1,http://localhost:80,http://127.0.0.1:80,http://localhost:5173,http://127.0.0.1:5173"
    )
    raw = os.getenv("CORS_ALLOWED_ORIGINS", default)
    origins = [value.strip() for value in raw.split(",") if value.strip()]
    return origins


def _remove_readonly(func, path, _exc_info):  # type: ignore[no-untyped-def]
    os.chmod(path, stat.S_IWRITE)
    func(path)


def ensure_workspace_layout() -> None:
    if not is_cloud_run_runtime():
        legacy_workspace_root = WORKSPACE_ROOT
        legacy_imports_root = legacy_workspace_root / "imports"
        legacy_items_root = legacy_imports_root / "items"
        legacy_orders_root = legacy_imports_root / "orders"

        legacy_pending = legacy_items_root / "pending"
        legacy_processed = legacy_items_root / "processed"
        if legacy_pending.is_dir() and not ITEMS_IMPORT_UNREGISTERED_ROOT.exists():
            ITEMS_IMPORT_ROOT.mkdir(parents=True, exist_ok=True)
            legacy_pending.rename(ITEMS_IMPORT_UNREGISTERED_ROOT)
        if legacy_processed.is_dir() and not ITEMS_IMPORT_REGISTERED_ROOT.exists():
            ITEMS_IMPORT_ROOT.mkdir(parents=True, exist_ok=True)
            legacy_processed.rename(ITEMS_IMPORT_REGISTERED_ROOT)

        legacy_quotations = legacy_workspace_root / "quotations"
        if legacy_quotations.is_dir() and not ORDERS_IMPORT_ROOT.exists():
            IMPORTS_ROOT.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copytree(str(legacy_quotations), str(ORDERS_IMPORT_ROOT))
                shutil.rmtree(str(legacy_quotations), onerror=_remove_readonly)
            except OSError:
                pass

        # Preserve historical repo-local imports when APP_DATA_ROOT now points elsewhere.
        if legacy_orders_root.is_dir() and not ORDERS_IMPORT_ROOT.exists():
            try:
                shutil.copytree(str(legacy_orders_root), str(ORDERS_IMPORT_ROOT))
            except OSError:
                pass
        if legacy_items_root.is_dir() and not ITEMS_IMPORT_ROOT.exists():
            try:
                shutil.copytree(str(legacy_items_root), str(ITEMS_IMPORT_ROOT))
            except OSError:
                pass

    for path in (
        APP_DATA_ROOT,
        GENERATED_ARTIFACTS_ROOT,
        EXPORTS_ROOT,
        IMPORTS_ROOT,
        ITEMS_IMPORT_ROOT,
        ITEMS_IMPORT_UNREGISTERED_ROOT,
        ITEMS_IMPORT_REGISTERED_ROOT,
        ORDERS_IMPORT_ROOT,
        ORDERS_IMPORT_REGISTERED_ROOT,
        ORDERS_IMPORT_UNREGISTERED_ROOT,
        ORDERS_IMPORT_REGISTERED_CSV_ROOT,
        ORDERS_IMPORT_REGISTERED_PDF_ROOT,
        ORDERS_IMPORT_UNREGISTERED_CSV_ROOT,
        ORDERS_IMPORT_UNREGISTERED_PDF_ROOT,
        STAGING_IMPORT_ROOT,
        ITEMS_IMPORT_STAGING_ROOT,
        ORDERS_IMPORT_STAGING_ROOT,
    ):
        path.mkdir(parents=True, exist_ok=True)
