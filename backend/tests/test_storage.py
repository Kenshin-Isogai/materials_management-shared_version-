from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from app import storage


class _FakeBlob:
    def __init__(self, objects: dict[str, bytes], timestamps: dict[str, datetime], name: str):
        self._objects = objects
        self._timestamps = timestamps
        self.name = name

    def exists(self) -> bool:
        return self.name in self._objects

    def upload_from_string(self, content: bytes) -> None:
        self._objects[self.name] = bytes(content)
        self._timestamps[self.name] = datetime(2026, 3, 28, 12, 0, 0)

    def download_as_bytes(self) -> bytes:
        return self._objects[self.name]

    def delete(self) -> None:
        self._objects.pop(self.name, None)
        self._timestamps.pop(self.name, None)

    @property
    def size(self) -> int:
        return len(self._objects[self.name])

    @property
    def updated(self) -> datetime:
        return self._timestamps[self.name]


class _FakeBucket:
    def __init__(self, objects: dict[str, bytes], timestamps: dict[str, datetime]):
        self._objects = objects
        self._timestamps = timestamps

    def blob(self, name: str) -> _FakeBlob:
        return _FakeBlob(self._objects, self._timestamps, name)

    def get_blob(self, name: str) -> _FakeBlob | None:
        if name not in self._objects:
            return None
        return _FakeBlob(self._objects, self._timestamps, name)


class _FakeClient:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.timestamps: dict[str, datetime] = {}

    def bucket(self, _name: str) -> _FakeBucket:
        return _FakeBucket(self.objects, self.timestamps)


def test_gcs_storage_backend_round_trip(monkeypatch, tmp_path: Path):
    fake_client = _FakeClient()
    monkeypatch.setattr(storage.config, "GCS_BUCKET", "materials-dev")
    monkeypatch.setattr(storage.config, "GCS_OBJECT_PREFIX", "materials/dev")
    monkeypatch.setattr(storage.config, "get_storage_backend", lambda: storage.config.STORAGE_BACKEND_GCS)
    monkeypatch.setattr(storage, "_get_gcs_client", lambda: fake_client)

    written = storage.write_storage_bytes(
        bucket=storage.GENERATED_ARTIFACTS_BUCKET,
        filename="report.csv",
        content=b"hello,world\n",
        subdir="missing_items",
    )
    assert written.storage_ref == (
        "gcs://materials-dev/"
        "materials/dev/artifacts/generated_artifacts/missing_items/report.csv"
    )
    assert written.path is None

    filename, payload = storage.read_storage_bytes(written.storage_ref)
    assert filename == "report.csv"
    assert payload == b"hello,world\n"

    duplicate = storage.write_storage_bytes(
        bucket=storage.GENERATED_ARTIFACTS_BUCKET,
        filename="report.csv",
        content=b"second\n",
        subdir="missing_items",
    )
    assert duplicate.storage_ref.endswith("report_1.csv")

    source = tmp_path / "move-me.csv"
    source.write_bytes(b"moved\n")
    moved = storage.move_file_to_storage(
        bucket=storage.ORDERS_REGISTERED_CSV_BUCKET,
        source_path=source,
        subdir="SupplierA",
    )
    assert source.exists() is False
    assert moved.storage_ref == (
        "gcs://materials-dev/"
        "materials/dev/archives/orders_registered_csv/SupplierA/move-me.csv"
    )
    assert storage.stat_storage_ref(moved.storage_ref) is not None

    storage.delete_storage_ref(moved.storage_ref)
    assert storage.stat_storage_ref(moved.storage_ref) is None


def test_gcs_storage_ref_rejects_bucket_mismatch(monkeypatch):
    fake_client = _FakeClient()
    monkeypatch.setattr(storage.config, "GCS_BUCKET", "materials-dev")
    monkeypatch.setattr(storage.config, "GCS_OBJECT_PREFIX", "materials/dev")
    monkeypatch.setattr(storage.config, "get_storage_backend", lambda: storage.config.STORAGE_BACKEND_GCS)
    monkeypatch.setattr(storage, "_get_gcs_client", lambda: fake_client)

    with pytest.raises(storage.AppError) as exc_info:
        storage.stat_storage_ref(
            "gcs://other-bucket/materials/dev/artifacts/generated_artifacts/report.csv"
        )

    assert exc_info.value.code == "ARTIFACT_NOT_FOUND"
    assert "does not match configured GCS bucket" in exc_info.value.message
