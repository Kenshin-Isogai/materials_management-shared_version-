# Shared-Server Adaptation Plan

> Status: proposed implementation plan
> Last updated: 2026-03-25
> Scope: user management UI, upload-first batch import, server-managed PDF handling, and browser-delivered generated files

---

## 1. Purpose

This document defines the next implementation phase after the PostgreSQL migration foundation:

- make the application practical for shared-server browser usage
- remove user dependence on direct server-folder access
- remove user dependence on local filesystem paths inside import CSV files
- make generated files downloadable from the browser instead of requiring application-directory access

This plan is intentionally phased so the system can improve without destabilizing existing import logic all at once.

---

## 2. Current State Summary

### 2.1 User management

Current backend state:

- user CRUD endpoints already exist:
  - `GET /api/users`
  - `GET /api/users/{id}`
  - `GET /api/users/me`
  - `POST /api/users`
  - `PUT /api/users/{id}`
  - `DELETE /api/users/{id}`

Current frontend state:

- the frontend only exposes a user selector in `frontend/src/components/AppShell.tsx`
- there is no dedicated UI for creating, editing, activating, or deactivating users

### 2.2 Batch import workflows

Current backend/frontend state:

- Items batch registration and Orders unregistered batch import assume files already exist under server-side workspace folders
- those flows were practical for local development but are not appropriate as the primary UX on a shared server

Current examples:

- Items:
  - `POST /api/items/register-unregistered-batch`
- Orders:
  - `POST /api/orders/import-unregistered`

### 2.3 PDF linkage

Current state:

- manual import accepts `pdf_link` values as blank, filename-only, or canonical workspace-relative server paths
- unregistered batch import can normalize/move PDFs into canonical registered server locations
- quotation rows store the canonical server-relative path after successful registration

Problem for shared-server use:

- browser users should not need to know or type server filesystem paths
- browser users cannot reliably reference a local machine path from a server process

### 2.4 Generated CSV outputs

Current state:

- some outputs already use direct HTTP download responses
- some batch flows still produce artifacts under workspace folders for later handling

Problem for shared-server use:

- users should not be expected to open server directories directly
- generated files should be delivered through browser download or through a managed artifact list

---

## 3. Target Principles

The shared-server version should follow these rules:

1. Users interact through the browser only.
2. Server filesystem layout remains an internal backend concern.
3. Batch input files are uploaded into backend-managed staging/storage.
4. Import CSVs should use logical references such as filenames, not server paths.
5. Generated files should be downloaded through HTTP or listed as managed artifacts in the UI.
6. Existing domain logic should be reused where possible instead of rewriting import logic from scratch.

---

## 4. Recommended Delivery Order

Implement in this order:

1. Add frontend user management UI.
2. Add server-managed upload staging for batch imports.
3. Replace path-based PDF expectations with upload-associated filename resolution.
4. Standardize generated-file delivery as browser downloads or managed artifacts.
5. Deprecate direct folder-operated workflows from the main UI.

This order keeps the changes incremental and reduces the risk of breaking the working PostgreSQL migration foundation.

---

## 5. Phase 1: Frontend User Management

### 5.1 Goal

Allow administrators to create and maintain users from the frontend UI instead of relying on API-only access.

### 5.2 Scope

Add a dedicated Users page in the frontend:

- list users
- create user
- edit display name / role / active state
- deactivate user

### 5.3 Backend changes

No major backend contract change is required because the API already supports this.

Optional small backend additions:

- pagination/filtering improvements on `/api/users`
- optional explicit re-activate endpoint, or allow reactivation through `PUT /api/users/{id}`

### 5.4 Frontend changes

Add:

- `frontend/src/pages/UsersPage.tsx`
- route entry in router
- nav link in `AppShell.tsx`

### 5.5 Acceptance criteria

- an admin/operator can create a new user entirely from the browser
- user picker refreshes correctly after create/update/deactivate
- deactivated users do not remain selectable for mutations

---

## 6. Phase 2: Upload-First Batch Import

### 6.1 Goal

Replace user-managed server-folder placement with browser upload into backend-managed staging.

### 6.2 Recommended UX

#### Items batch

Replace or supplement "Process Pending CSVs" with:

- upload one or more item registration CSV files
- backend stores them into a staging area under server control
- backend runs the existing registration logic from those staged files
- result is shown in the UI with downloadable issue CSVs when needed

#### Orders batch

Replace or supplement "Unregistered Folder Batch" with:

- upload a ZIP package containing:
  - order CSV files
  - related quotation PDFs
- backend extracts the ZIP into a server-managed staging directory
- backend runs the current unregistered import logic against that staged structure

ZIP upload is the best fit for Orders because the current logic already expects a directory-like relationship between CSVs and PDFs.

### 6.3 Backend architecture

Add a staging concept, for example:

- `imports/staging/items/<job-id>/...`
- `imports/staging/orders/<job-id>/...`

Optional persistence layer for visibility:

- `upload_jobs`
- `upload_job_files`
- or a lighter artifact metadata table if needed for history/debugging

### 6.4 Proposed API additions

#### Items

- `POST /api/items/batch-upload`
  - multipart upload for one-or-more CSV files
  - stores to staging
  - optionally executes immediately

#### Orders

- `POST /api/orders/batch-upload`
  - multipart upload for one ZIP file
  - extracts into staging
  - executes existing unregistered import flow

Optional follow-up:

- `GET /api/upload-jobs`
- `GET /api/upload-jobs/{job_id}`
- `GET /api/upload-jobs/{job_id}/artifacts/{artifact_id}`

### 6.5 Reuse strategy

Do not rewrite the current import domain logic first.

Instead:

- keep `service.register_unregistered_item_csvs(...)`
- keep `service.import_unregistered_order_csvs(...)`
- add an adapter layer that materializes uploaded files into the folder layout those services already expect

This minimizes risk.

### 6.6 Acceptance criteria

- users can execute batch import without manual access to server folders
- staged uploads are server-managed and isolated per upload job
- existing import semantics and missing-item handling still work

---

## 7. Phase 3: Shared-Server PDF Handling

### 7.1 Goal

Ensure users never need to type server filesystem paths in import CSV files.

### 7.2 Target contract

For browser-based order import:

- `pdf_link` in CSV should be either:
  - blank, or
  - filename-only such as `Q2026-0001.pdf`

The actual PDF file should arrive by:

- the same ZIP package upload, or
- a paired multipart upload API

### 7.3 Backend behavior

During import:

1. backend receives uploaded file payloads
2. backend resolves filenames against uploaded PDFs in staging
3. backend moves the PDF into the canonical registered server path
4. backend stores the canonical relative path in `quotations.pdf_link`

### 7.4 Compatibility rule

Keep the current path-capable logic temporarily for:

- local development
- admin recovery operations
- backward compatibility with existing archives

But remove server-path entry from the primary UI guidance.

### 7.5 Acceptance criteria

- normal shared-server users never need to know `imports/orders/...` paths
- the database still stores canonical server-relative PDF paths after import
- legacy existing data remains readable

---

## 8. Phase 4: Generated File Delivery

### 8.1 Goal

Make every user-facing generated file reachable from the browser.

### 8.2 Preferred delivery modes

Use two supported modes only:

1. Immediate HTTP download
2. Managed artifact history with explicit download links

### 8.3 Apply this to current flows

#### Immediate download candidates

- unresolved item registration CSV exports
- template/reference CSV downloads
- planning exports
- procurement exports

These already fit the browser model and should remain direct download responses.

#### Managed artifact candidates

- batch-generated missing-item register CSVs
- batch result summaries
- imported ZIP processing reports

For these, the backend should store the generated artifact and expose a browser download endpoint.

### 8.4 Proposed backend additions

Optional artifact metadata table:

- `generated_artifacts`
  - `artifact_id`
  - `artifact_type`
  - `source_job_type`
  - `source_job_id`
  - `filename`
  - `relative_path`
  - `created_at`
  - `expires_at` nullable

Proposed API:

- `GET /api/artifacts`
- `GET /api/artifacts/{artifact_id}`
- `GET /api/artifacts/{artifact_id}/download`

### 8.5 Acceptance criteria

- every file the UI tells users about is downloadable from the browser
- users no longer need direct application-directory access

---

## 9. Phase 5: UI Deprecation And Cleanup

### 9.1 Goal

Remove shared-server-hostile workflow language from the main UI.

### 9.2 Required UI changes

Replace folder-oriented labels such as:

- "Process Pending CSVs"
- "Unregistered Folder Batch"

With upload-oriented labels such as:

- "Upload Batch CSVs"
- "Upload Orders ZIP"
- "Run Imported Batch"

### 9.3 Documentation updates

Update:

- `README.md`
- `backend/README.md`
- `frontend/README.md`
- `documents/technical_documentation.md`
- `documents/source_current_state.md`
- `documents/change_log.md`
- `specification.md` if user-visible contracts change

---

## 10. Suggested Implementation Slices

These are the recommended code slices, in order:

### Slice A

Frontend Users page

- low risk
- isolated
- already-backed by existing API

### Slice B

Orders ZIP upload staging

- highest shared-server value
- directly addresses both folder-access and PDF path problems

### Slice C

Items multi-file batch upload staging

- simpler than Orders once the staging pattern exists

### Slice D

Artifact registry/download history

- standardizes generated-file handling

### Slice E

UI wording cleanup and deprecation of direct-folder assumptions

---

## 11. Testing Strategy

### 11.1 Backend

Add tests for:

- user CRUD UI-backed flows if any backend contract changes occur
- upload staging lifecycle
- ZIP extraction and validation
- filename-only PDF resolution
- generated artifact download

Run:

- `uv run python -m pytest`

### 11.2 Frontend

Add tests for:

- user creation/edit/deactivation flows
- upload form validation
- upload success/failure messaging
- artifact download buttons

Run:

- `npm run build`
- frontend test suite if maintained for touched pages

### 11.3 Manual smoke tests

Validate in browser:

1. create a user
2. select that user in header
3. upload an Orders ZIP
4. verify PDFs land in canonical server storage
5. download unresolved-items artifact from browser
6. retry resolution flow without server-folder access

---

## 12. Recommendation

Do not try to implement all four concerns in one change set.

Recommended immediate next action:

1. implement Phase 1 (Users page)
2. then implement Phase 2 + Phase 3 together for Orders as the first upload-first shared-server workflow

That gives the biggest practical improvement while keeping the change set defensible and testable.

