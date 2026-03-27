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
