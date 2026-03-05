## Optical Component Inventory Management Backend

### Setup

```bash
uv sync
```

### Run API Server

```bash
uv run main.py serve --host 127.0.0.1 --port 8000
```

API base URL: `http://127.0.0.1:8000/api`

### Initialize Database

```bash
uv run main.py init-db
```

### CLI Examples

```bash
uv run main.py import-orders --supplier "Thorlabs" --csv-path ".\\sample\\order_import.csv"
uv run main.py register-missing --csv-path ".\\sample\\missing_items_registration.csv"
uv run main.py register-unregistered-missing --continue-on-error
uv run main.py import-unregistered-orders --continue-on-error
uv run main.py bom-analyze --csv-path ".\\sample\\bom.csv" --target-date 2026-04-01
uv run main.py purchase-candidates-from-project --project-id 1 --target-date 2026-04-01
uv run main.py migrate-quotations-layout --dry-run
uv run main.py migrate-quotations-layout --apply
uv run main.py move --item-id 1 --quantity 5 --from-location STOCK --to-location BENCH_A
uv run main.py reserve --item-id 1 --quantity 2 --purpose "Experiment A"
uv run main.py list-reservations
```

### Quotations Folder Layout

Canonical batch paths:

- `quotations/unregistered/csv_files/<supplier>/*.csv`
- `quotations/unregistered/pdf_files/<supplier>/*`
- `quotations/unregistered/missing_item_registers/*_missing_items_registration*.csv` (generated consolidated register files)
- `quotations/registered/csv_files/<supplier>/*.csv`
- `quotations/registered/pdf_files/<supplier>/*`

Manual `import-orders` / `/api/orders/import` CSV rule for `pdf_link`:

- Use `quotations/registered/pdf_files/<supplier>/<file>.pdf` or leave blank.
- Filename-only values (e.g. `Q-2026-001.pdf`) are auto-normalized to the selected supplier path.
- `unregistered/...` paths are rejected for manual import.

Run migration in two steps:

1. `uv run main.py migrate-quotations-layout --dry-run`
2. `uv run main.py migrate-quotations-layout --apply`


## Additional CSV imports

- `POST /api/inventory/import-csv` with CSV columns `operation_type,item_id,quantity,from_location,to_location,location,note`
- `POST /api/reservations/import-csv` with CSV columns `item_id` or `assembly`, `quantity`, optional `assembly_quantity,purpose,deadline,note,project_id`
