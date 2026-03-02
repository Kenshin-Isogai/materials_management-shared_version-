# Source Current State

Last updated: 2026-03-02 (JST)

## 1. System Snapshot

- Project type: local-first optical component inventory management application.
- Stack:
  - Backend: Python + FastAPI + SQLite
  - Frontend: React + TypeScript + Vite + SWR
- Runtime posture:
  - Current: personal/local usage
  - Direction: PoC designed to remain compatible with future multi-user/RBAC expansion

## 2. Repository Structure (active areas)

- `backend/`
  - `main.py`: CLI entrypoint and command routing
  - `app/api.py`: HTTP API routes (73 endpoints)
  - `app/service.py`: domain logic (single business logic layer)
  - `app/db.py`: schema + indexes + migration logic (17 tables)
  - `tests/`: integration/service/path tests
- `frontend/`
  - `src/pages/`: tab/page UI for dashboard, items, inventory, orders, reservations, assemblies, projects, BOM, locations, snapshot, history, master data
  - `src/lib/api.ts`: API client with fallback API base probing
- `documents/`
  - `technical_documentation.md`
  - `team_onboarding.md`
  - `source_current_state.md` (this file)
  - `change_log.md`

## 3. Backend State

### 3.1 API and Domain

- API wrapper uses common response envelope:
  - success: `status=ok`
  - error: `status=error` with code/message/details
- Business rules are centralized in `backend/app/service.py` and shared by API and CLI.
- Current auth posture:
  - no enforced auth for PoC
  - capability metadata endpoint exists: `GET /api/auth/capabilities`
  - auth mode read from `INVENTORY_AUTH_MODE` (`none`, `rbac_dry_run`, `rbac_enforced`)

### 3.2 Data Model

- SQLite with normalized core entities:
  - items, inventory ledger, orders/quotations, reservations
  - assemblies/projects with requirements
  - supplier item aliases and category aliases
  - import jobs/effects for reversible item imports
  - transaction log with undo chain
- Referential integrity and checks are enforced with foreign keys, constraints, indexes, and order validation triggers.

### 3.3 Reservation Behavior

- Reservation release/consume now supports:
  - full action (status transition to `RELEASED` / `CONSUMED`)
  - partial action (status remains `ACTIVE`, reservation quantity decreases)
- API endpoints accept optional body quantity for partial operations:
  - `POST /api/reservations/{id}/release`
  - `POST /api/reservations/{id}/consume`
- CLI supports partial quantity flags:
  - `release-reservation --reservation-id <id> --quantity <n>`
  - `consume-reservation --reservation-id <id> --quantity <n>`

## 4. Frontend State

- SPA navigation is implemented with React Router via `AppShell`.
- Data fetching is SWR-based with typed API client wrappers.
- Reservations page supports partial release/consume via quantity prompt.
- Orders page `Order List` supports client-side sorting by order id, supplier, item, quantity, expected arrival, and status.
- Orders page now also shows an `Imported Quotations` table sourced from `GET /api/quotations` (ID, supplier, quotation number, issue date, pdf_link) with client-side sorting and filtering controls.
- Imported Quotations includes dedicated quotation-number search plus a secondary text filter for supplier/issue-date/PDF-link fields.
- Orders page mutation flows (manual import, unregistered batch steps, arrival processing) revalidate both orders and quotations datasets to avoid stale `Imported Quotations` content after successful operations.
- Order List panel now starts collapsed and can be expanded/collapsed inline, reducing scroll distance to the `Imported Quotations` section when reviewing quotations.
- Items page `Item List` supports client-side sorting by ID, item number, manufacturer, category, and URL.
- Item List URL values render as clickable external links (`target=_blank`, `rel=noopener noreferrer`).
- Dashboard overdue section supports keyword filtering and shows a full-table view when more than eight overdue rows match the filter.
- Build system: `npm run build` (Vite production build + TypeScript build).

## 5. File and Import Workflow State

- Canonical quotation folder layout is active:
  - `quotations/unregistered/csv_files/<supplier>/`
  - `quotations/unregistered/pdf_files/<supplier>/`
  - `quotations/registered/csv_files/<supplier>/`
  - `quotations/registered/pdf_files/<supplier>/`
- Batch import functions normalize legacy/typo paths, move files safely, and emit warnings for unresolved paths.
- Unregistered batch order import writes missing-item rows into one consolidated register CSV per run under `quotations/unregistered/missing_item_registers/`; source CSV/PDF files remain in place for unresolved quotations.
- Consolidated missing-item registers de-duplicate repeated unresolved rows by `(supplier, manufacturer_name, item_number)` across all quotations in the same batch run.
- Temporary per-file missing-item CSVs generated during batch consolidation are supplier-prefixed and only removed after consolidated register creation succeeds.
- Collision-safe file move behavior is implemented (`_1`, `_2`, ... suffixing).
- Unregistered batch order import accepts non-canonical `pdf_link` path forms (including `quotations/unregistered/...` and typo-normalizable variants) and normalizes/moves links during processing.
- Per-file unregistered order import now executes CSV/PDF moves atomically with rollback on move failure, preventing partial file relocation.
- Order import accepts common date formats with slash or flexible month/day (`YYYY/M/D`, `YYYY-MM-DD`) and normalizes to `YYYY-MM-DD`.
- Fully empty CSV rows are ignored during order import to avoid false validation failures from trailing blank lines.
- Missing-item registration now rejects unresolved `new_item` rows with all metadata blank, preventing accidental `UNKNOWN` placeholder item creation.
- Manual and unregistered batch order imports reject duplicate quotation re-import for the same supplier when existing orders already reference that quotation.
- Missing-item batch registration now reads both `quotations/unregistered/csv_files/**/_missing_items_registration.csv` and consolidated registers under `quotations/unregistered/missing_item_registers/`.
- `missing_items_registration.csv` uses `supplier` (not `manufacturer`) because rows are resolved in supplier alias scope; `new_item` rows may specify `manufacturer_name` (or `manufacturer`) and default to `UNKNOWN` when blank.
- JSON missing-item registration endpoint (`/api/register-missing/rows`) accepts both `manufacturer_name` and `manufacturer` fields for `new_item` rows.
- Supplier resolution for order import and missing-item registration now falls back to case-insensitive lookup before creating a new supplier, preventing alias-scope mismatches from supplier name casing differences.
- Order import alias resolution now falls back to case-insensitive `ordered_item_number` matching within a supplier when exact alias text does not match.
- Order import alias resolution also normalizes item-number variants (NFKC, dash variants like `-`/`−`, and whitespace removal) before final alias lookup to prevent false missing-items caused by visually similar SKU text.

## 6. Quality State

- Backend tests: `52 passed` (latest run on 2026-03-02).
- Frontend production build: success (latest run on 2026-03-02).

## 7. Known Directional Gaps (intentional for current phase)

- Auth/RBAC enforcement is not active yet (capability scaffolding only).
- Multi-user concurrency hardening beyond current SQLite/local posture is not implemented.
- Hash-based quotation duplicate detection and strict provenance metadata are planned, not yet implemented.
- Compliance controls (retention/backup policy enforcement) are not yet implemented.

## Orders/Quotations maintenance UI (latest)

- Orders page now supports:
  - deleting non-arrived orders from `Order List`
  - inline editing of quotation `issue_date` and `pdf_link`
  - deleting quotations directly from `Imported Quotations` (blocked if any linked order is already `Arrived`)
- Backend now keeps CSV and DB aligned for these maintenance operations by rewriting/deleting matching rows in discovered quotation CSV files under registered/unregistered CSV roots.
- For duplicate item rows under the same quotation, order-level CSV sync now matches a single row by per-order occurrence identity so update/delete touches only the targeted order row.
