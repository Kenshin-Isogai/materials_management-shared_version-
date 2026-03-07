## 2026-03-07

### Changed

- Added a new `/workspace` frontend route as the summary-first future-demand surface.
  - default view: project summary dashboard with committed-vs-draft semantics
  - pipeline view: committed projects with cumulative generic-consumption visibility
  - planning board: selected-project deep dive with server-driven shortage rows and supply-source breakdown chips
  - contextual right-side drawer: local breadcrumb navigation across Project, Item, and RFQ context without leaving the board
  - project drawer now supports full inline project editing, including preview-first bulk requirement entry
  - item drawer now shows incoming orders and cross-project planning allocation context for the selected item
  - RFQ drawer now supports inline RFQ batch and line editing from the planning loop
  - drawer close/breadcrumb/back behavior now protects unsaved project and RFQ drafts
  - planning board now supports CSV export for the selected project/date
- Added backend workspace summary endpoint `GET /api/workspace/summary`.
  - returns aggregate project dashboard rows without per-project planning-analysis fan-out
  - committed rows include authoritative planning totals
  - `PLANNING` rows return explicit preview-required semantics plus RFQ counts
- Added backend item planning/context and export support.
  - added `GET /api/items/{item_id}/planning-context` for cross-project item allocation drill-in
  - added `GET /api/workspace/planning-export` for CSV export of the selected planning view
  - extended `GET /api/orders` with optional `item_id` / `project_id` filters for drawer-side order context
- Enriched the canonical planning engine payload.
  - planning rows now expose `supply_sources_by_start` and `recovery_sources_after_start`
  - pipeline rows now expose `generic_committed_total` and `cumulative_generic_consumed_before_total`
- Corrected workspace/RFQ drawer state handling regressions.
  - workspace board date now re-syncs to the effective planning `target_date` when the same project refreshes without local preview edits, so exports and RFQ actions no longer run against a hidden/stale date
  - reopening an earlier drawer stack entry now confirms before truncating dirty project/RFQ drawers, including non-breadcrumb navigation paths
  - RFQ batch detail refresh now rehydrates saved line drafts from the server response even when `rfq_id` is unchanged, so backend-normalized fields such as cleared non-`ORDERED` `linked_order_id` values are reflected immediately
  - item-scoped RFQ drawers now keep the full batch visible and move the focused item rows to the top instead of hiding the rest of the batch
- Refined workspace drawer/editor follow-up issues from review.
  - nested picker Escape handling now stops at the picker so dismissing `CatalogPicker` results does not also close the workspace drawer
  - workspace summary refresh now repairs stale `selectedProjectId` values before rebuilding the planning board request
  - project drawer RFQ metrics now reuse authoritative `workspace/summary` aggregates instead of reducing a paginated `rfq-batches` slice
  - shared project requirement rows now preserve existing item/assembly selections even when the stored id is outside the preloaded first page
  - shared RFQ line order linking now loads per-item options across all pages and backfills already linked orders so current selections stay visible
  - hidden drawer panels now suspend their SWR fetches and heavy preload queries while they remain in the breadcrumb stack
  - backend planning snapshot construction now batches project/requirement, assembly-component, and inventory lookups, and item planning context narrows snapshot expansion to the requested item

### Docs

- Updated `README.md` with the new workspace-first future-planning workflow and fallback-page posture.
- Updated `specification.md` with the workspace editor/export/item-context endpoints and order-filter additions.
- Updated `documents/technical_documentation.md` and `documents/source_current_state.md` with the drawer editing, dirty-state guard, item planning context, and export behavior.
- Updated `documents/technical_documentation.md` and `documents/source_current_state.md` with the workspace/RFQ state-resynchronization and drawer-stack guard fixes.

### Tests

- Added backend regression coverage for planning source breakdowns and cumulative generic-consumption metrics.
- Added backend API coverage for `GET /api/workspace/summary` committed-vs-draft semantics and RFQ summary fields.
- Added backend API coverage for `GET /api/orders?item_id=...` filtering.
- Added frontend Vitest coverage for shared editor draft helpers and workspace drawer active-panel/back behavior.
- Added frontend Vitest coverage for the workspace and RFQ state helper regressions around effective dates, drawer-stack truncation, and RFQ line rehydration.
- Added frontend Vitest coverage for `CatalogPicker` Escape handling so picker dismissal does not bubble into workspace drawer close handlers.
- Frontend production build executed: `npm run build`.

## 2026-03-06

### Changed

- Reworked the future-planning workflow around sequential project netting.
  - Added a dedicated planning engine that processes committed projects in `planned_start` order.
  - Earlier project shortages now become backlog demand, so later generic arrivals are consumed by older committed work before newer projects can use them.
  - Added `GET /api/projects/{project_id}/planning-analysis` and `GET /api/planning/pipeline`.
  - `GET /api/projects/{project_id}/gap-analysis` is now a compatibility view over the sequential planning engine.
- Added project-dedicated RFQ persistence and UI workflow.
  - Added DB tables `rfq_batches` and `rfq_lines`.
  - Added `POST /api/projects/{project_id}/rfq-batches`, `GET /api/rfq-batches`, `GET /api/rfq-batches/{rfq_id}`, `PUT /api/rfq-batches/{rfq_id}`, and `PUT /api/rfq-lines/{line_id}`.
  - Planning page can convert uncovered start-date shortages into RFQ batches.
  - RFQ page now supports supplier / quantity / lead-time / expected-arrival refinement and order linking.
- Added project-dedicated order assignment for planning.
  - Orders now have optional `project_id`.
  - Project-linked orders are excluded from the generic future-arrival pool and treated as dedicated supply for that project.
  - Orders page now displays project assignment so dedicated supply is visible to the operator.
- Added phase-1 import UX support for current CSV workflows.
  - Added `GET /api/items|inventory|orders|reservations/import-template` endpoints that return header-only UTF-8-with-BOM template CSVs.
  - Added `GET /api/items|inventory|orders|reservations/import-reference` endpoints that return live reference CSVs generated from current DB state.
  - Orders import reference now supports optional `supplier_name` scoping so alias rows match the selected supplier context.
  - Frontend import areas on Items, Orders, Movements, and Reservations now download templates/reference data from the backend instead of generating sample CSVs client-side.
  - Table headers now remain sticky inside the existing horizontally scrollable table wrappers to improve browse-mode scanability on major table pages.
- Added the catalog search foundation and first `CatalogPicker` rollout.
  - Added `GET /api/catalog/search` with typed item/assembly/supplier/project results for write-flow selectors.
  - Item search now considers supplier alias text in addition to canonical item metadata.
  - Added reusable frontend `CatalogPicker` with grouped results, keyboard navigation, and `localStorage` recent selections.
  - Projects page requirement rows now use `CatalogPicker` for item and assembly selection.
  - Assemblies page component rows now use `CatalogPicker` for item selection.
- Extended the `CatalogPicker` rollout and added the first import preview flow.
  - BOM spreadsheet entry now uses `CatalogPicker` in type-or-search mode for supplier and item cells.
  - Reservations entry now uses `CatalogPicker` for item selection.
  - Orders manual import supplier selection now uses `CatalogPicker`.
  - Added `POST /api/orders/import-preview` plus preview-confirmation support on `POST /api/orders/import` via `row_overrides` and `alias_saves`.
  - Orders page manual import now previews reconciliation status, ranked suggestions, duplicate quotation conflicts, and optional alias-save checkboxes before commit.
- Extended preview-first CSV import to the remaining manual flows.
  - Added `POST /api/items/import-preview`, `POST /api/inventory/import-preview`, and `POST /api/reservations/import-preview`.
  - Added preview-confirmation `row_overrides` support on `POST /api/items/import`, `POST /api/inventory/import-csv`, and `POST /api/reservations/import-csv`.
  - Items page now previews duplicate item rows, alias create/update behavior, canonical-item correction, and units-per-order overrides before import.
  - Movements page now previews row validation, sequential stock effects, and unresolved item corrections before import.
  - Reservations page now previews item/assembly target resolution, assembly expansion, stock shortages, and manual target correction before import.
- Added the next CR1 reconciliation slice for Projects quick-entry parsing.
  - Added `POST /api/projects/requirements/preview` for `item_number,quantity` bulk text parsing.
  - Projects page quick parser now previews exact/high-confidence/review/unresolved matches, uses `CatalogPicker` for manual correction, and then applies the result into editable project requirement rows.
- Completed the remaining CR1 reconciliation slice for BOM spreadsheet entry.
  - Added `POST /api/bom/preview` for supplier/item reconciliation before analyze, reserve, or shortage persistence.
  - BOM preview returns ranked supplier and item candidates plus projected canonical quantity, available stock, and shortage for the suggested item match.
  - BOM page is now preview-first and uses `CatalogPicker` for row-level supplier/item correction inside the preview.
  - `POST /api/bom/analyze` no longer creates missing suppliers as a side effect when a row resolves by direct canonical item number.
- Simplified the Movements page entry workflow.
  - Removed the separate `Single Move` form.
  - Expanded the table-based `Movement Entry` section to cover both one-off and multi-row moves.
  - Switched movement rows to `CatalogPicker` item selection and widened the editable grid to use the full panel width.
  - `Add Row` now inherits the latest completed `from/to` locations so repeated transfers keep the same source/destination pair by default.

### Fixed

- Fixed Projects page requirements table header overlap.
  - Global sticky table header styling was pinning the requirements header over editable input rows, making fields look partially hidden while scrolling.
  - Added a per-table opt-out class and applied it to the Projects requirements entry table so inline form rows remain fully visible.
- Fixed sticky-header overlap on multi-row entry grids across core write workflows.
  - Applied the existing `no-sticky-header` table opt-out to Bulk Item Entry, Bulk Move Entry, Reservation Entry, Create Assembly components, and BOM spreadsheet entry tables.
  - This keeps typed input rows readable while horizontally scrolling and prevents headers from covering row fields on narrow or zoomed layouts.

- Backfilled legacy `orders.project_id_manual` values during DB migration.
  - Existing orders with `project_id` and no ORDERED RFQ ownership are now marked manual (`project_id_manual=1`) so RFQ unlink sync does not clear historical manual project assignment.
- Cleaned `.gitignore` merge artifacts and duplicate local-ignore sections so the ignore rules are intentional again.
- Hardened preview-confirmation multipart JSON validation for item, movement, order, and reservation imports.
  - malformed JSON now returns `422 INVALID_REQUEST`
  - wrong top-level shapes, missing required keys, unsupported fields, and CSV row references that do not exist now return deterministic flow-specific `422` errors
  - these validation failures no longer bubble as `5xx`
- Corrected preview reconciliation state handling in the frontend.
  - `CatalogPicker` single-select inputs now resync visible text when parent state changes while the picker is open
  - movement and reservation preview confirmation now preserve an explicit cleared selection instead of silently falling back to a stale suggested match
- Expanded in-page error surfacing for preview-first workflows.
  - movement import, reservation import, Projects quick-entry preview, BOM analyze/reserve, and item/order import preview messaging now consistently show user-visible failure text instead of relying on uncaught promise errors

- Corrected planning pipeline handling for already-started committed projects.
  - `CONFIRMED` / `ACTIVE` projects are no longer dropped when their `planned_start` is earlier than today.
  - In-flight committed projects can now be analyzed through `GET /api/projects/{project_id}/planning-analysis` without a false `INVALID_TARGET_DATE`.
  - Committed projects without a persisted start date are sequenced at `today_jst()` until a date is stored.
- Corrected RFQ creation to persist and reuse the analysis planning date.
  - `POST /api/projects/{project_id}/rfq-batches` now accepts optional `target_date`.
  - Auto-confirming a `PLANNING` project now persists the analysis date into `projects.planned_start`, preventing the newly committed project from disappearing from later planning runs.
- Corrected RFQ linked-order synchronization.
  - `orders.project_id` is now driven only by `ORDERED` RFQ lines.
  - Replacing or clearing a linked order now clears/reassigns the dedicated order ownership so generic supply is not stranded on the wrong project.
- Prevented manual order project edits from overriding RFQ-owned dedicated supply.
  - `PUT /api/orders/{order_id}` now rejects conflicting `project_id` changes when an `ORDERED` RFQ line already owns that order.
  - Direct order edits can no longer move dedicated supply to the wrong project or back into the generic arrival pool while the RFQ still points elsewhere.
- Corrected RFQ line downgrade behavior when a stale linked order is submitted.
  - Non-`ORDERED` RFQ saves now clear `linked_order_id` automatically.
  - Reverting an RFQ line from `ORDERED` to `QUOTED` no longer leaves dedicated supply invisible to planning because of a stale order link.
- Corrected reservation import commit precedence for preview-confirmation target fixes.
  - `POST /api/reservations/import-csv` now honors an explicit `assembly_id` override even when the raw CSV row still contains stale `item_id` text.
- Corrected RFQ-owned order splitting so dedicated supply is not cloned onto sibling rows.
  - Splitting an RFQ-linked order now keeps `project_id` only on the original linked row; the new split order remains generic until an RFQ line explicitly owns it.
- Corrected gap-analysis metadata to return the effective planning date.
  - `GET /api/projects/{project_id}/gap-analysis` now reports the actual `target_date` used by the shared planning engine instead of echoing `NULL`/stale project metadata.

### Docs

- Updated `README.md` with the new `Projects -> Planning -> RFQ -> Orders / Reservations` workflow.
- Updated `README.md` with frontend test commands plus the stricter preview-confirmation override validation notes.
- Updated `specification.md` with RFQ tables, project-linked order semantics, planning endpoint contracts, revised project planning behavior, and the RFQ-owned order assignment guardrails.
- Updated `specification.md` with strict `422` contracts for preview-confirmation `row_overrides` / `alias_saves`.
- Updated `documents/technical_documentation.md` with the sequential planning pipeline, RFQ architecture, and RFQ/order ownership invariants.
- Updated `documents/technical_documentation.md` and `documents/source_current_state.md` with the stricter import validation rules, picker state-sync behavior, and preview error-surfacing notes.
- Updated `documents/source_current_state.md` with the current Planning/RFQ behavior, including stale-link clearing and RFQ-owned order assignment rules.
- Updated `README.md`, `specification.md`, `documents/technical_documentation.md`, and `documents/source_current_state.md` with the CSV template/reference download endpoints and sticky-table UI behavior.
- Updated `README.md`, `specification.md`, `documents/technical_documentation.md`, and `documents/source_current_state.md` with preview-first item/movement/reservation CSV import behavior and endpoint contracts.
- Updated `README.md`, `specification.md`, `documents/technical_documentation.md`, and `documents/source_current_state.md` with the new Projects quick-parser preview endpoint and workflow.
- Updated `README.md`, `specification.md`, `documents/technical_documentation.md`, and `documents/source_current_state.md` with the new BOM preview endpoint and preview-first reconciliation workflow.
- Updated `specification.md`, `documents/technical_documentation.md`, and `documents/source_current_state.md` with reservation override precedence, RFQ split-order ownership, and effective gap-analysis `target_date` behavior.
- Updated `documents/technical_documentation.md` and `documents/source_current_state.md` with the unified Movements entry workflow, `CatalogPicker` rollout, and movement-row location inheritance behavior.

### Tests

- Added backend API regression coverage for:
  - malformed preview-confirmation JSON on order import
  - wrong `row_overrides` / `alias_saves` top-level JSON shapes
  - missing required reservation override keys
  - out-of-range movement override row references
- Added frontend Vitest coverage for:
  - `CatalogPicker` syncing external single-select changes while open
  - movement-entry location inheritance when adding new rows
  - preview state helpers preserving explicit cleared selections and formatting user-visible action errors

- Added backend regression coverage for:
  - started committed projects remaining in the planning pipeline
  - planning analysis for in-flight committed projects with past `planned_start`
  - RFQ auto-confirm persisting a planning start date
  - RFQ linked-order assignment/reassignment/clear behavior
  - RFQ batch creation with an explicit planning `target_date`
- Added backend regression coverage for:
  - blocking manual order `project_id` reassignment when an `ORDERED` RFQ line owns the order
  - clearing stale `linked_order_id` values when RFQ lines are saved back to non-`ORDERED` states
- Added backend integration coverage for:
  - header-only BOM template CSV downloads for items, inventory, orders, and reservations
  - live reference CSV downloads for items, inventory, orders, and reservations
- Added backend integration coverage for catalog search:
  - typed result payloads across item/assembly/project search
  - item alias matches
  - invalid type rejection
- Added backend integration coverage for orders import preview / preview-confirmation override flow.
- Added backend integration coverage for:
  - items import preview and alias override confirmation
  - inventory import preview and preview-confirmation item overrides
  - reservations import preview and preview-confirmation target overrides
- Added backend integration coverage for project requirement quick-parser preview.
- Added backend integration coverage for:
  - BOM preview exact/review/unresolved classification
  - BOM analyze avoiding supplier creation side effects for direct canonical items
- Added backend regression coverage for:
  - reservation import commit honoring an `assembly_id` override over stale raw `item_id` text
  - RFQ-owned order splits keeping dedicated `project_id` only on the original linked row
  - gap-analysis returning the effective planning `target_date` when callers omit one
- Added backend API coverage for gap-analysis returning the effective planning `target_date`.
- Backend suite executed: `uv run python -m pytest -q` -> `122 passed`.
- Frontend test suite executed: `npm run test` -> `3 passed`.
- Frontend production build executed: `npm.cmd run build`.

## 2026-03-05

### Changed

- Projects requirement-entry productivity improvements:
  - Added searchable item target input on Projects requirements (`item_number #item_id` suggestions) to avoid long dropdown scanning when item count is large.
  - Added bulk requirement text parser (`item_number,quantity` per line) that auto-maps registered items and warns on unregistered item numbers.
  - Added project edit workflow in Projects page (load existing project, update requirement rows/quantities/types, save via update API).
- BOM planning workflow enhancement:
  - Added optional `target_date` to `POST /api/bom/analyze` for date-aware gap analysis.
  - BOM projected availability now includes open orders with `expected_arrival <= target_date` in addition to current net available stock.
  - Added CLI support for date-aware BOM analysis via `bom-analyze --target-date YYYY-MM-DD`.
  - Updated BOM page UI to accept an analysis date and show the effective analysis basis (`target_date` or current availability).
- Project planning gap projection enhancement:
  - Added optional `target_date` query support to `GET /api/projects/{project_id}/gap-analysis`.
  - Project gap analysis now uses the same future-arrival projection basis as BOM analysis.
- Pre-PO purchasing workflow enhancement:
  - Added persistent `purchase_candidates` table and API/CLI workflows for shortage tracking before PO creation.
  - Added endpoints to create candidates from BOM or project gap analyses and to update candidate status.
  - Added a dedicated frontend `Purchase Candidates` page and BOM-page `Save Shortages` action.

### Fixed

- Projects requirement bulk parser now disambiguates duplicate `item_number` values across manufacturers.
  - Duplicate matches are marked as ambiguous/unregistered instead of silently binding to an arbitrary `item_id`.
- Projects requirement free-text `#<id>` parsing now validates parsed IDs against loaded item/assembly options before marking rows as matched.
  - Invalid or unknown IDs remain unregistered client-side, preventing avoidable backend foreign-key errors on save.

- Frontend reservation/planning UX clarification:
  - Renamed navigation label from `Reserve` to `Reservations`.
  - Reservations page title/help text now explicitly distinguishes execution-time reservations from project planning.
  - Projects page help text now explicitly positions Projects as future-demand planning before reservation execution.
- Reservations page entry workflow simplification:
  - Removed the separate `Single Reservation` form.
  - Expanded the table-based reservation entry section (single + batch in one place) and increased default row count for faster multi-line input.
- Prevented misleading historical BOM projections by rejecting past `target_date` values for BOM analysis.
  - `target_date < today` now returns `422` with `INVALID_TARGET_DATE`.
- Prevented misleading historical project-gap projections by rejecting past `target_date` values in project gap analysis (`422`, `INVALID_TARGET_DATE`).
- BOM page `Save Shortages` now catches API failures and surfaces a user-visible error message instead of failing silently.
- Item deletion/update reference detection now includes `purchase_candidates`.
  - Deleting an item referenced by a purchase candidate now returns controlled domain/API error handling (`ITEM_REFERENCED`) instead of bubbling raw SQLite FK errors.

### Tests

- Added backend service regression tests for BOM date-aware analysis and past-date validation.
- Added backend API integration tests for `/api/bom/analyze` with and without `target_date`.
- Added backend service/API regression coverage for project-gap `target_date` projection and purchase-candidate create/list/update flows.
- Replaced hardcoded near-future target dates in target-date tests with a deterministic far-future value to avoid time-dependent failures.
- Added backend service regression coverage for item deletion blocked by `purchase_candidates` references.

# Change Log

This file tracks meaningful changes to code, behavior, and documentation.

Format style: Keep a simple date-based log while repository versioning policy is being finalized.

## 2026-03-04

### Changed

- Item-centric flow tracing workflow:
  - Added `GET /api/items/{item_id}/flow` to provide a single timeline with stock increases/decreases and reasons.
  - Timeline merges historical stock-changing transactions with forward-looking expected arrivals (orders) and reservation deadlines (demand).
  - Added Item List row action `Flow` to open the timeline panel and show when/how many/why for the selected item.

- Frontend workflow visibility update:
  - Added an `Orders` count column to the Orders page `Imported Quotations` table so users can immediately see how many order rows are linked to each quotation.

- Snapshot filtering enhancement:
  - Added a dedicated description-substring filter on the Snapshot page (`description contains`) so users can narrow rows by terms like `kinematic` in item descriptions.
  - Extended snapshot API row payloads to include item `description`, enabling description-aware filtering in the frontend.

- Missing-item registration compatibility update:
  - Clarified contract/docs that `resolution_type` is canonical, while legacy `row_type` remains accepted as an alias in row payloads.
  - Backend request schema now normalizes `row_type=item` to `resolution_type=new_item` for `POST /api/register-missing/rows`.

- Orders reliability/scalability upgrade (Phase 2):
  - Added durable lineage storage table `order_lineage_events` to persist split/merge/arrival lineage events with timestamped metadata.
  - Added `POST /api/orders/merge` to merge two compatible open rows (`item_id`, `quotation_id`, `ordered_item_number`) into one open row while preserving CSV/DB consistency.
  - Added `GET /api/orders/{order_id}/lineage` so traceability views and audits can consume persisted lineage instead of inferring from mutable order rows.
  - Extended split ETA update flow to append lineage events and hardened validation (`split_quantity` must be integer, positive, and split-safe).
  - Added backend API/service regression coverage for merge + lineage behavior.

### Fixed

- Item flow stock delta accuracy:
  - Updated transaction-to-stock delta mapping so allocation-only `RESERVE` logs (with `from_location`/`to_location` as `NULL`) no longer appear as physical stock decreases in `GET /api/items/{item_id}/flow`.
  - Legacy reserve transactions that explicitly move into/out of `STOCK` are still reflected as stock deltas.
  - Added backend regression coverage for reservation create/release flow timeline to prevent double-counting against reservation deadline demand.

### Tests

- Backend test suite executed with `uv run python -m pytest`.
- Frontend production build executed successfully.

## 2026-03-02

### Changed

- Frontend list UX improvements:
  - Added sortable table headers to `Order List` on the Orders page.
  - Made the `Order List` section collapsible (collapsed by default) to reduce scrolling before reaching `Imported Quotations`.
  - Added an `Imported Quotations` table to the Orders page to surface existing quotation records from the backend listing API.
  - Added client-side sorting for Imported Quotations columns (ID, supplier, quotation number, issue date, pdf link).
  - Added filter controls for Imported Quotations, including dedicated quotation-number search.
  - Orders-page import and arrival actions now revalidate both `/orders` and `/quotations` SWR caches so the `Imported Quotations` section reflects newly created quotations immediately after mutations.
  - Added sortable table headers to `Item List` on the Items page.
  - Item List URL column now renders active clickable external links.
  - Dashboard overdue widget now supports keyword filtering and an expanded table view to inspect all matching overdue orders (while still keeping the top summary list).

- Clarified missing-item registration semantics in docs: the CSV `supplier` column is supplier-alias scope (not manufacturer), and `new_item` rows default manufacturer to `UNKNOWN`.
- Added missing-item registration support for manufacturer input: `new_item` rows can now specify `manufacturer_name` (or `manufacturer`) in CSV; blank still defaults to `UNKNOWN`.
- Fixed `/api/register-missing/rows` schema to accept manufacturer input (`manufacturer_name`, plus `manufacturer` alias), so JSON row registration now persists manufacturer instead of dropping it.
- Updated missing-item output behavior for unregistered order batch import.
  - Per-file unresolved rows are no longer left beside quotation CSV files.
  - A single consolidated register CSV is generated per batch run under `quotations/unregistered/missing_item_registers/`.
  - Missing-item batch registration now scans that consolidated folder in addition to legacy per-file locations.

### Fixed

- Fixed false missing-item detection in order import when supplier/item alias casing differed from registered values.
  - Supplier resolution now checks existing suppliers case-insensitively before creating a new supplier record.
  - Alias resolution during order import now falls back to case-insensitive `ordered_item_number` matching within the resolved supplier scope.
  - Missing-item registration now reuses the same case-insensitive supplier lookup behavior, preventing duplicate supplier namespaces from case-only variations.
- Fixed false missing-item detection for visually similar SKU text variants during order import (e.g. `B1-E02-10` vs `B1−E02−10`).
  - After exact and case-insensitive alias lookup, order import now performs normalized alias matching (NFKC + dash normalization + whitespace removal) within supplier scope.
- Fixed duplicate rows in consolidated `batch_missing_items_registration_*.csv` outputs.
  - Unregistered batch import now de-duplicates unresolved rows by `(supplier, manufacturer_name, item_number)` across multiple source quotations in the same run.
- Fixed unregistered order CSV discovery to avoid interference from generated missing-item register files.
  - Order batch import now explicitly skips files under `quotations/unregistered/missing_item_registers/`.
- Fixed consolidated missing-item register follow-up regressions.
  - Per-file temporary missing-item filenames are now supplier-prefixed to avoid same-stem collisions across suppliers during a batch run.
  - Batch flow now writes the consolidated register before deleting per-file temporary files, preventing data loss on consolidated-write failures.
  - Corrected batch register filename timestamp generation (`datetime.now`) to avoid runtime `NameError`.
  - Expanded consolidated register discovery glob to include timestamped names (`*_missing_items_registration*.csv`).
  - Consolidated register archive during `register-unregistered-missing` now uses `registered/csv_files/UNKNOWN/` with an explicit warning, instead of treating `missing_item_registers` as a supplier name.
- Fixed unregistered order batch behavior where PDF files could be moved even if the same CSV ended in an error later in the per-file flow.
  - Added atomic per-file filesystem move handling for unregistered import.
  - CSV/PDF moves are now executed as one planned set, with rollback of already moved files if any move fails.
- Clarified and verified missing-items path behavior for unregistered import:
  - when a file returns `missing_items`, source CSV/PDF files remain under `quotations/unregistered/...`.
- Fixed duplicate quotation ingestion risk in order imports.
  - Order import now rejects re-import of the same `(supplier, quotation_number)` when orders already exist for that quotation.
  - API returns conflict error `DUPLICATE_QUOTATION_IMPORT` with duplicated quotation numbers in details.

### Fixed

- Item flow stock delta accuracy:
  - Updated transaction-to-stock delta mapping so allocation-only `RESERVE` logs (with `from_location`/`to_location` as `NULL`) no longer appear as physical stock decreases in `GET /api/items/{item_id}/flow`.
  - Legacy reserve transactions that explicitly move into/out of `STOCK` are still reflected as stock deltas.
  - Added backend regression coverage for reservation create/release flow timeline to prevent double-counting against reservation deadline demand.

### Tests

- Backend test suite executed: `40 passed`.
- Added regression coverage for:
  - case-insensitive supplier lookup reuse for order import and missing-item registration
  - case-insensitive alias matching for order import
  - dash-variant/normalized alias matching for order import
  - preserving source CSV/PDF when unregistered import returns `missing_items`
  - rollback safety when a CSV move fails after PDF move started (no leaked PDF relocation)
  - rejecting duplicate quotation re-import for the same supplier

## 2026-03-02

### Changed

- Reservation architecture reconstructed for long-term scalability and traceability:
  - reservation creation no longer moves stock from `STOCK` to `RESERVED`
  - release no longer moves stock back to `STOCK`
  - consume now decrements physical inventory at allocated locations
  - added `reservation_allocations` table to represent active/released/consumed allocation rows
- Reservation/project/BOM availability checks now use net available quantity (`on_hand - active_allocations`) instead of `STOCK` singleton assumptions.
- Reservation undo behavior updated to resolve and release allocation rows instead of reversing `RESERVED` movement.

### Docs

- Updated `specification.md` reservation and movement semantics to allocation-based behavior.
- Updated `documents/technical_documentation.md` with reservation allocation architecture notes.
- Updated `documents/source_current_state.md` reservation behavior section.

## 2026-03-01

### Added

- `documents/team_onboarding.md` with step-by-step setup for team members:
  - local clone
  - `uv` backend environment setup
  - `npm` frontend install
  - init/run/verify/test workflow
- Root `README.md` with project overview, setup, run, testing, and documentation pointers.
- `documents/technical_documentation.md` with:
  - software architecture overview
  - inventory/undo sequence diagram
  - ER diagram
  - maintenance guidance
- `AGENTS.md` application update workflow section (implementation -> tests -> docs).
- API capability endpoint:
  - `GET /api/auth/capabilities`
  - reports auth mode and planned RBAC roles metadata.
- New docs in `documents/`:
  - `team_onboarding.md`
  - `source_current_state.md`
  - `change_log.md` (this file)

### Changed

- Frontend workflow visibility update:
  - Added an `Orders` count column to the Orders page `Imported Quotations` table so users can immediately see how many order rows are linked to each quotation.

- Snapshot filtering enhancement:
  - Added a dedicated description-substring filter on the Snapshot page (`description contains`) so users can narrow rows by terms like `kinematic` in item descriptions.
  - Extended snapshot API row payloads to include item `description`, enabling description-aware filtering in the frontend.

- Requirements/specification updates (`specification.md`):
  - local-first PoC with forward compatibility to multi-user
  - auth stance: PoC no auth, RBAC planned (`admin`, `operator`, `viewer`)
  - timezone fixed to JST
  - scale targets set to items=10,000 / orders=5,000 / transactions~100,000
  - requirement precedence defined:
    1. specification
    2. technical documentation
    3. code behavior
  - reservation policy updated to allow partial release/consume
  - assembly policy clarified as advisory now, enforceable checks in future mode
  - QA gate and release/compliance posture sections added
  - file management section cleaned to canonical directory tree
- Technical documentation (`documents/technical_documentation.md`) aligned to the same baseline and QA policy.

- Backend reservation behavior:
  - partial release/consume implemented in service layer
  - API release/consume endpoints accept optional quantity and note payload
  - CLI `release-reservation` and `consume-reservation` now support `--quantity` and `--note`
- Frontend reservation UI:
  - release/consume actions now support partial quantity input.

### Fixed

- Reservation full-release/full-consume implementation adjusted to respect DB constraint `reservations.quantity > 0` by preserving original quantity on terminal status rows.
- Fixed unregistered batch import failure where non-canonical `pdf_link` paths were incorrectly rejected by manual-import validation.
  - Unregistered batch flow now allows non-canonical path text and resolves/normalizes PDF links in the batch post-processing step.
- Fixed API route conflict causing `Items Import History` to show `Request validation failed`.
  - `GET /api/items/import-jobs` no longer collides with `GET /api/items/{item_id}`.
- Fixed manual order import UX where HTTP 422 failures could appear as "no response" in UI.
  - Orders page now displays explicit import error messages and guidance when `pdf_link` is non-canonical for manual import.
- Fixed unregistered batch import failures for supplier CSV date formats like `YYYY/M/D`.
  - Date normalization now accepts slash/flexible formats and stores normalized `YYYY-MM-DD`.
- Fixed false validation failures from trailing blank CSV rows in order import.
  - Fully empty rows are now skipped.
- Prevented accidental automatic creation of unresolved `UNKNOWN` items from missing-item templates.
  - Missing-item registration now rejects `new_item` rows when category/url/description are all blank.
  - Missing-item batch registration is now file-atomic via savepoints (no partial apply within a file on error).

### Fixed

- Item flow stock delta accuracy:
  - Updated transaction-to-stock delta mapping so allocation-only `RESERVE` logs (with `from_location`/`to_location` as `NULL`) no longer appear as physical stock decreases in `GET /api/items/{item_id}/flow`.
  - Legacy reserve transactions that explicitly move into/out of `STOCK` are still reflected as stock deltas.
  - Added backend regression coverage for reservation create/release flow timeline to prevent double-counting against reservation deadline demand.

### Tests

- Backend test suite executed: `33 passed`.
- Frontend production build executed successfully.
- Added test coverage for:
  - auth capability endpoint
  - partial reservation release/consume behavior (API + service)
  - invalid partial quantity handling
  - unregistered batch import with `quotations/unregistered/...` `pdf_link`
  - items import-jobs listing endpoint route behavior
  - slash-date order import acceptance
  - unresolved missing-item row rejection

## Notes

- Formal semantic versioning and release tags can be adopted once GitHub release workflow is started.
- Recommended next step: map this log format to `vX.Y.Z` releases and attach migration notes per release.

## 2026-03-02 (UI order/quotation maintenance)

### Added

- Orders API endpoints:
  - `DELETE /api/orders/{order_id}`
  - `DELETE /api/quotations/{quotation_id}`
- Orders frontend UI actions:
  - delete order from `Order List`
  - edit quotation `issue_date` / `pdf_link`
  - delete quotation (and linked orders)

### Changed

- Frontend workflow visibility update:
  - Added an `Orders` count column to the Orders page `Imported Quotations` table so users can immediately see how many order rows are linked to each quotation.

- Snapshot filtering enhancement:
  - Added a dedicated description-substring filter on the Snapshot page (`description contains`) so users can narrow rows by terms like `kinematic` in item descriptions.
  - Extended snapshot API row payloads to include item `description`, enabling description-aware filtering in the frontend.

- Quotation update flow now synchronizes matching source order CSV rows (`issue_date`, `pdf_link`) with DB updates.
- Order delete and quotation delete flows now synchronize matching rows in quotation CSV files so CSV and DB remain consistent.
- Fixed order CSV maintenance targeting for duplicate item rows: `update_order`/`delete_order` now update/delete only the CSV row corresponding to the target order identity instead of fan-out matching all duplicate `(supplier, quotation_number, item_number)` rows.
- Hardened quotation deletion guard: `delete_quotation` now returns conflict when any linked order is `Arrived`, preventing bypass of arrived-order immutability.

### Fixed

- Item flow stock delta accuracy:
  - Updated transaction-to-stock delta mapping so allocation-only `RESERVE` logs (with `from_location`/`to_location` as `NULL`) no longer appear as physical stock decreases in `GET /api/items/{item_id}/flow`.
  - Legacy reserve transactions that explicitly move into/out of `STOCK` are still reflected as stock deltas.
  - Added backend regression coverage for reservation create/release flow timeline to prevent double-counting against reservation deadline demand.

### Tests

- Added backend coverage for quotation update/delete CSV+DB synchronization and API delete endpoints.

## 2026-03-02 (snapshot usability: sort/filter/search)

### Added

- Snapshot frontend UX controls:
  - free-text quick search (item number, location, category, quantity)
  - location filter
  - category filter
  - per-column sorting for item/location/quantity/category
  - clear-filters action and filtered-row count display

### Changed

- Frontend workflow visibility update:
  - Added an `Orders` count column to the Orders page `Imported Quotations` table so users can immediately see how many order rows are linked to each quotation.

- Snapshot filtering enhancement:
  - Added a dedicated description-substring filter on the Snapshot page (`description contains`) so users can narrow rows by terms like `kinematic` in item descriptions.
  - Extended snapshot API row payloads to include item `description`, enabling description-aware filtering in the frontend.

- Snapshot table now defaults to quantity ascending so low-stock items can be spotted sooner for purchasing decisions.
- Snapshot summary now shows `filtered / total` row counts for situational awareness while planning.
- Snapshot page now includes a low-stock/shortage-only toggle with a configurable quantity threshold (`quantity <= threshold`) for faster purchase candidate extraction.
- Snapshot location/category filter "All" sentinel now uses a non-data value (`__ALL__`) to avoid collisions with real category/location values such as `all`.

### Fixed

- Item flow stock delta accuracy:
  - Updated transaction-to-stock delta mapping so allocation-only `RESERVE` logs (with `from_location`/`to_location` as `NULL`) no longer appear as physical stock decreases in `GET /api/items/{item_id}/flow`.
  - Legacy reserve transactions that explicitly move into/out of `STOCK` are still reflected as stock deltas.
  - Added backend regression coverage for reservation create/release flow timeline to prevent double-counting against reservation deadline demand.

### Tests

- Frontend production build executed successfully.

## 2026-03-02 (reservation consistency and ARRIVAL undo regression fix)

### Fixed

- Prevented silent reservation state corruption in allocation-based flows:
  - `release_reservation` and `consume_reservation` now validate that the sum of `ACTIVE` `reservation_allocations` is sufficient for the requested quantity before mutating reservation rows.
  - When active allocations are missing/insufficient, both operations now fail with `RESERVATION_ALLOCATION_INCONSISTENT` instead of updating reservation status/quantity without corresponding allocation/inventory effects.
- Fixed ARRIVAL undo regression introduced by allocation-aware availability checks:
  - `undo_transaction` for `ARRIVAL` now computes reversible quantity from `STOCK` on-hand only (the location actually decremented during undo), preventing false `INSUFFICIENT_STOCK` failures when non-STOCK inventory exists.

### Fixed

- Item flow stock delta accuracy:
  - Updated transaction-to-stock delta mapping so allocation-only `RESERVE` logs (with `from_location`/`to_location` as `NULL`) no longer appear as physical stock decreases in `GET /api/items/{item_id}/flow`.
  - Legacy reserve transactions that explicitly move into/out of `STOCK` are still reflected as stock deltas.
  - Added backend regression coverage for reservation create/release flow timeline to prevent double-counting against reservation deadline demand.

### Tests

- Added backend service tests covering:
  - release failure when reservation has no/insufficient `ACTIVE` allocations
  - consume failure when reservation has no/insufficient `ACTIVE` allocations
  - ARRIVAL undo partial behavior when most inventory has moved out of `STOCK`


## 2026-03-02 (movement/reservation CSV import + assembly-aware reservation expansion)

### Added

- API endpoints:
  - `POST /api/inventory/import-csv`
  - `POST /api/reservations/import-csv`
- Backend services for CSV imports:
  - movement CSV -> normalized batch operations
  - reservation CSV -> direct item reservations or assembly-expanded component reservations
- Frontend upload forms on Movements and Reserve pages with explicit column format hints.

### Changed

- Frontend workflow visibility update:
  - Added an `Orders` count column to the Orders page `Imported Quotations` table so users can immediately see how many order rows are linked to each quotation.

- Snapshot filtering enhancement:
  - Added a dedicated description-substring filter on the Snapshot page (`description contains`) so users can narrow rows by terms like `kinematic` in item descriptions.
  - Extended snapshot API row payloads to include item `description`, enabling description-aware filtering in the frontend.

- Assembly feature is now used directly in reservation CSV import by expanding assembly rows to component reservation rows, improving workflow efficiency without turning assemblies into enforced inventory constraints.
- CSV movement/reservation imports now convert non-numeric numeric fields (`item_id`, `quantity`, `project_id`, `assembly_quantity`) into `AppError` validation responses (`422`) instead of surfacing unhandled `ValueError` as internal errors.

## 2026-03-04 (CSV sibling-order bug fixes for split/merge)

### Fixed

- Fixed merge CSV synchronization to compute source/target sibling occurrence matchers before deleting source DB row, and adjusted target occurrence handling when source precedes target so merged quantity/ETA updates apply to the correct CSV row.
- Fixed split CSV insertion ordering so newly created split rows are appended after the existing sibling block (order-id occurrence order), preventing row-identity drift when splitting a non-final sibling row.

### Fixed

- Item flow stock delta accuracy:
  - Updated transaction-to-stock delta mapping so allocation-only `RESERVE` logs (with `from_location`/`to_location` as `NULL`) no longer appear as physical stock decreases in `GET /api/items/{item_id}/flow`.
  - Legacy reserve transactions that explicitly move into/out of `STOCK` are still reflected as stock deltas.
  - Added backend regression coverage for reservation create/release flow timeline to prevent double-counting against reservation deadline demand.

### Tests

- Backend test suite executed successfully: `73 passed`.
- Added targeted regression coverage for:
  - merging non-first sibling rows without deleting/updating the wrong CSV entry
  - splitting a non-final sibling row while preserving sibling-block row order in CSV

## 2026-03-04 (UI navigation improvements for Item Flow / Order Context)

### Changed

- Items page ergonomics:
  - Added expand/collapse controls to `Item List` to reduce page-height occupation when many items exist.
  - `Flow` action now auto-collapses `Item List` and smooth-scrolls to `Item Increase/Decrease Timeline` for quicker access.
- Orders page ergonomics:
  - `Order List` row-level `Details` now auto-collapses `Order List` and smooth-scrolls to `Order Context`.
  - Added `Details` action in `Imported Quotations` to open `Order Context` directly via a linked order, removing the need to expand `Order List` first when reviewing quotation details.

### Tests

- Frontend production build executed successfully.
