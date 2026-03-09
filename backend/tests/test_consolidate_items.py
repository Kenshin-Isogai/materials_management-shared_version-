"""Tests for consolidate_registered_item_csvs()."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from app import service
from app.service import consolidate_registered_item_csvs, _load_csv_rows_from_path


FIELDNAMES = ["row_type", "item_number", "manufacturer_name", "category"]


def _write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str] = FIELDNAMES) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def test_consolidates_multiple_csvs_into_one(tmp_path: Path):
    month = tmp_path / "2026-03"
    _write_csv(month / "a.csv", [
        {"row_type": "item", "item_number": "A-001", "manufacturer_name": "MfgA", "category": "Lens"},
    ])
    _write_csv(month / "b.csv", [
        {"row_type": "item", "item_number": "B-001", "manufacturer_name": "MfgB", "category": "Mirror"},
    ])

    result = consolidate_registered_item_csvs(tmp_path)

    assert result["consolidated"] == 2
    assert len(result["folders"]) == 1
    assert result["folders"][0]["folder"] == "2026-03"
    assert result["folders"][0]["total_rows"] == 2
    assert result["folders"][0]["output_files"] == 1

    consolidated = month / "items_2026-03_001.csv"
    assert consolidated.exists()
    assert not (month / "a.csv").exists()
    assert not (month / "b.csv").exists()

    rows = _load_csv_rows_from_path(consolidated)
    assert len(rows) == 2
    assert rows[0]["item_number"] == "A-001"
    assert rows[1]["item_number"] == "B-001"


def test_respects_max_rows_limit(tmp_path: Path):
    month = tmp_path / "2026-01"
    rows = [{"row_type": "item", "item_number": f"ITEM-{i:04d}", "manufacturer_name": "Mfg", "category": "Cat"}
            for i in range(12)]
    _write_csv(month / "big.csv", rows)

    result = consolidate_registered_item_csvs(tmp_path, max_rows=5)

    assert result["folders"][0]["output_files"] == 3
    assert result["folders"][0]["total_rows"] == 12

    f1 = _load_csv_rows_from_path(month / "items_2026-01_001.csv")
    f2 = _load_csv_rows_from_path(month / "items_2026-01_002.csv")
    f3 = _load_csv_rows_from_path(month / "items_2026-01_003.csv")
    assert len(f1) == 5
    assert len(f2) == 5
    assert len(f3) == 2
    assert not (month / "big.csv").exists()


def test_appends_to_existing_consolidated_files(tmp_path: Path):
    month = tmp_path / "2026-02"
    # Pre-existing consolidated file with 3 rows
    _write_csv(month / "items_2026-02_001.csv", [
        {"row_type": "item", "item_number": f"OLD-{i:03d}", "manufacturer_name": "Mfg", "category": "Cat"}
        for i in range(3)
    ])
    # New unconsolidated file
    _write_csv(month / "new_data.csv", [
        {"row_type": "item", "item_number": "NEW-001", "manufacturer_name": "Mfg", "category": "Cat"},
    ])

    result = consolidate_registered_item_csvs(tmp_path, max_rows=5000)

    assert result["consolidated"] == 1
    consolidated = month / "items_2026-02_001.csv"
    rows = _load_csv_rows_from_path(consolidated)
    assert len(rows) == 4
    assert rows[3]["item_number"] == "NEW-001"
    assert not (month / "new_data.csv").exists()


def test_splits_when_existing_plus_new_exceeds_limit(tmp_path: Path):
    month = tmp_path / "2026-04"
    _write_csv(month / "items_2026-04_001.csv", [
        {"row_type": "item", "item_number": f"OLD-{i:03d}", "manufacturer_name": "Mfg", "category": "Cat"}
        for i in range(4)
    ])
    _write_csv(month / "fresh.csv", [
        {"row_type": "item", "item_number": f"NEW-{i:03d}", "manufacturer_name": "Mfg", "category": "Cat"}
        for i in range(3)
    ])

    result = consolidate_registered_item_csvs(tmp_path, max_rows=5)

    assert result["folders"][0]["output_files"] == 2
    f1 = _load_csv_rows_from_path(month / "items_2026-04_001.csv")
    f2 = _load_csv_rows_from_path(month / "items_2026-04_002.csv")
    assert len(f1) == 5
    assert len(f2) == 2


def test_no_op_when_no_unconsolidated_files(tmp_path: Path):
    month = tmp_path / "2026-05"
    _write_csv(month / "items_2026-05_001.csv", [
        {"row_type": "item", "item_number": "ONLY-001", "manufacturer_name": "Mfg", "category": "Cat"},
    ])

    result = consolidate_registered_item_csvs(tmp_path)

    assert result["consolidated"] == 0
    assert result["folders"] == []
    # Existing consolidated file untouched
    rows = _load_csv_rows_from_path(month / "items_2026-05_001.csv")
    assert len(rows) == 1


def test_empty_registered_root(tmp_path: Path):
    result = consolidate_registered_item_csvs(tmp_path / "nonexistent")
    assert result == {"consolidated": 0, "folders": []}


def test_handles_csvs_with_different_headers(tmp_path: Path):
    month = tmp_path / "2026-06"
    _write_csv(month / "manual.csv", [
        {"row_type": "item", "item_number": "M-001", "manufacturer_name": "Mfg", "category": "Lens"},
    ], fieldnames=["row_type", "item_number", "manufacturer_name", "category"])
    _write_csv(month / "batch.csv", [
        {"source_csv": "orders/Q1.csv", "source_supplier": "Sup", "item_number": "B-001", "resolution_type": "new_item"},
    ], fieldnames=["source_csv", "source_supplier", "item_number", "resolution_type"])

    result = consolidate_registered_item_csvs(tmp_path)

    consolidated = month / "items_2026-06_001.csv"
    rows = _load_csv_rows_from_path(consolidated)
    assert len(rows) == 2
    # batch.csv sorts before manual.csv, so batch row is first
    assert rows[0]["item_number"] == "B-001"
    assert rows[0].get("manufacturer_name", "") == ""
    assert rows[1]["item_number"] == "M-001"
    assert rows[1].get("source_csv", "") == ""


def test_multiple_month_folders(tmp_path: Path):
    for m in ("2026-01", "2026-02"):
        _write_csv(tmp_path / m / "data.csv", [
            {"row_type": "item", "item_number": f"{m}-001", "manufacturer_name": "Mfg", "category": "Cat"},
        ])

    result = consolidate_registered_item_csvs(tmp_path)

    assert result["consolidated"] == 2
    assert len(result["folders"]) == 2
    assert (tmp_path / "2026-01" / "items_2026-01_001.csv").exists()
    assert (tmp_path / "2026-02" / "items_2026-02_001.csv").exists()


def test_empty_csv_files_are_removed(tmp_path: Path):
    month = tmp_path / "2026-07"
    # CSV with only a header, no data rows
    _write_csv(month / "empty.csv", [])

    result = consolidate_registered_item_csvs(tmp_path)

    assert result["consolidated"] == 1
    assert not (month / "empty.csv").exists()
    # No consolidated file created for zero rows
    assert not (month / "items_2026-07_001.csv").exists()


def test_preserves_existing_consolidated_files_when_staged_write_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    month = tmp_path / "2026-08"
    existing_rows = [
        {"row_type": "item", "item_number": "OLD-001", "manufacturer_name": "Mfg", "category": "Cat"},
    ]
    _write_csv(month / "items_2026-08_001.csv", existing_rows)
    _write_csv(month / "fresh.csv", [
        {"row_type": "item", "item_number": "NEW-001", "manufacturer_name": "Mfg", "category": "Cat"},
    ])

    def _raise_csv_bytes(fieldnames: list[str], rows: list[dict[str, str]]) -> bytes:
        raise OSError("simulated staged write failure")

    monkeypatch.setattr(service, "_csv_bytes", _raise_csv_bytes)

    with pytest.raises(OSError, match="simulated staged write failure"):
        consolidate_registered_item_csvs(tmp_path)

    assert (month / "items_2026-08_001.csv").exists()
    assert (month / "fresh.csv").exists()
    assert _load_csv_rows_from_path(month / "items_2026-08_001.csv") == existing_rows
    assert list(month.glob(".tmp_items_2026-08_001.csv.*")) == []
