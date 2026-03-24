# Plan: Order ↔ Project Allocation & Linking UI

## Problem

The planning engine calculates project supply needs using both dedicated supply (orders with `project_id` set) and generic supply (stock + orders with `project_id = NULL`). However, the generic supply consumption is **virtual** — it's calculated at planning time but never persisted. This means:

1. Users cannot see a complete picture of "all parts allocated to Project A"
2. Generic orders consumed by a project remain `project_id = NULL`
3. The only way to create procurement batches is from shortage rows, so fully-covered items (covered by generic supply) are invisible to the procurement workflow
4. There is no UI to manually assign `project_id` on orders

Additionally, the Procurement page lacks line-level editing, so even the shortage-to-order linking workflow is incomplete.

## Approach

Three changes, in dependency order:

### 1. Orders Page — Add Project Assignment (manual shortcut)

Add a project selector to the order edit flow so users can directly assign/clear `project_id` on any order.

- Add project selector dropdown to existing order edit UI (alongside `expected_arrival` and `split_quantity`)
- Send `project_id` in existing `PUT /api/orders/{id}` (backend already supports this)
- Handle `ORDER_PROJECT_MANAGED_BY_RFQ` / `ORDER_PROJECT_MANAGED_BY_PROCUREMENT` conflict errors in UI
- Pre-populate with current `project_id` when editing
- This provides the manual fallback for any scenario

### 2. Confirm Allocation — Persist Planning's Virtual Allocation

Add a "Confirm Allocation" action to the Workspace planning board that converts the planning engine's virtual generic-supply consumption into real data:

**Backend: `POST /api/projects/{id}/confirm-allocation`**

- Accepts `target_date` (same date used in the planning board analysis)
- Accepts optional `dry_run: true` for preview mode
- Runs `_build_project_planning_snapshot()` to get the same planning result the user sees
- Iterates over each item's `supply_sources_by_start`:
  - `source_type: "generic_order"` with partial consumption → **split order** (via existing `update_order` with `split_quantity`), then set `project_id` on the consumed portion
  - `source_type: "generic_order"` with full consumption → directly set `project_id` on the order
  - `source_type: "stock"` → create **reservation** with `project_id` (via existing `create_reservation`)
- Returns a preview/result summary:
  ```json
  {
    "orders_assigned": [{"order_id": 42, "item_id": 1, "quantity": 4, "action": "assign"}],
    "orders_split": [{"original_order_id": 42, "new_order_id": 99, "item_id": 1, "assigned_quantity": 4, "remaining_quantity": 2}],
    "reservations_created": [{"reservation_id": 10, "item_id": 2, "quantity": 3}],
    "skipped": [{"item_id": 5, "reason": "already dedicated"}]
  }
  ```

**Frontend: Workspace planning board**

- New "Confirm Allocation" button (enabled when the project has generic supply sources)
- First click → dry_run preview showing what will happen
- Confirm → execute and refresh planning view
- After execution, all previously-generic supply shows as dedicated → planning picture is complete

**Edge cases:**
- Orders already managed by RFQ/procurement lines → skip (cannot reassign)
- `project_id_manual` flag set to 1 for all manual assignments
- If planning snapshot changes between preview and confirm (e.g. another user modified orders), re-run snapshot and compare; abort if material changes detected

### 3. Procurement Page — Add Line Editing

Add per-line editing to the procurement batch detail panel for shortage follow-up:

- Make procurement lines editable inline when a batch is selected
- Editable fields: `status`, `finalized_quantity`, `supplier_name`, `expected_arrival`, `linked_order_id`, `note`
- For `linked_order_id`, reuse lazy-loading order selector pattern from `rfqEditorState.ts`
- Use existing `PUT /api/procurement-lines/{line_id}`
- When status → ORDERED + linked_order_id set, backend auto-assigns `orders.project_id`

### What this enables (end-to-end flow)

```
Workspace: Analyze project at target date
  │
  ├─ Generic supply covers some items → "Confirm Allocation"
  │   → Orders split/assigned, reservations created
  │   → Everything shows as dedicated supply
  │
  ├─ Shortages remain → "Create RFQ From Gaps"
  │   → Procurement batch created
  │   → Procurement page: edit lines, link to orders
  │
  └─ Ad-hoc needs → Orders page: manual project_id assignment
```

## Implementation Notes (needed features)

- Migrating legacy `rfq_batches`/`rfq_lines` data to `procurement_batches`/`procurement_lines`.  There is no data yet in `rfq_batches`/`rfq_lines`, so I think you don't have to consider the compatibility of the migration with existing data.
- Updating Workspace Quoted/Ordered line counts to read from procurement tables
- "Undo allocation" (reversing confirm-allocation; can be done manually via Orders page)

## Todos

1. `orders-project-selector` — Add project selector to Orders page edit flow
2. `confirm-allocation-backend` — New `POST /api/projects/{id}/confirm-allocation` endpoint (dry_run + execute)
3. `confirm-allocation-frontend` — Add Confirm Allocation button + preview to Workspace planning board
4. `procurement-line-editing` — Add inline line editing to Procurement page batch detail
5. `update-docs` — Update documentation (source_current_state, technical_documentation, change_log, specification)

