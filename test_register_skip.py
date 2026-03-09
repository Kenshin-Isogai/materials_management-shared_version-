import sys
import sqlite3
import csv
from pathlib import Path
sys.path.append(r"c:\\Users\\IsogaiKenshin\\Documents\\Yaqumo\\applications\\materials_management\\backend")
from app.service import register_unregistered_missing_items_csvs
from app.quotation_paths import build_roots

conn = sqlite3.connect(":memory:")

# Initialize database schema
with open(r"c:\\Users\\IsogaiKenshin\\Documents\\Yaqumo\\applications\\materials_management\\backend\\schema.sql", "r", encoding="utf-8") as f:
    conn.executescript(f.read())

roots = build_roots()
dummy_missing = roots.unregistered_missing_root / "batch_missing_items_registration_2026.csv"
dummy_missing.parent.mkdir(parents=True, exist_ok=True)
with open(dummy_missing, "w", encoding="utf-8-sig", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["source_csv", "source_supplier", "supplier", "item_number", "manufacturer_name", "category", "url", "description", "resolution_type", "canonical_item_number", "units_per_order"])
    writer.writerow(["dummy.csv", "Sup", "Sup", "ITEM123", "Man", "", "", "", "new_item", "", ""])
    writer.writerow(["dummy.csv", "Sup", "Sup", "ITEM456", "Man", "Cat", "http", "Desc", "new_item", "", ""])

result = register_unregistered_missing_items_csvs(conn, continue_on_error=True)
import json
print(json.dumps(result, indent=2))
