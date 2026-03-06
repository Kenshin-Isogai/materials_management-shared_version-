# Materials Management

Materials Management is a full-stack inventory system for optical components. It manages item master data, stock by location, supplier quotations and orders, reservations, assemblies, projects, and transaction history with undo support.

The recommended future-planning workflow is now:

`Workspace` -> `Projects` / `Planning` / `RFQ` -> `Orders` / `Reservations`

`Workspace` is the default summary-first route for future demand. It opens with a project dashboard, provides a committed pipeline view, and offers a planning board that previews project impact with server-owned sequential netting data and supply-source breakdowns. The dedicated `Projects`, `Planning`, and `RFQ` pages remain available for heavier editing and operational fallback.

The workspace drawers now complete the main planning loop in place:

- Project drawer: inline project requirement editing plus preview-first bulk item entry
- Item drawer: inventory, incoming orders, and cross-project planning allocation context for the selected item
- RFQ drawer: inline RFQ batch and line editing, including supplier, ETA, status, and linked-order updates
- Planning board: CSV export for the currently selected project/preview date

`Planning` still performs sequential project netting so earlier committed projects, including already-started work, consume future planning capacity before later projects are analyzed. `RFQ` stores project-dedicated shortage follow-up, reuses the planning date selected on the planning board, and links real orders back to the project when purchasing starts.

## Tech Stack

- Backend: Python, FastAPI, SQLite, `uv`
- Frontend: React, TypeScript, Vite, SWR
- Data/Files: SQLite database + workspace folders (`quotations/`, `exports/`)

## Repository Structure

- `backend/`: API server, CLI, database schema/migrations, business logic, tests
- `frontend/`: Web UI
- `quotations/`: Registered/unregistered quotation CSV/PDF files
- `exports/`: Generated CSV exports (for example missing-item registration templates)
- `documents/`: Technical documentation
- `specification.md`: Detailed functional specification
- `start-dev.bat` / `stop-dev.bat`: Windows helper scripts to start/stop both servers

## Quick Start (Windows)

1. Install prerequisites:
- Python 3.10+ and `uv`
- Node.js 18+

2. Start both backend and frontend from project root:

```bat
start-dev.bat
```

This starts:
- Backend API on the first free port in `8000, 8001, 8010, 18000`
- Frontend on `http://127.0.0.1:5173`

3. Stop both:

```bat
stop-dev.bat
```

## Manual Setup

Backend:

```powershell
cd backend
uv sync
uv run main.py init-db
uv run main.py serve --host 127.0.0.1 --port 8000
```

Frontend:

```powershell
cd frontend
npm install
$env:VITE_API_BASE = "http://127.0.0.1:8000/api"
npm run dev
```

## API and CLI

- API base: `http://127.0.0.1:8000/api`
- API docs (Swagger): `http://127.0.0.1:8000/docs`
- CLI entry: `backend/main.py`

Example CLI commands:

```powershell
uv run main.py import-orders --supplier "Thorlabs" --csv-path ".\sample\order_import.csv"
uv run main.py import-unregistered-orders --continue-on-error
uv run main.py bom-analyze --csv-path ".\sample\bom.csv" --target-date 2026-04-01
uv run main.py purchase-candidates-from-project --project-id 1 --target-date 2026-04-01
uv run main.py move --item-id 1 --quantity 5 --from-location STOCK --to-location BENCH_A
uv run main.py reserve --item-id 1 --quantity 2 --purpose "Experiment A"
```

## Database and File Layout

- Default DB path: `backend/database/inventory.db`
- Quotations roots:
  - `quotations/unregistered/csv_files/<supplier>/`
  - `quotations/unregistered/pdf_files/<supplier>/`
  - `quotations/unregistered/missing_item_registers/` (single consolidated missing-item CSV per batch run)
  - `quotations/registered/csv_files/<supplier>/`
  - `quotations/registered/pdf_files/<supplier>/`

## Testing

```powershell
cd backend
uv run python -m pytest -q
cd ..\frontend
npm run test
npm run build
```

## Documentation

- Functional specification: [`specification.md`](specification.md)
- Technical architecture and ER diagrams: [`documents/technical_documentation.md`](documents/technical_documentation.md)
- Team onboarding (clone/install/run/test): [`documents/team_onboarding.md`](documents/team_onboarding.md)
- Current source snapshot: [`documents/source_current_state.md`](documents/source_current_state.md)
- Project change history: [`documents/change_log.md`](documents/change_log.md)


### CSV import shortcuts

- Header-only template downloads (UTF-8 with BOM):
  - `GET /api/items/import-template`
  - `GET /api/inventory/import-template`
  - `GET /api/orders/import-template`
  - `GET /api/reservations/import-template`
- Preview-first manual imports:
  - `POST /api/items/import-preview`
  - previews duplicate item rows, alias create/update behavior, and canonical-item reconciliation before final `POST /api/items/import`
  - final item import accepts optional per-row `row_overrides` (`canonical_item_number`, `units_per_order`)
  - `POST /api/inventory/import-preview`
  - validates movement rows, simulates stock balance changes, and allows per-row `item_id` correction before final `POST /api/inventory/import-csv`
  - `POST /api/orders/import-preview`
  - classifies rows as `exact`, `high_confidence`, `needs_review`, or `unresolved`
  - surfaces duplicate quotation conflicts before commit
  - supports per-row canonical item correction plus optional supplier-alias save on final `POST /api/orders/import`
  - `POST /api/reservations/import-preview`
  - validates item/assembly targets, previews assembly expansion, and allows per-row `item_id`/`assembly_id` correction before final `POST /api/reservations/import-csv`
  - preview-confirmation JSON fields are strict: malformed JSON, wrong top-level shapes, missing required keys, and override row numbers not present in the uploaded CSV return `422` instead of bubbling as server errors
- Projects quick requirement parsing:
  - `POST /api/projects/requirements/preview`
  - parses `item_number,quantity` lines, classifies exact/review/unresolved matches, and lets the UI apply corrected rows into project requirements
- BOM spreadsheet reconciliation:
  - `POST /api/bom/preview`
  - classifies supplier/item matches as `exact`, `high_confidence`, `needs_review`, or `unresolved`
  - returns ranked supplier and item candidates plus projected shortage data before the UI runs `POST /api/bom/analyze`, `POST /api/bom/reserve`, or `POST /api/purchase-candidates/from-bom`
- Live reference CSV downloads:
  - `GET /api/items/import-reference`
  - `GET /api/inventory/import-reference`
  - `GET /api/orders/import-reference` (optional `?supplier_name=...`)
  - `GET /api/reservations/import-reference`
- Movements CSV upload: `POST /api/inventory/import-csv`
  - columns: `operation_type,item_id,quantity,from_location,to_location,location,note`
- Reservations CSV upload: `POST /api/reservations/import-csv`
  - columns: `item_id` or `assembly`, `quantity`, optional `assembly_quantity,purpose,deadline,note,project_id`

### Catalog search shortcut

- Typed selector search for write flows: `GET /api/catalog/search?q=...&types=item,assembly,supplier,project`
- `CatalogPicker` now powers Projects requirements, Assemblies components, BOM spreadsheet entry and BOM preview reconciliation, Reservations entry, and Items/Orders/Movements/Reservations import reconciliation
- Single-select `CatalogPicker` inputs now resync their visible text when the parent selection changes while the popover is open, so preview correction rows stay aligned with the final submitted state
