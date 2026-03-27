# Provisional Allocation UX Improvement Plan

Last updated: 2026-03-26 (UTC)

## Goal

Support provisional project linkage for long-lead/general-purpose items *before* design/BOM finalization, while keeping existing planning/procurement constraints intact.

## Phase 1 (this change set)

- Add project selection to Reservations page `Reservation Entry` rows.
- Submit optional `project_id` in reservation batch creation payload.
- Display linked project in Reservation List.
- Add backend create-time validation for provided `project_id` to return controlled `PROJECT_NOT_FOUND` errors.

## Phase 2 (next)

- Add a dedicated “Provisional Allocation” entry path on Workspace and/or Orders to reduce context switching.
  - **Implemented (partial):** Orders `Order Details` now offers `Create Provisional Reservation…` that navigates to prefilled Reservations entry fields.
- Allow selecting source type:
  - stock-backed reservation
  - open-order dedication (where ownership is not RFQ/procurement-managed)
- Keep all existing managed-order guardrails and surface them with inline UX guidance.

## Phase 3 (next)

- Add workflow-level summaries:
  - provisional allocations by project
  - uncommitted vs project-dedicated incoming supply
- Add CSV export for provisional allocation review.
  - **Implemented (Reservations page):** `Provisional Allocation Summary` now shows project-level active reserved qty/count plus open incoming dedicated qty and global uncommitted incoming qty, with `Export Summary CSV`.

## Validation approach

1. Frontend type-check and targeted tests.
2. Backend targeted reservation API tests.
3. Runtime smoke check in Docker-first environment (`start-app.ps1`) for user flow:
   - create reservation with project
   - list reservation project linkage
   - release/consume regression check
