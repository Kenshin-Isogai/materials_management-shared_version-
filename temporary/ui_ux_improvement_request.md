# UI/UX Improvement Request Sheet

**Date:** 2026-03-06
**Requested by:** Product Owner
**Project:** Materials Management Application
**Priority legend:** P0 = Critical / P1 = High / P2 = Medium / P3 = Nice-to-have

---

## Purpose

This sheet refines the UI/UX improvement request into an implementation-ready document for the current codebase.

The original product direction is valid:

- Default to **Comprehend mode** on every page.
- Keep **Execute mode** features opt-in.
- Solve spelling inconsistency and canonical naming drift at the source and during import.

This document also adds engineering constraints so the request can be delivered incrementally without a risky cross-cutting rewrite.

---

## Governing Principles

### Two user modes

| Mode | Goal | Primary needs |
|---|---|---|
| **Comprehend** | Confirm stock, browse records, inspect future inventory state | Fast tables, broad visibility, free-text filtering, zero forced scoping |
| **Execute** | Plan projects, reconcile imports, create RFQs, place orders | Guided selection, scoped workflows, reconciliation, data-entry assistance |

### Non-negotiable rules

1. Every page opens in **Comprehend mode**.
2. Default state is **unscoped** and shows all relevant data.
3. Execute-mode helpers must be triggered only by explicit user action.
4. Read-only table filtering remains permissive and fast. Do not replace broad search inputs with restrictive pickers.
5. Each change request must be independently shippable.

---

## Engineering Constraints and Clarifications

### 1. Import preview API strategy

Do not start with one overly generic `POST /api/import/preview` contract for every flow.

Use:

- A shared backend reconciliation service
- Flow-specific preview endpoints with flow-specific validation contracts

Recommended shape:

- `POST /api/items/import-preview`
- `POST /api/inventory/import-preview`
- `POST /api/orders/import-preview`
- `POST /api/reservations/import-preview`
- Project bulk parser preview endpoint
- BOM spreadsheet preview endpoint

Rationale:

- Each import flow already has different semantics and validation rules.
- A shared service is reusable.
- Flow-specific endpoints reduce frontend branching and backend ambiguity.

### 2. Alias model

Do not introduce a single universal alias table unless a concrete need appears across multiple entity types.

Use this decision order:

1. Reuse existing `supplier_item_aliases` where supplier-scoped ordered names already exist.
2. Add entity-specific alias tables only when the behavior and uniqueness rules are clear.
3. Keep project, assembly, supplier, and item aliasing separate unless proven otherwise.

Rationale:

- Supplier item aliases have different semantics from project-name aliases or assembly-name aliases.
- A generic alias table is likely to blur constraints and complicate reconciliation logic.

### 3. Template download format

Do not place import rows and reference rows in the same CSV file.

Minimum acceptable delivery:

- `Download Template CSV`: header-only import template with the exact required columns
- `Download Reference CSV`: live canonical values from the current database

Optional enhanced delivery:

- Single `.xlsx` workbook with separate `template` and `reference` sheets

Rationale:

- Plain CSV does not support multiple sheets.
- Appending reference rows below the template risks accidental re-import of example/reference data.

### 4. Performance targets

Performance numbers in this sheet are target budgets, not guarantees until benchmarked.

Before enforcing them as acceptance gates, define:

- dataset size
- browser target
- hardware baseline
- whether catalog data is prefetched or queried on demand

### 5. Encoding and text fidelity

This document should be stored and edited as UTF-8. Remove corrupted symbols or mojibake before implementation work begins.

---

## Change Request 1: Reconciliation Preview for Imports

**Priority:** P0
**Pages affected:** ItemsPage, InventoryPage, OrdersPage, ReservationsPage, ProjectsPage, BomPage
**Goal:** Intercept spelling drift before data is committed.

### Product requirements

1. Every CSV or bulk text import flow must provide a preview step before commit.
2. The preview step must classify each imported reference as:
   - exact match
   - high-confidence match
   - needs review
   - unresolved
3. If all rows are exact or high-confidence matches above the auto-accept threshold, allow one-click confirmation.
4. Users must be able to manually select a canonical target for unresolved or suspicious rows.
5. When a manual mapping reflects a reusable supplier-scoped ordered name, offer to save it as a supplier item alias.

### Preview table

| Raw Input | Suggested Canonical Match | Confidence | Status | User Action |
|---|---|---|---|---|
| `ThorLabs KM100` | `KM100 (Thorlabs Inc.)` | 95% | Auto-acceptable | Confirm |
| `Sigma Koki SH-1` | `SH-1 (Sigma Koki)` | 82% | Review | Accept or change |
| `Custom Lens XYZ` | none | none | Unresolved | Search catalog or create new |

### Matching rules

- Prefer existing alias tables before fuzzy matching.
- Match against relevant canonical fields only for the target flow.
- Suggested techniques:
  - normalized exact match
  - token normalization
  - supplier alias lookup
  - fuzzy ranking with `rapidfuzz`

Suggested confidence bands:

- `>= 95`: auto-acceptable
- `70 to 94`: review
- `< 70`: unresolved

Thresholds must be configurable in backend settings or constants.

### Backend design

Shared service responsibilities:

- normalize candidate text
- retrieve candidate pool
- score and rank matches
- return top suggestions with match rationale

Suggested shared function:

- `preview_reconciliation(flow_type, rows) -> list[preview_row]`

Suggested helper:

- `match_catalog_entity(entity_kind, raw_value, context=None) -> list[candidate]`

Suggested endpoints:

- `POST /api/items/import-preview`
- `POST /api/inventory/import-preview`
- `POST /api/orders/import-preview`
- `POST /api/reservations/import-preview`

For ProjectsPage and BomPage, use preview endpoints shaped to their existing parser payloads.

### Rollout guidance

Do not deliver all flows at once.

Recommended rollout:

1. Orders import preview
2. Items import preview
3. Inventory and reservations
4. Project bulk parser and BOM spreadsheet entry

### Acceptance criteria

- [ ] Each import flow has a preview before commit.
- [ ] High-confidence, low-risk imports can still be confirmed in one action.
- [ ] Review and unresolved rows are visually distinct.
- [ ] Manual correction can invoke catalog search.
- [ ] Alias save prompt appears only when the chosen mapping fits the current alias model.
- [ ] Preview step does not add more than 1 second on the benchmark dataset for clean imports.

---

## Change Request 2: Reusable `<CatalogPicker>` Component

**Priority:** P0
**Pages affected:** ProjectsPage, BomPage, OrdersPage, ReservationsPage, AssembliesPage
**Goal:** Replace fragile free-text entry in write flows with a consistent searchable selector.

### Product requirements

The component must support:

- typeahead search
- grouped results by entity type
- keyboard navigation
- single-select and multi-select modes
- recent selections stored in `localStorage`
- configurable allowed entity types per caller

It must not replace broad filter/search bars used for table browsing.

### UI behavior

- Search opens inline or as a popover depending on context.
- Results are grouped by `Items`, `Assemblies`, `Suppliers`, `Projects`.
- Each result shows enough metadata to distinguish near-duplicates.
- Escape closes the picker.
- Enter selects the highlighted row.

### Backend design

Suggested endpoint:

- `GET /api/catalog/search?q=...&types=item,assembly,supplier,project`

Search must:

- respect existing supplier item aliases where relevant
- return typed results
- include a display label and summary metadata

### Rollout guidance

Do not replace all free-text fields in one pass.

Recommended rollout:

1. ProjectsPage requirement selector
2. AssembliesPage component selector
3. BOM row item selector
4. Reservations and orders write forms
5. Reuse inside import reconciliation previews

### Acceptance criteria

- [ ] All targeted write-flow selectors use `<CatalogPicker>`.
- [ ] Read-only table filters remain free-text.
- [ ] Keyboard navigation works end-to-end.
- [ ] Recent selections persist in browser `localStorage`.
- [ ] Search remains responsive on the agreed benchmark dataset.

---

## Change Request 3: Downloadable Import Template and Reference Data

**Priority:** P1
**Pages affected:** All pages with import functionality
**Goal:** Let users build import files from current canonical vocabulary.

### Required behavior

Add two actions next to each import area:

- `Download Template CSV`
- `Download Reference CSV`

### Template CSV

- UTF-8 with BOM for Excel compatibility
- exact import headers for that flow
- no sample rows unless explicitly marked as non-importable and separated from live import data

### Reference CSV

- generated on demand from current database state
- includes canonical values relevant to that import flow

Examples:

- item import reference: item number, manufacturer
- order import reference: supplier, canonical item number, known ordered aliases where appropriate
- project import reference: item numbers, assembly names

### Optional enhanced delivery

If `.xlsx` generation is feasible, provide one workbook with:

- `template` sheet
- `reference` sheet

This can be a later phase and is not required for first delivery.

### Backend design

Suggested endpoints:

- `GET /api/items/import-template`
- `GET /api/items/import-reference`
- `GET /api/orders/import-template`
- `GET /api/orders/import-reference`
- `GET /api/reservations/import-template`
- `GET /api/reservations/import-reference`

### Acceptance criteria

- [ ] Every import form exposes template and reference downloads.
- [ ] Reference files reflect current DB state at request time.
- [ ] CSV files open correctly in Excel with Japanese text intact.

---

## Change Request 4: Command Palette

**Priority:** P1
**Pages affected:** AppShell
**Goal:** Provide fast navigation and action launching for power users.

### Shortcut policy

Because `Ctrl+K` often conflicts with browser behavior, use:

- `Ctrl+/` on Windows and Linux
- `Cmd+K` on macOS

`Ctrl+K` can be added later only if conflict handling is acceptable.

### Search targets

- pages
- entities
- common actions

Examples:

- `Items`
- `Project Alpha`
- `Import orders CSV`
- `Take snapshot`

### Behavior

- opens from any page
- instant filtering
- grouped results
- Enter navigates or executes
- Escape closes

### Acceptance criteria

- [ ] Global shortcut works on supported platforms.
- [ ] Results are grouped and navigable by keyboard.
- [ ] Selecting an entity opens the relevant page with useful context applied.
- [ ] Shortcut choice does not break expected browser behavior on the benchmark browsers.

---

## Change Request 5: Table UX Improvements

**Priority:** P1
**Pages affected:** Table-heavy pages across the app
**Goal:** Improve scanability and batch operations without changing default browse behavior.

### 5a. Sticky table headers

- column headers remain visible during vertical scroll

### 5b. Bulk selection and action bar

- checkbox column on major write-oriented tables
- floating action bar appears only when rows are selected
- actions must be table-specific

Start with:

- Items
- Orders
- Reservations

Do not force bulk-selection patterns onto purely analytical tables unless there is a clear action model.

### 5c. Column pinning

- lower priority
- begin with one important column such as `item_number`

### 5d. Saved filter presets

- lower priority
- store named presets in `localStorage`

### Acceptance criteria

- [ ] Sticky headers work on major table pages.
- [ ] Bulk selection works on initial target tables.
- [ ] At least one key column can be pinned where horizontal scroll is common.
- [ ] Filter presets can be saved and restored where implemented.

---

## Change Request 6: Active Project Context Selector

**Priority:** P2
**Pages affected:** AppShell header, PlanningPage, RfqPage, OrdersPage, InventoryPage, SnapshotPage
**Goal:** Provide explicit execute-mode scoping without changing default browse behavior.

### Required behavior

- header control displays `Viewing: All` by default
- no project context is applied on initial load
- project context changes only after explicit user selection
- active scoping is visually obvious and easy to clear

### State rule

Default behavior on refresh must remain `All`.

Do not persist project context across refresh unless a later requirement explicitly changes that rule.

### Acceptance criteria

- [ ] Every page defaults to `All`.
- [ ] Scoped behavior appears only after explicit selection.
- [ ] Clear action is always visible while scoped.
- [ ] No page regresses when no project is selected.

---

## Change Request 7: Dashboard Enhancements

**Priority:** P2
**Pages affected:** DashboardPage and AppShell

### 7a. Notification bell

- persistent bell in the header
- badge count for alert summary
- dropdown with links to relevant pages
- dashboard keeps the full detail view

### 7b. "What's Next?" project cards

- appears below existing alert content
- collapsible
- collapse state stored in `localStorage`

### Acceptance criteria

- [ ] Bell is visible on all pages.
- [ ] Alert dropdown provides useful shortcuts.
- [ ] Existing dashboard alert content remains primary and unchanged at the top.
- [ ] "What's Next?" section is collapsible and remembers its state.

---

## Change Request 8: Planning Page Visual Enhancements

**Priority:** P2
**Pages affected:** PlanningPage

### 8a. Timeline strip

- horizontal project strip above the existing analysis table
- color-coded by gap severity
- clicking a bar focuses the related table section

### 8b. Analysis diff toggle

- opt-in
- default off
- adds delta indicators when enabled

### Acceptance criteria

- [ ] Existing table remains the primary source of detail.
- [ ] Visual enhancements do not replace the table.
- [ ] Diff view is off by default and non-destructive to existing layout.

---

## Change Request 9: Import Flow Convenience Improvements

**Priority:** P3
**Pages affected:** Import-capable pages, especially OrdersPage

### 9a. Drag-and-drop upload zone

- visible drop zone for CSV files
- supports click-to-browse and drag-and-drop
- first 5 rows preview before entering the reconciliation flow

### 9b. Quotation folder detection indicator

- OrdersPage shows counts of new unregistered quotation CSV files by supplier
- check on page load and optionally by polling
- provides a direct preview/import action

### Acceptance criteria

- [ ] Drop zone works for click and drag-and-drop.
- [ ] Initial file preview is shown before import preview/commit.
- [ ] OrdersPage shows unregistered quotation file counts by supplier.

---

## Recommended Delivery Order

This request should be delivered as a roadmap, not as one bundled change.

| Phase | Changes | Notes |
|---|---|---|
| 1 | CR3, CR5a | Quick wins with low architectural risk |
| 2 | Catalog search backend, `<CatalogPicker>` first rollout | Shared foundation for later write flows |
| 3 | CR1 import preview for one or two flows | Start with highest-value imports before expanding |
| 4 | Remaining CR1 rollout, CR5b | Extend preview and introduce batch actions |
| 5 | CR4, CR6, CR7 | App-shell and workflow enhancements |
| 6 | CR8, CR9 | Polish and advanced workflow support |

---

## Testing Requirements

For each implemented change request:

1. Add backend unit tests for new matching, preview, or search services.
2. Add API integration tests for each new endpoint.
3. Run manual UI validation on affected pages.
4. Confirm that default Comprehend-mode browsing is not degraded.
5. Run the full backend suite with `uv run python -m pytest` before merge.
6. Perform browser smoke checks on Chrome and Firefox.
7. Where performance targets exist, validate them on the agreed benchmark dataset rather than by assumption.

---

## Documentation Updates Required

For each implemented change request, update:

- `documents/technical_documentation.md`
- `documents/source_current_state.md`
- `documents/change_log.md`
- `specification.md` if behavior or API contracts change

If new endpoints, shared components, or alias rules are added, they must be documented in the same change set.

---

## Summary for Engineering

The highest-value work remains:

1. canonical-name assistance in write flows
2. preview-and-reconcile import workflows
3. low-risk table and import usability wins

The main delivery rule is to avoid a broad rewrite. Build shared services and components where they help, but keep endpoint contracts and rollout plans specific to each workflow.
