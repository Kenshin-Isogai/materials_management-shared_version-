from __future__ import annotations

from pathlib import Path

import pytest

from app.errors import AppError
from app.order_import_paths import build_roots, iter_unregistered_order_csvs, supplier_from_unregistered_csv_path


def test_supplier_from_canonical_csv_path(tmp_path: Path):
    roots = build_roots(
        unregistered_root=tmp_path / "orders" / "unregistered",
        registered_root=tmp_path / "orders" / "registered",
    )
    csv_path = roots.unregistered_csv_root / "SupplierA" / "Q-001.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.write_text("item_number,quantity\nA,1\n", encoding="utf-8")

    supplier, warnings = supplier_from_unregistered_csv_path(csv_path, roots=roots)

    assert supplier == "SupplierA"
    assert warnings == []


def test_supplier_from_noncanonical_csv_path_is_invalid(tmp_path: Path):
    roots = build_roots(
        unregistered_root=tmp_path / "orders" / "unregistered",
        registered_root=tmp_path / "orders" / "registered",
    )
    csv_path = roots.unregistered_root / "LegacySupplier" / "Q-legacy.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.write_text("item_number,quantity\nA,1\n", encoding="utf-8")

    with pytest.raises(AppError):
        supplier_from_unregistered_csv_path(csv_path, roots=roots)


def test_iter_unregistered_order_csvs_skips_missing_item_registration_files(tmp_path: Path):
    roots = build_roots(
        unregistered_root=tmp_path / "orders" / "unregistered",
        registered_root=tmp_path / "orders" / "registered",
    )

    normal_csv = roots.unregistered_csv_root / "SupplierA" / "Q-001.csv"
    normal_csv.parent.mkdir(parents=True, exist_ok=True)
    normal_csv.write_text("item_number,quantity\nA,1\n", encoding="utf-8")

    missing_register = roots.unregistered_csv_root / "SupplierA" / "SupplierA__Q-001_missing_items_registration.csv"
    missing_register.parent.mkdir(parents=True, exist_ok=True)
    missing_register.write_text("item_number,supplier\nA,SupplierA\n", encoding="utf-8")

    order_csvs = iter_unregistered_order_csvs(roots)

    assert order_csvs == [normal_csv]
