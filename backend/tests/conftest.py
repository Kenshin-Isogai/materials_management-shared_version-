from __future__ import annotations

import os
from pathlib import Path

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

os.environ.setdefault("AUTH_MODE", "oidc_enforced")
os.environ.setdefault("RBAC_MODE", "rbac_enforced")
os.environ.setdefault("JWT_SHARED_SECRET", "pytest-shared-secret-for-oidc-tests-32b")
os.environ.setdefault("OIDC_PROVIDER", "test-oidc")
os.environ.setdefault("OIDC_EXPECTED_ISSUER", "https://issuer.example.test")
os.environ.setdefault("OIDC_EXPECTED_AUDIENCE", "materials-management-tests")

from app import config, order_import_paths, service, storage
from app.api import create_app
from app.db import get_connection, init_db


@pytest.fixture
def workspace_roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    workspace_root = tmp_path / "workspace"
    backend_root = workspace_root / "backend"
    exports_root = workspace_root / "exports"
    generated_artifacts_root = workspace_root / "generated_artifacts"
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
    staging_import_root = imports_root / "staging"
    items_staging_root = staging_import_root / "items"
    orders_staging_root = staging_import_root / "orders"

    config_overrides = {
        "WORKSPACE_ROOT": workspace_root,
        "BACKEND_ROOT": backend_root,
        "APP_DATA_ROOT": workspace_root,
        "GENERATED_ARTIFACTS_ROOT": generated_artifacts_root,
        "DEFAULT_EXPORTS_DIR": exports_root,
        "EXPORTS_ROOT": exports_root,
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
        "STAGING_IMPORT_ROOT": staging_import_root,
        "ITEMS_IMPORT_STAGING_ROOT": items_staging_root,
        "ORDERS_IMPORT_STAGING_ROOT": orders_staging_root,
    }
    for name, value in config_overrides.items():
        monkeypatch.setattr(config, name, value)

    monkeypatch.setattr(storage.config, "GENERATED_ARTIFACTS_ROOT", generated_artifacts_root)
    monkeypatch.setattr(service, "ITEMS_IMPORT_UNREGISTERED_ROOT", items_unregistered_root)
    monkeypatch.setattr(service, "ITEMS_IMPORT_REGISTERED_ROOT", items_registered_root)
    monkeypatch.setattr(service, "ITEMS_IMPORT_STAGING_ROOT", items_staging_root)

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
def database_url() -> str:
    url = os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL or DATABASE_URL is required for PostgreSQL-backed tests")
    return url


def _reset_database(database_url: str) -> None:
    engine = create_engine(database_url, future=True, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    engine.dispose()


def _make_bearer_token(
    *,
    sub: str,
    email: str,
    hd: str = "example.test",
    iss: str | None = None,
    aud: str | None = None,
) -> str:
    payload = {
        "sub": sub,
        "email": email,
        "email_verified": True,
        "hd": hd,
        "iss": iss or os.environ["OIDC_EXPECTED_ISSUER"],
        "aud": aud or os.environ["OIDC_EXPECTED_AUDIENCE"],
    }
    return jwt.encode(payload, os.environ["JWT_SHARED_SECRET"], algorithm="HS256")


def auth_headers_for_user(
    *,
    sub: str,
    email: str,
    hd: str = "example.test",
    iss: str | None = None,
    aud: str | None = None,
) -> dict[str, str]:
    return {"Authorization": f"Bearer {_make_bearer_token(sub=sub, email=email, hd=hd, iss=iss, aud=aud)}"}


@pytest.fixture
def conn(database_url: str, workspace_roots: dict[str, Path]):
    _reset_database(database_url)
    init_db(database_url)
    connection = get_connection(database_url)
    try:
        yield connection
    finally:
        connection.close()


@pytest.fixture
def client(database_url: str, workspace_roots: dict[str, Path]):
    _reset_database(database_url)
    init_db(database_url)
    seed_conn = get_connection(database_url)
    try:
        service.create_user(
            seed_conn,
            {
                "username": "pytest",
                "display_name": "Pytest User",
                "email": "pytest@example.test",
                "external_subject": "sub-pytest",
                "identity_provider": "test-oidc",
                "hosted_domain": "example.test",
                "role": "admin",
                "is_active": True,
            },
        )
        seed_conn.commit()
    finally:
        seed_conn.close()
    app = create_app(database_url=database_url)
    with TestClient(app) as test_client:
        test_client.headers.update(auth_headers_for_user(sub="sub-pytest", email="pytest@example.test"))
        yield test_client
