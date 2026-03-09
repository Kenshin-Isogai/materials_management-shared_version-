import sys
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.append(r"c:\\Users\\IsogaiKenshin\\Documents\\Yaqumo\\applications\\materials_management\\backend")

from app.quotation_paths import build_roots, ensure_roots, iter_unregistered_order_csvs


def main() -> None:
    with TemporaryDirectory() as tmp_dir:
        workspace = Path(tmp_dir)
        roots = build_roots(
            unregistered_root=workspace / "quotations" / "unregistered",
            registered_root=workspace / "quotations" / "registered",
        )
        ensure_roots(roots)

        items_pending_root = workspace / "imports" / "items" / "pending"
        items_processed_root = workspace / "imports" / "items" / "processed"
        items_pending_root.mkdir(parents=True, exist_ok=True)
        items_processed_root.mkdir(parents=True, exist_ok=True)

        dummy_csv = roots.unregistered_csv_root / "test_supplier" / "order.csv"
        dummy_csv.parent.mkdir(parents=True, exist_ok=True)
        dummy_csv.touch()

        pending_register = items_pending_root / "batch_missing_items_registration_20260309_110217.csv"
        pending_register.touch()

        print("Quotation roots:")
        print("unregistered_root:", roots.unregistered_root)
        print("unregistered_csv_root:", roots.unregistered_csv_root)
        print("unregistered_pdf_root:", roots.unregistered_pdf_root)
        print("registered_root:", roots.registered_root)
        print("items_pending_root:", items_pending_root)
        print("items_processed_root:", items_processed_root)

        print("\nFiles found by iter_unregistered_order_csvs:")
        for csv_path in iter_unregistered_order_csvs(roots):
            print(csv_path)

        print("\nPending item registers:")
        print(pending_register)


if __name__ == "__main__":
    main()
