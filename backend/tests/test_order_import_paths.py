from __future__ import annotations

from pathlib import Path

import pytest

from app.errors import AppError
from app.order_import_paths import (
    build_roots,
    iter_unregistered_order_csvs,
    normalize_legacy_path_text,
    normalize_pdf_link,
    supplier_from_unregistered_csv_path,
)


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


def test_supplier_from_legacy_csv_path_has_warning(tmp_path: Path):
    roots = build_roots(
        unregistered_root=tmp_path / "orders" / "unregistered",
        registered_root=tmp_path / "orders" / "registered",
    )
    csv_path = roots.unregistered_root / "LegacySupplier" / "Q-legacy.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.write_text("item_number,quantity\nA,1\n", encoding="utf-8")

    supplier, warnings = supplier_from_unregistered_csv_path(csv_path, roots=roots)

    assert supplier == "LegacySupplier"
    assert warnings


def test_supplier_under_pdf_files_is_invalid(tmp_path: Path):
    roots = build_roots(
        unregistered_root=tmp_path / "orders" / "unregistered",
        registered_root=tmp_path / "orders" / "registered",
    )
    csv_path = roots.unregistered_pdf_root / "SupplierA" / "Q-001.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.write_text("item_number,quantity\nA,1\n", encoding="utf-8")

    with pytest.raises(AppError):
        supplier_from_unregistered_csv_path(csv_path, roots=roots)


def test_normalize_legacy_path_text_rewrites_known_typos():
    normalized, changed = normalize_legacy_path_text(
        r"quatations\unregistred\pdf_files\SupplierA\Q-001.pdf"
    )

    assert changed is True
    assert normalized == "imports/orders/unregistered/pdf_files/SupplierA/Q-001.pdf"


def test_resolve_pdf_link_with_typoed_workspace_relative_path(tmp_path: Path):
    roots = build_roots(
        unregistered_root=tmp_path / "orders" / "unregistered",
        registered_root=tmp_path / "orders" / "registered",
    )
    pdf_path = roots.unregistered_pdf_root / "SupplierA" / "Q-001.pdf"
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    pdf_path.write_bytes(b"%PDF-1.4\n")

    csv_path = roots.unregistered_csv_root / "SupplierA" / "Q-001.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.write_text("item_number,quantity\nA,1\n", encoding="utf-8")

    source_pdf, normalized, normalizations, warnings = normalize_pdf_link(
        pdf_link="quatations/unregistred/pdf_files/SupplierA/Q-001.pdf",
        supplier_name="SupplierA",
        roots=roots,
        csv_path=csv_path,
    )

    assert source_pdf == pdf_path.resolve()
    assert normalized == "imports/orders/unregistered/pdf_files/SupplierA/Q-001.pdf"
    assert normalizations
    assert warnings == []


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
