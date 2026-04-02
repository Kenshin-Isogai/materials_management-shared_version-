from __future__ import annotations

import importlib
import importlib.util
import os
import sys
import tempfile
import types
from contextlib import nullcontext
from pathlib import Path

import app.config as config_module


def _reload_config():
    return importlib.reload(config_module)


def test_cloud_run_runtime_defaults_to_tmp_app_data_root_and_port():
    original_env = os.environ.copy()
    try:
        os.environ["APP_RUNTIME_TARGET"] = "cloud_run"
        os.environ["PORT"] = "9090"
        os.environ.pop("APP_DATA_ROOT", None)
        os.environ.pop("APP_PORT", None)
        os.environ.pop("K_SERVICE", None)

        config = _reload_config()

        assert config.get_runtime_target() == config.RUNTIME_TARGET_CLOUD_RUN
        assert config.is_cloud_run_runtime() is True
        assert config.APP_PORT == 9090
        assert config.APP_DATA_ROOT == (Path(tempfile.gettempdir()) / "materials-management").resolve()
        assert config.AUTO_MIGRATE_ON_STARTUP is False
        assert config.STRUCTURED_LOGGING is True
        assert config.get_cors_allowed_origins() == []
        assert config.DB_POOL_RECYCLE_SECONDS == 1800
        assert config.MAX_UPLOAD_BYTES == 32 * 1024 * 1024
        assert config.HEAVY_REQUEST_TARGET_SECONDS == 60
        assert config.CLOUD_RUN_CONCURRENCY_TARGET == 10
        assert config.get_recovery_policy_summary()["status"] == "documented_not_verified"
        assert config.get_recovery_policy_summary()["cloud_sql"]["pitr_required_environments"] == [
            "staging",
            "prod",
        ]
        assert config.get_storage_backend() == config.STORAGE_BACKEND_LOCAL
        assert config.get_storage_prefix("artifacts") == "artifacts"
    finally:
        os.environ.clear()
        os.environ.update(original_env)
        _reload_config()


def test_workspace_layout_no_longer_migrates_legacy_workspace_paths(tmp_path: Path):
    original_env = os.environ.copy()
    try:
        workspace_root = tmp_path / "workspace"
        app_data_root = tmp_path / "appdata"
        legacy_quotations = workspace_root / "quotations" / "registered" / "pdf_files" / "SupplierA"
        legacy_quotations.mkdir(parents=True, exist_ok=True)
        (legacy_quotations / "Q-001.pdf").write_bytes(b"%PDF-1.4 test")

        os.environ["APP_DATA_ROOT"] = str(app_data_root)

        config = _reload_config()
        config.WORKSPACE_ROOT = workspace_root
        config.ensure_workspace_layout()

        assert legacy_quotations.exists()
        assert not (config.ORDERS_IMPORT_ROOT / "registered" / "pdf_files" / "SupplierA" / "Q-001.pdf").exists()
        assert config.ORDERS_IMPORT_ROOT.exists()
        assert config.EXPORTS_ROOT.exists()
    finally:
        os.environ.clear()
        os.environ.update(original_env)
        _reload_config()


def test_local_runtime_defaults_keep_startup_migration_and_local_cors():
    original_env = os.environ.copy()
    try:
        os.environ.pop("APP_RUNTIME_TARGET", None)
        os.environ.pop("K_SERVICE", None)
        os.environ.pop("AUTO_MIGRATE_ON_STARTUP", None)
        os.environ.pop("CORS_ALLOWED_ORIGINS", None)
        os.environ.pop("DB_POOL_RECYCLE_SECONDS", None)

        config = _reload_config()

        assert config.get_runtime_target() == config.RUNTIME_TARGET_LOCAL
        assert config.AUTO_MIGRATE_ON_STARTUP is True
        assert config.STRUCTURED_LOGGING is False
        assert "http://localhost:5173" in config.get_cors_allowed_origins()
        assert config.DB_POOL_RECYCLE_SECONDS == 0
    finally:
        os.environ.clear()
        os.environ.update(original_env)
        _reload_config()


def test_runtime_config_honors_explicit_pool_and_cors_settings():
    original_env = os.environ.copy()
    try:
        os.environ["DB_POOL_SIZE"] = "7"
        os.environ["DB_MAX_OVERFLOW"] = "3"
        os.environ["DB_POOL_TIMEOUT"] = "12"
        os.environ["DB_POOL_RECYCLE_SECONDS"] = "45"
        os.environ["CORS_ALLOWED_ORIGINS"] = "https://frontend.example.com, https://admin.example.com "
        os.environ["MAX_UPLOAD_BYTES"] = "4096"
        os.environ["HEAVY_REQUEST_TARGET_SECONDS"] = "75"
        os.environ["CLOUD_RUN_CONCURRENCY_TARGET"] = "8"
        os.environ["INSTANCE_CONNECTION_NAME"] = "project:region:instance"
        os.environ["BACKEND_PUBLIC_BASE_URL"] = "https://backend-abc.a.run.app"
        os.environ["FRONTEND_PUBLIC_BASE_URL"] = "https://frontend-abc.a.run.app"
        os.environ["GCS_BUCKET"] = "materials-prod"
        os.environ["GCS_OBJECT_PREFIX"] = "/materials-management/prod/"
        os.environ["STORAGE_BACKEND"] = "gcs"
        os.environ["DATABASE_URL"] = "postgresql+psycopg://user:pass@/materials_db?host=/cloudsql/project:region:instance"
        os.environ["STRUCTURED_LOGGING"] = "0"

        config = _reload_config()

        assert config.DB_POOL_SIZE == 7
        assert config.DB_MAX_OVERFLOW == 3
        assert config.DB_POOL_TIMEOUT == 12
        assert config.DB_POOL_RECYCLE_SECONDS == 45
        assert config.MAX_UPLOAD_BYTES == 4096
        assert config.HEAVY_REQUEST_TARGET_SECONDS == 75
        assert config.CLOUD_RUN_CONCURRENCY_TARGET == 8
        assert config.STRUCTURED_LOGGING is False
        assert config.INSTANCE_CONNECTION_NAME == "project:region:instance"
        assert config.BACKEND_PUBLIC_BASE_URL == "https://backend-abc.a.run.app"
        assert config.FRONTEND_PUBLIC_BASE_URL == "https://frontend-abc.a.run.app"
        assert config.GCS_BUCKET == "materials-prod"
        assert config.GCS_OBJECT_PREFIX == "materials-management/prod"
        assert config.get_storage_backend() == config.STORAGE_BACKEND_GCS
        assert config.get_storage_prefix("archives") == "materials-management/prod/archives"
        assert config.get_recovery_policy_summary()["cloud_sql"]["instance_connection_name_configured"] is True
        assert config.get_recovery_policy_summary()["object_storage"]["retention_days"]["staging"] == 7
        assert config.get_recovery_policy_summary()["object_storage"]["retention_days"]["archives"] is None
        assert config.uses_cloud_sql_unix_socket() is True
        assert config.get_cors_allowed_origins() == [
            "https://frontend.example.com",
            "https://admin.example.com",
        ]
    finally:
        os.environ.clear()
        os.environ.update(original_env)
        _reload_config()


def test_alembic_env_prefers_database_url_env_over_ini(monkeypatch):
    migration_env_path = Path(__file__).resolve().parents[1] / "alembic" / "env.py"
    captured: dict[str, object] = {}

    class _Config:
        config_file_name = None

        @staticmethod
        def get_main_option(name: str) -> str:
            if name == "sqlalchemy.url":
                return "postgresql+psycopg://fallback:fallback@127.0.0.1:5432/materials_db"
            return ""

    fake_context = types.SimpleNamespace(
        config=_Config(),
        is_offline_mode=lambda: True,
        configure=lambda **kwargs: captured.update(kwargs),
        begin_transaction=lambda: nullcontext(),
        run_migrations=lambda: captured.setdefault("ran_migrations", True),
    )
    fake_alembic = types.ModuleType("alembic")
    fake_alembic.context = fake_context
    fake_sqlalchemy = types.ModuleType("sqlalchemy")
    fake_sqlalchemy.create_engine = lambda *args, **kwargs: None
    fake_sqlalchemy.pool = types.SimpleNamespace(NullPool=object())

    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://cloudrun:secret@/materials_db?host=/cloudsql/project:region:instance",
    )
    previous_alembic = sys.modules.get("alembic")
    previous_sqlalchemy = sys.modules.get("sqlalchemy")
    sys.modules["alembic"] = fake_alembic
    sys.modules["sqlalchemy"] = fake_sqlalchemy

    try:
        spec = importlib.util.spec_from_file_location("test_alembic_env_module", migration_env_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        if previous_alembic is None:
            sys.modules.pop("alembic", None)
        else:
            sys.modules["alembic"] = previous_alembic
        if previous_sqlalchemy is None:
            sys.modules.pop("sqlalchemy", None)
        else:
            sys.modules["sqlalchemy"] = previous_sqlalchemy

    assert captured["url"] == os.environ["DATABASE_URL"]
    assert captured["ran_migrations"] is True
