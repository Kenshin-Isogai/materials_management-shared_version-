import csv
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.append(r"c:\\Users\\IsogaiKenshin\\Documents\\Yaqumo\\applications\\materials_management\\backend")

from app.db import get_connection, init_db
from app.service import register_pending_item_csvs
from app.utils import today_jst


def _write_pending_csv(csv_path: Path, rows: list[dict[str, str]]) -> None:
    with csv_path.open("w", encoding="utf-8-sig", newline="") as fp:
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
        writer.writerows(rows)


def main() -> None:
    with TemporaryDirectory() as tmp_dir:
        workspace = Path(tmp_dir)
        db_path = workspace / "inventory.db"
        pending_root = workspace / "imports" / "items" / "pending"
        processed_root = workspace / "imports" / "items" / "processed"
        pending_root.mkdir(parents=True, exist_ok=True)
        processed_root.mkdir(parents=True, exist_ok=True)

        bad_csv = pending_root / "batch_missing_items_registration_bad.csv"
        good_csv = pending_root / "batch_missing_items_registration_good.csv"
        _write_pending_csv(
            bad_csv,
            [
                {
                    "source_csv": "quotations/unregistered/csv_files/Sup/bad.csv",
                    "source_supplier": "Sup",
                    "item_number": "ITEM-BAD",
                    "supplier": "Sup",
                    "manufacturer_name": "",
                    "resolution_type": "new_item",
                    "category": "",
                    "url": "",
                    "description": "",
                    "canonical_item_number": "",
                    "units_per_order": "",
                }
            ],
        )
        _write_pending_csv(
            good_csv,
            [
                {
                    "source_csv": "quotations/unregistered/csv_files/Sup/good.csv",
                    "source_supplier": "Sup",
                    "item_number": "ITEM-GOOD",
                    "supplier": "Sup",
                    "manufacturer_name": "Man",
                    "resolution_type": "new_item",
                    "category": "Cat",
                    "url": "http://example.invalid/item-good",
                    "description": "Valid debug row",
                    "canonical_item_number": "",
                    "units_per_order": "",
                }
            ],
        )

        init_db(str(db_path))
        conn = get_connection(str(db_path))
        try:
            result = register_pending_item_csvs(
                conn,
                items_pending_root=pending_root,
                items_processed_root=processed_root,
                continue_on_error=True,
            )
            conn.commit()
        finally:
            conn.close()

        archived_good_csv = processed_root / today_jst()[:7] / good_csv.name
        print(
            json.dumps(
                {
                    "result": result,
                    "archived_good_csv": str(archived_good_csv),
                    "archived_good_exists": archived_good_csv.exists(),
                    "bad_csv_still_pending": bad_csv.exists(),
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
