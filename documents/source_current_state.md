# Source Current State

Last updated: 2026-03-06 (JST)

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
  - `app/api.py`: HTTP API routes (107 endpoints)
  - `app/service.py`: domain logic (single business logic layer)
  - `app/db.py`: schema + indexes + migration logic (18 tables)
  - `tests/`: integration/service/path tests
- `frontend/`
  - `src/pages/`: tab/page UI for dashboard, items, inventory, orders, reservations, assemblies, projects, purchase candidates, BOM, locations, snapshot, history, master data
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
  - sequential planning pipeline summaries derived from project status + planned_start
  - persistent `rfq_batches` / `rfq_lines` for project-dedicated shortage follow-up
  - purchase candidate persistence for pre-PO shortages
  - supplier item aliases and category aliases
  - import jobs/effects for reversible item imports
  - transaction log with undo chain
- Referential integrity and checks are enforced with foreign keys, constraints, indexes, and order validation triggers.
- DB migration now backfills legacy `orders.project_id_manual` for rows with `project_id` and no ORDERED RFQ ownership, preserving historical manual project linkage during RFQ unlink sync.
- Item reference guards for identity mutation/deletion include `purchase_candidates`, returning controlled domain errors before raw FK failures.

### 3.3 Reservation Behavior

- Reservation create/release no longer transfers inventory to/from `RESERVED`.
- Active reserved quantities are tracked via per-location rows in `reservation_allocations`.
- Partial/full release updates allocation states without changing `inventory_ledger` quantities.
- Partial/full consume decrements physical inventory at allocated locations and transitions allocation states.
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
- Reservations page now uses a single expanded `Reservation Entry` table for both one-off and multi-row reservation creation (the separate `Single Reservation` form was removed).
- Reservations and Projects page headers now include guidance clarifying scope: Reservations is execution-time allocation, Projects is future-demand planning.
- Added typed catalog search endpoint `/api/catalog/search` for write-flow selectors (`item`, `assembly`, `supplier`, `project`).
- Projects page requirement entry now uses `CatalogPicker` for item and assembly targets instead of ad hoc `#id` text matching/datalist suggestions.
- Projects page requirement entry now supports preview-first bulk text parsing (`item_number,quantity` per line).
  - `POST /api/projects/requirements/preview` classifies each line as `exact`, `high_confidence`, `needs_review`, or `unresolved`
  - preview rows return ranked item candidates, support `CatalogPicker` correction, and can be applied back into the editable requirement grid
- Projects page bulk-parser unresolved rows keep their raw typed query visible until the user remaps them through the picker.
- Assemblies page component rows now use the same `CatalogPicker` item selector, with keyboard search and recent selections stored in `localStorage`.
- BOM spreadsheet entry now uses `CatalogPicker` in type-or-search mode for supplier and item columns while still allowing raw text entry.
- BOM page is now preview-first:
  - `POST /api/bom/preview` classifies supplier/item matches as `exact`, `high_confidence`, `needs_review`, or `unresolved`
  - preview rows return ranked supplier/item candidates and projected canonical quantity / available stock / shortage
  - BOM analyze, reserve, and shortage-save actions now run from the corrected preview set instead of directly from the raw grid
- Reservations `Reservation Entry` rows now use `CatalogPicker` for item selection instead of a long static `<select>`.
- Items manual CSV import is now preview-first:
  - `POST /api/items/import-preview` classifies duplicate item rows, alias create/update rows, and unresolved canonical alias rows before commit
  - preview confirmation can send per-row `canonical_item_number` / `units_per_order` overrides back through `POST /api/items/import`
- Movements CSV import is now preview-first:
  - `POST /api/inventory/import-preview` validates operation/location rules, simulates inventory effects row-by-row, and flags unresolved item ids or stock shortages before commit
  - preview confirmation can send per-row `item_id` overrides back through `POST /api/inventory/import-csv`
- Projects page now supports editing an existing project (load details into form, then save via project update API) including requirement composition/quantities.
- Planning page is now the primary future-demand workflow surface.
  - Select a project and analyze it at its planned start (or an override date).
  - Later projects are netted against earlier committed projects (`CONFIRMED` / `ACTIVE`) instead of being analyzed in isolation, including committed work whose start date is already in the past.
  - On-time shortage rows can be converted directly into RFQ batches, and RFQ creation now reuses the planning date selected on the Planning page.
- RFQ page is now the primary project-shortage follow-up surface.
  - RFQ batches persist project-specific shortage rows.
  - RFQ lines capture supplier, finalized quantity, lead time, expected arrival, status, and an order link that is only retained while the line is `ORDERED`.
  - An `ORDERED` linked order is synchronized into `orders.project_id`; draft/quoted lines do not pull the order out of the generic planning pool, and manual order project reassignment is blocked while an `ORDERED` RFQ line owns that assignment.
- BOM page now supports optional analysis date input and sends `target_date` to `POST /api/bom/analyze` for future-arrival-aware gap checks.
- BOM page now supports `Save Shortages` to persist shortage/missing rows as purchase candidates before PO creation.
- BOM page `Save Shortages` now surfaces API errors in-page (message area) instead of failing silently on rejected inputs such as past `target_date`.
- BOM analysis no longer creates missing suppliers as a side effect when a row references a direct canonical item number.
- Purchase Candidates page provides persistent shortage tracking with status transitions (`OPEN`, `ORDERING`, `ORDERED`, `CANCELLED`) and project-gap candidate creation.
- Orders page `Order List` supports client-side sorting by order id, supplier, item, quantity, expected arrival, and status.
- Orders page `Order List` now supports inline editing of `expected_arrival` (ETA) for open orders, backed by `PUT /api/orders/{order_id}`.
- ETA edit flow supports partial postponement using split quantity (e.g., postpone 30 of 50), which creates a second open-order row with the new ETA while preserving traceability-safe quantities.
- Backend now persists split/merge/partial-arrival order lineage in `order_lineage_events`; API exposes `POST /api/orders/merge` and `GET /api/orders/{order_id}/lineage` for durable traceability and future scale-out reporting.
- Orders manual CSV import is now preview-first:
  - `POST /api/orders/import-preview` classifies each row as `exact`, `high_confidence`, `needs_review`, or `unresolved`
  - preview surfaces duplicate quotation conflicts before commit and returns ranked candidate matches
  - preview confirmation can send per-row canonical overrides plus optional supplier-alias saves back through `POST /api/orders/import`
- Reservations CSV import is now preview-first:
  - `POST /api/reservations/import-preview` validates item/assembly targets, previews assembly expansion, and flags inventory shortages before commit
  - preview confirmation can send per-row `item_id` / `assembly_id` overrides back through `POST /api/reservations/import-csv`
  - explicit preview-confirmation target overrides win over stale raw CSV target fields during commit
- Preview-confirmation multipart JSON (`row_overrides`, `alias_saves`) now fails fast with controlled `422` responses for malformed JSON, wrong top-level shapes, missing required keys, unsupported fields, and row numbers not present in the uploaded CSV.
- Orders import supplier input now uses `CatalogPicker`, and Items/Orders/Movements/Reservations preview reconciliation rows use the same picker for manual item/assembly correction.
- `CatalogPicker` single-select inputs now resync their visible text when parent state changes while the picker is open, and preview flows preserve explicit cleared selections instead of silently reverting to stale suggested matches.
- Preview/analyze/import actions for BOM, Projects quick-entry, Items, Orders, Movements, and Reservations now surface API failures through in-page status messages instead of relying on uncaught promise errors.
- Snapshot page supports client-side quick search, location/category filtering, low-stock/shortage-only threshold filtering, description-substring filtering, and table-column sorting (item, location, quantity, category) to accelerate planning and purchase checks from projected inventory states.
- BOM analysis endpoint now supports optional `target_date` projection (`current net available + open orders arriving by date`) while BOM reserve remains current-availability execution behavior.
- Project planning now has two layers:
  - `GET /api/projects/{id}/planning-analysis` for sequential multi-project netting with backlog carry-forward
  - `GET /api/projects/{id}/gap-analysis` as a compatibility view over the same planning engine, returning the effective planning `target_date` used for the analysis
- Splitting an RFQ-owned open order now keeps the dedicated `project_id` only on the original RFQ-linked order; the new sibling order remains generic until an RFQ line explicitly links it.
- Purchase candidate endpoints are now available:
  - `GET /api/purchase-candidates`
  - `GET /api/purchase-candidates/{id}`
  - `POST /api/purchase-candidates/from-bom`
  - `POST /api/purchase-candidates/from-project/{project_id}`
  - `PUT /api/purchase-candidates/{id}`
- Orders page now also shows an `Imported Quotations` table sourced from `GET /api/quotations` (ID, supplier, quotation number, issue date, pdf_link) with client-side sorting and filtering controls.
- Imported Quotations includes dedicated quotation-number search plus a secondary text filter for supplier/issue-date/PDF-link fields.
- Imported Quotations now includes an `Orders` count column so each quotation row shows how many order rows currently reference that quotation.
- Orders page mutation flows (manual import, unregistered batch steps, arrival processing) revalidate both orders and quotations datasets to avoid stale `Imported Quotations` content after successful operations.
- Order List panel now starts collapsed and can be expanded/collapsed inline, reducing scroll distance to the `Imported Quotations` section when reviewing quotations.
- Orders page includes an `Order Context` panel (row-level Details action) that consolidates item metadata, related order arrivals, and related quotation metadata to reduce cross-tab lookup overhead.
- `Order List` row-level `Details` now auto-collapses the list and smooth-scrolls to `Order Context` to reduce manual navigation.
- `Imported Quotations` now also includes a row-level `Details` action that directly opens `Order Context` using a linked order, so quotation review no longer requires expanding `Order List` first.
- Item List now includes a row-level `Flow` action that opens an item-specific increase/decrease timeline (when/how many/why) combining transaction logs, expected order arrivals, and active reservation deadlines.
- Items page `Item List` now supports expand/collapse and auto-collapses when `Flow` is opened, reducing scroll overhead to reach the timeline panel.
- Items page `Item List` supports client-side sorting by ID, item number, manufacturer, category, and URL.
- Item List URL values render as clickable external links (`target=_blank`, `rel=noopener noreferrer`).
- Import-capable pages now use backend-driven CSV downloads instead of frontend-generated examples:
  - `Items`, `Orders`, `Movements`, and `Reservations` each expose `Download Template CSV` and `Download Reference CSV`
  - template CSVs are header-only and encoded as UTF-8 with BOM
  - reference CSVs are generated from live DB state at request time
- Table headers now stay sticky across the existing horizontally scrollable table wrappers, improving scanability on table-heavy browse pages without changing the default unscoped browse behavior.
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
- Missing-item registration payloads now also accept legacy `row_type` (`item`/`alias`) as an alias of `resolution_type` (`new_item`/`alias`); `item` is normalized to `new_item`.
- Supplier resolution for order import and missing-item registration now falls back to case-insensitive lookup before creating a new supplier, preventing alias-scope mismatches from supplier name casing differences.
- Order import alias resolution now falls back to case-insensitive `ordered_item_number` matching within a supplier when exact alias text does not match.
- Order import alias resolution also normalizes item-number variants (NFKC, dash variants like `-`/`−`, and whitespace removal) before final alias lookup to prevent false missing-items caused by visually similar SKU text.

## 6. Quality State

- Backend tests: `122 passed` (latest run on 2026-03-06).
- Frontend tests: `3 passed` via `npm run test` (latest run on 2026-03-06).
- Frontend production build: success (latest run on 2026-03-06).

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

- Added movement CSV import endpoint and service mapping to batch operations (`/api/inventory/import-csv`).
- Added reservation CSV import endpoint with assembly-aware expansion (`/api/reservations/import-csv`), allowing one row to reserve all assembly components.
- Added CSV template/reference download endpoints for current import-capable flows:
  - `/api/items/import-template`, `/api/items/import-reference`
  - `/api/inventory/import-template`, `/api/inventory/import-reference`
  - `/api/orders/import-template`, `/api/orders/import-reference`
  - `/api/reservations/import-template`, `/api/reservations/import-reference`
- Added Orders manual import preview endpoint `/api/orders/import-preview` and confirmation-side `row_overrides` / `alias_saves` support on `/api/orders/import`.
- Added preview endpoints for the remaining manual CSV flows:
  - `/api/items/import-preview`
  - `/api/inventory/import-preview`
  - `/api/reservations/import-preview`
- Added preview-confirmation `row_overrides` support on:
  - `/api/items/import`
  - `/api/inventory/import-csv`
  - `/api/reservations/import-csv`
- Added project bulk-parser preview endpoint `/api/projects/requirements/preview` for `item_number,quantity` quick-entry reconciliation before rows are applied to project requirements.
- Movement/reservation CSV import numeric parse failures now return API validation errors (`422`) instead of internal errors for malformed rows.
