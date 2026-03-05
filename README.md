# Materials Management

Materials Management is a full-stack inventory system for optical components. It manages item master data, stock by location, supplier quotations and orders, reservations, assemblies, projects, and transaction history with undo support.

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
uv run python -m pytest
```

## Documentation

- Functional specification: [`specification.md`](specification.md)
- Technical architecture and ER diagrams: [`documents/technical_documentation.md`](documents/technical_documentation.md)
- Team onboarding (clone/install/run/test): [`documents/team_onboarding.md`](documents/team_onboarding.md)
- Current source snapshot: [`documents/source_current_state.md`](documents/source_current_state.md)
- Project change history: [`documents/change_log.md`](documents/change_log.md)


### CSV import shortcuts

- Movements CSV upload: `POST /api/inventory/import-csv`
  - columns: `operation_type,item_id,quantity,from_location,to_location,location,note`
- Reservations CSV upload: `POST /api/reservations/import-csv`
  - columns: `item_id` or `assembly`, `quantity`, optional `assembly_quantity,purpose,deadline,note,project_id`
