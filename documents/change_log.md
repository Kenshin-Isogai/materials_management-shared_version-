# Change Log

This file tracks meaningful changes to code, behavior, and documentation.

Format style: Keep a simple date-based log while repository versioning policy is being finalized.

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

- Quotation update flow now synchronizes matching source order CSV rows (`issue_date`, `pdf_link`) with DB updates.
- Order delete and quotation delete flows now synchronize matching rows in quotation CSV files so CSV and DB remain consistent.
- Fixed order CSV maintenance targeting for duplicate item rows: `update_order`/`delete_order` now update/delete only the CSV row corresponding to the target order identity instead of fan-out matching all duplicate `(supplier, quotation_number, item_number)` rows.
- Hardened quotation deletion guard: `delete_quotation` now returns conflict when any linked order is `Arrived`, preventing bypass of arrived-order immutability.

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

- Snapshot table now defaults to quantity ascending so low-stock items can be spotted sooner for purchasing decisions.
- Snapshot summary now shows `filtered / total` row counts for situational awareness while planning.
- Snapshot page now includes a low-stock/shortage-only toggle with a configurable quantity threshold (`quantity <= threshold`) for faster purchase candidate extraction.
- Snapshot location/category filter "All" sentinel now uses a non-data value (`__ALL__`) to avoid collisions with real category/location values such as `all`.

### Tests

- Frontend production build executed successfully.

## 2026-03-02 (reservation consistency and ARRIVAL undo regression fix)

### Fixed

- Prevented silent reservation state corruption in allocation-based flows:
  - `release_reservation` and `consume_reservation` now validate that the sum of `ACTIVE` `reservation_allocations` is sufficient for the requested quantity before mutating reservation rows.
  - When active allocations are missing/insufficient, both operations now fail with `RESERVATION_ALLOCATION_INCONSISTENT` instead of updating reservation status/quantity without corresponding allocation/inventory effects.
- Fixed ARRIVAL undo regression introduced by allocation-aware availability checks:
  - `undo_transaction` for `ARRIVAL` now computes reversible quantity from `STOCK` on-hand only (the location actually decremented during undo), preventing false `INSUFFICIENT_STOCK` failures when non-STOCK inventory exists.

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

- Assembly feature is now used directly in reservation CSV import by expanding assembly rows to component reservation rows, improving workflow efficiency without turning assemblies into enforced inventory constraints.
- CSV movement/reservation imports now convert non-numeric numeric fields (`item_id`, `quantity`, `project_id`, `assembly_quantity`) into `AppError` validation responses (`422`) instead of surfacing unhandled `ValueError` as internal errors.
