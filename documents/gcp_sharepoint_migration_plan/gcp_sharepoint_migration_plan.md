# GCP + SharePoint Migration Plan

Last updated: 2026-03-27 (JST)

## Implementation Progress (2026-03-27)

- Completed:
  - Phase 1 core contract shift for manual/imported quotation and purchase-order document URLs
  - Phase 2 primary Orders CSV import contract update to metadata-only document URLs
  - Phase 3 frontend/API de-emphasis of ZIP/PDF flows as explicit legacy compatibility paths
  - Phase 4 frontend/API cleanup so generated artifact metadata is browser-facing and no longer depends on displaying workspace-relative paths
  - Phase 4 backend artifact cleanup: generated artifacts are now registered in the DB with opaque IDs instead of being discovered by folder scan
  - Phase 5 initial DB-tracked manual order import-job model (`import_jobs` / `import_job_effects`, plus `/api/orders/import-jobs`)
- Still pending:
  - deeper Phase 5 cleanup to remove remaining folder-encoded workflow state from legacy order-batch processing
  - Phase 6 removal/quarantine of remaining path-rewrite compatibility code

## Goal

Prepare this application for a future GCP deployment where:

- frontend and backend run on Cloud Run
- PostgreSQL runs on Cloud SQL
- secrets are managed outside the container runtime
- persistent business documents such as quotation PDFs and purchase-order sheets remain in SharePoint
- this application stores only document references such as SharePoint URLs plus related business metadata
- Cloud Run local filesystem is used only for request-scoped temporary work, never as persistent storage

This plan is intentionally phased so the current Docker-first deployment can keep working while the application is gradually moved away from filesystem-coupled behavior.

## Target Operating Model

### System responsibilities

- SharePoint
  - system of record for quotation sheets, purchase-order sheets, and related business documents
  - operators manage actual document files outside this application
- This application
  - stores structured procurement, inventory, planning, and reservation data in PostgreSQL
  - stores document references such as SharePoint URLs
  - validates, displays, and links to those references
  - generates CSV exports and reference files from database state when needed
- Cloud Run local disk
  - only for temporary request-scoped processing such as parsing uploaded CSV files or extracting a ZIP during transition phases
- GCS
  - optional for retained generated artifacts if later re-download is required
  - not the source of truth for quotation PDFs in the target design

### Target document model

- quotation and purchase-order files are not uploaded into this application
- imports and manual entry flows accept document URLs instead of PDF files or server paths
- database rows store normalized external document references
- frontend shows `Open document` style actions instead of exposing server filesystem paths

## Current-State Constraints Driving This Plan

The current codebase still has strong filesystem coupling around order import and generated artifacts.

### Main coupling points

- `backend/app/config.py`
  - defines `APP_DATA_ROOT`, `IMPORTS_ROOT`, `EXPORTS_ROOT`
- `backend/app/order_import_paths.py`
  - normalizes and migrates path-shaped `pdf_link` values
- `backend/app/service.py`
  - stages uploads under `imports/staging/...`
  - moves CSV/PDF files between unregistered and registered folders
  - discovers generated artifacts by scanning local folders
  - rewrites CSV archive rows to keep file paths aligned
- `backend/app/api.py`
  - exposes artifact download endpoints backed by local files
  - exposes upload-first batch endpoints for ZIP and CSV payloads
- `frontend/src/pages/OrdersPage.tsx`
  - still teaches path/file-based semantics in several places
  - still surfaces `pdf_link` as text rather than a document-reference UX
- `frontend/src/pages/ReservationsPage.tsx`
  - generates summary CSV on the client side

### Current behavior that does not fit Cloud Run target design

- persistent registered/unregistered CSV and PDF folder structures
- server-side PDF moves as part of import completion
- local artifact registry by directory scan
- historical CSV rewrite logic whose main purpose is file-path consistency
- ZIP upload flows that bundle order CSVs together with quotation PDFs

## Design Principles For Migration

1. The database must become the only source of truth for business records.
2. SharePoint document URLs must replace filesystem paths as the canonical document reference.
3. Filesystem-era workflows should be isolated behind compatibility layers, then removed.
4. Generated CSVs should be produced from database state, not treated as durable source records.
5. Runtime behavior should remain Docker-valid during the migration until the Cloud Run path is complete.

## Proposed Data Model Direction

### Short-term compatibility approach

Keep `quotations.pdf_link` temporarily, but redefine its intended meaning in the migration path as:

- an external document URL
- not a local file path
- not an uploaded file owned by this application

This minimizes immediate schema churn while code and UI are being refactored.

### Medium-term preferred model

Rename or supplement `pdf_link` with clearer fields such as:

- `quotation_document_url`
- `purchase_order_document_url`

If one quotation or order may have multiple external references later, introduce a separate table such as:

- `document_references`
  - `document_reference_id`
  - `entity_type`
  - `entity_id`
  - `document_kind`
  - `url`
  - `display_name`
  - `source_system` (`sharepoint`)
  - `created_at`
  - `updated_at`

## Phase Plan

## Phase 0: Planning And Compatibility Contract

### Objective

Lock the target architecture and define which current behaviors are legacy-only versus future-supported.

### Deliverables

- approve the target rule that quotation and PO files remain in SharePoint
- define allowed document-reference formats
  - full SharePoint URL only, or
  - full URL plus optional filename display metadata
- decide whether generated CSV artifacts need retention after download
- decide whether legacy ZIP-with-PDF import remains temporarily supported in local/shared-server deployments only

### Decisions to record

- whether `pdf_link` will be repurposed or replaced
- whether order rows also need their own external purchase-order document URL separate from quotation document URL
- whether Cloud Run deployment should keep any retained artifacts in GCS

### Exit criteria

- this plan is accepted as the target migration shape
- field naming direction is chosen

## Phase 1: Domain Contract Refactor For External Document References

### Objective

Move the domain model away from filesystem semantics without breaking the current app.

### Backend changes

- add a document-reference normalization helper in the service layer
- accept and validate external URL values for quotation/order document fields
- stop treating document references as local filesystem paths in new code paths
- isolate existing path-specific normalization and migration logic behind compatibility wrappers

### API changes

- update import preview/import endpoints so document fields are documented as external URLs
- keep existing request field names temporarily if needed for compatibility
- return normalized document URL fields in API responses

### Frontend changes

- update Orders page copy:
  - remove guidance that prefers filename-only or server-path values for the target path
  - explain that operators should enter SharePoint URLs
- replace plain display of path-like values with `Open document` links where possible

### Affected code areas

- `backend/app/service.py`
- `backend/app/api.py`
- `frontend/src/pages/OrdersPage.tsx`
- `specification.md`
- `documents/technical_documentation.md`
- `documents/source_current_state.md`

### Exit criteria

- users can manually enter or import external document URLs
- new target documentation no longer describes filesystem path entry as the preferred contract

## Phase 2: CSV Import Redesign Around Metadata-Only Documents

### Objective

Allow imports to carry structured business data plus SharePoint URLs, without any PDF transfer.

### Backend changes

- redesign manual order CSV preview/import rules so the document column contains URL text
- validate allowed URL scheme and minimum structure
- remove target-path canonicalization from the primary import path
- keep duplicate quotation detection based on supplier + quotation number and related business keys

### Frontend changes

- update import templates and reference CSV generation to use the revised document field semantics
- change error messages to talk about invalid document URLs instead of invalid server paths

### Validation rules to add

- empty document URL allowed only if the business rule permits it
- invalid URL format returns controlled `422`
- duplicate quotation import still rejected regardless of document URL value
- preview and commit use the same normalization rules

### Affected code areas

- `backend/app/service.py`
- `backend/app/api.py`
- `backend/tests/test_api_integration.py`
- `frontend/src/pages/OrdersPage.tsx`

### Exit criteria

- order import works with business metadata plus external document URLs only
- no target-path requirement remains in the primary import contract

## Phase 3: De-emphasize And Isolate Filesystem-Era PDF Batch Flows

### Objective

Prevent legacy ZIP/PDF folder workflows from contaminating the future Cloud Run path.

### Backend changes

- remove ZIP + PDF upload flow from the primary API contract once backward compatibility is no longer required
- keep the target future import path as metadata-only CSV input

### Frontend changes

- remove legacy ZIP + PDF upload from the primary workflow for the future deployment path
- if retained temporarily, label it explicitly as local/shared-server compatibility

### Documentation changes

- make clear that Cloud Run deployment does not use PDF upload into this app

### Exit criteria

- the intended production workflow no longer depends on bundled PDF upload
- legacy path is removed entirely

## Phase 4: Generated CSV Strategy Cleanup

### Objective

Stop using local folders as long-term storage for CSV artifacts.

### Recommended target behavior

- template CSVs
  - generated on demand from code
- reference CSVs
  - generated on demand from live DB state
- planning/procurement exports
  - generated on demand from DB state
- missing-item registration CSVs
  - generated on demand from import/validation results
  - optionally retained only if operations require re-download later

### Backend changes

- replace local-directory artifact discovery with explicit artifact generation responses
- if retention is needed, back artifacts by DB metadata plus optional GCS object storage
- if retention is not needed, stream content directly and avoid storing files after response

### Frontend changes

- continue using download endpoints, but decouple UI from any `relative_path` meaning
- show user-facing filename and creation time only

### Special note

`frontend/src/pages/ReservationsPage.tsx` currently creates summary CSVs in the browser. Decide whether to:

- keep that client-side behavior, or
- standardize all export behavior behind backend endpoints for consistency and auditability

### Exit criteria

- CSV exports no longer rely on persistent local folders
- artifact APIs no longer assume workspace filesystem persistence

## Phase 5: Database-Centric Import Job Model

### Objective

Replace folder-state workflow with database-tracked job-state workflow.

### Rationale

The current `unregistered` and `registered` folder model encodes process state in the filesystem. This is fragile for Cloud Run and unnecessary once documents are external references.

### Proposed import-job concept

- `import_jobs`
  - `import_job_id`
  - `job_type`
  - `status`
  - `created_at`
  - `created_by`
  - `source_filename`
  - `summary_json`
- optional `import_job_artifacts`
  - generated CSV result references

### Behavior

- user uploads CSV or submits form input
- backend creates preview/result state in DB-backed job records
- commit persists business rows
- optional missing-item register is returned as generated output, not written into workflow folders

### Implemented in this repository

- manual `POST /api/orders/import` now creates `import_jobs(import_type='orders')`
- row-level `import_job_effects` record:
  - `order_created`
  - `order_missing_item`
  - `order_duplicate_quotation`
- new read endpoints:
  - `GET /api/orders/import-jobs`
  - `GET /api/orders/import-jobs/{import_job_id}`
- import-job rows keep shared job statuses (`ok`, `partial`, `error`) even when the immediate order-import API response reports `status="missing_items"`
- legacy compatibility batch APIs now return `import_job_id` plus stable per-file `file_id` values so browser retry no longer depends on `csv_path` / root strings
- legacy compatibility batch jobs are now inspectable through DB-backed read endpoints without exposing internal path snapshots
- legacy order-batch compatibility internals were removed after backward-compatibility support was dropped
- uploaded ZIP compatibility batches now use DB-tracked staged-file rows as the source of queued work instead of scanning extracted folders
- successful uploaded ZIP compatibility batches now also write final CSV/PDF move outcomes back into staged-file rows
- legacy ZIP/PDF compatibility still uses filesystem storage and file moves internally, but business workflow state for both uploaded-ZIP and configured-root legacy batch processing is now DB-tracked rather than folder-encoded

### Exit criteria

- no business workflow state is encoded primarily in `imports/items/...` or `imports/orders/...`

## Phase 6: Schema Cleanup And Naming Cleanup

### Objective

Remove misleading filesystem-era names and compatibility assumptions.

### Changes

- replace or deprecate `pdf_link`
- introduce explicit external document field naming
- remove path-migration helpers that only exist for local folder compatibility
- remove CSV archive rewrite logic that only exists to keep paths aligned

### Candidate removals or simplifications

- parts of `backend/app/order_import_paths.py`
- PDF path normalization branches in `backend/app/service.py`
- tests that assert canonical local `imports/orders/...` path rewrites

### Exit criteria

- external document references are first-class schema and API concepts
- path-specific compatibility code is gone or clearly quarantined

### Implemented in this repository

- `quotations.pdf_link` has been removed from the DB schema
- quotation updates now accept `quotation_document_url` instead of path-style PDF metadata
- legacy CSV `pdf_link` remains quarantined to the compatibility batch importer as an input-only PDF move hint
- the order-layout migration helper no longer rewrites quotation DB rows or archived CSV contents merely to keep path text canonical

## Phase 7: Cloud Run Deployment Hardening

### Objective

Finalize runtime assumptions for GCP deployment.

### Infrastructure alignment

- Cloud Run for frontend/backend
- Cloud SQL for PostgreSQL
- Secret Manager for app/database configuration
- optional GCS only for retained generated artifacts
- structured logging with import-job ids and entity ids

### Runtime rules

- local disk only for `/tmp` style temporary files
- no durable reliance on container-local directories
- startup does not assume workspace import/export folders exist

### Exit criteria

- application can run with zero persistent local filesystem assumptions

### Implemented in this repository

- backend runtime now supports explicit `APP_RUNTIME_TARGET=cloud_run`
- Cloud Run mode defaults `APP_DATA_ROOT` to an ephemeral temp directory when unset
- Cloud Run mode skips legacy workspace/import folder migration during startup
- backend container startup now honors Cloud Run `PORT`
- `/api/health` exposes runtime posture fields so deployment validation can confirm Cloud Run-safe mode

## Keep / Replace / Remove Matrix

### Keep

- PostgreSQL as system of record for business data
- backend-generated template/reference/export endpoints
- browser-side download UX patterns
- Docker-first local validation during migration

### Replace

- `pdf_link` as filesystem path
  - replace with external SharePoint URL semantics
- registered/unregistered folder state
  - replace with DB job state
- folder-scan artifact registry
  - replace with explicit generated artifact handling

### Remove

- production dependence on CSV + PDF ZIP upload
- production dependence on moving PDFs between folders
- path rewrite logic whose only purpose is archive-path consistency
- persistent local CSV archives as operational source records

## Validation Strategy By Phase

### Automated validation

- backend targeted API tests for:
  - URL validation and normalization
  - duplicate quotation/order protection
  - import preview/commit consistency
  - generated CSV endpoint behavior
- frontend type-check/build
- frontend tests for revised Orders import UX and document-link rendering

### Runtime validation

Use the intended Docker-first environment while the app is still in transition:

1. `.\start-app.ps1`
2. validate manual order entry with SharePoint URL
3. validate CSV import with SharePoint URL column
4. validate quotation/order detail rendering and document link opening behavior
5. validate generated CSV download behavior for changed user flows

### Cloud-target validation before rollout

- run with no mounted persistent workspace folders
- confirm startup succeeds without `imports/...` or `exports/...` assumptions
- confirm all changed workflows still function with only DB plus optional temp storage

## Initial Implementation Order Recommendation

To minimize churn and avoid mixing legacy and target behavior too early, implement in this order:

1. Phase 1
   - redefine document semantics in domain/API/UI
2. Phase 2
   - make metadata-only CSV import fully valid
3. Phase 4
   - clean up generated CSV behavior
4. Phase 3
   - isolate or remove legacy ZIP/PDF workflow from primary UX
5. Phase 5
   - move to DB-tracked import jobs
6. Phase 6
   - remove compatibility/path debt
7. Phase 7
   - finalize Cloud Run deployment posture

This sequence makes the application usable with SharePoint URLs early, before deeper cleanup work is finished.

## Open Questions

- Should quotation documents and purchase-order documents be stored on separate fields from the beginning?
- Should empty document URLs be allowed for draft quotations/orders?
- Should generated missing-item CSVs be retained for later download, or only streamed once?
- Should legacy ZIP/PDF import remain available in local Docker deployments after the Cloud Run path is complete?
- Should SharePoint URL validation be strict to company tenant domains only, or generic `https` URL validation at first?

## Recommended Next Concrete Task

Start with Phase 1 and Phase 2 together in one implementation stream:

- redefine the order/quotation document field contract as external URL
- update Orders UI text and validation
- update CSV import preview/import rules
- update templates/reference docs

That will deliver the first meaningful business transition away from local file path dependence while keeping later cleanup phases manageable.
