from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from io import StringIO
import json
import re
import unicodedata
from pathlib import Path
import shutil
import sqlite3
from typing import Any, Iterable
from uuid import uuid4

from .config import DEFAULT_EXPORTS_DIR
from .errors import AppError
from .quotation_paths import (
    QuotationRoots,
    build_roots,
    ensure_roots,
    is_legacy_supplier_dir,
    iter_unregistered_missing_csvs,
    iter_unregistered_order_csvs,
    normalize_pdf_link,
    registered_csv_supplier_dir,
    registered_pdf_supplier_dir,
    safe_workspace_relative,
    supplier_from_unregistered_csv_path,
    validate_retry_unregistered_csv_path,
)
from .utils import (
    normalize_optional_date,
    now_jst_iso,
    require_non_empty,
    require_positive_int,
    to_dict,
    today_jst,
)


@dataclass
class Pagination:
    page: int
    per_page: int
    total: int
    total_pages: int


def _rows_to_dict(rows: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


def _paginate(
    conn: sqlite3.Connection,
    sql: str,
    params: tuple[Any, ...],
    page: int,
    per_page: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    page = max(1, int(page))
    per_page = max(1, int(per_page))
    total = int(conn.execute(f"SELECT COUNT(*) AS c FROM ({sql}) AS _q", params).fetchone()["c"])
    offset = (page - 1) * per_page
    rows = conn.execute(f"{sql} LIMIT ? OFFSET ?", (*params, per_page, offset)).fetchall()
    total_pages = (total + per_page - 1) // per_page if total else 0
    return _rows_to_dict(rows), asdict(Pagination(page, per_page, total, total_pages))


def _get_entity_or_404(
    conn: sqlite3.Connection,
    table: str,
    key_name: str,
    key_value: Any,
    code: str,
    message: str,
) -> sqlite3.Row:
    row = conn.execute(
        f"SELECT * FROM {table} WHERE {key_name} = ?",
        (key_value,),
    ).fetchone()
    if row is None:
        raise AppError(code=code, message=message, status_code=404)
    return row


def _item_reference_queries() -> dict[str, str]:
    return {
        "orders": "SELECT 1 FROM orders WHERE item_id = ? LIMIT 1",
        "inventory": "SELECT 1 FROM inventory_ledger WHERE item_id = ? LIMIT 1",
        "reservations": "SELECT 1 FROM reservations WHERE item_id = ? LIMIT 1",
        "assembly_components": "SELECT 1 FROM assembly_components WHERE item_id = ? LIMIT 1",
        "project_requirements": "SELECT 1 FROM project_requirements WHERE item_id = ? LIMIT 1",
        "aliases": "SELECT 1 FROM supplier_item_aliases WHERE canonical_item_id = ? LIMIT 1",
    }


def _first_item_reference(conn: sqlite3.Connection, item_id: int) -> str | None:
    for label, sql in _item_reference_queries().items():
        if conn.execute(sql, (item_id,)).fetchone():
            return label
    return None


def _resolve_item_by_number(conn: sqlite3.Connection, item_number: str) -> int | None:
    rows = conn.execute(
        "SELECT item_id FROM items_master WHERE item_number = ? ORDER BY item_id",
        (item_number,),
    ).fetchall()
    if not rows:
        return None
    if len(rows) > 1:
        raise AppError(
            code="AMBIGUOUS_ITEM_NUMBER",
            message=f"Multiple items found for item_number '{item_number}'. Use canonical_item_id.",
            status_code=409,
        )
    return int(rows[0]["item_id"])


def _get_or_create_manufacturer(conn: sqlite3.Connection, name: str) -> int:
    normalized = require_non_empty(name, "manufacturer_name")
    row = conn.execute(
        "SELECT manufacturer_id FROM manufacturers WHERE name = ?",
        (normalized,),
    ).fetchone()
    if row:
        return int(row["manufacturer_id"])
    cur = conn.execute("INSERT INTO manufacturers (name) VALUES (?)", (normalized,))
    return int(cur.lastrowid)


def _get_or_create_supplier(conn: sqlite3.Connection, name: str) -> int:
    normalized = require_non_empty(name, "supplier")
    row = conn.execute("SELECT supplier_id FROM suppliers WHERE name = ?", (normalized,)).fetchone()
    if row:
        return int(row["supplier_id"])
    casefold_rows = conn.execute(
        "SELECT supplier_id FROM suppliers WHERE lower(name) = lower(?) ORDER BY supplier_id",
        (normalized,),
    ).fetchall()
    if len(casefold_rows) == 1:
        return int(casefold_rows[0]["supplier_id"])
    if len(casefold_rows) > 1:
        raise AppError(
            code="AMBIGUOUS_SUPPLIER_NAME",
            message=(
                f"Multiple suppliers match '{normalized}' case-insensitively. "
                "Use supplier_id to disambiguate."
            ),
            status_code=409,
        )
    cur = conn.execute("INSERT INTO suppliers (name) VALUES (?)", (normalized,))
    return int(cur.lastrowid)


def _resolve_supplier_id(
    conn: sqlite3.Connection,
    supplier_id: int | None = None,
    supplier_name: str | None = None,
) -> int:
    if supplier_id is not None:
        _get_entity_or_404(
            conn,
            "suppliers",
            "supplier_id",
            supplier_id,
            "SUPPLIER_NOT_FOUND",
            f"Supplier with id {supplier_id} not found",
        )
        return int(supplier_id)
    if supplier_name is None:
        raise AppError(
            code="INVALID_SUPPLIER",
            message="supplier_id or supplier_name is required",
            status_code=422,
        )
    return _get_or_create_supplier(conn, supplier_name)


def _resolve_order_item(
    conn: sqlite3.Connection,
    supplier_id: int,
    ordered_item_number: str,
) -> tuple[int | None, int]:
    direct = _resolve_item_by_number(conn, ordered_item_number)
    if direct is not None:
        return direct, 1
    alias = conn.execute(
        """
        SELECT canonical_item_id, units_per_order
        FROM supplier_item_aliases
        WHERE supplier_id = ? AND ordered_item_number = ?
        """,
        (supplier_id, ordered_item_number),
    ).fetchone()
    if alias is None:
        alias_rows = conn.execute(
            """
            SELECT canonical_item_id, units_per_order
            FROM supplier_item_aliases
            WHERE supplier_id = ? AND lower(ordered_item_number) = lower(?)
            ORDER BY alias_id
            """,
            (supplier_id, ordered_item_number),
        ).fetchall()
        if len(alias_rows) > 1:
            raise AppError(
                code="AMBIGUOUS_ORDERED_ITEM_ALIAS",
                message=(
                    f"Multiple aliases found for '{ordered_item_number}' under supplier {supplier_id} "
                    "when matching case-insensitively."
                ),
                status_code=409,
            )
        if len(alias_rows) == 1:
            alias = alias_rows[0]
    if alias is None:
        normalized_lookup = _normalize_item_number_for_lookup(ordered_item_number)
        if normalized_lookup:
            candidate_rows = conn.execute(
                """
                SELECT ordered_item_number, canonical_item_id, units_per_order
                FROM supplier_item_aliases
                WHERE supplier_id = ?
                ORDER BY alias_id
                """,
                (supplier_id,),
            ).fetchall()
            normalized_matches = [
                row
                for row in candidate_rows
                if _normalize_item_number_for_lookup(str(row["ordered_item_number"])) == normalized_lookup
            ]
            if len(normalized_matches) > 1:
                raise AppError(
                    code="AMBIGUOUS_ORDERED_ITEM_ALIAS",
                    message=(
                        f"Multiple aliases found for '{ordered_item_number}' under supplier {supplier_id} "
                        "when matching normalized item numbers."
                    ),
                    status_code=409,
                )
            if len(normalized_matches) == 1:
                alias = normalized_matches[0]
    if alias is None:
        return None, 1
    return int(alias["canonical_item_id"]), int(alias["units_per_order"])


def _normalize_item_number_for_lookup(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).strip().casefold()
    if not normalized:
        return ""
    for dash in ("−", "‐", "‑", "‒", "–", "—", "―", "ー", "－"):
        normalized = normalized.replace(dash, "-")
    normalized = re.sub(r"\s+", "", normalized)
    return normalized


def _get_inventory_quantity(conn: sqlite3.Connection, item_id: int, location: str) -> int:
    row = conn.execute(
        "SELECT quantity FROM inventory_ledger WHERE item_id = ? AND location = ?",
        (item_id, location),
    ).fetchone()
    if row is None:
        return 0
    return int(row["quantity"])


def _get_reserved_allocation_quantity(
    conn: sqlite3.Connection, item_id: int, location: str
) -> int:
    row = conn.execute(
        """
        SELECT COALESCE(SUM(quantity), 0) AS qty
        FROM reservation_allocations
        WHERE item_id = ? AND location = ? AND status = 'ACTIVE'
        """,
        (item_id, location),
    ).fetchone()
    if row is None:
        return 0
    return int(row["qty"] or 0)


def _get_available_inventory_quantity(conn: sqlite3.Connection, item_id: int, location: str) -> int:
    on_hand = _get_inventory_quantity(conn, item_id, location)
    allocated = _get_reserved_allocation_quantity(conn, item_id, location)
    return max(0, on_hand - allocated)


def _list_item_available_inventory(
    conn: sqlite3.Connection, item_id: int
) -> list[tuple[str, int]]:
    rows = conn.execute(
        """
        SELECT location, quantity
        FROM inventory_ledger
        WHERE item_id = ? AND quantity > 0 AND location <> 'RESERVED'
        ORDER BY CASE WHEN location = 'STOCK' THEN 0 ELSE 1 END, location
        """,
        (item_id,),
    ).fetchall()
    available_rows: list[tuple[str, int]] = []
    for row in rows:
        location = str(row["location"])
        available = _get_available_inventory_quantity(conn, item_id, location)
        if available > 0:
            available_rows.append((location, available))
    return available_rows


def _get_total_available_inventory(conn: sqlite3.Connection, item_id: int) -> int:
    return sum(qty for _, qty in _list_item_available_inventory(conn, item_id))


def _apply_inventory_delta(
    conn: sqlite3.Connection,
    item_id: int,
    location: str,
    delta: int,
) -> int:
    normalized_location = require_non_empty(location, "location")
    current = _get_inventory_quantity(conn, item_id, normalized_location)
    updated = current + int(delta)
    if updated < 0:
        raise AppError(
            code="INSUFFICIENT_STOCK",
            message=f"Not enough inventory at {normalized_location}",
            status_code=409,
            details={
                "item_id": item_id,
                "location": normalized_location,
                "requested_delta": delta,
                "available": current,
            },
        )
    if updated == 0:
        conn.execute(
            "DELETE FROM inventory_ledger WHERE item_id = ? AND location = ?",
            (item_id, normalized_location),
        )
    elif current == 0:
        conn.execute(
            """
            INSERT INTO inventory_ledger (item_id, location, quantity, last_updated)
            VALUES (?, ?, ?, ?)
            """,
            (item_id, normalized_location, updated, now_jst_iso()),
        )
    else:
        conn.execute(
            """
            UPDATE inventory_ledger
            SET quantity = ?, last_updated = ?
            WHERE item_id = ? AND location = ?
            """,
            (updated, now_jst_iso(), item_id, normalized_location),
        )
    return updated


def _log_transaction(
    conn: sqlite3.Connection,
    *,
    operation_type: str,
    item_id: int,
    quantity: int,
    from_location: str | None,
    to_location: str | None,
    note: str | None = None,
    batch_id: str | None = None,
    undo_of_log_id: int | None = None,
) -> dict[str, Any]:
    cur = conn.execute(
        """
        INSERT INTO transaction_log (
            timestamp,
            operation_type,
            item_id,
            quantity,
            from_location,
            to_location,
            note,
            batch_id,
            undo_of_log_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            now_jst_iso(),
            operation_type,
            item_id,
            quantity,
            from_location,
            to_location,
            note,
            batch_id,
            undo_of_log_id,
        ),
    )
    return get_transaction(conn, int(cur.lastrowid))


def _get_or_create_quotation(
    conn: sqlite3.Connection,
    supplier_id: int,
    quotation_number: str,
    issue_date: str | None,
    pdf_link: str | None,
) -> int:
    normalized_number = require_non_empty(quotation_number, "quotation_number")
    normalized_issue_date = normalize_optional_date(issue_date, "issue_date")
    row = conn.execute(
        """
        SELECT quotation_id FROM quotations
        WHERE supplier_id = ? AND quotation_number = ?
        """,
        (supplier_id, normalized_number),
    ).fetchone()
    if row:
        conn.execute(
            """
            UPDATE quotations
            SET issue_date = COALESCE(?, issue_date),
                pdf_link = COALESCE(?, pdf_link)
            WHERE quotation_id = ?
            """,
            (normalized_issue_date, pdf_link, int(row["quotation_id"])),
        )
        return int(row["quotation_id"])
    cur = conn.execute(
        """
        INSERT INTO quotations (supplier_id, quotation_number, issue_date, pdf_link)
        VALUES (?, ?, ?, ?)
        """,
        (supplier_id, normalized_number, normalized_issue_date, pdf_link),
    )
    return int(cur.lastrowid)


def _load_csv_rows_from_content(content: bytes) -> list[dict[str, str]]:
    text = content.decode("utf-8-sig")
    reader = csv.DictReader(StringIO(text))
    return [{k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in row.items()} for row in reader]


def _read_csv_text(content: bytes) -> str:
    return content.decode("utf-8-sig")


def _load_csv_rows_from_path(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as fp:
        reader = csv.DictReader(fp)
        return [{k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in row.items()} for row in reader]


def _to_json_text(value: dict[str, Any] | None) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=True, sort_keys=True)


def _from_json_text(value: str | None) -> dict[str, Any] | None:
    if value is None:
        return None
    try:
        loaded = json.loads(value)
    except json.JSONDecodeError:
        return None
    if not isinstance(loaded, dict):
        return None
    return loaded


def _alias_row_by_supplier_and_ordered(
    conn: sqlite3.Connection,
    *,
    supplier_id: int,
    ordered_item_number: str,
) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT
            a.alias_id,
            a.supplier_id,
            s.name AS supplier_name,
            a.ordered_item_number,
            a.canonical_item_id,
            im.item_number AS canonical_item_number,
            a.units_per_order,
            a.created_at
        FROM supplier_item_aliases a
        JOIN suppliers s ON s.supplier_id = a.supplier_id
        JOIN items_master im ON im.item_id = a.canonical_item_id
        WHERE a.supplier_id = ? AND a.ordered_item_number = ?
        """,
        (supplier_id, ordered_item_number),
    ).fetchone()
    return dict(row) if row is not None else None


def _record_import_job(
    conn: sqlite3.Connection,
    *,
    import_type: str,
    source_name: str,
    source_content: str,
    continue_on_error: bool,
    redo_of_job_id: int | None = None,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO import_jobs (
            import_type,
            source_name,
            source_content,
            continue_on_error,
            created_at,
            redo_of_job_id
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            import_type,
            source_name,
            source_content,
            1 if continue_on_error else 0,
            now_jst_iso(),
            redo_of_job_id,
        ),
    )
    return int(cur.lastrowid)


def _record_import_job_effect(
    conn: sqlite3.Connection,
    *,
    import_job_id: int,
    row_number: int,
    status: str,
    effect_type: str,
    entry_type: str | None = None,
    item_id: int | None = None,
    alias_id: int | None = None,
    supplier_id: int | None = None,
    item_number: str | None = None,
    supplier_name: str | None = None,
    canonical_item_number: str | None = None,
    units_per_order: int | None = None,
    message: str | None = None,
    code: str | None = None,
    before_state: dict[str, Any] | None = None,
    after_state: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO import_job_effects (
            import_job_id,
            row_number,
            status,
            entry_type,
            effect_type,
            item_id,
            alias_id,
            supplier_id,
            item_number,
            supplier_name,
            canonical_item_number,
            units_per_order,
            message,
            code,
            before_state,
            after_state,
            created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            import_job_id,
            row_number,
            status,
            entry_type,
            effect_type,
            item_id,
            alias_id,
            supplier_id,
            item_number,
            supplier_name,
            canonical_item_number,
            units_per_order,
            message,
            code,
            _to_json_text(before_state),
            _to_json_text(after_state),
            now_jst_iso(),
        ),
    )


def _finalize_import_job(conn: sqlite3.Connection, *, import_job_id: int, result: dict[str, Any]) -> None:
    conn.execute(
        """
        UPDATE import_jobs
        SET
            status = ?,
            processed = ?,
            created_count = ?,
            duplicate_count = ?,
            failed_count = ?
        WHERE import_job_id = ?
        """,
        (
            result["status"],
            int(result["processed"]),
            int(result["created_count"]),
            int(result["duplicate_count"]),
            int(result["failed_count"]),
            import_job_id,
        ),
    )


def _normalize_import_job_row(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["continue_on_error"] = bool(data.get("continue_on_error"))
    return data


def _normalize_import_job_effect_row(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["before_state"] = _from_json_text(data.get("before_state"))
    data["after_state"] = _from_json_text(data.get("after_state"))
    return data


def _import_job_matches_state(
    current: dict[str, Any] | None,
    expected: dict[str, Any] | None,
    keys: tuple[str, ...],
) -> bool:
    if current is None or expected is None:
        return False
    for key in keys:
        if current.get(key) != expected.get(key):
            return False
    return True


def _raise_import_undo_conflict(message: str, *, effect_id: int, row_number: int) -> None:
    raise AppError(
        code="IMPORT_UNDO_CONFLICT",
        message=message,
        status_code=409,
        details={"effect_id": effect_id, "row": row_number},
    )


MISSING_ITEMS_FIELDNAMES = [
    "item_number",
    "supplier",
    "manufacturer_name",
    "resolution_type",
    "category",
    "url",
    "description",
    "canonical_item_number",
    "units_per_order",
]




def _safe_filename_component(value: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value).strip())
    return sanitized.strip("._") or "unknown"


def _write_missing_items_csv(
    rows: list[dict[str, Any]],
    source_name: str,
    output_dir: str | Path | None = None,
) -> str:
    target_dir = Path(output_dir) if output_dir is not None else DEFAULT_EXPORTS_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(source_name).stem or "order_import"
    file_path = target_dir / f"{stem}_missing_items_registration.csv"
    with file_path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=MISSING_ITEMS_FIELDNAMES)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in MISSING_ITEMS_FIELDNAMES})
    return str(file_path)


def _write_batch_missing_items_register(
    missing_reports: list[dict[str, Any]],
    *,
    output_dir: Path,
) -> str:
    output_dir.mkdir(parents=True, exist_ok=True)
    batch_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target_path = output_dir / f"batch_missing_items_registration_{batch_timestamp}.csv"

    with target_path.open("w", encoding="utf-8", newline="") as fp:
        fieldnames = [
            "source_csv",
            "source_supplier",
            *MISSING_ITEMS_FIELDNAMES,
        ]
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        seen_missing_keys: set[tuple[str, str, str]] = set()
        for report in missing_reports:
            source_csv = str(report.get("file", ""))
            source_supplier = str(report.get("supplier", ""))
            for row in report.get("missing_rows", []):
                item_number = str(row.get("item_number", "")).strip()
                manufacturer_name = str(row.get("manufacturer_name", "")).strip()
                supplier_name = str(row.get("supplier", source_supplier)).strip()
                dedupe_key = (
                    supplier_name.casefold(),
                    manufacturer_name.casefold(),
                    item_number.casefold(),
                )
                if dedupe_key in seen_missing_keys:
                    continue
                seen_missing_keys.add(dedupe_key)
                out_row = {
                    "source_csv": source_csv,
                    "source_supplier": source_supplier,
                }
                for key in MISSING_ITEMS_FIELDNAMES:
                    out_row[key] = row.get(key, "")
                writer.writerow(out_row)
    return str(target_path)


def _safe_workspace_relative(path: Path) -> str:
    return safe_workspace_relative(path)


def _move_file_preserve_name(src: Path, dst_dir: Path) -> Path:
    dst_dir.mkdir(parents=True, exist_ok=True)
    target = dst_dir / src.name
    if target.exists():
        stem = src.stem
        suffix = src.suffix
        idx = 1
        while True:
            candidate = dst_dir / f"{stem}_{idx}{suffix}"
            if not candidate.exists():
                target = candidate
                break
            idx += 1
    shutil.move(str(src), str(target))
    return target


def _move_file_to_target(src: Path, target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(target))
    return target


def _execute_planned_file_moves(planned_moves: list[tuple[Path, Path]]) -> None:
    applied_moves: list[tuple[Path, Path]] = []
    try:
        for src, target in planned_moves:
            src_path = src.resolve()
            target_path = target.resolve()
            if str(src_path).casefold() == str(target_path).casefold():
                continue
            if not src_path.exists():
                raise AppError(
                    code="FILE_MOVE_FAILED",
                    message=f"Source file does not exist: {src_path}",
                    status_code=500,
                )
            moved_to = _move_file_to_target(src_path, target_path)
            applied_moves.append((moved_to.resolve(), src_path))
    except Exception as exc:  # noqa: BLE001
        rollback_errors: list[str] = []
        for moved_to, original_src in reversed(applied_moves):
            try:
                if moved_to.exists():
                    _move_file_to_target(moved_to, original_src)
            except Exception as rollback_exc:  # noqa: BLE001
                rollback_errors.append(f"{moved_to} -> {original_src}: {rollback_exc}")
        detail = f"Failed to move import files: {exc}"
        if rollback_errors:
            detail += f" (rollback issues: {'; '.join(rollback_errors)})"
        raise AppError(
            code="FILE_MOVE_FAILED",
            message=detail,
            status_code=500,
        ) from exc


def _supplier_name_from_unregistered_path(csv_path: Path, roots: QuotationRoots) -> tuple[str, list[str]]:
    return supplier_from_unregistered_csv_path(csv_path, roots=roots)


def _resolve_pdf_source_path(
    csv_path: Path,
    pdf_link: str,
    roots: QuotationRoots,
    supplier_name: str,
) -> tuple[Path | None, str, list[dict[str, str]], list[str]]:
    return normalize_pdf_link(
        pdf_link=pdf_link,
        supplier_name=supplier_name,
        roots=roots,
        csv_path=csv_path,
    )


def list_items(
    conn: sqlite3.Connection,
    *,
    q: str | None = None,
    category: str | None = None,
    manufacturer: str | None = None,
    page: int = 1,
    per_page: int = 50,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if q:
        clauses.append(
            "(im.item_number LIKE ? OR im.description LIKE ? OR im.category LIKE ? OR m.name LIKE ?)"
        )
        wildcard = f"%{q}%"
        params.extend([wildcard, wildcard, wildcard, wildcard])
    if category:
        clauses.append("COALESCE(ca.canonical_category, im.category) = ?")
        params.append(category)
    if manufacturer:
        clauses.append("m.name = ?")
        params.append(manufacturer)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"""
        SELECT
            im.item_id,
            im.item_number,
            im.category AS raw_category,
            COALESCE(ca.canonical_category, im.category) AS category,
            im.url,
            im.description,
            m.manufacturer_id,
            m.name AS manufacturer_name
        FROM items_master im
        JOIN manufacturers m ON m.manufacturer_id = im.manufacturer_id
        LEFT JOIN category_aliases ca ON ca.alias_category = im.category
        {where}
        ORDER BY im.item_number, im.item_id
    """
    return _paginate(conn, sql, tuple(params), page, per_page)


def get_item(conn: sqlite3.Connection, item_id: int) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT
            im.item_id,
            im.item_number,
            im.category AS raw_category,
            COALESCE(ca.canonical_category, im.category) AS category,
            im.url,
            im.description,
            m.manufacturer_id,
            m.name AS manufacturer_name
        FROM items_master im
        JOIN manufacturers m ON m.manufacturer_id = im.manufacturer_id
        LEFT JOIN category_aliases ca ON ca.alias_category = im.category
        WHERE im.item_id = ?
        """,
        (item_id,),
    ).fetchone()
    if row is None:
        raise AppError(
            code="ITEM_NOT_FOUND",
            message=f"Item with id {item_id} not found",
            status_code=404,
        )
    return dict(row)


def create_item(conn: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    manufacturer_id = payload.get("manufacturer_id")
    manufacturer_name = payload.get("manufacturer_name")
    if manufacturer_id is None:
        if manufacturer_name:
            manufacturer_id = _get_or_create_manufacturer(conn, manufacturer_name)
        else:
            manufacturer_id = _get_or_create_manufacturer(conn, "UNKNOWN")
    else:
        _get_entity_or_404(
            conn,
            "manufacturers",
            "manufacturer_id",
            manufacturer_id,
            "MANUFACTURER_NOT_FOUND",
            f"Manufacturer with id {manufacturer_id} not found",
        )
    try:
        cur = conn.execute(
            """
            INSERT INTO items_master (
                item_number, manufacturer_id, category, url, description
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                require_non_empty(payload["item_number"], "item_number"),
                int(manufacturer_id),
                payload.get("category"),
                payload.get("url"),
                payload.get("description"),
            ),
        )
    except sqlite3.IntegrityError as exc:
        raise AppError(
            code="ITEM_ALREADY_EXISTS",
            message="Item already exists for this manufacturer and item_number",
            status_code=409,
        ) from exc
    return get_item(conn, int(cur.lastrowid))


def import_items_from_rows(
    conn: sqlite3.Connection,
    *,
    rows: list[dict[str, str]],
    continue_on_error: bool = True,
    import_job_id: int | None = None,
) -> dict[str, Any]:
    def _normalize_row_type(row: dict[str, str]) -> str:
        row_type_raw = (row.get("row_type") or row.get("resolution_type") or "item").strip().lower()
        return "item" if row_type_raw in {"", "item", "new_item"} else row_type_raw

    processed = 0
    created_count = 0
    duplicate_count = 0
    failed_count = 0
    report: list[dict[str, Any]] = []
    deferred_aliases: list[dict[str, Any]] = []

    csv_item_numbers = {
        (row.get("item_number") or "").strip()
        for row in rows
        if any(str(value or "").strip() for value in row.values())
        and _normalize_row_type(row) == "item"
        and (row.get("item_number") or "").strip()
    }

    for idx, row in enumerate(rows, start=2):
        if not any(str(value or "").strip() for value in row.values()):
            continue
        processed += 1

        item_number = (row.get("item_number") or "").strip()
        row_type = _normalize_row_type(row)

        if row_type not in {"item", "alias"}:
            failed_count += 1
            error_row = {
                "row": idx,
                "status": "error",
                "item_number": item_number or None,
                "error": "row_type must be either 'item' or 'alias'",
                "code": "INVALID_ROW_TYPE",
            }
            report.append(error_row)
            if import_job_id is not None:
                _record_import_job_effect(
                    conn,
                    import_job_id=import_job_id,
                    row_number=idx,
                    status="error",
                    entry_type=None,
                    effect_type="invalid_row_type",
                    item_number=item_number or None,
                    message=error_row["error"],
                    code=error_row["code"],
                )
            if not continue_on_error:
                break
            continue

        try:
            if row_type == "item":
                manufacturer_name = (
                    (row.get("manufacturer_name") or row.get("manufacturer") or "UNKNOWN").strip()
                    or "UNKNOWN"
                )
                payload = {
                    "item_number": item_number,
                    "manufacturer_name": manufacturer_name,
                    "category": (row.get("category") or "").strip() or None,
                    "url": (row.get("url") or "").strip() or None,
                    "description": (row.get("description") or "").strip() or None,
                }
                if not item_number:
                    raise AppError(
                        code="INVALID_ITEM_NUMBER",
                        message="item_number is required",
                        status_code=422,
                    )
                item = create_item(conn, payload)
                created_count += 1
                created_row = {
                    "row": idx,
                    "status": "created",
                    "item_id": item["item_id"],
                    "item_number": item["item_number"],
                    "entry_type": "item",
                }
                report.append(created_row)
                if import_job_id is not None:
                    _record_import_job_effect(
                        conn,
                        import_job_id=import_job_id,
                        row_number=idx,
                        status="created",
                        entry_type="item",
                        effect_type="item_created",
                        item_id=int(item["item_id"]),
                        item_number=item["item_number"],
                        after_state={
                            "item_id": int(item["item_id"]),
                            "item_number": item["item_number"],
                            "manufacturer_id": int(item["manufacturer_id"]),
                            "category": item.get("category"),
                            "url": item.get("url"),
                            "description": item.get("description"),
                        },
                    )
            else:
                if not item_number:
                    raise AppError(
                        code="INVALID_ALIAS",
                        message="item_number is required for alias rows",
                        status_code=422,
                    )
                if item_number in csv_item_numbers or _resolve_item_by_number(conn, item_number) is not None:
                    raise AppError(
                        code="ALIAS_CONFLICT_DIRECT_ITEM",
                        message=(
                            f"ordered_item_number '{item_number}' matches an existing direct item_number; "
                            "alias would never be used"
                        ),
                        status_code=409,
                    )
                supplier_name = require_non_empty(str(row.get("supplier", "")), "supplier")
                canonical_item_number = require_non_empty(
                    str(row.get("canonical_item_number", "")),
                    "canonical_item_number",
                )
                units_raw = str(row.get("units_per_order") or "").strip()
                units_per_order = require_positive_int(int(units_raw), "units_per_order") if units_raw else 1
                canonical_exists = _resolve_item_by_number(conn, canonical_item_number) is not None
                canonical_in_csv = canonical_item_number in csv_item_numbers
                if not canonical_exists and not canonical_in_csv:
                    raise AppError(
                        code="ITEM_NOT_FOUND",
                        message=f"Canonical item '{canonical_item_number}' not found",
                        status_code=404,
                    )
                deferred_aliases.append(
                    {
                        "row": idx,
                        "item_number": item_number,
                        "supplier_name": supplier_name,
                        "canonical_item_number": canonical_item_number,
                        "units_per_order": units_per_order,
                    }
                )
        except AppError as exc:
            if exc.code == "ITEM_ALREADY_EXISTS":
                duplicate_count += 1
                duplicate_row = {
                    "row": idx,
                    "status": "duplicate",
                    "item_number": item_number,
                    "error": exc.message,
                }
                report.append(duplicate_row)
                if import_job_id is not None:
                    _record_import_job_effect(
                        conn,
                        import_job_id=import_job_id,
                        row_number=idx,
                        status="duplicate",
                        entry_type="item",
                        effect_type="item_duplicate",
                        item_number=item_number or None,
                        message=exc.message,
                        code=exc.code,
                    )
            else:
                failed_count += 1
                error_row = {
                    "row": idx,
                    "status": "error",
                    "item_number": item_number or None,
                    "error": exc.message,
                    "code": exc.code,
                }
                report.append(error_row)
                if import_job_id is not None:
                    _record_import_job_effect(
                        conn,
                        import_job_id=import_job_id,
                        row_number=idx,
                        status="error",
                        entry_type=row_type if row_type in {"item", "alias"} else None,
                        effect_type=f"{row_type}_error" if row_type in {"item", "alias"} else "import_row_error",
                        item_number=item_number or None,
                        message=exc.message,
                        code=exc.code,
                    )
            if not continue_on_error:
                break
        except Exception as exc:  # noqa: BLE001
            failed_count += 1
            error_row = {
                "row": idx,
                "status": "error",
                "item_number": item_number or None,
                "error": str(exc),
            }
            report.append(error_row)
            if import_job_id is not None:
                _record_import_job_effect(
                    conn,
                    import_job_id=import_job_id,
                    row_number=idx,
                    status="error",
                    entry_type=row_type if row_type in {"item", "alias"} else None,
                    effect_type="import_row_exception",
                    item_number=item_number or None,
                    message=error_row["error"],
                )
            if not continue_on_error:
                break

    for alias_row in deferred_aliases:
        try:
            supplier_name = str(alias_row["supplier_name"])
            supplier_id = _get_or_create_supplier(conn, supplier_name)
            before_alias = _alias_row_by_supplier_and_ordered(
                conn,
                supplier_id=supplier_id,
                ordered_item_number=str(alias_row["item_number"]),
            )
            alias = upsert_supplier_item_alias(
                conn,
                supplier_id=supplier_id,
                ordered_item_number=str(alias_row["item_number"]),
                canonical_item_number=str(alias_row["canonical_item_number"]),
                units_per_order=int(alias_row["units_per_order"]),
            )
            created_count += 1
            created_row = {
                "row": alias_row["row"],
                "status": "created",
                "item_number": alias_row["item_number"],
                "entry_type": "alias",
                "supplier": supplier_name,
                "canonical_item_number": alias["canonical_item_number"],
                "units_per_order": alias["units_per_order"],
            }
            report.append(created_row)
            if import_job_id is not None:
                effect_type = "alias_updated" if before_alias is not None else "alias_created"
                _record_import_job_effect(
                    conn,
                    import_job_id=import_job_id,
                    row_number=int(alias_row["row"]),
                    status="created",
                    entry_type="alias",
                    effect_type=effect_type,
                    item_number=str(alias_row["item_number"]),
                    supplier_id=int(alias["supplier_id"]),
                    supplier_name=supplier_name,
                    alias_id=int(alias["alias_id"]),
                    canonical_item_number=alias["canonical_item_number"],
                    units_per_order=int(alias["units_per_order"]),
                    before_state=before_alias,
                    after_state=alias,
                )
        except AppError as exc:
            failed_count += 1
            error_row = {
                "row": alias_row["row"],
                "status": "error",
                "item_number": alias_row["item_number"] or None,
                "error": exc.message,
                "code": exc.code,
            }
            report.append(error_row)
            if import_job_id is not None:
                _record_import_job_effect(
                    conn,
                    import_job_id=import_job_id,
                    row_number=int(alias_row["row"]),
                    status="error",
                    entry_type="alias",
                    effect_type="alias_error",
                    item_number=str(alias_row["item_number"]),
                    supplier_name=str(alias_row["supplier_name"]),
                    canonical_item_number=str(alias_row["canonical_item_number"]),
                    units_per_order=int(alias_row["units_per_order"]),
                    message=exc.message,
                    code=exc.code,
                )
            if not continue_on_error:
                break
        except Exception as exc:  # noqa: BLE001
            failed_count += 1
            error_row = {
                "row": alias_row["row"],
                "status": "error",
                "item_number": alias_row["item_number"] or None,
                "error": str(exc),
            }
            report.append(error_row)
            if import_job_id is not None:
                _record_import_job_effect(
                    conn,
                    import_job_id=import_job_id,
                    row_number=int(alias_row["row"]),
                    status="error",
                    entry_type="alias",
                    effect_type="alias_exception",
                    item_number=str(alias_row["item_number"]),
                    supplier_name=str(alias_row["supplier_name"]),
                    canonical_item_number=str(alias_row["canonical_item_number"]),
                    units_per_order=int(alias_row["units_per_order"]),
                    message=error_row["error"],
                )
            if not continue_on_error:
                break

    report.sort(key=lambda row: int(row.get("row", 0)))
    status = "ok" if failed_count == 0 else ("partial" if (created_count or duplicate_count) else "error")
    return {
        "status": status,
        "processed": processed,
        "created_count": created_count,
        "duplicate_count": duplicate_count,
        "failed_count": failed_count,
        "rows": report,
    }


def import_items_from_content(
    conn: sqlite3.Connection,
    *,
    content: bytes,
    continue_on_error: bool = True,
) -> dict[str, Any]:
    rows = _load_csv_rows_from_content(content)
    return import_items_from_rows(
        conn,
        rows=rows,
        continue_on_error=continue_on_error,
    )


def import_items_from_csv_path(
    conn: sqlite3.Connection,
    *,
    csv_path: str | Path,
    continue_on_error: bool = True,
) -> dict[str, Any]:
    rows = _load_csv_rows_from_path(csv_path)
    return import_items_from_rows(
        conn,
        rows=rows,
        continue_on_error=continue_on_error,
    )


def import_items_from_content_with_job(
    conn: sqlite3.Connection,
    *,
    content: bytes,
    source_name: str = "items_import.csv",
    continue_on_error: bool = True,
    redo_of_job_id: int | None = None,
) -> dict[str, Any]:
    source_text = content.decode("utf-8-sig")
    import_job_id = _record_import_job(
        conn,
        import_type="items",
        source_name=source_name,
        source_content=source_text,
        continue_on_error=continue_on_error,
        redo_of_job_id=redo_of_job_id,
    )
    rows = _load_csv_rows_from_content(content)
    result = import_items_from_rows(
        conn,
        rows=rows,
        continue_on_error=continue_on_error,
        import_job_id=import_job_id,
    )
    _finalize_import_job(conn, import_job_id=import_job_id, result=result)
    return {**result, "import_job_id": import_job_id}


def _get_items_import_job_row(conn: sqlite3.Connection, import_job_id: int) -> sqlite3.Row:
    row = conn.execute(
        """
        SELECT
            import_job_id,
            import_type,
            source_name,
            source_content,
            continue_on_error,
            status,
            processed,
            created_count,
            duplicate_count,
            failed_count,
            lifecycle_state,
            created_at,
            undone_at,
            redo_of_job_id,
            last_redo_job_id
        FROM import_jobs
        WHERE import_job_id = ? AND import_type = 'items'
        """,
        (import_job_id,),
    ).fetchone()
    if row is None:
        raise AppError(
            code="IMPORT_JOB_NOT_FOUND",
            message=f"Items import job {import_job_id} not found",
            status_code=404,
        )
    return row


def list_items_import_jobs(
    conn: sqlite3.Connection,
    *,
    page: int = 1,
    per_page: int = 50,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    sql = """
        SELECT
            import_job_id,
            import_type,
            source_name,
            continue_on_error,
            status,
            processed,
            created_count,
            duplicate_count,
            failed_count,
            lifecycle_state,
            created_at,
            undone_at,
            redo_of_job_id,
            last_redo_job_id
        FROM import_jobs
        WHERE import_type = 'items'
        ORDER BY created_at DESC, import_job_id DESC
    """
    rows, pagination = _paginate(conn, sql, tuple(), page, per_page)
    normalized = []
    for row in rows:
        row["continue_on_error"] = bool(row.get("continue_on_error"))
        normalized.append(row)
    return normalized, pagination


def get_items_import_job(conn: sqlite3.Connection, import_job_id: int) -> dict[str, Any]:
    job = _normalize_import_job_row(_get_items_import_job_row(conn, import_job_id))
    effects = conn.execute(
        """
        SELECT
            effect_id,
            import_job_id,
            row_number,
            status,
            entry_type,
            effect_type,
            item_id,
            alias_id,
            supplier_id,
            item_number,
            supplier_name,
            canonical_item_number,
            units_per_order,
            message,
            code,
            before_state,
            after_state,
            created_at
        FROM import_job_effects
        WHERE import_job_id = ?
        ORDER BY row_number, effect_id
        """,
        (import_job_id,),
    ).fetchall()
    return {
        "job": job,
        "effects": [_normalize_import_job_effect_row(row) for row in effects],
    }


def undo_items_import_job(conn: sqlite3.Connection, import_job_id: int) -> dict[str, Any]:
    job_row = _get_items_import_job_row(conn, import_job_id)
    job = _normalize_import_job_row(job_row)
    if job["lifecycle_state"] == "undone":
        raise AppError(
            code="IMPORT_JOB_ALREADY_UNDONE",
            message=f"Items import job {import_job_id} has already been undone",
            status_code=409,
        )

    effects = conn.execute(
        """
        SELECT
            effect_id,
            row_number,
            status,
            entry_type,
            effect_type,
            item_id,
            alias_id,
            supplier_id,
            item_number,
            supplier_name,
            canonical_item_number,
            units_per_order,
            message,
            code,
            before_state,
            after_state
        FROM import_job_effects
        WHERE import_job_id = ? AND status = 'created'
        ORDER BY effect_id DESC
        """,
        (import_job_id,),
    ).fetchall()
    effect_rows = [_normalize_import_job_effect_row(row) for row in effects]
    alias_effects = [row for row in effect_rows if row["effect_type"] in {"alias_created", "alias_updated"}]
    item_effects = [row for row in effect_rows if row["effect_type"] == "item_created"]

    savepoint = f"sp_undo_items_import_{uuid4().hex}"
    conn.execute(f"SAVEPOINT {savepoint}")
    undone_aliases = 0
    restored_aliases = 0
    undone_items = 0
    try:
        for effect in alias_effects:
            effect_id = int(effect["effect_id"])
            row_number = int(effect["row_number"])
            effect_type = str(effect["effect_type"])
            after_state = effect.get("after_state")
            if not isinstance(after_state, dict):
                _raise_import_undo_conflict(
                    "Missing alias after_state snapshot for undo",
                    effect_id=effect_id,
                    row_number=row_number,
                )
            supplier_id = int(after_state["supplier_id"])
            ordered_item_number = str(after_state["ordered_item_number"])
            current_alias = _alias_row_by_supplier_and_ordered(
                conn,
                supplier_id=supplier_id,
                ordered_item_number=ordered_item_number,
            )
            if effect_type == "alias_created":
                if not _import_job_matches_state(
                    current_alias,
                    after_state,
                    (
                        "alias_id",
                        "supplier_id",
                        "ordered_item_number",
                        "canonical_item_id",
                        "units_per_order",
                    ),
                ):
                    _raise_import_undo_conflict(
                        (
                            "Alias no longer matches imported state; "
                            f"cannot safely undo row {row_number}"
                        ),
                        effect_id=effect_id,
                        row_number=row_number,
                    )
                delete_supplier_item_alias(conn, int(current_alias["alias_id"]))
                undone_aliases += 1
                continue

            if effect_type == "alias_updated":
                before_state = effect.get("before_state")
                if not isinstance(before_state, dict):
                    _raise_import_undo_conflict(
                        "Missing alias before_state snapshot for undo",
                        effect_id=effect_id,
                        row_number=row_number,
                    )
                if not _import_job_matches_state(
                    current_alias,
                    after_state,
                    (
                        "alias_id",
                        "supplier_id",
                        "ordered_item_number",
                        "canonical_item_id",
                        "units_per_order",
                    ),
                ):
                    _raise_import_undo_conflict(
                        (
                            "Alias was modified after import; "
                            f"cannot safely undo row {row_number}"
                        ),
                        effect_id=effect_id,
                        row_number=row_number,
                    )
                upsert_supplier_item_alias(
                    conn,
                    supplier_id=int(before_state["supplier_id"]),
                    ordered_item_number=str(before_state["ordered_item_number"]),
                    canonical_item_id=int(before_state["canonical_item_id"]),
                    units_per_order=int(before_state["units_per_order"]),
                )
                restored_aliases += 1
                continue

        for effect in item_effects:
            effect_id = int(effect["effect_id"])
            row_number = int(effect["row_number"])
            after_state = effect.get("after_state")
            if not isinstance(after_state, dict):
                _raise_import_undo_conflict(
                    "Missing item after_state snapshot for undo",
                    effect_id=effect_id,
                    row_number=row_number,
                )
            item_id = int(after_state["item_id"])
            current_item_row = conn.execute(
                """
                SELECT item_id, item_number, manufacturer_id, category, url, description
                FROM items_master
                WHERE item_id = ?
                """,
                (item_id,),
            ).fetchone()
            current_item = dict(current_item_row) if current_item_row is not None else None
            if not _import_job_matches_state(
                current_item,
                after_state,
                ("item_id", "item_number", "manufacturer_id", "category", "url", "description"),
            ):
                _raise_import_undo_conflict(
                    (
                        "Item was modified after import; "
                        f"cannot safely undo row {row_number}"
                    ),
                    effect_id=effect_id,
                    row_number=row_number,
                )
            delete_item(conn, item_id)
            undone_items += 1

        undone_at = now_jst_iso()
        conn.execute(
            """
            UPDATE import_jobs
            SET lifecycle_state = 'undone', undone_at = ?
            WHERE import_job_id = ?
            """,
            (undone_at, import_job_id),
        )
        conn.execute(f"RELEASE {savepoint}")
        return {
            "import_job_id": import_job_id,
            "status": "undone",
            "undone_at": undone_at,
            "removed_aliases": undone_aliases,
            "restored_aliases": restored_aliases,
            "removed_items": undone_items,
        }
    except Exception:
        conn.execute(f"ROLLBACK TO {savepoint}")
        conn.execute(f"RELEASE {savepoint}")
        raise


def redo_items_import_job(conn: sqlite3.Connection, import_job_id: int) -> dict[str, Any]:
    job_row = _get_items_import_job_row(conn, import_job_id)
    job = _normalize_import_job_row(job_row)
    if job["lifecycle_state"] != "undone":
        raise AppError(
            code="IMPORT_JOB_REDO_REQUIRES_UNDONE",
            message=f"Items import job {import_job_id} must be undone before redo",
            status_code=409,
        )
    source_text = str(job_row["source_content"] or "")
    if not source_text:
        raise AppError(
            code="IMPORT_JOB_SOURCE_MISSING",
            message=f"Items import job {import_job_id} does not have source content to redo",
            status_code=422,
        )

    result = import_items_from_content_with_job(
        conn,
        content=source_text.encode("utf-8"),
        source_name=str(job_row["source_name"]),
        continue_on_error=bool(job["continue_on_error"]),
        redo_of_job_id=import_job_id,
    )
    redo_job_id = int(result["import_job_id"])
    conn.execute(
        "UPDATE import_jobs SET last_redo_job_id = ? WHERE import_job_id = ?",
        (redo_job_id, import_job_id),
    )
    return {
        "source_job_id": import_job_id,
        "redo_job_id": redo_job_id,
        "import_result": result,
    }


def update_item(conn: sqlite3.Connection, item_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    current = get_item(conn, item_id)
    updates: list[str] = []
    params: list[Any] = []
    resolved_item_number = current["item_number"]
    resolved_manufacturer_id = int(current["manufacturer_id"])
    pending_manufacturer_name: str | None = None
    manufacturer_changed = False
    item_number_changed = False

    if "item_number" in payload and payload["item_number"] is not None:
        resolved_item_number = require_non_empty(payload["item_number"], "item_number")
        item_number_changed = resolved_item_number != current["item_number"]

    if payload.get("manufacturer_id") is not None:
        mid = int(payload["manufacturer_id"])
        _get_entity_or_404(
            conn,
            "manufacturers",
            "manufacturer_id",
            mid,
            "MANUFACTURER_NOT_FOUND",
            f"Manufacturer with id {mid} not found",
        )
        resolved_manufacturer_id = mid
        manufacturer_changed = resolved_manufacturer_id != int(current["manufacturer_id"])
    elif payload.get("manufacturer_name"):
        normalized = require_non_empty(payload["manufacturer_name"], "manufacturer_name")
        if normalized != current["manufacturer_name"]:
            existing = conn.execute(
                "SELECT manufacturer_id FROM manufacturers WHERE name = ?",
                (normalized,),
            ).fetchone()
            if existing is None:
                pending_manufacturer_name = normalized
                resolved_manufacturer_id = -1
            else:
                resolved_manufacturer_id = int(existing["manufacturer_id"])
            manufacturer_changed = True

    identity_changed = item_number_changed or manufacturer_changed
    if identity_changed:
        ref = _first_item_reference(conn, item_id)
        if ref is not None:
            raise AppError(
                code="ITEM_REFERENCED_IMMUTABLE",
                message=f"Item identity cannot be changed because it is referenced by {ref}",
                status_code=409,
            )

    if item_number_changed:
        updates.append("item_number = ?")
        params.append(resolved_item_number)
    if manufacturer_changed:
        if pending_manufacturer_name is not None:
            resolved_manufacturer_id = _get_or_create_manufacturer(conn, pending_manufacturer_name)
        updates.append("manufacturer_id = ?")
        params.append(resolved_manufacturer_id)

    for key in ("category", "url", "description"):
        if key in payload:
            updates.append(f"{key} = ?")
            params.append(payload.get(key))
    if updates:
        try:
            conn.execute(
                f"UPDATE items_master SET {', '.join(updates)} WHERE item_id = ?",
                (*params, item_id),
            )
        except sqlite3.IntegrityError as exc:
            raise AppError(
                code="ITEM_ALREADY_EXISTS",
                message="Item already exists for this manufacturer and item_number",
                status_code=409,
            ) from exc
    return get_item(conn, item_id)


def bulk_update_item_metadata(
    conn: sqlite3.Connection,
    *,
    rows: list[dict[str, Any]],
    continue_on_error: bool = True,
) -> dict[str, Any]:
    processed = 0
    updated_count = 0
    failed_count = 0
    report: list[dict[str, Any]] = []

    for idx, row in enumerate(rows, start=1):
        processed += 1
        item_id = int(row["item_id"])
        payload: dict[str, Any] = {}
        for key in ("category", "url", "description"):
            if key not in row:
                continue
            value = row.get(key)
            if isinstance(value, str):
                value = value.strip()
            payload[key] = value if value != "" else None
        if not payload:
            failed_count += 1
            report.append(
                {
                    "row": idx,
                    "status": "error",
                    "item_id": item_id,
                    "code": "INVALID_METADATA_UPDATE",
                    "error": "at least one metadata field is required",
                }
            )
            if not continue_on_error:
                break
            continue

        try:
            updated = update_item(conn, item_id, payload)
            updated_count += 1
            report.append(
                {
                    "row": idx,
                    "status": "updated",
                    "item_id": item_id,
                    "item_number": updated["item_number"],
                }
            )
        except AppError as exc:
            failed_count += 1
            report.append(
                {
                    "row": idx,
                    "status": "error",
                    "item_id": item_id,
                    "code": exc.code,
                    "error": exc.message,
                }
            )
            if not continue_on_error:
                break

    status = "ok" if failed_count == 0 else ("partial" if updated_count else "error")
    return {
        "status": status,
        "processed": processed,
        "updated_count": updated_count,
        "failed_count": failed_count,
        "rows": report,
    }


def delete_item(conn: sqlite3.Connection, item_id: int) -> None:
    _get_entity_or_404(
        conn,
        "items_master",
        "item_id",
        item_id,
        "ITEM_NOT_FOUND",
        f"Item with id {item_id} not found",
    )
    ref = _first_item_reference(conn, item_id)
    if ref is not None:
        raise AppError(
            code="ITEM_REFERENCED",
            message=f"Item cannot be deleted because it is referenced by {ref}",
            status_code=409,
        )
    conn.execute("DELETE FROM items_master WHERE item_id = ?", (item_id,))


def list_item_history(conn: sqlite3.Connection, item_id: int) -> list[dict[str, Any]]:
    _get_entity_or_404(
        conn,
        "items_master",
        "item_id",
        item_id,
        "ITEM_NOT_FOUND",
        f"Item with id {item_id} not found",
    )
    rows = conn.execute(
        """
        SELECT *
        FROM transaction_log
        WHERE item_id = ?
        ORDER BY timestamp DESC, log_id DESC
        """,
        (item_id,),
    ).fetchall()
    return _rows_to_dict(rows)


def list_inventory(
    conn: sqlite3.Connection,
    *,
    item_id: int | None = None,
    location: str | None = None,
    page: int = 1,
    per_page: int = 50,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if item_id is not None:
        clauses.append("il.item_id = ?")
        params.append(item_id)
    if location is not None:
        clauses.append("il.location = ?")
        params.append(location)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"""
        SELECT
            il.ledger_id,
            il.item_id,
            im.item_number,
            il.location,
            il.quantity,
            il.last_updated,
            m.name AS manufacturer_name,
            COALESCE(ca.canonical_category, im.category) AS category
        FROM inventory_ledger il
        JOIN items_master im ON im.item_id = il.item_id
        JOIN manufacturers m ON m.manufacturer_id = im.manufacturer_id
        LEFT JOIN category_aliases ca ON ca.alias_category = im.category
        {where}
        ORDER BY il.location, im.item_number
    """
    return _paginate(conn, sql, tuple(params), page, per_page)


def move_inventory(
    conn: sqlite3.Connection,
    *,
    item_id: int,
    quantity: int,
    from_location: str,
    to_location: str,
    note: str | None = None,
    batch_id: str | None = None,
    operation_type: str = "MOVE",
) -> dict[str, Any]:
    require_positive_int(quantity, "quantity")
    if from_location == to_location:
        raise AppError(
            code="INVALID_LOCATION",
            message="from_location and to_location must differ",
            status_code=422,
        )
    _get_entity_or_404(
        conn,
        "items_master",
        "item_id",
        item_id,
        "ITEM_NOT_FOUND",
        f"Item with id {item_id} not found",
    )
    _apply_inventory_delta(conn, item_id, from_location, -int(quantity))
    _apply_inventory_delta(conn, item_id, to_location, int(quantity))
    return _log_transaction(
        conn,
        operation_type=operation_type,
        item_id=item_id,
        quantity=int(quantity),
        from_location=from_location,
        to_location=to_location,
        note=note,
        batch_id=batch_id,
    )


def consume_inventory(
    conn: sqlite3.Connection,
    *,
    item_id: int,
    quantity: int,
    from_location: str,
    note: str | None = None,
    batch_id: str | None = None,
) -> dict[str, Any]:
    require_positive_int(quantity, "quantity")
    _get_entity_or_404(
        conn,
        "items_master",
        "item_id",
        item_id,
        "ITEM_NOT_FOUND",
        f"Item with id {item_id} not found",
    )
    _apply_inventory_delta(conn, item_id, from_location, -int(quantity))
    return _log_transaction(
        conn,
        operation_type="CONSUME",
        item_id=item_id,
        quantity=int(quantity),
        from_location=from_location,
        to_location=None,
        note=note,
        batch_id=batch_id,
    )


def adjust_inventory(
    conn: sqlite3.Connection,
    *,
    item_id: int,
    quantity_delta: int,
    location: str,
    note: str | None = None,
    batch_id: str | None = None,
) -> dict[str, Any]:
    if quantity_delta == 0:
        raise AppError(
            code="INVALID_QUANTITY",
            message="quantity_delta cannot be 0",
            status_code=422,
        )
    _get_entity_or_404(
        conn,
        "items_master",
        "item_id",
        item_id,
        "ITEM_NOT_FOUND",
        f"Item with id {item_id} not found",
    )
    _apply_inventory_delta(conn, item_id, location, int(quantity_delta))
    from_location = None if quantity_delta > 0 else location
    to_location = location if quantity_delta > 0 else None
    return _log_transaction(
        conn,
        operation_type="ADJUST",
        item_id=item_id,
        quantity=abs(int(quantity_delta)),
        from_location=from_location,
        to_location=to_location,
        note=note,
        batch_id=batch_id,
    )


def batch_inventory_operations(
    conn: sqlite3.Connection,
    operations: list[dict[str, Any]],
    batch_id: str | None = None,
) -> dict[str, Any]:
    working_batch_id = batch_id or uuid4().hex
    results: list[dict[str, Any]] = []
    for op in operations:
        op_type = op["operation_type"].upper()
        if op_type == "MOVE":
            results.append(
                move_inventory(
                    conn,
                    item_id=op["item_id"],
                    quantity=op["quantity"],
                    from_location=op["from_location"],
                    to_location=op["to_location"],
                    note=op.get("note"),
                    batch_id=working_batch_id,
                    operation_type="MOVE",
                )
            )
        elif op_type == "CONSUME":
            results.append(
                consume_inventory(
                    conn,
                    item_id=op["item_id"],
                    quantity=op["quantity"],
                    from_location=op["from_location"],
                    note=op.get("note"),
                    batch_id=working_batch_id,
                )
            )
        elif op_type == "RESERVE":
            results.append(
                move_inventory(
                    conn,
                    item_id=op["item_id"],
                    quantity=op["quantity"],
                    from_location=op["from_location"] or "STOCK",
                    to_location=op["to_location"] or "RESERVED",
                    note=op.get("note"),
                    batch_id=working_batch_id,
                    operation_type="RESERVE",
                )
            )
        elif op_type == "ADJUST":
            quantity_delta = op.get("quantity_delta")
            if quantity_delta is None:
                quantity_delta = op["quantity"]
            results.append(
                adjust_inventory(
                    conn,
                    item_id=op["item_id"],
                    quantity_delta=int(quantity_delta),
                    location=op.get("location") or op.get("to_location") or op.get("from_location"),
                    note=op.get("note"),
                    batch_id=working_batch_id,
                )
            )
        elif op_type == "ARRIVAL":
            _apply_inventory_delta(conn, op["item_id"], op.get("to_location") or "STOCK", op["quantity"])
            results.append(
                _log_transaction(
                    conn,
                    operation_type="ARRIVAL",
                    item_id=op["item_id"],
                    quantity=op["quantity"],
                    from_location=None,
                    to_location=op.get("to_location") or "STOCK",
                    note=op.get("note"),
                    batch_id=working_batch_id,
                )
            )
        else:
            raise AppError(
                code="INVALID_OPERATION",
                message=f"Unsupported batch operation_type: {op_type}",
                status_code=422,
            )
    return {"batch_id": working_batch_id, "operations": results}




def _normalize_inventory_csv_operation_type(value: str) -> str:
    normalized = str(value or "").strip().upper()
    if not normalized:
        raise AppError(code="INVALID_OPERATION", message="operation_type is required", status_code=422)
    aliases = {
        "TRANSFER": "MOVE",
    }
    return aliases.get(normalized, normalized)


def _parse_csv_int_field(*, value: Any, row_index: int, field_name: str, code: str) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise AppError(
            code=code,
            message=f"row {row_index}: {field_name} must be an integer",
            status_code=422,
        ) from exc


def import_inventory_movements_from_rows(
    conn: sqlite3.Connection,
    *,
    rows: list[dict[str, Any]],
    batch_id: str | None = None,
) -> dict[str, Any]:
    operations: list[dict[str, Any]] = []
    for idx, row in enumerate(rows, start=2):
        op_type = _normalize_inventory_csv_operation_type(row.get("operation_type", ""))
        item_id_raw = row.get("item_id")
        if item_id_raw in (None, ""):
            raise AppError(code="INVALID_ITEM", message=f"row {idx}: item_id is required", status_code=422)
        quantity_raw = row.get("quantity")
        if quantity_raw in (None, ""):
            raise AppError(code="INVALID_QUANTITY", message=f"row {idx}: quantity is required", status_code=422)
        quantity = require_positive_int(
            _parse_csv_int_field(value=quantity_raw, row_index=idx, field_name="quantity", code="INVALID_QUANTITY"),
            f"row {idx} quantity",
        )
        operation: dict[str, Any] = {
            "operation_type": op_type,
            "item_id": _parse_csv_int_field(value=item_id_raw, row_index=idx, field_name="item_id", code="INVALID_ITEM"),
            "quantity": quantity,
            "from_location": str(row.get("from_location") or "").strip() or None,
            "to_location": str(row.get("to_location") or "").strip() or None,
            "location": str(row.get("location") or "").strip() or None,
            "note": str(row.get("note") or "").strip() or None,
        }
        if op_type in {"MOVE", "CONSUME", "RESERVE"} and not operation["from_location"]:
            raise AppError(code="INVALID_LOCATION", message=f"row {idx}: from_location is required for {op_type}", status_code=422)
        if op_type in {"MOVE", "ARRIVAL", "RESERVE"} and not operation["to_location"]:
            raise AppError(code="INVALID_LOCATION", message=f"row {idx}: to_location is required for {op_type}", status_code=422)
        if op_type == "ADJUST" and not operation["location"]:
            operation["location"] = operation["to_location"] or operation["from_location"]
            if not operation["location"]:
                raise AppError(code="INVALID_LOCATION", message=f"row {idx}: location is required for ADJUST", status_code=422)
        operations.append(operation)
    if not operations:
        raise AppError(code="EMPTY_CSV", message="No movement rows found in CSV", status_code=422)
    return batch_inventory_operations(conn, operations=operations, batch_id=batch_id)


def import_inventory_movements_from_content(
    conn: sqlite3.Connection,
    *,
    content: bytes,
    batch_id: str | None = None,
) -> dict[str, Any]:
    rows = _load_csv_rows_from_content(content)
    return import_inventory_movements_from_rows(conn, rows=rows, batch_id=batch_id)


def _assembly_lookup_map(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute("SELECT assembly_id, name FROM assemblies").fetchall()
    result: dict[str, int] = {}
    for row in rows:
        result[str(row["assembly_id"]).casefold()] = int(row["assembly_id"])
        result[str(row["name"]).strip().casefold()] = int(row["assembly_id"])
    return result


def import_reservations_from_rows(
    conn: sqlite3.Connection,
    *,
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    created: list[dict[str, Any]] = []
    assembly_map = _assembly_lookup_map(conn)
    for idx, row in enumerate(rows, start=2):
        qty_raw = row.get("quantity")
        if qty_raw in (None, ""):
            raise AppError(code="INVALID_QUANTITY", message=f"row {idx}: quantity is required", status_code=422)
        quantity = require_positive_int(
            _parse_csv_int_field(value=qty_raw, row_index=idx, field_name="quantity", code="INVALID_QUANTITY"),
            f"row {idx} quantity",
        )
        purpose = str(row.get("purpose") or "").strip() or None
        deadline = normalize_optional_date((row.get("deadline") or None), "deadline")
        note = str(row.get("note") or "").strip() or None
        project_id_raw = row.get("project_id")
        project_id = (
            _parse_csv_int_field(value=project_id_raw, row_index=idx, field_name="project_id", code="INVALID_PROJECT")
            if project_id_raw not in (None, "")
            else None
        )

        item_id_raw = row.get("item_id")
        assembly_ref = str(row.get("assembly") or row.get("assembly_name") or "").strip()
        assembly_qty_raw = row.get("assembly_quantity")

        if item_id_raw not in (None, ""):
            created.append(
                create_reservation(
                    conn,
                    {
                        "item_id": _parse_csv_int_field(value=item_id_raw, row_index=idx, field_name="item_id", code="INVALID_ITEM"),
                        "quantity": quantity,
                        "purpose": purpose,
                        "deadline": deadline,
                        "note": note,
                        "project_id": project_id,
                    },
                )
            )
            continue

        if not assembly_ref:
            raise AppError(code="INVALID_ITEM", message=f"row {idx}: either item_id or assembly is required", status_code=422)
        assembly_id = assembly_map.get(assembly_ref.casefold())
        if assembly_id is None:
            raise AppError(code="ASSEMBLY_NOT_FOUND", message=f"row {idx}: assembly '{assembly_ref}' not found", status_code=404)
        assembly_quantity = (
            _parse_csv_int_field(
                value=assembly_qty_raw,
                row_index=idx,
                field_name="assembly_quantity",
                code="INVALID_QUANTITY",
            )
            if assembly_qty_raw not in (None, "")
            else 1
        )
        assembly_quantity = require_positive_int(assembly_quantity, f"row {idx} assembly_quantity")
        assembly = get_assembly(conn, assembly_id)
        for component in assembly.get("components", []):
            created.append(
                create_reservation(
                    conn,
                    {
                        "item_id": int(component["item_id"]),
                        "quantity": int(component["quantity"]) * quantity * assembly_quantity,
                        "purpose": purpose or f"Assembly:{assembly['name']}",
                        "deadline": deadline,
                        "note": note,
                        "project_id": project_id,
                    },
                )
            )
    if not rows:
        raise AppError(code="EMPTY_CSV", message="No reservation rows found in CSV", status_code=422)
    return created


def import_reservations_from_content(
    conn: sqlite3.Connection,
    *,
    content: bytes,
) -> list[dict[str, Any]]:
    rows = _load_csv_rows_from_content(content)
    return import_reservations_from_rows(conn, rows=rows)
def list_orders(
    conn: sqlite3.Connection,
    *,
    status: str | None = None,
    supplier: str | None = None,
    include_arrived: bool = True,
    page: int = 1,
    per_page: int = 50,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if status:
        clauses.append("o.status = ?")
        params.append(status)
    if supplier:
        clauses.append("s.name = ?")
        params.append(supplier)
    if not include_arrived:
        clauses.append("o.status <> 'Arrived'")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"""
        SELECT
            o.*,
            im.item_number AS canonical_item_number,
            s.supplier_id,
            s.name AS supplier_name,
            q.quotation_number,
            q.issue_date,
            q.pdf_link
        FROM orders o
        JOIN items_master im ON im.item_id = o.item_id
        JOIN quotations q ON q.quotation_id = o.quotation_id
        JOIN suppliers s ON s.supplier_id = q.supplier_id
        {where}
        ORDER BY o.order_date DESC, o.order_id DESC
    """
    return _paginate(conn, sql, tuple(params), page, per_page)


def get_order(conn: sqlite3.Connection, order_id: int) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT
            o.*,
            im.item_number AS canonical_item_number,
            q.quotation_number,
            q.issue_date,
            q.pdf_link,
            s.supplier_id,
            s.name AS supplier_name
        FROM orders o
        JOIN items_master im ON im.item_id = o.item_id
        JOIN quotations q ON q.quotation_id = o.quotation_id
        JOIN suppliers s ON s.supplier_id = q.supplier_id
        WHERE o.order_id = ?
        """,
        (order_id,),
    ).fetchone()
    if row is None:
        raise AppError(
            code="ORDER_NOT_FOUND",
            message=f"Order with id {order_id} not found",
            status_code=404,
        )
    return dict(row)


def update_order(conn: sqlite3.Connection, order_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    current = get_order(conn, order_id)
    if current["status"] == "Arrived":
        raise AppError(
            code="ORDER_ALREADY_ARRIVED",
            message="Arrived orders cannot be updated",
            status_code=409,
        )
    expected_arrival = normalize_optional_date(payload.get("expected_arrival"), "expected_arrival")
    status = payload.get("status")
    if status and status != "Ordered":
        raise AppError(
            code="INVALID_ORDER_STATUS",
            message="update_order only supports status='Ordered' for open orders",
            status_code=422,
        )
    row_matcher = _order_csv_row_matcher_for_identity(conn, current)

    conn.execute(
        """
        UPDATE orders
        SET expected_arrival = ?, status = COALESCE(?, status)
        WHERE order_id = ?
        """,
        (expected_arrival, status, order_id),
    )
    updated = get_order(conn, order_id)

    roots = build_roots()
    expected_arrival = updated.get("expected_arrival")

    def _updater(row: dict[str, Any]) -> dict[str, Any]:
        row["expected_arrival"] = expected_arrival or ""
        return row

    _rewrite_order_csv_rows(roots, row_matcher=row_matcher, row_updater=_updater)
    return updated


def delete_order(conn: sqlite3.Connection, order_id: int) -> dict[str, Any]:
    order = get_order(conn, order_id)
    if order["status"] == "Arrived":
        raise AppError(
            code="ORDER_ALREADY_ARRIVED",
            message="Arrived orders cannot be deleted",
            status_code=409,
        )
    row_matcher = _order_csv_row_matcher_for_identity(conn, order)

    conn.execute("DELETE FROM orders WHERE order_id = ?", (order_id,))

    roots = build_roots()
    csv_sync = _rewrite_order_csv_rows(roots, row_matcher=row_matcher, row_updater=None)

    remaining = conn.execute(
        "SELECT COUNT(*) AS c FROM orders WHERE quotation_id = ?",
        (order["quotation_id"],),
    ).fetchone()
    quotation_deleted = False
    if int(remaining["c"]) == 0:
        conn.execute("DELETE FROM quotations WHERE quotation_id = ?", (order["quotation_id"],))
        quotation_deleted = True
    return {
        "deleted": True,
        "order_id": order_id,
        "quotation_deleted": quotation_deleted,
        "csv_sync": csv_sync,
    }


def _order_csv_row_matcher_for_identity(
    conn: sqlite3.Connection,
    order_row: dict[str, Any],
) -> Any:
    sibling_rows = conn.execute(
        """
        SELECT o.order_id
        FROM orders o
        JOIN quotations q ON q.quotation_id = o.quotation_id
        JOIN suppliers s ON s.supplier_id = q.supplier_id
        WHERE s.name = ?
          AND q.quotation_number = ?
          AND o.ordered_item_number = ?
        ORDER BY o.order_id ASC
        """,
        (
            str(order_row.get("supplier_name") or ""),
            str(order_row.get("quotation_number") or ""),
            str(order_row.get("ordered_item_number") or ""),
        ),
    ).fetchall()
    sibling_ids = [int(row["order_id"]) for row in sibling_rows]
    order_id = int(order_row["order_id"])
    occurrence_index = sibling_ids.index(order_id) if order_id in sibling_ids else 0
    seen = -1

    def _matcher(csv_row: dict[str, Any]) -> bool:
        nonlocal seen
        is_same_order_key = (
            str(csv_row.get("supplier") or "").strip() == str(order_row.get("supplier_name") or "")
            and str(csv_row.get("quotation_number") or "").strip() == str(order_row.get("quotation_number") or "")
            and str(csv_row.get("item_number") or "").strip() == str(order_row.get("ordered_item_number") or "")
        )
        if not is_same_order_key:
            return False
        seen += 1
        return seen == occurrence_index

    return _matcher


def _normalize_manual_pdf_link(
    pdf_link: str | None,
    *,
    supplier_name: str,
    row_index: int,
    allow_noncanonical_path: bool = False,
) -> str | None:
    raw = (pdf_link or "").strip()
    if not raw:
        return None

    normalized = raw.replace("\\", "/")
    parts = [part for part in normalized.split("/") if part and part != "."]
    if not parts:
        return None

    if len(parts) == 1:
        filename = parts[0]
        if Path(filename).suffix.lower() != ".pdf":
            raise AppError(
                code="INVALID_CSV",
                message=(
                    f"pdf_link must be a PDF filename or canonical registered path "
                    f"(row {row_index})"
                ),
                status_code=422,
            )
        return f"quotations/registered/pdf_files/{supplier_name}/{filename}"

    if allow_noncanonical_path:
        filename = parts[-1]
        if Path(filename).suffix.lower() != ".pdf":
            raise AppError(
                code="INVALID_CSV",
                message=f"pdf_link target must be a .pdf file (row {row_index})",
                status_code=422,
            )
        return "/".join(parts)

    if len(parts) != 5:
        raise AppError(
            code="INVALID_CSV",
            message=(
                "pdf_link must be empty, a PDF filename, or "
                "'quotations/registered/pdf_files/<supplier>/<file>.pdf' "
                f"(row {row_index})"
            ),
            status_code=422,
        )

    expected_prefix = ["quotations", "registered", "pdf_files"]
    if [part.lower() for part in parts[:3]] != expected_prefix:
        raise AppError(
            code="INVALID_CSV",
            message=(
                "pdf_link must be under "
                "'quotations/registered/pdf_files/<supplier>/' "
                f"(row {row_index})"
            ),
            status_code=422,
        )

    supplier_in_path = parts[3]
    if supplier_in_path != supplier_name and supplier_in_path.lower() != supplier_name.lower():
        raise AppError(
            code="INVALID_CSV",
            message=(
                f"pdf_link supplier folder '{supplier_in_path}' does not match "
                f"selected supplier '{supplier_name}' (row {row_index})"
            ),
            status_code=422,
        )

    filename = parts[4]
    if Path(filename).suffix.lower() != ".pdf":
        raise AppError(
            code="INVALID_CSV",
            message=f"pdf_link target must be a .pdf file (row {row_index})",
            status_code=422,
        )

    return f"quotations/registered/pdf_files/{supplier_name}/{filename}"


def _iter_order_csv_files(roots: QuotationRoots) -> list[Path]:
    files: list[Path] = []
    seen: set[str] = set()
    for base in (roots.unregistered_csv_root, roots.registered_csv_root):
        if not base.exists():
            continue
        for csv_file in sorted(base.rglob("*.csv"), key=lambda p: str(p).lower()):
            try:
                if csv_file.resolve().is_relative_to(roots.unregistered_missing_root.resolve()):
                    continue
            except Exception:
                pass
            key = str(csv_file.resolve()).casefold()
            if key in seen:
                continue
            seen.add(key)
            files.append(csv_file)
    return files


def _rewrite_order_csv_rows(
    roots: QuotationRoots,
    *,
    row_matcher: Any,
    row_updater: Any | None = None,
) -> dict[str, Any]:
    rewritten_files = 0
    updated_rows = 0
    deleted_rows = 0
    touched_files: list[str] = []

    for csv_file in _iter_order_csv_files(roots):
        with csv_file.open("r", encoding="utf-8-sig", newline="") as fp:
            reader = csv.DictReader(fp)
            fieldnames = list(reader.fieldnames or [])
            rows = list(reader)

        if not fieldnames:
            continue

        changed = False
        next_rows: list[dict[str, Any]] = []
        for row in rows:
            if not row_matcher(row):
                next_rows.append(row)
                continue
            changed = True
            if row_updater is None:
                deleted_rows += 1
                continue
            updated = row_updater(dict(row))
            if updated is None:
                deleted_rows += 1
                continue
            if updated != row:
                updated_rows += 1
            next_rows.append(updated)

        if not changed:
            continue

        with csv_file.open("w", encoding="utf-8", newline="") as fp:
            writer = csv.DictWriter(fp, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(next_rows)
        rewritten_files += 1
        touched_files.append(str(csv_file))

    return {
        "rewritten_files": rewritten_files,
        "updated_rows": updated_rows,
        "deleted_rows": deleted_rows,
        "files": touched_files,
    }


def _process_order_rows_for_import(
    conn: sqlite3.Connection,
    *,
    supplier_id: int,
    rows: list[dict[str, str]],
    default_order_date: str | None = None,
    allow_noncanonical_pdf_link: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    resolved: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    supplier_name_row = conn.execute(
        "SELECT name FROM suppliers WHERE supplier_id = ?",
        (supplier_id,),
    ).fetchone()
    supplier_name = supplier_name_row["name"] if supplier_name_row else str(supplier_id)
    normalized_default_date = normalize_optional_date(default_order_date, "default_order_date")
    for idx, row in enumerate(rows, start=2):
        if not any(str(value or "").strip() for value in row.values()):
            continue
        item_number = require_non_empty(str(row.get("item_number", "")), f"item_number (row {idx})")
        quantity_raw = row.get("quantity")
        try:
            ordered_quantity = require_positive_int(int(quantity_raw), f"quantity (row {idx})")
        except Exception as exc:  # noqa: BLE001
            raise AppError(
                code="INVALID_CSV",
                message=f"quantity must be an integer > 0 (row {idx})",
                status_code=422,
            ) from exc
        normalized_pdf_link = _normalize_manual_pdf_link(
            row.get("pdf_link"),
            supplier_name=supplier_name,
            row_index=idx,
            allow_noncanonical_path=allow_noncanonical_pdf_link,
        )
        item_id, units_per_order = _resolve_order_item(conn, supplier_id, item_number)
        if item_id is None:
            missing.append(
                {
                    "row": idx,
                    "item_number": item_number,
                    "supplier": supplier_name,
                    "manufacturer_name": "",
                    "resolution_type": "new_item",
                    "category": "",
                    "url": "",
                    "description": "",
                    "canonical_item_number": "",
                    "units_per_order": "",
                }
            )
            continue
        order_date = normalize_optional_date(row.get("order_date"), f"order_date (row {idx})")
        if order_date is None:
            order_date = normalized_default_date or today_jst()
        resolved.append(
            {
                "item_id": item_id,
                "quotation_number": require_non_empty(
                    str(row.get("quotation_number", "")),
                    f"quotation_number (row {idx})",
                ),
                "issue_date": normalize_optional_date(row.get("issue_date"), f"issue_date (row {idx})"),
                "pdf_link": normalized_pdf_link,
                "order_amount": ordered_quantity * units_per_order,
                "ordered_quantity": ordered_quantity,
                "ordered_item_number": item_number,
                "order_date": order_date,
                "expected_arrival": normalize_optional_date(
                    row.get("expected_arrival"),
                    f"expected_arrival (row {idx})",
                ),
            }
        )
    return resolved, missing


def import_orders_from_rows(
    conn: sqlite3.Connection,
    *,
    supplier_id: int | None = None,
    supplier_name: str | None = None,
    rows: list[dict[str, str]],
    default_order_date: str | None = None,
    source_name: str = "order_import.csv",
    missing_output_dir: str | Path | None = None,
    allow_noncanonical_pdf_link: bool = False,
) -> dict[str, Any]:
    sid = _resolve_supplier_id(conn, supplier_id, supplier_name)
    resolved, missing = _process_order_rows_for_import(
        conn,
        supplier_id=sid,
        rows=rows,
        default_order_date=default_order_date,
        allow_noncanonical_pdf_link=allow_noncanonical_pdf_link,
    )
    if missing:
        missing_csv_path = _write_missing_items_csv(
            missing,
            source_name=source_name,
            output_dir=missing_output_dir,
        )
        return {
            "status": "missing_items",
            "missing_count": len(missing),
            "missing_csv_path": missing_csv_path,
            "rows": missing,
        }

    quotation_numbers = sorted({str(row["quotation_number"]).strip() for row in resolved if str(row["quotation_number"]).strip()})
    if quotation_numbers:
        placeholders = ",".join("?" for _ in quotation_numbers)
        duplicate_rows = conn.execute(
            f"""
            SELECT q.quotation_number
            FROM quotations q
            WHERE q.supplier_id = ?
              AND q.quotation_number IN ({placeholders})
              AND EXISTS (
                SELECT 1
                FROM orders o
                WHERE o.quotation_id = q.quotation_id
              )
            ORDER BY q.quotation_number
            """,
            (sid, *quotation_numbers),
        ).fetchall()
        if duplicate_rows:
            duplicated = [str(row["quotation_number"]) for row in duplicate_rows]
            raise AppError(
                code="DUPLICATE_QUOTATION_IMPORT",
                message=(
                    "Quotation already imported for this supplier: "
                    f"{', '.join(duplicated)}"
                ),
                status_code=409,
                details={"quotation_numbers": duplicated},
            )

    order_ids: list[int] = []
    for row in resolved:
        quotation_id = _get_or_create_quotation(
            conn,
            sid,
            row["quotation_number"],
            row["issue_date"],
            row["pdf_link"],
        )
        cur = conn.execute(
            """
            INSERT INTO orders (
                item_id,
                quotation_id,
                order_amount,
                ordered_quantity,
                ordered_item_number,
                order_date,
                expected_arrival,
                status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'Ordered')
            """,
            (
                row["item_id"],
                quotation_id,
                row["order_amount"],
                row["ordered_quantity"],
                row["ordered_item_number"],
                row["order_date"],
                row["expected_arrival"],
            ),
        )
        order_ids.append(int(cur.lastrowid))
    return {"status": "ok", "imported_count": len(order_ids), "order_ids": order_ids}


def import_orders_from_content(
    conn: sqlite3.Connection,
    *,
    supplier_id: int | None = None,
    supplier_name: str | None = None,
    content: bytes,
    default_order_date: str | None = None,
    source_name: str = "order_import.csv",
    missing_output_dir: str | Path | None = None,
) -> dict[str, Any]:
    rows = _load_csv_rows_from_content(content)
    return import_orders_from_rows(
        conn,
        supplier_id=supplier_id,
        supplier_name=supplier_name,
        rows=rows,
        default_order_date=default_order_date,
        source_name=source_name,
        missing_output_dir=missing_output_dir,
    )


def import_orders_from_csv_path(
    conn: sqlite3.Connection,
    *,
    supplier_name: str,
    csv_path: str | Path,
    default_order_date: str | None = None,
    missing_output_dir: str | Path | None = None,
) -> dict[str, Any]:
    rows = _load_csv_rows_from_path(csv_path)
    return import_orders_from_rows(
        conn,
        supplier_name=supplier_name,
        rows=rows,
        default_order_date=default_order_date,
        source_name=Path(csv_path).name,
        missing_output_dir=missing_output_dir,
    )


def register_unregistered_missing_items_csvs(
    conn: sqlite3.Connection,
    *,
    unregistered_root: str | Path | None = None,
    registered_root: str | Path | None = None,
    continue_on_error: bool = False,
) -> dict[str, Any]:
    roots = build_roots(
        unregistered_root=unregistered_root,
        registered_root=registered_root,
    )
    ensure_roots(roots)

    files = iter_unregistered_missing_csvs(roots)
    report: list[dict[str, Any]] = []
    processed = 0
    succeeded = 0
    failed = 0
    warnings: list[str] = []
    normalizations: list[dict[str, str]] = []

    for csv_path in files:
        processed += 1
        supplier_name = "UNKNOWN"
        file_warnings: list[str] = []
        try:
            if csv_path.resolve().is_relative_to(roots.unregistered_missing_root.resolve()):
                supplier_name = "UNKNOWN"
                supplier_warnings = [
                    "Consolidated missing-item register detected; registered archive folder uses UNKNOWN."
                ]
            else:
                supplier_name, supplier_warnings = _supplier_name_from_unregistered_path(csv_path, roots)
            for warning in supplier_warnings:
                if warning not in file_warnings:
                    file_warnings.append(warning)
                if warning not in warnings:
                    warnings.append(warning)
            savepoint = f"sp_register_missing_{uuid4().hex}"
            conn.execute(f"SAVEPOINT {savepoint}")
            try:
                result = register_missing_items_from_csv_path(conn, csv_path)
                moved_to = _move_file_preserve_name(
                    csv_path,
                    registered_csv_supplier_dir(roots, supplier_name),
                )
                conn.execute(f"RELEASE {savepoint}")
            except Exception:
                conn.execute(f"ROLLBACK TO {savepoint}")
                conn.execute(f"RELEASE {savepoint}")
                raise
            succeeded += 1
            report.append(
                {
                    "file": str(csv_path),
                    "supplier": supplier_name,
                    "status": "ok",
                    "moved_to": str(moved_to),
                    "result": result,
                    "warnings": file_warnings,
                    "normalizations": [],
                }
            )
        except Exception as exc:  # noqa: BLE001
            failed += 1
            report.append(
                {
                    "file": str(csv_path),
                    "supplier": supplier_name,
                    "status": "error",
                    "error": str(exc),
                    "warnings": file_warnings,
                    "normalizations": [],
                }
            )
            if not continue_on_error:
                break

    status = "ok" if failed == 0 else ("partial" if succeeded > 0 else "error")
    return {
        "status": status,
        "processed": processed,
        "succeeded": succeeded,
        "failed": failed,
        "files": report,
        "warnings": warnings,
        "normalizations": normalizations,
    }


def _import_unregistered_order_csv_file(
    conn: sqlite3.Connection,
    *,
    roots: QuotationRoots,
    csv_path: Path,
    supplier_name: str,
    default_order_date: str | None = None,
) -> dict[str, Any]:
    rows = _load_csv_rows_from_path(csv_path)
    result = import_orders_from_rows(
        conn,
        supplier_name=supplier_name,
        rows=rows,
        default_order_date=default_order_date,
        source_name=f"{_safe_filename_component(supplier_name)}__{csv_path.name}",
        missing_output_dir=roots.unregistered_missing_root,
        allow_noncanonical_pdf_link=True,
    )
    file_warnings: list[str] = []
    file_normalizations: list[dict[str, str]] = []

    if result["status"] == "missing_items":
        return {
            "file": str(csv_path),
            "supplier": supplier_name,
            "status": "missing_items",
            "missing_count": result.get("missing_count", 0),
            "missing_csv_path": result.get("missing_csv_path"),
            "missing_rows": result.get("rows", []),
            "warnings": file_warnings,
            "normalizations": file_normalizations,
        }

    supplier_id = _get_or_create_supplier(conn, supplier_name)
    pdf_updates: list[dict[str, str]] = []
    pdf_cache: dict[tuple[str, str], str] = {}
    planned_pdf_moves: list[tuple[Path, Path]] = []
    planned_pdf_target_by_source: dict[str, Path] = {}
    reserved_pdf_targets: set[str] = set()
    registered_pdf_dir = registered_pdf_supplier_dir(roots, supplier_name).resolve()

    for row in rows:
        quotation_number = (row.get("quotation_number") or "").strip()
        pdf_link = (row.get("pdf_link") or "").strip()
        if not quotation_number or not pdf_link:
            continue
        cache_key = (quotation_number, pdf_link)
        normalized_pdf_link = pdf_cache.get(cache_key)
        if normalized_pdf_link is None:
            source_pdf, normalized_pdf_link, link_normalizations, link_warnings = _resolve_pdf_source_path(
                csv_path,
                pdf_link,
                roots,
                supplier_name,
            )
            for warning in link_warnings:
                if warning not in file_warnings:
                    file_warnings.append(warning)
            for entry in link_normalizations:
                item = dict(entry)
                item.setdefault("file", str(csv_path))
                item.setdefault("quotation_number", quotation_number)
                if item not in file_normalizations:
                    file_normalizations.append(item)
            if source_pdf is not None and source_pdf.exists():
                resolved_source = source_pdf.resolve()
                if resolved_source.is_relative_to(registered_pdf_dir):
                    final_pdf = resolved_source
                else:
                    source_key = str(resolved_source).casefold()
                    planned_target = planned_pdf_target_by_source.get(source_key)
                    if planned_target is None:
                        predicted_target, _ = _predict_move_target(
                            resolved_source,
                            registered_pdf_dir,
                            reserved_pdf_targets,
                        )
                        planned_target = predicted_target.resolve()
                        planned_pdf_target_by_source[source_key] = planned_target
                        planned_pdf_moves.append((resolved_source, planned_target))
                        reserved_pdf_targets.add(str(planned_target).casefold())
                    final_pdf = planned_target
                normalized_pdf_link = _safe_workspace_relative(final_pdf)
            pdf_cache[cache_key] = normalized_pdf_link
        conn.execute(
            """
            UPDATE quotations
            SET pdf_link = ?
            WHERE supplier_id = ? AND quotation_number = ?
            """,
            (normalized_pdf_link, supplier_id, quotation_number),
        )
        pdf_updates.append(
            {
                "quotation_number": quotation_number,
                "pdf_link": normalized_pdf_link,
            }
        )

    csv_source = csv_path.resolve()
    csv_dest, _ = _predict_move_target(
        csv_source,
        registered_csv_supplier_dir(roots, supplier_name).resolve(),
        set(),
    )
    _execute_planned_file_moves([*planned_pdf_moves, (csv_source, csv_dest.resolve())])
    return {
        "file": str(csv_path),
        "supplier": supplier_name,
        "status": "ok",
        "moved_to": str(csv_dest),
        "imported_count": result.get("imported_count", 0),
        "pdf_updates": pdf_updates,
        "warnings": file_warnings,
        "normalizations": file_normalizations,
    }


def _validate_retry_unregistered_csv_path(csv_path: str | Path, roots: QuotationRoots) -> Path:
    return validate_retry_unregistered_csv_path(csv_path, roots=roots)


def retry_unregistered_order_csv(
    conn: sqlite3.Connection,
    *,
    csv_path: str | Path,
    unregistered_root: str | Path | None = None,
    registered_root: str | Path | None = None,
    default_order_date: str | None = None,
) -> dict[str, Any]:
    roots = build_roots(
        unregistered_root=unregistered_root,
        registered_root=registered_root,
    )
    ensure_roots(roots)

    validated_csv = _validate_retry_unregistered_csv_path(csv_path, roots)
    supplier_name, supplier_warnings = _supplier_name_from_unregistered_path(validated_csv, roots)

    savepoint = f"sp_retry_unreg_{uuid4().hex}"
    conn.execute(f"SAVEPOINT {savepoint}")
    try:
        report = _import_unregistered_order_csv_file(
            conn,
            roots=roots,
            csv_path=validated_csv,
            supplier_name=supplier_name,
            default_order_date=default_order_date,
        )
        conn.execute(f"RELEASE {savepoint}")
        file_warnings = report.setdefault("warnings", [])
        for warning in supplier_warnings:
            if warning not in file_warnings:
                file_warnings.append(warning)
        report.setdefault("normalizations", [])
        return report
    except Exception as exc:  # noqa: BLE001
        conn.execute(f"ROLLBACK TO {savepoint}")
        conn.execute(f"RELEASE {savepoint}")
        return {
            "file": str(validated_csv),
            "supplier": supplier_name,
            "status": "error",
            "error": str(exc),
            "warnings": supplier_warnings,
            "normalizations": [],
        }


def import_unregistered_order_csvs(
    conn: sqlite3.Connection,
    *,
    unregistered_root: str | Path | None = None,
    registered_root: str | Path | None = None,
    default_order_date: str | None = None,
    continue_on_error: bool = False,
) -> dict[str, Any]:
    roots = build_roots(
        unregistered_root=unregistered_root,
        registered_root=registered_root,
    )
    ensure_roots(roots)

    files = iter_unregistered_order_csvs(roots)
    report: list[dict[str, Any]] = []
    processed = 0
    succeeded = 0
    missing_items = 0
    failed = 0
    warnings: list[str] = []
    normalizations: list[dict[str, str]] = []
    missing_reports: list[dict[str, Any]] = []

    for csv_path in files:
        processed += 1
        supplier_name = "UNKNOWN"
        supplier_warnings: list[str] = []
        try:
            supplier_name, supplier_warnings = _supplier_name_from_unregistered_path(csv_path, roots)
            for warning in supplier_warnings:
                if warning not in warnings:
                    warnings.append(warning)
            savepoint = f"sp_unreg_batch_{uuid4().hex}"
            conn.execute(f"SAVEPOINT {savepoint}")
            try:
                file_report = _import_unregistered_order_csv_file(
                    conn,
                    roots=roots,
                    csv_path=csv_path,
                    supplier_name=supplier_name,
                    default_order_date=default_order_date,
                )
                conn.execute(f"RELEASE {savepoint}")
            except Exception:
                conn.execute(f"ROLLBACK TO {savepoint}")
                conn.execute(f"RELEASE {savepoint}")
                raise

            if file_report["status"] == "missing_items":
                missing_items += 1
                missing_reports.append(file_report)
            elif file_report["status"] == "ok":
                succeeded += 1
            else:
                failed += 1
            file_report_warnings = file_report.setdefault("warnings", [])
            for warning in supplier_warnings:
                if warning not in file_report_warnings:
                    file_report_warnings.append(warning)
            for warning in file_report_warnings:
                if warning not in warnings:
                    warnings.append(warning)
            for entry in file_report.get("normalizations", []):
                if entry not in normalizations:
                    normalizations.append(entry)
            report.append(file_report)
        except Exception as exc:  # noqa: BLE001
            failed += 1
            for warning in supplier_warnings:
                if warning not in warnings:
                    warnings.append(warning)
            report.append(
                {
                    "file": str(csv_path),
                    "supplier": supplier_name,
                    "status": "error",
                    "error": str(exc),
                    "warnings": supplier_warnings,
                    "normalizations": [],
                }
            )
            if not continue_on_error:
                break

    batch_missing_csv_path: str | None = None
    if missing_reports:
        batch_missing_csv_path = _write_batch_missing_items_register(
            missing_reports,
            output_dir=roots.unregistered_missing_root,
        )
        for item in missing_reports:
            per_file_path = item.get("missing_csv_path")
            if per_file_path:
                try:
                    Path(per_file_path).unlink(missing_ok=True)
                except OSError as exc:
                    warning = f"Failed to remove temporary missing-items CSV {per_file_path}: {exc}"
                    file_warnings = item.setdefault("warnings", [])
                    if warning not in file_warnings:
                        file_warnings.append(warning)
                    if warning not in warnings:
                        warnings.append(warning)
            item["missing_csv_path"] = batch_missing_csv_path

    status = "ok" if failed == 0 else ("partial" if (succeeded or missing_items) else "error")
    return {
        "status": status,
        "processed": processed,
        "succeeded": succeeded,
        "missing_items": missing_items,
        "failed": failed,
        "files": report,
        "missing_items_register_csv": batch_missing_csv_path,
        "warnings": warnings,
        "normalizations": normalizations,
    }


def _predict_move_target(src: Path, dst_dir: Path, reserved_targets: set[str]) -> tuple[Path, bool]:
    target = dst_dir / src.name
    target_key = str(target).casefold()
    if target_key not in reserved_targets and not target.exists():
        return target, False

    stem = src.stem
    suffix = src.suffix
    idx = 1
    while True:
        candidate = dst_dir / f"{stem}_{idx}{suffix}"
        candidate_key = str(candidate).casefold()
        if candidate_key not in reserved_targets and not candidate.exists():
            return candidate, True
        idx += 1


def migrate_quotations_layout(
    conn: sqlite3.Connection,
    *,
    unregistered_root: str | Path | None = None,
    registered_root: str | Path | None = None,
    apply: bool = False,
) -> dict[str, Any]:
    roots = build_roots(
        unregistered_root=unregistered_root,
        registered_root=registered_root,
    )
    mode = "apply" if apply else "dry_run"
    if apply:
        ensure_roots(roots)

    warnings: list[str] = []
    normalizations: list[dict[str, str]] = []
    move_entries: list[dict[str, str]] = []
    csv_rewrite_entries: list[dict[str, str]] = []
    db_rewrite_entries: list[dict[str, str]] = []
    move_conflicts = 0
    moved_count = 0
    csv_apply_count = 0
    db_apply_count = 0

    reserved_targets: set[str] = set()
    roots_to_scan = [
        ("unregistered", roots.unregistered_root, roots.unregistered_csv_root, roots.unregistered_pdf_root),
        ("registered", roots.registered_root, roots.registered_csv_root, roots.registered_pdf_root),
    ]

    for scope, source_root, csv_target_root, pdf_target_root in roots_to_scan:
        if not source_root.exists():
            continue
        for child in sorted(source_root.iterdir(), key=lambda p: p.name):
            if not is_legacy_supplier_dir(child):
                continue
            supplier_name = child.name
            for src in sorted(child.rglob("*"), key=lambda p: str(p).lower()):
                if not src.is_file():
                    continue
                target_root = csv_target_root if src.suffix.lower() == ".csv" else pdf_target_root
                target_dir = target_root / supplier_name
                predicted_target, renamed = _predict_move_target(src, target_dir, reserved_targets)
                reserved_targets.add(str(predicted_target).casefold())
                if renamed:
                    move_conflicts += 1

                entry: dict[str, str] = {
                    "scope": scope,
                    "supplier": supplier_name,
                    "from": str(src),
                    "to": str(predicted_target),
                    "status": "planned",
                }
                if apply:
                    moved_to = _move_file_preserve_name(src, target_dir)
                    entry["to"] = str(moved_to)
                    entry["status"] = "moved"
                    moved_count += 1
                move_entries.append(entry)

    for csv_file in sorted(roots.unregistered_csv_root.rglob("*.csv"), key=lambda p: str(p).lower()):
        try:
            supplier_name, supplier_warnings = _supplier_name_from_unregistered_path(csv_file, roots)
            for warning in supplier_warnings:
                if warning not in warnings:
                    warnings.append(warning)
        except AppError as exc:
            text = str(exc)
            if text not in warnings:
                warnings.append(text)
            continue

        with csv_file.open("r", encoding="utf-8-sig", newline="") as fp:
            reader = csv.DictReader(fp)
            fieldnames = list(reader.fieldnames or [])
            rows = list(reader)

        if "pdf_link" not in fieldnames:
            continue

        changed = False
        for row_index, row in enumerate(rows, start=2):
            raw_link = (row.get("pdf_link") or "").strip()
            if not raw_link:
                continue
            source_pdf, normalized_link, link_normalizations, link_warnings = normalize_pdf_link(
                pdf_link=raw_link,
                supplier_name=supplier_name,
                roots=roots,
                csv_path=csv_file,
            )
            for warning in link_warnings:
                if warning not in warnings:
                    warnings.append(warning)
            for item in link_normalizations:
                norm = dict(item)
                norm.setdefault("file", str(csv_file))
                norm.setdefault("row", str(row_index))
                if norm not in normalizations:
                    normalizations.append(norm)

            canonical_link = normalized_link
            if source_pdf is not None and source_pdf.exists():
                canonical_link = _safe_workspace_relative(source_pdf)
            if canonical_link == raw_link:
                continue

            changed = True
            row["pdf_link"] = canonical_link
            csv_rewrite_entries.append(
                {
                    "file": str(csv_file),
                    "row": str(row_index),
                    "from": raw_link,
                    "to": canonical_link,
                    "status": "rewritten" if apply else "planned",
                }
            )

        if changed and apply:
            with csv_file.open("w", encoding="utf-8", newline="") as fp:
                writer = csv.DictWriter(fp, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
            csv_apply_count += 1

    quotation_rows = conn.execute(
        """
        SELECT
            q.quotation_id,
            q.pdf_link,
            s.name AS supplier_name
        FROM quotations q
        JOIN suppliers s ON s.supplier_id = q.supplier_id
        """
    ).fetchall()
    for row in quotation_rows:
        raw_link = (row["pdf_link"] or "").strip()
        if not raw_link:
            continue
        supplier_name = str(row["supplier_name"])
        source_pdf, normalized_link, link_normalizations, link_warnings = normalize_pdf_link(
            pdf_link=raw_link,
            supplier_name=supplier_name,
            roots=roots,
            csv_path=None,
        )
        for warning in link_warnings:
            if warning not in warnings:
                warnings.append(warning)
        for item in link_normalizations:
            norm = dict(item)
            norm.setdefault("quotation_id", str(row["quotation_id"]))
            if norm not in normalizations:
                normalizations.append(norm)

        canonical_link = normalized_link
        if source_pdf is not None and source_pdf.exists():
            canonical_link = _safe_workspace_relative(source_pdf)
        if canonical_link == raw_link:
            continue

        db_rewrite_entries.append(
            {
                "quotation_id": str(row["quotation_id"]),
                "supplier": supplier_name,
                "from": raw_link,
                "to": canonical_link,
                "status": "rewritten" if apply else "planned",
            }
        )
        if apply:
            conn.execute(
                "UPDATE quotations SET pdf_link = ? WHERE quotation_id = ?",
                (canonical_link, row["quotation_id"]),
            )
            db_apply_count += 1

    return {
        "status": "ok",
        "mode": mode,
        "planned_moves": len(move_entries),
        "moved": moved_count,
        "move_conflicts": move_conflicts,
        "moves": move_entries,
        "planned_csv_rewrites": len(csv_rewrite_entries),
        "csv_rewrites_applied": csv_apply_count,
        "csv_rewrites": csv_rewrite_entries,
        "planned_db_rewrites": len(db_rewrite_entries),
        "db_rewrites_applied": db_apply_count,
        "db_rewrites": db_rewrite_entries,
        "warnings": warnings,
        "normalizations": normalizations,
    }


def register_missing_items_from_rows(conn: sqlite3.Connection, rows: list[dict[str, str]]) -> dict[str, Any]:
    created_items = 0
    created_aliases = 0
    local_item_map: dict[tuple[int, str], int] = {}
    deferred_alias_rows: list[dict[str, str]] = []

    for row in rows:
        if not any(str(value or "").strip() for value in row.values()):
            continue
        supplier = require_non_empty(str(row.get("supplier", "")), "supplier")
        supplier_id = _get_or_create_supplier(conn, supplier)
        item_number = require_non_empty(str(row.get("item_number", "")), "item_number")
        resolution_type = (row.get("resolution_type") or "new_item").strip().lower()
        if resolution_type == "alias":
            deferred_alias_rows.append(row | {"_supplier_id": supplier_id, "_item_number": item_number})
            continue
        category_value = str(row.get("category") or "").strip()
        url_value = str(row.get("url") or "").strip()
        description_value = str(row.get("description") or "").strip()
        if not any((category_value, url_value, description_value)):
            raise AppError(
                code="MISSING_ITEM_UNRESOLVED",
                message=(
                    "new_item rows require at least one of category, url, or description. "
                    "Fill details before registering missing items."
                ),
                status_code=422,
                details={"supplier": supplier, "item_number": item_number},
            )

        manufacturer_name = str(
            row.get("manufacturer_name")
            or row.get("manufacturer")
            or ""
        ).strip() or "UNKNOWN"
        manufacturer_id = _get_or_create_manufacturer(conn, manufacturer_name)
        existing = conn.execute(
            """
            SELECT item_id
            FROM items_master
            WHERE manufacturer_id = ? AND item_number = ?
            """,
            (manufacturer_id, item_number),
        ).fetchone()
        if existing:
            item_id = int(existing["item_id"])
        else:
            cur = conn.execute(
                """
                INSERT INTO items_master (
                    item_number, manufacturer_id, category, url, description
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    item_number,
                    manufacturer_id,
                    category_value or None,
                    url_value or None,
                    description_value or None,
                ),
            )
            item_id = int(cur.lastrowid)
            created_items += 1
        local_item_map[(supplier_id, item_number)] = item_id

    for row in deferred_alias_rows:
        supplier_id = int(row["_supplier_id"])
        ordered_item_number = row["_item_number"]
        if _resolve_item_by_number(conn, ordered_item_number) is not None:
            raise AppError(
                code="ALIAS_CONFLICT_DIRECT_ITEM",
                message=(
                    f"ordered_item_number '{ordered_item_number}' matches an existing direct item_number; "
                    "alias would never be used"
                ),
                status_code=409,
            )
        canonical_item_number = require_non_empty(
            str(row.get("canonical_item_number", "")),
            "canonical_item_number",
        )
        units_per_order = int(row.get("units_per_order") or 1)
        require_positive_int(units_per_order, "units_per_order")
        canonical_item_id = local_item_map.get((supplier_id, canonical_item_number))
        if canonical_item_id is None:
            canonical_item_id = _resolve_item_by_number(conn, canonical_item_number)
        if canonical_item_id is None:
            raise AppError(
                code="CANONICAL_ITEM_NOT_FOUND",
                message=f"canonical_item_number '{canonical_item_number}' not found",
                status_code=422,
            )
        conn.execute(
            """
            INSERT INTO supplier_item_aliases (
                supplier_id,
                ordered_item_number,
                canonical_item_id,
                units_per_order,
                created_at
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (supplier_id, ordered_item_number)
            DO UPDATE SET
                canonical_item_id = excluded.canonical_item_id,
                units_per_order = excluded.units_per_order
            """,
            (supplier_id, ordered_item_number, canonical_item_id, units_per_order, now_jst_iso()),
        )
        created_aliases += 1

    return {"created_items": created_items, "created_aliases": created_aliases}


def register_missing_items_from_content(conn: sqlite3.Connection, content: bytes) -> dict[str, Any]:
    return register_missing_items_from_rows(conn, _load_csv_rows_from_content(content))


def register_missing_items_from_csv_path(conn: sqlite3.Connection, csv_path: str | Path) -> dict[str, Any]:
    return register_missing_items_from_rows(conn, _load_csv_rows_from_path(csv_path))


def process_order_arrival(
    conn: sqlite3.Connection,
    *,
    order_id: int,
    quantity: int | None = None,
) -> dict[str, Any]:
    order = get_order(conn, order_id)
    if order["status"] == "Arrived":
        raise AppError(
            code="ORDER_ALREADY_ARRIVED",
            message=f"Order {order_id} is already arrived",
            status_code=409,
        )
    order_amount = int(order["order_amount"])
    arrived_qty = order_amount if quantity is None else int(quantity)
    require_positive_int(arrived_qty, "quantity")
    if arrived_qty > order_amount:
        raise AppError(
            code="INVALID_ARRIVAL_QUANTITY",
            message="Arrival quantity cannot exceed open order_amount",
            status_code=422,
        )
    split_order_id: int | None = None
    if arrived_qty == order_amount:
        conn.execute(
            """
            UPDATE orders
            SET status = 'Arrived', arrival_date = ?
            WHERE order_id = ?
            """,
            (today_jst(), order_id),
        )
    else:
        original_ordered_qty = int(order["ordered_quantity"] or order_amount)
        arrived_ordered = original_ordered_qty * arrived_qty
        if arrived_ordered % order_amount != 0:
            raise AppError(
                code="PARTIAL_SPLIT_NOT_INTEGER_SAFE",
                message="Cannot split traceability quantities without fractional values",
                status_code=409,
            )
        arrived_ordered //= order_amount
        remaining_ordered = original_ordered_qty - arrived_ordered
        remaining_order_amount = order_amount - arrived_qty
        if arrived_ordered <= 0 or remaining_ordered <= 0 or remaining_order_amount <= 0:
            raise AppError(
                code="INVALID_PARTIAL_SPLIT",
                message="Partial arrival split would produce invalid quantities",
                status_code=409,
            )
        conn.execute(
            """
            UPDATE orders
            SET order_amount = ?, ordered_quantity = ?, status = 'Arrived', arrival_date = ?
            WHERE order_id = ?
            """,
            (arrived_qty, arrived_ordered, today_jst(), order_id),
        )
        cur = conn.execute(
            """
            INSERT INTO orders (
                item_id, quotation_id, order_amount, ordered_quantity, ordered_item_number,
                order_date, expected_arrival, arrival_date, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, 'Ordered')
            """,
            (
                order["item_id"],
                order["quotation_id"],
                remaining_order_amount,
                remaining_ordered,
                order["ordered_item_number"],
                order["order_date"],
                order["expected_arrival"],
            ),
        )
        split_order_id = int(cur.lastrowid)

    _apply_inventory_delta(conn, int(order["item_id"]), "STOCK", arrived_qty)
    log = _log_transaction(
        conn,
        operation_type="ARRIVAL",
        item_id=int(order["item_id"]),
        quantity=arrived_qty,
        from_location=None,
        to_location="STOCK",
        note=f"order_id={order_id}",
        batch_id=f"arrival-{order_id}",
    )
    return {
        "order_id": order_id,
        "arrived_quantity": arrived_qty,
        "split_order_id": split_order_id,
        "transaction": log,
    }


def list_quotations(
    conn: sqlite3.Connection,
    *,
    supplier: str | None = None,
    page: int = 1,
    per_page: int = 50,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if supplier:
        clauses.append("s.name = ?")
        params.append(supplier)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"""
        SELECT q.*, s.name AS supplier_name
        FROM quotations q
        JOIN suppliers s ON s.supplier_id = q.supplier_id
        {where}
        ORDER BY q.issue_date DESC, q.quotation_id DESC
    """
    return _paginate(conn, sql, tuple(params), page, per_page)


def update_quotation(conn: sqlite3.Connection, quotation_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    _get_entity_or_404(
        conn,
        "quotations",
        "quotation_id",
        quotation_id,
        "QUOTATION_NOT_FOUND",
        f"Quotation with id {quotation_id} not found",
    )
    next_issue_date = normalize_optional_date(payload.get("issue_date"), "issue_date")
    next_pdf_link = payload.get("pdf_link")
    conn.execute(
        """
        UPDATE quotations
        SET issue_date = COALESCE(?, issue_date),
            pdf_link = COALESCE(?, pdf_link)
        WHERE quotation_id = ?
        """,
        (
            next_issue_date,
            next_pdf_link,
            quotation_id,
        ),
    )
    row = conn.execute(
        """
        SELECT q.*, s.name AS supplier_name
        FROM quotations q
        JOIN suppliers s ON s.supplier_id = q.supplier_id
        WHERE q.quotation_id = ?
        """,
        (quotation_id,),
    ).fetchone()
    updated = dict(row)

    roots = build_roots()

    def _matcher(csv_row: dict[str, Any]) -> bool:
        return (
            str(csv_row.get("supplier") or "").strip() == str(updated.get("supplier_name") or "")
            and str(csv_row.get("quotation_number") or "").strip() == str(updated.get("quotation_number") or "")
        )

    def _updater(csv_row: dict[str, Any]) -> dict[str, Any]:
        if next_issue_date is not None:
            csv_row["issue_date"] = updated.get("issue_date") or ""
        if next_pdf_link is not None:
            csv_row["pdf_link"] = updated.get("pdf_link") or ""
        return csv_row

    _rewrite_order_csv_rows(roots, row_matcher=_matcher, row_updater=_updater)
    return updated


def delete_quotation(conn: sqlite3.Connection, quotation_id: int) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT q.*, s.name AS supplier_name
        FROM quotations q
        JOIN suppliers s ON s.supplier_id = q.supplier_id
        WHERE q.quotation_id = ?
        """,
        (quotation_id,),
    ).fetchone()
    if row is None:
        raise AppError(
            code="QUOTATION_NOT_FOUND",
            message=f"Quotation with id {quotation_id} not found",
            status_code=404,
        )

    arrived_count_row = conn.execute(
        "SELECT COUNT(*) AS c FROM orders WHERE quotation_id = ? AND status = 'Arrived'",
        (quotation_id,),
    ).fetchone()
    if int(arrived_count_row["c"] or 0) > 0:
        raise AppError(
            code="QUOTATION_HAS_ARRIVED_ORDERS",
            message="Quotations linked to arrived orders cannot be deleted",
            status_code=409,
        )

    conn.execute("DELETE FROM orders WHERE quotation_id = ?", (quotation_id,))
    conn.execute("DELETE FROM quotations WHERE quotation_id = ?", (quotation_id,))

    roots = build_roots()

    def _matcher(csv_row: dict[str, Any]) -> bool:
        return (
            str(csv_row.get("supplier") or "").strip() == str(row["supplier_name"] or "")
            and str(csv_row.get("quotation_number") or "").strip() == str(row["quotation_number"] or "")
        )

    csv_sync = _rewrite_order_csv_rows(roots, row_matcher=_matcher, row_updater=None)
    return {"deleted": True, "quotation_id": quotation_id, "csv_sync": csv_sync}


def list_reservations(
    conn: sqlite3.Connection,
    *,
    status: str | None = None,
    item_id: int | None = None,
    page: int = 1,
    per_page: int = 50,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if status:
        clauses.append("r.status = ?")
        params.append(status)
    if item_id:
        clauses.append("r.item_id = ?")
        params.append(item_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"""
        SELECT
            r.*,
            im.item_number,
            p.name AS project_name
        FROM reservations r
        JOIN items_master im ON im.item_id = r.item_id
        LEFT JOIN projects p ON p.project_id = r.project_id
        {where}
        ORDER BY r.created_at DESC, r.reservation_id DESC
    """
    return _paginate(conn, sql, tuple(params), page, per_page)


def get_reservation(conn: sqlite3.Connection, reservation_id: int) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT r.*, im.item_number, p.name AS project_name
        FROM reservations r
        JOIN items_master im ON im.item_id = r.item_id
        LEFT JOIN projects p ON p.project_id = r.project_id
        WHERE r.reservation_id = ?
        """,
        (reservation_id,),
    ).fetchone()
    if row is None:
        raise AppError(
            code="RESERVATION_NOT_FOUND",
            message=f"Reservation with id {reservation_id} not found",
            status_code=404,
        )
    return dict(row)


def create_reservation(conn: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    item_id = int(payload["item_id"])
    quantity = require_positive_int(int(payload["quantity"]), "quantity")
    _get_entity_or_404(
        conn,
        "items_master",
        "item_id",
        item_id,
        "ITEM_NOT_FOUND",
        f"Item with id {item_id} not found",
    )
    available_rows = _list_item_available_inventory(conn, item_id)
    total_available = sum(qty for _, qty in available_rows)
    if total_available < quantity:
        raise AppError(
            code="INSUFFICIENT_STOCK",
            message="Not enough available inventory for reservation",
            status_code=409,
            details={
                "item_id": item_id,
                "requested": quantity,
                "available": total_available,
            },
        )
    cur = conn.execute(
        """
        INSERT INTO reservations (
            item_id, quantity, purpose, deadline, created_at, status, note, project_id
        ) VALUES (?, ?, ?, ?, ?, 'ACTIVE', ?, ?)
        """,
        (
            item_id,
            quantity,
            payload.get("purpose"),
            normalize_optional_date(payload.get("deadline"), "deadline"),
            now_jst_iso(),
            payload.get("note"),
            payload.get("project_id"),
        ),
    )
    _log_transaction(
        conn,
        operation_type="RESERVE",
        item_id=item_id,
        quantity=quantity,
        from_location=None,
        to_location=None,
        note=payload.get("note") or payload.get("purpose"),
        batch_id=f"reservation-{cur.lastrowid}",
    )
    remaining_to_allocate = quantity
    for location, available in available_rows:
        if remaining_to_allocate <= 0:
            break
        allocated = min(available, remaining_to_allocate)
        conn.execute(
            """
            INSERT INTO reservation_allocations (
                reservation_id,
                item_id,
                location,
                quantity,
                status,
                created_at,
                note
            ) VALUES (?, ?, ?, ?, 'ACTIVE', ?, ?)
            """,
            (
                int(cur.lastrowid),
                item_id,
                location,
                allocated,
                now_jst_iso(),
                payload.get("note") or payload.get("purpose"),
            ),
        )
        remaining_to_allocate -= allocated
    return get_reservation(conn, int(cur.lastrowid))


def update_reservation(conn: sqlite3.Connection, reservation_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    reservation = get_reservation(conn, reservation_id)
    if reservation["status"] != "ACTIVE":
        raise AppError(
            code="RESERVATION_NOT_ACTIVE",
            message="Only ACTIVE reservations can be updated",
            status_code=409,
        )
    conn.execute(
        """
        UPDATE reservations
        SET purpose = COALESCE(?, purpose),
            deadline = COALESCE(?, deadline),
            note = COALESCE(?, note)
        WHERE reservation_id = ?
        """,
        (
            payload.get("purpose"),
            normalize_optional_date(payload.get("deadline"), "deadline"),
            payload.get("note"),
            reservation_id,
        ),
    )
    return get_reservation(conn, reservation_id)


def release_reservation(
    conn: sqlite3.Connection,
    reservation_id: int,
    *,
    quantity: int | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    reservation = get_reservation(conn, reservation_id)
    if reservation["status"] != "ACTIVE":
        raise AppError(
            code="RESERVATION_NOT_ACTIVE",
            message="Only ACTIVE reservations can be released",
            status_code=409,
        )
    reserved_quantity = int(reservation["quantity"])
    release_quantity = reserved_quantity if quantity is None else require_positive_int(int(quantity), "quantity")
    if release_quantity > reserved_quantity:
        raise AppError(
            code="INVALID_RESERVATION_QUANTITY",
            message="Release quantity cannot exceed remaining reservation quantity",
            status_code=422,
            details={
                "reservation_id": reservation_id,
                "requested": release_quantity,
                "remaining": reserved_quantity,
            },
        )
    item_id = int(reservation["item_id"])
    allocations = conn.execute(
        """
        SELECT allocation_id, quantity
        FROM reservation_allocations
        WHERE reservation_id = ? AND status = 'ACTIVE'
        ORDER BY allocation_id
        """,
        (reservation_id,),
    ).fetchall()
    allocatable_quantity = sum(int(alloc["quantity"]) for alloc in allocations)
    if allocatable_quantity < release_quantity:
        raise AppError(
            code="RESERVATION_ALLOCATION_INCONSISTENT",
            message="Active allocation quantity is insufficient to release requested amount",
            status_code=409,
            details={
                "reservation_id": reservation_id,
                "requested": release_quantity,
                "active_allocation_quantity": allocatable_quantity,
            },
        )
    remaining_to_release = release_quantity
    for alloc in allocations:
        if remaining_to_release <= 0:
            break
        alloc_qty = int(alloc["quantity"])
        consume_alloc = min(alloc_qty, remaining_to_release)
        left_qty = alloc_qty - consume_alloc
        if left_qty == 0:
            conn.execute(
                """
                UPDATE reservation_allocations
                SET status = 'RELEASED', released_at = ?, note = COALESCE(?, note)
                WHERE allocation_id = ?
                """,
                (now_jst_iso(), note, int(alloc["allocation_id"])),
            )
        else:
            conn.execute(
                "UPDATE reservation_allocations SET quantity = ? WHERE allocation_id = ?",
                (left_qty, int(alloc["allocation_id"])),
            )
            conn.execute(
                """
                INSERT INTO reservation_allocations (
                    reservation_id, item_id, location, quantity, status, created_at, released_at, note
                )
                SELECT reservation_id, item_id, location, ?, 'RELEASED', ?, ?, COALESCE(?, note)
                FROM reservation_allocations
                WHERE allocation_id = ?
                """,
                (consume_alloc, now_jst_iso(), now_jst_iso(), note, int(alloc["allocation_id"])),
            )
        remaining_to_release -= consume_alloc

    remaining = reserved_quantity - release_quantity
    if remaining == 0:
        conn.execute(
            """
            UPDATE reservations
            SET status = 'RELEASED', released_at = ?
            WHERE reservation_id = ?
            """,
            (now_jst_iso(), reservation_id),
        )
    else:
        conn.execute(
            """
            UPDATE reservations
            SET quantity = ?
            WHERE reservation_id = ?
            """,
            (remaining, reservation_id),
        )

    log_note = note or (
        f"release reservation {reservation_id}"
        if remaining == 0
        else f"partial release reservation {reservation_id} ({release_quantity}/{reserved_quantity})"
    )
    _log_transaction(
        conn,
        operation_type="RESERVE",
        item_id=item_id,
        quantity=release_quantity,
        from_location=None,
        to_location=None,
        note=log_note,
        batch_id=f"reservation-release-{reservation_id}",
    )
    return get_reservation(conn, reservation_id)


def consume_reservation(
    conn: sqlite3.Connection,
    reservation_id: int,
    *,
    quantity: int | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    reservation = get_reservation(conn, reservation_id)
    if reservation["status"] != "ACTIVE":
        raise AppError(
            code="RESERVATION_NOT_ACTIVE",
            message="Only ACTIVE reservations can be consumed",
            status_code=409,
        )
    reserved_quantity = int(reservation["quantity"])
    consume_quantity = reserved_quantity if quantity is None else require_positive_int(int(quantity), "quantity")
    if consume_quantity > reserved_quantity:
        raise AppError(
            code="INVALID_RESERVATION_QUANTITY",
            message="Consume quantity cannot exceed remaining reservation quantity",
            status_code=422,
            details={
                "reservation_id": reservation_id,
                "requested": consume_quantity,
                "remaining": reserved_quantity,
            },
        )
    item_id = int(reservation["item_id"])
    allocations = conn.execute(
        """
        SELECT allocation_id, location, quantity
        FROM reservation_allocations
        WHERE reservation_id = ? AND status = 'ACTIVE'
        ORDER BY allocation_id
        """,
        (reservation_id,),
    ).fetchall()
    allocatable_quantity = sum(int(alloc["quantity"]) for alloc in allocations)
    if allocatable_quantity < consume_quantity:
        raise AppError(
            code="RESERVATION_ALLOCATION_INCONSISTENT",
            message="Active allocation quantity is insufficient to consume requested amount",
            status_code=409,
            details={
                "reservation_id": reservation_id,
                "requested": consume_quantity,
                "active_allocation_quantity": allocatable_quantity,
            },
        )
    remaining_to_consume = consume_quantity
    for alloc in allocations:
        if remaining_to_consume <= 0:
            break
        alloc_qty = int(alloc["quantity"])
        use_qty = min(alloc_qty, remaining_to_consume)
        _apply_inventory_delta(conn, item_id, str(alloc["location"]), -use_qty)
        left_qty = alloc_qty - use_qty
        if left_qty == 0:
            conn.execute(
                """
                UPDATE reservation_allocations
                SET status = 'CONSUMED', released_at = ?, note = COALESCE(?, note)
                WHERE allocation_id = ?
                """,
                (now_jst_iso(), note, int(alloc["allocation_id"])),
            )
        else:
            conn.execute(
                "UPDATE reservation_allocations SET quantity = ? WHERE allocation_id = ?",
                (left_qty, int(alloc["allocation_id"])),
            )
            conn.execute(
                """
                INSERT INTO reservation_allocations (
                    reservation_id, item_id, location, quantity, status, created_at, released_at, note
                )
                SELECT reservation_id, item_id, location, ?, 'CONSUMED', ?, ?, COALESCE(?, note)
                FROM reservation_allocations
                WHERE allocation_id = ?
                """,
                (use_qty, now_jst_iso(), now_jst_iso(), note, int(alloc["allocation_id"])),
            )
        remaining_to_consume -= use_qty

    remaining = reserved_quantity - consume_quantity
    if remaining == 0:
        conn.execute(
            """
            UPDATE reservations
            SET status = 'CONSUMED', released_at = ?
            WHERE reservation_id = ?
            """,
            (now_jst_iso(), reservation_id),
        )
    else:
        conn.execute(
            """
            UPDATE reservations
            SET quantity = ?
            WHERE reservation_id = ?
            """,
            (remaining, reservation_id),
        )

    log_note = note or (
        f"consume reservation {reservation_id}"
        if remaining == 0
        else f"partial consume reservation {reservation_id} ({consume_quantity}/{reserved_quantity})"
    )
    _log_transaction(
        conn,
        operation_type="CONSUME",
        item_id=item_id,
        quantity=consume_quantity,
        from_location=None,
        to_location=None,
        note=log_note,
        batch_id=f"reservation-consume-{reservation_id}",
    )
    return get_reservation(conn, reservation_id)


def batch_create_reservations(
    conn: sqlite3.Connection, reservations: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    created: list[dict[str, Any]] = []
    for payload in reservations:
        created.append(create_reservation(conn, payload))
    return created


def list_assemblies(
    conn: sqlite3.Connection, *, page: int = 1, per_page: int = 50
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    sql = """
        SELECT
            a.*,
            COUNT(ac.item_id) AS component_count
        FROM assemblies a
        LEFT JOIN assembly_components ac ON ac.assembly_id = a.assembly_id
        GROUP BY a.assembly_id
        ORDER BY a.name
    """
    return _paginate(conn, sql, (), page, per_page)


def get_assembly(conn: sqlite3.Connection, assembly_id: int) -> dict[str, Any]:
    assembly = _get_entity_or_404(
        conn,
        "assemblies",
        "assembly_id",
        assembly_id,
        "ASSEMBLY_NOT_FOUND",
        f"Assembly with id {assembly_id} not found",
    )
    components = conn.execute(
        """
        SELECT
            ac.assembly_id,
            ac.item_id,
            ac.quantity,
            im.item_number
        FROM assembly_components ac
        JOIN items_master im ON im.item_id = ac.item_id
        WHERE ac.assembly_id = ?
        ORDER BY im.item_number
        """,
        (assembly_id,),
    ).fetchall()
    data = dict(assembly)
    data["components"] = _rows_to_dict(components)
    return data


def create_assembly(conn: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    cur = conn.execute(
        """
        INSERT INTO assemblies (name, description, created_at)
        VALUES (?, ?, ?)
        """,
        (
            require_non_empty(payload["name"], "name"),
            payload.get("description"),
            now_jst_iso(),
        ),
    )
    assembly_id = int(cur.lastrowid)
    for component in payload.get("components", []):
        conn.execute(
            """
            INSERT INTO assembly_components (assembly_id, item_id, quantity)
            VALUES (?, ?, ?)
            """,
            (
                assembly_id,
                int(component["item_id"]),
                require_positive_int(int(component["quantity"]), "quantity"),
            ),
        )
    return get_assembly(conn, assembly_id)


def update_assembly(conn: sqlite3.Connection, assembly_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    _get_entity_or_404(
        conn,
        "assemblies",
        "assembly_id",
        assembly_id,
        "ASSEMBLY_NOT_FOUND",
        f"Assembly with id {assembly_id} not found",
    )
    updates: list[str] = []
    params: list[Any] = []
    if payload.get("name") is not None:
        updates.append("name = ?")
        params.append(require_non_empty(payload["name"], "name"))
    if "description" in payload:
        updates.append("description = ?")
        params.append(payload.get("description"))
    if updates:
        conn.execute(
            f"UPDATE assemblies SET {', '.join(updates)} WHERE assembly_id = ?",
            (*params, assembly_id),
        )
    if "components" in payload and payload["components"] is not None:
        conn.execute("DELETE FROM assembly_components WHERE assembly_id = ?", (assembly_id,))
        for component in payload["components"]:
            conn.execute(
                """
                INSERT INTO assembly_components (assembly_id, item_id, quantity)
                VALUES (?, ?, ?)
                """,
                (
                    assembly_id,
                    int(component["item_id"]),
                    require_positive_int(int(component["quantity"]), "quantity"),
                ),
            )
    return get_assembly(conn, assembly_id)


def delete_assembly(conn: sqlite3.Connection, assembly_id: int) -> None:
    _get_entity_or_404(
        conn,
        "assemblies",
        "assembly_id",
        assembly_id,
        "ASSEMBLY_NOT_FOUND",
        f"Assembly with id {assembly_id} not found",
    )
    conn.execute("DELETE FROM assemblies WHERE assembly_id = ?", (assembly_id,))


def get_assembly_locations(conn: sqlite3.Connection, assembly_id: int) -> list[dict[str, Any]]:
    _get_entity_or_404(
        conn,
        "assemblies",
        "assembly_id",
        assembly_id,
        "ASSEMBLY_NOT_FOUND",
        f"Assembly with id {assembly_id} not found",
    )
    rows = conn.execute(
        """
        SELECT *
        FROM location_assembly_usage
        WHERE assembly_id = ?
        ORDER BY location
        """,
        (assembly_id,),
    ).fetchall()
    return _rows_to_dict(rows)


def set_location_assemblies(
    conn: sqlite3.Connection,
    *,
    location: str,
    assignments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    normalized_location = require_non_empty(location, "location")
    conn.execute(
        "DELETE FROM location_assembly_usage WHERE location = ?",
        (normalized_location,),
    )
    for assignment in assignments:
        _get_entity_or_404(
            conn,
            "assemblies",
            "assembly_id",
            assignment["assembly_id"],
            "ASSEMBLY_NOT_FOUND",
            f"Assembly with id {assignment['assembly_id']} not found",
        )
        conn.execute(
            """
            INSERT INTO location_assembly_usage (
                location, assembly_id, quantity, note, updated_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                normalized_location,
                int(assignment["assembly_id"]),
                require_positive_int(int(assignment["quantity"]), "quantity"),
                assignment.get("note"),
                now_jst_iso(),
            ),
        )
    rows = conn.execute(
        """
        SELECT lau.*, a.name AS assembly_name
        FROM location_assembly_usage lau
        JOIN assemblies a ON a.assembly_id = lau.assembly_id
        WHERE lau.location = ?
        ORDER BY a.name
        """,
        (normalized_location,),
    ).fetchall()
    return _rows_to_dict(rows)


def list_locations(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT location, COUNT(*) AS item_count, SUM(quantity) AS total_quantity
        FROM inventory_ledger
        GROUP BY location
        ORDER BY location
        """
    ).fetchall()
    return _rows_to_dict(rows)


def inspect_location(conn: sqlite3.Connection, location: str) -> dict[str, Any]:
    normalized_location = require_non_empty(location, "location")
    inventory_rows = conn.execute(
        """
        SELECT
            il.item_id,
            im.item_number,
            il.location,
            il.quantity
        FROM inventory_ledger il
        JOIN items_master im ON im.item_id = il.item_id
        WHERE il.location = ?
        ORDER BY im.item_number
        """,
        (normalized_location,),
    ).fetchall()
    assembly_rows = conn.execute(
        """
        SELECT
            lau.assembly_id,
            a.name AS assembly_name,
            lau.quantity,
            lau.note,
            lau.updated_at
        FROM location_assembly_usage lau
        JOIN assemblies a ON a.assembly_id = lau.assembly_id
        WHERE lau.location = ?
        ORDER BY a.name
        """,
        (normalized_location,),
    ).fetchall()
    advisory_rows = conn.execute(
        """
        SELECT
            ac.item_id,
            im.item_number,
            SUM(lau.quantity * ac.quantity) AS advisory_quantity
        FROM location_assembly_usage lau
        JOIN assembly_components ac ON ac.assembly_id = lau.assembly_id
        JOIN items_master im ON im.item_id = ac.item_id
        WHERE lau.location = ?
        GROUP BY ac.item_id, im.item_number
        ORDER BY im.item_number
        """,
        (normalized_location,),
    ).fetchall()
    return {
        "location": normalized_location,
        "inventory": _rows_to_dict(inventory_rows),
        "assemblies": _rows_to_dict(assembly_rows),
        "advisory_components": _rows_to_dict(advisory_rows),
    }


def disassemble_location(conn: sqlite3.Connection, location: str) -> dict[str, Any]:
    normalized_location = require_non_empty(location, "location")
    moved: list[dict[str, Any]] = []
    if normalized_location != "STOCK":
        rows = conn.execute(
            """
            SELECT item_id, quantity
            FROM inventory_ledger
            WHERE location = ?
            """,
            (normalized_location,),
        ).fetchall()
        for row in rows:
            log = move_inventory(
                conn,
                item_id=int(row["item_id"]),
                quantity=int(row["quantity"]),
                from_location=normalized_location,
                to_location="STOCK",
                note=f"disassemble location {normalized_location}",
                batch_id=f"location-disassemble-{normalized_location}",
            )
            moved.append(log)
    deleted_usage = conn.execute(
        "DELETE FROM location_assembly_usage WHERE location = ?",
        (normalized_location,),
    ).rowcount
    return {
        "location": normalized_location,
        "moved_transactions": moved,
        "deleted_assembly_assignments": deleted_usage,
    }


def list_projects(
    conn: sqlite3.Connection, *, page: int = 1, per_page: int = 50
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    sql = """
        SELECT p.*, COUNT(pr.requirement_id) AS requirement_count
        FROM projects p
        LEFT JOIN project_requirements pr ON pr.project_id = p.project_id
        GROUP BY p.project_id
        ORDER BY p.created_at DESC
    """
    return _paginate(conn, sql, (), page, per_page)


def _list_project_requirements(conn: sqlite3.Connection, project_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
            pr.*,
            a.name AS assembly_name,
            im.item_number
        FROM project_requirements pr
        LEFT JOIN assemblies a ON a.assembly_id = pr.assembly_id
        LEFT JOIN items_master im ON im.item_id = pr.item_id
        WHERE pr.project_id = ?
        ORDER BY pr.requirement_id
        """,
        (project_id,),
    ).fetchall()
    return _rows_to_dict(rows)


def get_project(conn: sqlite3.Connection, project_id: int) -> dict[str, Any]:
    project = _get_entity_or_404(
        conn,
        "projects",
        "project_id",
        project_id,
        "PROJECT_NOT_FOUND",
        f"Project with id {project_id} not found",
    )
    data = dict(project)
    data["requirements"] = _list_project_requirements(conn, project_id)
    return data


def _replace_project_requirements(
    conn: sqlite3.Connection,
    project_id: int,
    requirements: list[dict[str, Any]],
) -> None:
    conn.execute("DELETE FROM project_requirements WHERE project_id = ?", (project_id,))
    for req in requirements:
        conn.execute(
            """
            INSERT INTO project_requirements (
                project_id, assembly_id, item_id, quantity, requirement_type, note, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                req.get("assembly_id"),
                req.get("item_id"),
                require_positive_int(int(req["quantity"]), "quantity"),
                req.get("requirement_type", "INITIAL"),
                req.get("note"),
                now_jst_iso(),
            ),
        )


def create_project(conn: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    cur = conn.execute(
        """
        INSERT INTO projects (name, description, status, planned_start, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            require_non_empty(payload["name"], "name"),
            payload.get("description"),
            payload.get("status", "PLANNING"),
            normalize_optional_date(payload.get("planned_start"), "planned_start"),
            now_jst_iso(),
            now_jst_iso(),
        ),
    )
    project_id = int(cur.lastrowid)
    if payload.get("requirements"):
        _replace_project_requirements(conn, project_id, payload["requirements"])
    return get_project(conn, project_id)


def update_project(conn: sqlite3.Connection, project_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    _get_entity_or_404(
        conn,
        "projects",
        "project_id",
        project_id,
        "PROJECT_NOT_FOUND",
        f"Project with id {project_id} not found",
    )
    updates: list[str] = []
    params: list[Any] = []
    for key in ("name", "description", "status"):
        if key in payload and payload[key] is not None:
            updates.append(f"{key} = ?")
            params.append(payload[key])
    if "planned_start" in payload:
        updates.append("planned_start = ?")
        params.append(normalize_optional_date(payload.get("planned_start"), "planned_start"))
    if updates:
        updates.append("updated_at = ?")
        params.append(now_jst_iso())
        conn.execute(
            f"UPDATE projects SET {', '.join(updates)} WHERE project_id = ?",
            (*params, project_id),
        )
    if "requirements" in payload and payload["requirements"] is not None:
        _replace_project_requirements(conn, project_id, payload["requirements"])
    return get_project(conn, project_id)


def delete_project(conn: sqlite3.Connection, project_id: int) -> None:
    _get_entity_or_404(
        conn,
        "projects",
        "project_id",
        project_id,
        "PROJECT_NOT_FOUND",
        f"Project with id {project_id} not found",
    )
    conn.execute("DELETE FROM projects WHERE project_id = ?", (project_id,))


def _expand_requirement_to_items(conn: sqlite3.Connection, requirement: dict[str, Any]) -> list[tuple[int, int]]:
    quantity = int(requirement["quantity"])
    if requirement.get("item_id"):
        return [(int(requirement["item_id"]), quantity)]
    assembly_id = int(requirement["assembly_id"])
    components = conn.execute(
        """
        SELECT item_id, quantity
        FROM assembly_components
        WHERE assembly_id = ?
        """,
        (assembly_id,),
    ).fetchall()
    return [(int(row["item_id"]), int(row["quantity"]) * quantity) for row in components]


def project_gap_analysis(conn: sqlite3.Connection, project_id: int) -> dict[str, Any]:
    project = get_project(conn, project_id)
    required_by_item: dict[int, int] = {}
    for requirement in project["requirements"]:
        for item_id, quantity in _expand_requirement_to_items(conn, requirement):
            required_by_item[item_id] = required_by_item.get(item_id, 0) + quantity

    rows: list[dict[str, Any]] = []
    for item_id, required_qty in sorted(required_by_item.items()):
        item = get_item(conn, item_id)
        available = _get_total_available_inventory(conn, item_id)
        shortage = max(0, required_qty - available)
        rows.append(
            {
                "item_id": item_id,
                "item_number": item["item_number"],
                "required_quantity": required_qty,
                "available_stock": available,
                "shortage": shortage,
            }
        )
    return {"project": project, "rows": rows}


def reserve_project_requirements(conn: sqlite3.Connection, project_id: int) -> dict[str, Any]:
    project = get_project(conn, project_id)
    analysis = project_gap_analysis(conn, project_id)
    created: list[dict[str, Any]] = []
    for row in analysis["rows"]:
        reserve_qty = min(int(row["required_quantity"]), int(row["available_stock"]))
        if reserve_qty <= 0:
            continue
        created.append(
            create_reservation(
                conn,
                {
                    "item_id": row["item_id"],
                    "quantity": reserve_qty,
                    "purpose": f"Project:{project['name']}",
                    "note": "Project requirement reservation",
                    "project_id": project_id,
                },
            )
        )
    return {"project_id": project_id, "created_reservations": created}


def analyze_bom_rows(conn: sqlite3.Connection, rows: list[dict[str, Any]]) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for row in rows:
        supplier_name = require_non_empty(row["supplier"], "supplier")
        supplier_id = _get_or_create_supplier(conn, supplier_name)
        item_number = require_non_empty(row["item_number"], "item_number")
        required_quantity = int(row["required_quantity"])
        if required_quantity < 0:
            raise AppError(
                code="INVALID_QUANTITY",
                message="required_quantity must be >= 0",
                status_code=422,
            )
        item_id, units = _resolve_order_item(conn, supplier_id, item_number)
        if item_id is None:
            results.append(
                {
                    "supplier": supplier_name,
                    "item_number": item_number,
                    "required_quantity": required_quantity,
                    "status": "missing_item",
                }
            )
            continue
        canonical_required = required_quantity * units
        available = _get_total_available_inventory(conn, item_id)
        shortage = max(0, canonical_required - available)
        item = get_item(conn, item_id)
        results.append(
            {
                "supplier": supplier_name,
                "ordered_item_number": item_number,
                "item_id": item_id,
                "canonical_item_number": item["item_number"],
                "required_quantity": canonical_required,
                "available_stock": available,
                "shortage": shortage,
                "status": "ok",
            }
        )
    return {"rows": results}


def reserve_bom_rows(
    conn: sqlite3.Connection,
    rows: list[dict[str, Any]],
    *,
    purpose: str | None = "BOM reserve",
    deadline: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    analysis = analyze_bom_rows(conn, rows)
    created: list[dict[str, Any]] = []
    for row in analysis["rows"]:
        if row.get("status") != "ok":
            continue
        reserve_qty = min(int(row["required_quantity"]), int(row["available_stock"]))
        if reserve_qty <= 0:
            continue
        created.append(
            create_reservation(
                conn,
                {
                    "item_id": row["item_id"],
                    "quantity": reserve_qty,
                    "purpose": purpose,
                    "deadline": deadline,
                    "note": note or "BOM reservation",
                },
            )
        )
    return {"analysis": analysis["rows"], "created_reservations": created}


def list_transactions(
    conn: sqlite3.Connection,
    *,
    item_id: int | None = None,
    batch_id: str | None = None,
    page: int = 1,
    per_page: int = 50,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if item_id is not None:
        clauses.append("t.item_id = ?")
        params.append(item_id)
    if batch_id is not None:
        clauses.append("t.batch_id = ?")
        params.append(batch_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"""
        SELECT
            t.*,
            im.item_number
        FROM transaction_log t
        JOIN items_master im ON im.item_id = t.item_id
        {where}
        ORDER BY t.timestamp DESC, t.log_id DESC
    """
    return _paginate(conn, sql, tuple(params), page, per_page)


def get_transaction(conn: sqlite3.Connection, log_id: int) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT
            t.*,
            im.item_number
        FROM transaction_log t
        JOIN items_master im ON im.item_id = t.item_id
        WHERE t.log_id = ?
        """,
        (log_id,),
    ).fetchone()
    if row is None:
        raise AppError(
            code="TRANSACTION_NOT_FOUND",
            message=f"Transaction {log_id} not found",
            status_code=404,
        )
    return dict(row)


def undo_transaction(conn: sqlite3.Connection, log_id: int, note: str | None = None) -> dict[str, Any]:
    original = get_transaction(conn, log_id)
    if int(original["is_undone"]) == 1:
        raise AppError(
            code="ALREADY_UNDONE",
            message=f"Transaction {log_id} has already been undone",
            status_code=409,
        )
    op_type = original["operation_type"]
    item_id = int(original["item_id"])
    qty = int(original["quantity"])
    applied_qty = qty
    undo_note = note or f"undo log_id={log_id}"

    if op_type == "MOVE":
        available = _get_inventory_quantity(conn, item_id, original["to_location"])
        if available <= 0:
            raise AppError(
                code="UNDO_NOT_POSSIBLE",
                message="No quantity available at destination for MOVE undo",
                status_code=409,
            )
        applied_qty = min(qty, available)
        _apply_inventory_delta(conn, item_id, original["to_location"], -applied_qty)
        _apply_inventory_delta(conn, item_id, original["from_location"], applied_qty)
        undo_log = _log_transaction(
            conn,
            operation_type="MOVE",
            item_id=item_id,
            quantity=applied_qty,
            from_location=original["to_location"],
            to_location=original["from_location"],
            note=undo_note,
            batch_id=f"undo-{log_id}",
            undo_of_log_id=log_id,
        )
    elif op_type == "ARRIVAL":
        available = _get_inventory_quantity(conn, item_id, "STOCK")
        if available <= 0:
            raise AppError(
                code="UNDO_NOT_POSSIBLE",
                message="No quantity available in STOCK for ARRIVAL undo",
                status_code=409,
            )
        applied_qty = min(qty, available)
        _apply_inventory_delta(conn, item_id, "STOCK", -applied_qty)
        undo_log = _log_transaction(
            conn,
            operation_type="CONSUME",
            item_id=item_id,
            quantity=applied_qty,
            from_location="STOCK",
            to_location=None,
            note=undo_note,
            batch_id=f"undo-{log_id}",
            undo_of_log_id=log_id,
        )
    elif op_type == "CONSUME":
        target = original["from_location"] or "STOCK"
        _apply_inventory_delta(conn, item_id, target, qty)
        undo_log = _log_transaction(
            conn,
            operation_type="ADJUST",
            item_id=item_id,
            quantity=qty,
            from_location=None,
            to_location=target,
            note=undo_note,
            batch_id=f"undo-{log_id}",
            undo_of_log_id=log_id,
        )
    elif op_type == "ADJUST":
        if original["to_location"] and not original["from_location"]:
            available = _get_inventory_quantity(conn, item_id, original["to_location"])
            if available <= 0:
                raise AppError(
                    code="UNDO_NOT_POSSIBLE",
                    message="No quantity available for ADJUST undo",
                    status_code=409,
                )
            applied_qty = min(qty, available)
            _apply_inventory_delta(conn, item_id, original["to_location"], -applied_qty)
            undo_log = _log_transaction(
                conn,
                operation_type="ADJUST",
                item_id=item_id,
                quantity=applied_qty,
                from_location=original["to_location"],
                to_location=None,
                note=undo_note,
                batch_id=f"undo-{log_id}",
                undo_of_log_id=log_id,
            )
        elif original["from_location"] and not original["to_location"]:
            _apply_inventory_delta(conn, item_id, original["from_location"], qty)
            undo_log = _log_transaction(
                conn,
                operation_type="ADJUST",
                item_id=item_id,
                quantity=qty,
                from_location=None,
                to_location=original["from_location"],
                note=undo_note,
                batch_id=f"undo-{log_id}",
                undo_of_log_id=log_id,
            )
        else:
            available = _get_inventory_quantity(conn, item_id, original["to_location"])
            if available <= 0:
                raise AppError(
                    code="UNDO_NOT_POSSIBLE",
                    message="No quantity available for ADJUST undo",
                    status_code=409,
                )
            applied_qty = min(qty, available)
            _apply_inventory_delta(conn, item_id, original["to_location"], -applied_qty)
            _apply_inventory_delta(conn, item_id, original["from_location"], applied_qty)
            undo_log = _log_transaction(
                conn,
                operation_type="MOVE",
                item_id=item_id,
                quantity=applied_qty,
                from_location=original["to_location"],
                to_location=original["from_location"],
                note=undo_note,
                batch_id=f"undo-{log_id}",
                undo_of_log_id=log_id,
            )
    elif op_type == "RESERVE":
        reservation_id: int | None = None
        batch_id = str(original["batch_id"] or "")
        if batch_id.startswith("reservation-"):
            tail = batch_id.removeprefix("reservation-")
            if tail.isdigit():
                reservation_id = int(tail)
        if reservation_id is None:
            raise AppError(
                code="UNDO_NOT_POSSIBLE",
                message="Unable to resolve reservation for RESERVE undo",
                status_code=409,
            )
        reservation = get_reservation(conn, reservation_id)
        if reservation["status"] != "ACTIVE":
            raise AppError(
                code="UNDO_NOT_POSSIBLE",
                message="Reservation is no longer ACTIVE for RESERVE undo",
                status_code=409,
            )
        conn.execute(
            """
            UPDATE reservation_allocations
            SET status = 'RELEASED', released_at = ?, note = ?
            WHERE reservation_id = ? AND status = 'ACTIVE'
            """,
            (now_jst_iso(), undo_note, reservation_id),
        )
        conn.execute(
            """
            UPDATE reservations
            SET status = 'RELEASED', released_at = ?
            WHERE reservation_id = ?
            """,
            (now_jst_iso(), reservation_id),
        )
        undo_log = _log_transaction(
            conn,
            operation_type="RESERVE",
            item_id=item_id,
            quantity=qty,
            from_location=None,
            to_location=None,
            note=undo_note,
            batch_id=f"undo-{log_id}",
            undo_of_log_id=log_id,
        )
    else:
        raise AppError(
            code="UNDO_NOT_SUPPORTED",
            message=f"Undo is not supported for operation_type={op_type}",
            status_code=422,
        )

    conn.execute(
        "UPDATE transaction_log SET is_undone = 1 WHERE log_id = ?",
        (log_id,),
    )
    return {"original_log_id": log_id, "undo_log": undo_log, "applied_quantity": applied_qty}


def dashboard_summary(conn: sqlite3.Connection, low_stock_threshold: int = 5) -> dict[str, Any]:
    today = today_jst()
    next_week = (datetime.fromisoformat(today) + timedelta(days=7)).date().isoformat()
    overdue_orders = _rows_to_dict(
        conn.execute(
            """
            SELECT
                o.order_id,
                o.expected_arrival,
                o.order_amount,
                im.item_number,
                s.name AS supplier_name
            FROM orders o
            JOIN items_master im ON im.item_id = o.item_id
            JOIN quotations q ON q.quotation_id = o.quotation_id
            JOIN suppliers s ON s.supplier_id = q.supplier_id
            WHERE o.status = 'Ordered'
              AND o.expected_arrival IS NOT NULL
              AND o.expected_arrival < ?
            ORDER BY o.expected_arrival ASC
            LIMIT 50
            """,
            (today,),
        ).fetchall()
    )
    expiring_reservations = _rows_to_dict(
        conn.execute(
            """
            SELECT
                r.reservation_id,
                r.deadline,
                r.quantity,
                im.item_number
            FROM reservations r
            JOIN items_master im ON im.item_id = r.item_id
            WHERE r.status = 'ACTIVE'
              AND r.deadline IS NOT NULL
              AND r.deadline <= ?
            ORDER BY r.deadline ASC
            LIMIT 50
            """,
            (next_week,),
        ).fetchall()
    )
    low_stock = _rows_to_dict(
        conn.execute(
            """
            SELECT
                il.item_id,
                im.item_number,
                il.quantity
            FROM inventory_ledger il
            JOIN items_master im ON im.item_id = il.item_id
            WHERE il.location = 'STOCK' AND il.quantity <= ?
            ORDER BY il.quantity ASC, im.item_number
            LIMIT 100
            """,
            (int(low_stock_threshold),),
        ).fetchall()
    )
    recent_activity = _rows_to_dict(
        conn.execute(
            """
            SELECT
                t.*,
                im.item_number
            FROM transaction_log t
            JOIN items_master im ON im.item_id = t.item_id
            ORDER BY t.timestamp DESC, t.log_id DESC
            LIMIT 20
            """
        ).fetchall()
    )
    return {
        "overdue_orders": overdue_orders,
        "expiring_reservations": expiring_reservations,
        "low_stock_alerts": low_stock,
        "recent_activity": recent_activity,
    }


def _build_inventory_state(conn: sqlite3.Connection) -> dict[tuple[int, str], int]:
    rows = conn.execute(
        "SELECT item_id, location, quantity FROM inventory_ledger"
    ).fetchall()
    return {(int(r["item_id"]), str(r["location"])): int(r["quantity"]) for r in rows}


def _state_apply(state: dict[tuple[int, str], int], key: tuple[int, str], delta: int) -> None:
    current = state.get(key, 0)
    updated = current + delta
    if updated <= 0:
        state.pop(key, None)
    else:
        state[key] = updated


def get_inventory_snapshot(
    conn: sqlite3.Connection,
    *,
    target_date: str | None = None,
    mode: str | None = None,
) -> dict[str, Any]:
    if target_date is None:
        target_date = today_jst()
    normalized_target = normalize_optional_date(target_date, "date")
    if normalized_target is None:
        normalized_target = today_jst()
    today = today_jst()
    effective_mode = mode or ("past" if normalized_target < today else "future")
    if effective_mode not in {"past", "future"}:
        raise AppError(
            code="INVALID_SNAPSHOT_MODE",
            message="mode must be one of: past, future",
            status_code=422,
        )

    state = _build_inventory_state(conn)
    if effective_mode == "past":
        rows = conn.execute(
            """
            SELECT *
            FROM transaction_log
            WHERE date(timestamp) > date(?)
            ORDER BY timestamp DESC, log_id DESC
            """,
            (normalized_target,),
        ).fetchall()
        for row in rows:
            item_id = int(row["item_id"])
            quantity = int(row["quantity"])
            op = row["operation_type"]
            from_location = row["from_location"]
            to_location = row["to_location"]
            if op == "MOVE":
                if to_location:
                    _state_apply(state, (item_id, to_location), -quantity)
                if from_location:
                    _state_apply(state, (item_id, from_location), quantity)
            elif op == "CONSUME":
                if from_location:
                    _state_apply(state, (item_id, from_location), quantity)
            elif op == "RESERVE":
                _state_apply(state, (item_id, "RESERVED"), -quantity)
                _state_apply(state, (item_id, "STOCK"), quantity)
            elif op == "ARRIVAL":
                _state_apply(state, (item_id, "STOCK"), -quantity)
            elif op == "ADJUST":
                if to_location and not from_location:
                    _state_apply(state, (item_id, to_location), -quantity)
                elif from_location and not to_location:
                    _state_apply(state, (item_id, from_location), quantity)
                elif to_location and from_location:
                    _state_apply(state, (item_id, to_location), -quantity)
                    _state_apply(state, (item_id, from_location), quantity)
    else:
        pending_orders = conn.execute(
            """
            SELECT item_id, SUM(order_amount) AS qty
            FROM orders
            WHERE status <> 'Arrived'
              AND expected_arrival IS NOT NULL
              AND date(expected_arrival) <= date(?)
            GROUP BY item_id
            """,
            (normalized_target,),
        ).fetchall()
        for row in pending_orders:
            _state_apply(state, (int(row["item_id"]), "STOCK"), int(row["qty"]))
        pending_consumption = conn.execute(
            """
            SELECT item_id, SUM(quantity) AS qty
            FROM reservations
            WHERE status = 'ACTIVE'
              AND deadline IS NOT NULL
              AND date(deadline) <= date(?)
            GROUP BY item_id
            """,
            (normalized_target,),
        ).fetchall()
        for row in pending_consumption:
            _state_apply(state, (int(row["item_id"]), "RESERVED"), -int(row["qty"]))

    if not state:
        return {"date": normalized_target, "mode": effective_mode, "rows": []}

    item_ids = sorted({item_id for item_id, _ in state.keys()})
    placeholder = ",".join("?" for _ in item_ids)
    item_map_rows = conn.execute(
        f"""
        SELECT
            im.item_id,
            im.item_number,
            m.name AS manufacturer_name,
            COALESCE(ca.canonical_category, im.category) AS category
        FROM items_master im
        JOIN manufacturers m ON m.manufacturer_id = im.manufacturer_id
        LEFT JOIN category_aliases ca ON ca.alias_category = im.category
        WHERE im.item_id IN ({placeholder})
        """,
        tuple(item_ids),
    ).fetchall()
    item_map = {int(row["item_id"]): dict(row) for row in item_map_rows}

    rows: list[dict[str, Any]] = []
    for (item_id, location), quantity in sorted(state.items(), key=lambda r: (r[0][1], r[0][0])):
        if quantity <= 0:
            continue
        item = item_map.get(item_id)
        rows.append(
            {
                "item_id": item_id,
                "item_number": item["item_number"] if item else None,
                "manufacturer_name": item["manufacturer_name"] if item else None,
                "category": item["category"] if item else None,
                "location": location,
                "quantity": quantity,
            }
        )
    return {"date": normalized_target, "mode": effective_mode, "rows": rows}


def list_manufacturers(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT manufacturer_id, name FROM manufacturers ORDER BY name"
    ).fetchall()
    return _rows_to_dict(rows)


def create_manufacturer(conn: sqlite3.Connection, name: str) -> dict[str, Any]:
    normalized = require_non_empty(name, "name")
    cur = conn.execute("INSERT INTO manufacturers (name) VALUES (?)", (normalized,))
    return to_dict(
        conn.execute(
            "SELECT manufacturer_id, name FROM manufacturers WHERE manufacturer_id = ?",
            (cur.lastrowid,),
        ).fetchone()
    ) or {}


def list_suppliers(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT supplier_id, name FROM suppliers ORDER BY name").fetchall()
    return _rows_to_dict(rows)


def create_supplier(conn: sqlite3.Connection, name: str) -> dict[str, Any]:
    normalized = require_non_empty(name, "name")
    cur = conn.execute("INSERT INTO suppliers (name) VALUES (?)", (normalized,))
    return to_dict(
        conn.execute(
            "SELECT supplier_id, name FROM suppliers WHERE supplier_id = ?",
            (cur.lastrowid,),
        ).fetchone()
    ) or {}


def list_supplier_item_aliases(conn: sqlite3.Connection, supplier_id: int) -> list[dict[str, Any]]:
    _get_entity_or_404(
        conn,
        "suppliers",
        "supplier_id",
        supplier_id,
        "SUPPLIER_NOT_FOUND",
        f"Supplier with id {supplier_id} not found",
    )
    rows = conn.execute(
        """
        SELECT
            a.alias_id,
            a.supplier_id,
            s.name AS supplier_name,
            a.ordered_item_number,
            a.canonical_item_id,
            im.item_number AS canonical_item_number,
            a.units_per_order,
            a.created_at
        FROM supplier_item_aliases a
        JOIN suppliers s ON s.supplier_id = a.supplier_id
        JOIN items_master im ON im.item_id = a.canonical_item_id
        WHERE a.supplier_id = ?
        ORDER BY a.ordered_item_number
        """,
        (supplier_id,),
    ).fetchall()
    return _rows_to_dict(rows)


def upsert_supplier_item_alias(
    conn: sqlite3.Connection,
    *,
    supplier_id: int,
    ordered_item_number: str,
    canonical_item_id: int | None = None,
    canonical_item_number: str | None = None,
    units_per_order: int = 1,
) -> dict[str, Any]:
    _get_entity_or_404(
        conn,
        "suppliers",
        "supplier_id",
        supplier_id,
        "SUPPLIER_NOT_FOUND",
        f"Supplier with id {supplier_id} not found",
    )
    if canonical_item_id is None:
        if canonical_item_number is None:
            raise AppError(
                code="INVALID_ALIAS",
                message="canonical_item_id or canonical_item_number is required",
                status_code=422,
            )
        canonical_item_id = _resolve_item_by_number(conn, canonical_item_number)
        if canonical_item_id is None:
            raise AppError(
                code="ITEM_NOT_FOUND",
                message=f"Canonical item '{canonical_item_number}' not found",
                status_code=404,
            )
    _get_entity_or_404(
        conn,
        "items_master",
        "item_id",
        canonical_item_id,
        "ITEM_NOT_FOUND",
        f"Item with id {canonical_item_id} not found",
    )
    normalized_item_number = require_non_empty(ordered_item_number, "ordered_item_number")
    if _resolve_item_by_number(conn, normalized_item_number) is not None:
        raise AppError(
            code="ALIAS_CONFLICT_DIRECT_ITEM",
            message=(
                f"ordered_item_number '{normalized_item_number}' matches an existing direct item_number; "
                "alias would never be used"
            ),
            status_code=409,
        )
    units = require_positive_int(units_per_order, "units_per_order")
    conn.execute(
        """
        INSERT INTO supplier_item_aliases (
            supplier_id, ordered_item_number, canonical_item_id, units_per_order, created_at
        ) VALUES (?, ?, ?, ?, ?)
        ON CONFLICT (supplier_id, ordered_item_number)
        DO UPDATE SET
            canonical_item_id = excluded.canonical_item_id,
            units_per_order = excluded.units_per_order
        """,
        (supplier_id, normalized_item_number, canonical_item_id, units, now_jst_iso()),
    )
    row = conn.execute(
        """
        SELECT
            a.alias_id,
            a.supplier_id,
            s.name AS supplier_name,
            a.ordered_item_number,
            a.canonical_item_id,
            im.item_number AS canonical_item_number,
            a.units_per_order,
            a.created_at
        FROM supplier_item_aliases a
        JOIN suppliers s ON s.supplier_id = a.supplier_id
        JOIN items_master im ON im.item_id = a.canonical_item_id
        WHERE a.supplier_id = ? AND a.ordered_item_number = ?
        """,
        (supplier_id, normalized_item_number),
    ).fetchone()
    return dict(row)


def delete_supplier_item_alias(conn: sqlite3.Connection, alias_id: int) -> None:
    row = conn.execute(
        "SELECT alias_id FROM supplier_item_aliases WHERE alias_id = ?",
        (alias_id,),
    ).fetchone()
    if row is None:
        raise AppError(
            code="ALIAS_NOT_FOUND",
            message=f"Alias with id {alias_id} not found",
            status_code=404,
        )
    conn.execute("DELETE FROM supplier_item_aliases WHERE alias_id = ?", (alias_id,))


def list_raw_categories(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        """
        SELECT DISTINCT category
        FROM items_master
        WHERE category IS NOT NULL AND trim(category) <> ''
        ORDER BY category
        """
    ).fetchall()
    return [str(row["category"]) for row in rows]


def list_category_aliases(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT alias_category, canonical_category, created_at, updated_at
        FROM category_aliases
        ORDER BY alias_category
        """
    ).fetchall()
    return _rows_to_dict(rows)


def list_categories(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        """
        SELECT DISTINCT COALESCE(ca.canonical_category, im.category) AS category
        FROM items_master im
        LEFT JOIN category_aliases ca ON ca.alias_category = im.category
        WHERE im.category IS NOT NULL AND trim(im.category) <> ''
        ORDER BY category
        """
    ).fetchall()
    return [str(row["category"]) for row in rows]


def get_category_usage(conn: sqlite3.Connection, category: str) -> dict[str, Any]:
    normalized = require_non_empty(category, "category")
    rows = conn.execute(
        """
        SELECT
            im.item_id,
            im.item_number,
            im.category AS raw_category,
            COALESCE(ca.canonical_category, im.category) AS effective_category
        FROM items_master im
        LEFT JOIN category_aliases ca ON ca.alias_category = im.category
        WHERE im.category = ? OR COALESCE(ca.canonical_category, im.category) = ?
        ORDER BY im.item_number
        """,
        (normalized, normalized),
    ).fetchall()
    return {"category": normalized, "items": _rows_to_dict(rows)}


def merge_category_alias(
    conn: sqlite3.Connection, source_category: str, target_category: str
) -> dict[str, Any]:
    source = require_non_empty(source_category, "alias_category")
    target = require_non_empty(target_category, "canonical_category")
    if source == target:
        raise AppError(
            code="INVALID_CATEGORY_ALIAS",
            message="alias_category and canonical_category must differ",
            status_code=422,
        )
    now = now_jst_iso()
    conn.execute(
        """
        INSERT INTO category_aliases (
            alias_category, canonical_category, created_at, updated_at
        ) VALUES (?, ?, ?, ?)
        ON CONFLICT (alias_category)
        DO UPDATE SET
            canonical_category = excluded.canonical_category,
            updated_at = excluded.updated_at
        """,
        (source, target, now, now),
    )
    row = conn.execute(
        """
        SELECT alias_category, canonical_category, created_at, updated_at
        FROM category_aliases
        WHERE alias_category = ?
        """,
        (source,),
    ).fetchone()
    return dict(row)


def remove_category_alias(conn: sqlite3.Connection, source_category: str) -> None:
    normalized = require_non_empty(source_category, "alias_category")
    row = conn.execute(
        "SELECT alias_category FROM category_aliases WHERE alias_category = ?",
        (normalized,),
    ).fetchone()
    if row is None:
        raise AppError(
            code="CATEGORY_ALIAS_NOT_FOUND",
            message=f"Category alias '{normalized}' not found",
            status_code=404,
        )
    conn.execute(
        "DELETE FROM category_aliases WHERE alias_category = ?",
        (normalized,),
    )


def rename_category(conn: sqlite3.Connection, source_category: str, target_category: str) -> dict[str, Any]:
    return merge_category_alias(conn, source_category, target_category)
