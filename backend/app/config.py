from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_DB_PATH = BACKEND_ROOT / "database" / "inventory.db"
DEFAULT_EXPORTS_DIR = WORKSPACE_ROOT / "exports"
IMPORTS_ROOT = WORKSPACE_ROOT / "imports"
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
AUTH_MODE_NONE = "none"
AUTH_MODE_DRY_RUN = "rbac_dry_run"
AUTH_MODE_ENFORCED = "rbac_enforced"


def resolve_db_path(explicit: str | None = None) -> Path:
    raw = explicit or os.getenv("INVENTORY_DB_PATH")
    if raw:
        return Path(raw).expanduser().resolve()
    return DEFAULT_DB_PATH


def get_auth_mode() -> str:
    raw = (os.getenv("INVENTORY_AUTH_MODE") or AUTH_MODE_NONE).strip().lower()
    if raw not in {AUTH_MODE_NONE, AUTH_MODE_DRY_RUN, AUTH_MODE_ENFORCED}:
        return AUTH_MODE_NONE
    return raw


def _remove_readonly(func, path, _exc_info):  # type: ignore[no-untyped-def]
    """Error handler for shutil.rmtree to clear read-only flag on Windows."""
    os.chmod(path, stat.S_IWRITE)
    func(path)


def ensure_workspace_layout() -> None:
    # Migrate legacy directory names (pending→unregistered, processed→registered)
    _legacy_pending = ITEMS_IMPORT_ROOT / "pending"
    _legacy_processed = ITEMS_IMPORT_ROOT / "processed"
    if _legacy_pending.is_dir() and not ITEMS_IMPORT_UNREGISTERED_ROOT.exists():
        _legacy_pending.rename(ITEMS_IMPORT_UNREGISTERED_ROOT)
    if _legacy_processed.is_dir() and not ITEMS_IMPORT_REGISTERED_ROOT.exists():
        _legacy_processed.rename(ITEMS_IMPORT_REGISTERED_ROOT)

    # Migrate legacy quotations/ → imports/orders/
    _legacy_quotations = WORKSPACE_ROOT / "quotations"
    if _legacy_quotations.is_dir() and not ORDERS_IMPORT_ROOT.exists():
        IMPORTS_ROOT.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copytree(str(_legacy_quotations), str(ORDERS_IMPORT_ROOT))
            shutil.rmtree(str(_legacy_quotations), onerror=_remove_readonly)
        except OSError:
            pass  # Best-effort; new dirs will be created below

    for path in (
        DEFAULT_DB_PATH.parent,
        DEFAULT_EXPORTS_DIR,
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
    ):
        path.mkdir(parents=True, exist_ok=True)
