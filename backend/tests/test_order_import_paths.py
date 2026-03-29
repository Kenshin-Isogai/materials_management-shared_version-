from __future__ import annotations

from pathlib import Path

import pytest

from app.errors import AppError
from app.order_import_paths import build_roots, supplier_from_unregistered_csv_path


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
