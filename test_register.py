import csv
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.append(r"c:\\Users\\IsogaiKenshin\\Documents\\Yaqumo\\applications\\materials_management\\backend")

from app.db import get_connection, init_db
from app.service import register_pending_item_csvs
from app.utils import today_jst


def main() -> None:
    with TemporaryDirectory() as tmp_dir:
        workspace = Path(tmp_dir)
        db_path = workspace / "inventory.db"
        pending_root = workspace / "imports" / "items" / "pending"
        processed_root = workspace / "imports" / "items" / "processed"
        pending_root.mkdir(parents=True, exist_ok=True)
        processed_root.mkdir(parents=True, exist_ok=True)

        register_csv = pending_root / "batch_missing_items_registration_20260309_000000.csv"
        with register_csv.open("w", encoding="utf-8-sig", newline="") as fp:
            writer = csv.DictWriter(
                fp,
                fieldnames=[
                    "source_csv",
                    "source_supplier",
                    "item_number",
                    "supplier",
                    "manufacturer_name",
                    "resolution_type",
                    "category",
                    "url",
                    "description",
                    "canonical_item_number",
                    "units_per_order",
                ],
            )
            writer.writeheader()
            writer.writerow(
                {
                    "source_csv": "quotations/unregistered/csv_files/Sup/dummy.csv",
                    "source_supplier": "Sup",
                    "item_number": "ITEM123",
                    "supplier": "Sup",
                    "manufacturer_name": "Man",
                    "resolution_type": "new_item",
                    "category": "Lens",
                    "url": "",
                    "description": "Debug registration row",
                    "canonical_item_number": "",
                    "units_per_order": "",
                }
            )

        init_db(str(db_path))
        conn = get_connection(str(db_path))
        try:
            result = register_pending_item_csvs(
                conn,
                items_pending_root=pending_root,
                items_processed_root=processed_root,
            )
            conn.commit()
        finally:
            conn.close()

        archived_csv = processed_root / today_jst()[:7] / register_csv.name
        print("Result of register_pending_item_csvs:")
        print(json.dumps({"result": result, "archived_csv": str(archived_csv), "archived_exists": archived_csv.exists()}, indent=2))


if __name__ == "__main__":
    main()
