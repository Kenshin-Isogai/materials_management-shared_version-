from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys

import uvicorn

from app.api import create_app
from app.db import get_connection, init_db
from app import service


def _print(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _load_bom_rows(csv_path: str) -> list[dict[str, str]]:
    with Path(csv_path).open("r", encoding="utf-8-sig", newline="") as fp:
        return list(csv.DictReader(fp))


def _run_with_db(args: argparse.Namespace, fn) -> int:
    init_db(args.db)
    conn = get_connection(args.db)
    try:
        result = fn(conn)
        conn.commit()
        _print({"status": "ok", "data": result})
        return 0
    except Exception as exc:  # noqa: BLE001
        conn.rollback()
        _print({"status": "error", "error": {"message": str(exc)}})
        return 1
    finally:
        conn.close()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Optical Component Inventory Management CLI")
    parser.add_argument("--db", default=None, help="SQLite database path")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="Run FastAPI server")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)

    sub.add_parser("init-db", help="Initialize database")

    imp = sub.add_parser("import-orders", help="Import order CSV")
    imp.add_argument("--supplier", required=True)
    imp.add_argument("--csv-path", required=True)
    imp.add_argument("--default-order-date", default=None)

    miss = sub.add_parser("register-missing", help="Register missing items CSV")
    miss.add_argument("--csv-path", required=True)

    unreg_missing = sub.add_parser(
        "register-unregistered-missing",
        help="Batch register *_missing_items_registration.csv under unregistered root",
    )
    unreg_missing.add_argument("--unregistered-root", default=None)
    unreg_missing.add_argument("--registered-root", default=None)
    unreg_missing.add_argument("--continue-on-error", action="store_true")

    unreg_orders = sub.add_parser(
        "import-unregistered-orders",
        help="Batch import order CSV files under unregistered root",
    )
    unreg_orders.add_argument("--unregistered-root", default=None)
    unreg_orders.add_argument("--registered-root", default=None)
    unreg_orders.add_argument("--default-order-date", default=None)
    unreg_orders.add_argument("--continue-on-error", action="store_true")

    migrate_layout = sub.add_parser(
        "migrate-quotations-layout",
        help="Migrate quotations folders/links to canonical csv_files/pdf_files layout",
    )
    migrate_layout.add_argument("--unregistered-root", default=None)
    migrate_layout.add_argument("--registered-root", default=None)
    migrate_mode = migrate_layout.add_mutually_exclusive_group()
    migrate_mode.add_argument("--dry-run", action="store_true", help="Preview changes only (default)")
    migrate_mode.add_argument("--apply", action="store_true", help="Apply migration changes")

    arrival = sub.add_parser("arrival", help="Process order arrival")
    arrival.add_argument("--order-id", type=int, required=True)
    arrival.add_argument("--quantity", type=int, default=None)

    move = sub.add_parser("move", help="Move inventory")
    move.add_argument("--item-id", type=int, required=True)
    move.add_argument("--quantity", type=int, required=True)
    move.add_argument("--from-location", required=True)
    move.add_argument("--to-location", required=True)
    move.add_argument("--note", default=None)

    consume = sub.add_parser("consume", help="Consume inventory")
    consume.add_argument("--item-id", type=int, required=True)
    consume.add_argument("--quantity", type=int, required=True)
    consume.add_argument("--from-location", required=True)
    consume.add_argument("--note", default=None)

    reserve = sub.add_parser("reserve", help="Create reservation")
    reserve.add_argument("--item-id", type=int, required=True)
    reserve.add_argument("--quantity", type=int, required=True)
    reserve.add_argument("--purpose", default=None)
    reserve.add_argument("--deadline", default=None)
    reserve.add_argument("--note", default=None)
    reserve.add_argument("--project-id", type=int, default=None)

    list_res = sub.add_parser("list-reservations", help="List reservations")
    list_res.add_argument("--status", default=None)
    list_res.add_argument("--item-id", type=int, default=None)

    rel = sub.add_parser("release-reservation", help="Release reservation")
    rel.add_argument("--reservation-id", type=int, required=True)
    rel.add_argument("--quantity", type=int, default=None)
    rel.add_argument("--note", default=None)

    conr = sub.add_parser("consume-reservation", help="Consume reservation")
    conr.add_argument("--reservation-id", type=int, required=True)
    conr.add_argument("--quantity", type=int, default=None)
    conr.add_argument("--note", default=None)

    bom = sub.add_parser("bom-analyze", help="BOM gap analysis")
    bom.add_argument("--csv-path", required=True)
    bom.add_argument("--target-date", default=None, help="Optional date (YYYY-MM-DD) for future-arrival-aware analysis")

    bom_res = sub.add_parser("bom-reserve", help="Reserve BOM items")
    bom_res.add_argument("--csv-path", required=True)
    bom_res.add_argument("--purpose", default="BOM reserve")
    bom_res.add_argument("--deadline", default=None)
    bom_res.add_argument("--note", default=None)

    pc_list = sub.add_parser("list-purchase-candidates", help="List purchase candidates")
    pc_list.add_argument("--status", default=None)
    pc_list.add_argument("--source-type", default=None)
    pc_list.add_argument("--target-date", default=None)

    pc_bom = sub.add_parser("purchase-candidates-from-bom", help="Create purchase candidates from BOM shortage rows")
    pc_bom.add_argument("--csv-path", required=True)
    pc_bom.add_argument("--target-date", default=None)
    pc_bom.add_argument("--note", default=None)

    pc_project = sub.add_parser(
        "purchase-candidates-from-project",
        help="Create purchase candidates from project gap analysis",
    )
    pc_project.add_argument("--project-id", type=int, required=True)
    pc_project.add_argument("--target-date", default=None)
    pc_project.add_argument("--note", default=None)

    pc_update = sub.add_parser("update-purchase-candidate", help="Update purchase candidate")
    pc_update.add_argument("--candidate-id", type=int, required=True)
    pc_update.add_argument("--status", default=None)
    pc_update.add_argument("--note", default=None)

    search = sub.add_parser("search", help="Search items")
    search.add_argument("--q", default=None)
    search.add_argument("--category", default=None)
    search.add_argument("--manufacturer", default=None)

    loc_inspect = sub.add_parser("location-inspect", help="Inspect location")
    loc_inspect.add_argument("--location", required=True)

    loc_dis = sub.add_parser("location-disassemble", help="Disassemble location")
    loc_dis.add_argument("--location", required=True)

    asm_create = sub.add_parser("assembly-create", help="Create assembly")
    asm_create.add_argument("--name", required=True)
    asm_create.add_argument("--description", default=None)
    asm_create.add_argument(
        "--components",
        required=True,
        help='JSON array, e.g. [{"item_id":1,"quantity":2}]',
    )

    sub.add_parser("assembly-list", help="List assemblies")

    asm_show = sub.add_parser("assembly-show", help="Show assembly")
    asm_show.add_argument("--assembly-id", type=int, required=True)

    asm_del = sub.add_parser("assembly-delete", help="Delete assembly")
    asm_del.add_argument("--assembly-id", type=int, required=True)

    set_asm = sub.add_parser("location-set-assembly", help="Set location assembly usage")
    set_asm.add_argument("--location", required=True)
    set_asm.add_argument(
        "--assignments",
        required=True,
        help='JSON array, e.g. [{"assembly_id":1,"quantity":2}]',
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "serve":
        init_db(args.db)
        app = create_app(db_path=args.db)
        uvicorn.run(app, host=args.host, port=args.port)
        return 0

    if args.command == "init-db":
        resolved = init_db(args.db)
        _print({"status": "ok", "data": {"db_path": str(resolved)}})
        return 0

    if args.command == "import-orders":
        return _run_with_db(
            args,
            lambda conn: service.import_orders_from_csv_path(
                conn,
                supplier_name=args.supplier,
                csv_path=args.csv_path,
                default_order_date=args.default_order_date,
            ),
        )

    if args.command == "register-missing":
        return _run_with_db(
            args,
            lambda conn: service.register_missing_items_from_csv_path(conn, args.csv_path),
        )

    if args.command == "register-unregistered-missing":
        return _run_with_db(
            args,
            lambda conn: service.register_unregistered_missing_items_csvs(
                conn,
                unregistered_root=args.unregistered_root,
                registered_root=args.registered_root,
                continue_on_error=args.continue_on_error,
            ),
        )

    if args.command == "import-unregistered-orders":
        return _run_with_db(
            args,
            lambda conn: service.import_unregistered_order_csvs(
                conn,
                unregistered_root=args.unregistered_root,
                registered_root=args.registered_root,
                default_order_date=args.default_order_date,
                continue_on_error=args.continue_on_error,
            ),
        )

    if args.command == "migrate-quotations-layout":
        return _run_with_db(
            args,
            lambda conn: service.migrate_quotations_layout(
                conn,
                unregistered_root=args.unregistered_root,
                registered_root=args.registered_root,
                apply=bool(args.apply),
            ),
        )

    if args.command == "arrival":
        return _run_with_db(
            args,
            lambda conn: service.process_order_arrival(
                conn,
                order_id=args.order_id,
                quantity=args.quantity,
            ),
        )

    if args.command == "move":
        return _run_with_db(
            args,
            lambda conn: service.move_inventory(
                conn,
                item_id=args.item_id,
                quantity=args.quantity,
                from_location=args.from_location,
                to_location=args.to_location,
                note=args.note,
            ),
        )

    if args.command == "consume":
        return _run_with_db(
            args,
            lambda conn: service.consume_inventory(
                conn,
                item_id=args.item_id,
                quantity=args.quantity,
                from_location=args.from_location,
                note=args.note,
            ),
        )

    if args.command == "reserve":
        return _run_with_db(
            args,
            lambda conn: service.create_reservation(
                conn,
                {
                    "item_id": args.item_id,
                    "quantity": args.quantity,
                    "purpose": args.purpose,
                    "deadline": args.deadline,
                    "note": args.note,
                    "project_id": args.project_id,
                },
            ),
        )

    if args.command == "list-reservations":
        return _run_with_db(
            args,
            lambda conn: service.list_reservations(
                conn,
                status=args.status,
                item_id=args.item_id,
                page=1,
                per_page=1000,
            )[0],
        )

    if args.command == "release-reservation":
        return _run_with_db(
            args,
            lambda conn: service.release_reservation(
                conn,
                args.reservation_id,
                quantity=args.quantity,
                note=args.note,
            ),
        )

    if args.command == "consume-reservation":
        return _run_with_db(
            args,
            lambda conn: service.consume_reservation(
                conn,
                args.reservation_id,
                quantity=args.quantity,
                note=args.note,
            ),
        )

    if args.command == "bom-analyze":
        rows = _load_bom_rows(args.csv_path)
        return _run_with_db(
            args,
            lambda conn: service.analyze_bom_rows(conn, rows, target_date=args.target_date),
        )

    if args.command == "bom-reserve":
        rows = _load_bom_rows(args.csv_path)
        return _run_with_db(
            args,
            lambda conn: service.reserve_bom_rows(
                conn,
                rows,
                purpose=args.purpose,
                deadline=args.deadline,
                note=args.note,
            ),
        )

    if args.command == "list-purchase-candidates":
        return _run_with_db(
            args,
            lambda conn: service.list_purchase_candidates(
                conn,
                status=args.status,
                source_type=args.source_type,
                target_date=args.target_date,
                page=1,
                per_page=1000,
            )[0],
        )

    if args.command == "purchase-candidates-from-bom":
        rows = _load_bom_rows(args.csv_path)
        return _run_with_db(
            args,
            lambda conn: service.create_purchase_candidates_from_bom(
                conn,
                rows=rows,
                target_date=args.target_date,
                note=args.note,
            ),
        )

    if args.command == "purchase-candidates-from-project":
        return _run_with_db(
            args,
            lambda conn: service.create_purchase_candidates_from_project_gap(
                conn,
                args.project_id,
                target_date=args.target_date,
                note=args.note,
            ),
        )

    if args.command == "update-purchase-candidate":
        return _run_with_db(
            args,
            lambda conn: service.update_purchase_candidate(
                conn,
                args.candidate_id,
                {k: v for k, v in {"status": args.status, "note": args.note}.items() if v is not None},
            ),
        )

    if args.command == "search":
        return _run_with_db(
            args,
            lambda conn: service.list_items(
                conn,
                q=args.q,
                category=args.category,
                manufacturer=args.manufacturer,
                page=1,
                per_page=1000,
            )[0],
        )

    if args.command == "location-inspect":
        return _run_with_db(
            args,
            lambda conn: service.inspect_location(conn, args.location),
        )

    if args.command == "location-disassemble":
        return _run_with_db(
            args,
            lambda conn: service.disassemble_location(conn, args.location),
        )

    if args.command == "assembly-create":
        components = json.loads(args.components)
        return _run_with_db(
            args,
            lambda conn: service.create_assembly(
                conn,
                {
                    "name": args.name,
                    "description": args.description,
                    "components": components,
                },
            ),
        )

    if args.command == "assembly-list":
        return _run_with_db(
            args,
            lambda conn: service.list_assemblies(conn, page=1, per_page=1000)[0],
        )

    if args.command == "assembly-show":
        return _run_with_db(
            args,
            lambda conn: service.get_assembly(conn, args.assembly_id),
        )

    if args.command == "assembly-delete":
        return _run_with_db(
            args,
            lambda conn: (service.delete_assembly(conn, args.assembly_id), {"deleted": True})[1],
        )

    if args.command == "location-set-assembly":
        assignments = json.loads(args.assignments)
        return _run_with_db(
            args,
            lambda conn: service.set_location_assemblies(
                conn,
                location=args.location,
                assignments=assignments,
            ),
        )

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
