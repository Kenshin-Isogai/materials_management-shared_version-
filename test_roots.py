import sys
from pathlib import Path
sys.path.append(r"c:\\Users\\IsogaiKenshin\\Documents\\Yaqumo\\applications\\materials_management\\backend")
from app.quotation_paths import build_roots, iter_unregistered_order_csvs

roots = build_roots()
print("Roots:")
print("unregistered_root:", roots.unregistered_root)
print("unregistered_csv_root:", roots.unregistered_csv_root)
print("unregistered_missing_root:", roots.unregistered_missing_root)

# Create dummy files
roots.unregistered_csv_root.mkdir(parents=True, exist_ok=True)
roots.unregistered_missing_root.mkdir(parents=True, exist_ok=True)
dummy_csv = roots.unregistered_csv_root / "test_supplier" / "order.csv"
dummy_csv.parent.mkdir(parents=True, exist_ok=True)
dummy_csv.touch()

dummy_missing = roots.unregistered_missing_root / "batch_missing_items_registration_20260309_110217.csv"
dummy_missing.touch()

print("\nFiles found by iter_unregistered_order_csvs:")
files = iter_unregistered_order_csvs(roots)
for f in files:
    print(f)
