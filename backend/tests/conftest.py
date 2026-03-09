from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config, order_import_paths, service
from app.api import create_app
from app.db import get_connection, init_db


@pytest.fixture
def workspace_roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    workspace_root = tmp_path / "workspace"
    backend_root = workspace_root / "backend"
    database_root = backend_root / "database"
    exports_root = workspace_root / "exports"
    imports_root = workspace_root / "imports"
    items_import_root = imports_root / "items"
    items_unregistered_root = items_import_root / "unregistered"
    items_registered_root = items_import_root / "registered"
    orders_import_root = imports_root / "orders"
    orders_unregistered_root = orders_import_root / "unregistered"
    orders_registered_root = orders_import_root / "registered"
    orders_unregistered_csv_root = orders_unregistered_root / "csv_files"
    orders_unregistered_pdf_root = orders_unregistered_root / "pdf_files"
    orders_registered_csv_root = orders_registered_root / "csv_files"
    orders_registered_pdf_root = orders_registered_root / "pdf_files"
    default_db_path = database_root / "inventory.db"

    config_overrides = {
        "WORKSPACE_ROOT": workspace_root,
        "BACKEND_ROOT": backend_root,
        "DEFAULT_DB_PATH": default_db_path,
        "DEFAULT_EXPORTS_DIR": exports_root,
        "IMPORTS_ROOT": imports_root,
        "ITEMS_IMPORT_ROOT": items_import_root,
        "ITEMS_IMPORT_UNREGISTERED_ROOT": items_unregistered_root,
        "ITEMS_IMPORT_REGISTERED_ROOT": items_registered_root,
        "ORDERS_IMPORT_ROOT": orders_import_root,
        "ORDERS_IMPORT_UNREGISTERED_ROOT": orders_unregistered_root,
        "ORDERS_IMPORT_REGISTERED_ROOT": orders_registered_root,
        "ORDERS_IMPORT_UNREGISTERED_CSV_ROOT": orders_unregistered_csv_root,
        "ORDERS_IMPORT_UNREGISTERED_PDF_ROOT": orders_unregistered_pdf_root,
        "ORDERS_IMPORT_REGISTERED_CSV_ROOT": orders_registered_csv_root,
        "ORDERS_IMPORT_REGISTERED_PDF_ROOT": orders_registered_pdf_root,
    }
    for name, value in config_overrides.items():
        monkeypatch.setattr(config, name, value)

    monkeypatch.setattr(service, "DEFAULT_EXPORTS_DIR", exports_root)
    monkeypatch.setattr(service, "ITEMS_IMPORT_UNREGISTERED_ROOT", items_unregistered_root)
    monkeypatch.setattr(service, "ITEMS_IMPORT_REGISTERED_ROOT", items_registered_root)

    monkeypatch.setattr(order_import_paths, "WORKSPACE_ROOT", workspace_root)
    monkeypatch.setattr(order_import_paths, "ORDERS_IMPORT_UNREGISTERED_ROOT", orders_unregistered_root)
    monkeypatch.setattr(order_import_paths, "ORDERS_IMPORT_REGISTERED_ROOT", orders_registered_root)

    config.ensure_workspace_layout()
    return {
        "workspace_root": workspace_root,
        "items_unregistered_root": items_unregistered_root,
        "items_registered_root": items_registered_root,
        "orders_unregistered_root": orders_unregistered_root,
        "orders_registered_root": orders_registered_root,
        "exports_root": exports_root,
    }


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "inventory.db"


@pytest.fixture
def conn(db_path: Path, workspace_roots: dict[str, Path]):
    init_db(str(db_path))
    connection = get_connection(str(db_path))
    try:
        yield connection
    finally:
        connection.close()


@pytest.fixture
def client(db_path: Path, workspace_roots: dict[str, Path]):
    app = create_app(db_path=str(db_path))
    with TestClient(app) as test_client:
        yield test_client

