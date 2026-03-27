from __future__ import annotations

import importlib
import os
import tempfile
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
        assert config.get_cors_allowed_origins() == []
        assert config.DB_POOL_RECYCLE_SECONDS == 1800
    finally:
        os.environ.clear()
        os.environ.update(original_env)
        _reload_config()


def test_cloud_run_runtime_skips_legacy_workspace_migration(tmp_path: Path):
    original_env = os.environ.copy()
    try:
        workspace_root = tmp_path / "workspace"
        app_data_root = tmp_path / "appdata"
        legacy_quotations = workspace_root / "quotations" / "registered" / "pdf_files" / "SupplierA"
        legacy_quotations.mkdir(parents=True, exist_ok=True)
        (legacy_quotations / "Q-001.pdf").write_bytes(b"%PDF-1.4 test")

        os.environ["APP_RUNTIME_TARGET"] = "cloud_run"
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

        config = _reload_config()

        assert config.DB_POOL_SIZE == 7
        assert config.DB_MAX_OVERFLOW == 3
        assert config.DB_POOL_TIMEOUT == 12
        assert config.DB_POOL_RECYCLE_SECONDS == 45
        assert config.get_cors_allowed_origins() == [
            "https://frontend.example.com",
            "https://admin.example.com",
        ]
    finally:
        os.environ.clear()
        os.environ.update(original_env)
        _reload_config()
