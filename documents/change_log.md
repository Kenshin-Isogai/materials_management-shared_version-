## 2026-04-02

### Changed

- Simplified the hosted auth and user-admin UX after the verified-email rollout.
  - the main header now hides the manual bearer-token fallback in hosted Identity Platform environments and keeps it only for localhost-style local/test use
  - anonymous dashboard visits now stop at explicit sign-in guidance instead of surfacing a confusing backend/database unavailable message
  - the header now exposes a first-time-user registration guidance link before sign-in, clarifying that registration starts after verified sign-in
  - the Users page now removes `identity_provider` / `hosted_domain` from the primary operator UI and tucks raw external-subject mapping behind an advanced recovery toggle
  - the verify-email page now refreshes the stored session on demand after verification so the browser no longer remains stuck on an old unverified token
  - the Users page summary cards now show `—` when the protected `/users` data is unavailable instead of implying that the system has zero users

- Extended the browser auth flow for `OIDC_REQUIRE_EMAIL_VERIFIED=1` launch readiness.
  - shared header login now supports Identity Platform email/password sign-up in addition to sign-in
  - newly created accounts now trigger verification-email delivery and signed-in-but-unverified users are redirected to a dedicated `/verify-email` holding page with resend support
  - app routing now distinguishes `unverified identity` from `verified but unmapped identity`, sending the latter to `/registration` only after email verification succeeds

- Added self-service onboarding with admin approval for Identity Platform sign-ins.
  - signed-in identities that are not yet mapped to an active app user are now redirected into `/registration`
  - applicants submit `username`, required `display_name`, requested role, and optional memo; email remains token-derived
  - backend now stores `registration_requests` separately from active users, preserving rejection history and reviewer audit metadata
  - admins can review pending requests from the Users page, approve with a final role/username/display name override, or reject with a required reason
  - dashboard summary now exposes pending-registration counts, and the shell no longer keeps the email/password inputs visible after sign-in

- Tightened cloud-auth UX and error handling after the first GCP rollout validation.
  - frontend API failures now distinguish auth-required, backend-unavailable, and generic request failures instead of surfacing a generic fetch error
  - frontend mutation requests now preserve auth-classified header-preparation failures (including expired-session refresh failures) instead of masking them as backend-unavailable errors
  - dashboard and shell login status now show operator-meaningful messages when a token is missing, invalid, or not mapped to an active app user
  - dashboard/workspace views and the global shell now show dedicated sign-in guidance and environment-unavailable callouts instead of raw error strings
  - projects, inventory, reservations, orders, items, history, and shared editor surfaces now reuse the same API error presentation instead of rendering raw `String(error)` output
  - backend JWT verification failures are now normalized into `INVALID_TOKEN` API responses instead of leaking PyJWT exceptions through the middleware stack

## 2026-04-01

### Changed

- Replaced the transitional browser Google-sign-in path with Identity Platform email/password sign-in for the Cloud Run rollout.
  - frontend header login now accepts email/password against Identity Platform when `VITE_IDENTITY_PLATFORM_API_KEY` is configured
  - frontend auth storage now keeps refresh tokens in session-scoped storage, migrates the legacy local token key, ignores stale in-flight refreshes after sign-out/token replacement, and refreshes bearer sessions before expiry
  - backend deploy assets now preserve the working Identity Platform settings by defaulting to `JWT_SIGNING_ALGORITHMS=RS256` and exposing `OIDC_REQUIRE_EMAIL_VERIFIED` as an explicit deployment choice
  - Cloud Run deployment assets now include backend/frontend env templates, PowerShell deploy scripts, a migration-job script, a Secret Manager helper, and a GitHub Actions deployment workflow
  - the GitHub Actions workflow now supports `backend`, `frontend`, and `full` deployment targets so first-time environment rollout does not require both public URLs up front
  - added a first-time environment bootstrap runbook with concrete `gcloud`, GitHub Actions, and bootstrap-admin examples
  - rollout docs now describe Identity Platform configuration instead of Google Identity client setup

## 2026-03-30

### Changed

- Fixed purchase-order header integrity gaps in the purchasing refactor.
  - manual order import now reuses supplier-scoped purchase-order headers when `purchase_order_document_url` is blank instead of creating duplicate header rows
  - purchase-order-line merge now rejects lines from different purchase orders instead of allowing an invalid cross-header merge
- Refactored purchasing document modeling to split purchase-order headers from line data.
  - added `purchase_orders` as an independent header entity and backfilled `orders.purchase_order_id`
  - removed `orders.purchase_order_document_url` from persisted line storage and now resolve PO document URLs through the header entity
  - order import now creates or reuses quotation headers and purchase-order headers independently before inserting line rows
  - quotation deletion now also prunes orphaned purchase-order headers, and purchase-order deletion prunes orphaned quotations when its lines were the last references
  - added `/api/purchase-orders` management endpoints and `/api/purchase-order-lines/*` aliases for the line-centric API surface
  - Orders UI now points its import and mutation calls at the new purchase-order-line endpoints and uses purchase-order-line wording in the main views
  - Orders UI browsing was reorganized around `Quotations` / `Purchase Orders` / `Purchase Order Lines` instead of the older expandable `Imported Quotations` + `Order List` workflow
  - line browsing now uses denser cards plus a side detail pane to reduce vertical scrolling when each line exposes many fields
  - quotation and purchase-order headers now have dedicated searchable panes with linked-line counts and header-level edit/delete actions

## 2026-03-29

### Changed

- Fixed follow-up auth and user-management validation gaps from branch review.
  - `update_user` now enforces the same `admin` / `operator` / `viewer` role validation already used on user creation
  - OIDC hosted-domain allow-lists no longer reject otherwise valid tokens that omit the optional `hd` claim in either shared-secret or JWKS verifier mode
  - partial user updates can now change one identity-mapping field at a time when the merged stored result remains valid, with final pair validation still enforced in the service layer

- Addressed review follow-ups on the OIDC auth slice.
  - renamed the OIDC user-identity Alembic file to `009_oidc_user_identity.py` so the filename sequence matches the revision id
  - `/api/auth/capabilities` now reports the resolved/configured identity provider and keeps diagnostics paths listed under the role that actually grants access
  - `/api/users/me` now reports bearer-token user-context requirements instead of the retired selected-user wording
  - CORS preflight `OPTIONS` requests now bypass auth/RBAC checks instead of inheriting the target endpoint role
  - JWT email verification now requires `email_verified` to be explicitly `true` when an email claim is present and verification is enabled
  - cleaned up Google Identity script error listeners on unmount and kept the basic Playwright layout smoke test runnable without an E2E bearer token

- Closed the remaining repo-side trust-boundary slice for browser auth and diagnostics.
  - frontend header now supports Google Identity sign-in via `VITE_GOOGLE_CLIENT_ID` and keeps manual Bearer token entry as a fallback
  - backend bearer verification now supports `JWT_VERIFIER=jwks` with `OIDC_JWKS_URL` for deployed OIDC/JWKS verification
  - Cloud Run diagnostics can now be restricted through `DIAGNOSTICS_AUTH_ROLE`, with cloud defaulting to `admin` while `/healthz` and `/readyz` stay public
  - successful high-impact mutations and export/download flows now emit `domain.audit` structured log events
  - added backend regression coverage for JWKS mode, Cloud Run diagnostics access, and audit emission gating

- Replaced the temporary local identity bridge with Bearer JWT / OIDC-oriented identity plumbing.
  - `backend/app/api.py` now resolves `Authorization: Bearer <JWT>` into `request.state.identity` and maps active app users into `request.state.user`
  - auth and authorization are now split across `AUTH_MODE` (`none`, `oidc_dry_run`, `oidc_enforced`) and `RBAC_MODE` (`none`, `rbac_dry_run`, `rbac_enforced`)
  - `/api/auth/capabilities` and `/api/health` now describe the bearer-token posture and endpoint role policy instead of the old temporary mutation bridge
  - `backend/app/service.py`, `backend/app/schemas.py`, and Alembic revision `009_oidc_user_identity` add OIDC-facing user mapping fields (`email`, `external_subject`, `identity_provider`, `hosted_domain`)
  - frontend API calls now send Bearer tokens, and the shell stores a token instead of a locally selected operator identity
- Added the next repository-only Cloud Run hardening slice on the backend.
  - `backend/app/api.py` now exposes `GET /healthz` and `GET /readyz` so Cloud Run can separate fast liveness from DB-backed readiness
  - backend startup/shutdown and per-request events now emit structured log payloads when `STRUCTURED_LOGGING=1`, including request IDs, latency, status code, and auth mode
  - `/api/health` remains a posture/contract endpoint and now points operators to the dedicated probe paths instead of attempting DB readiness inline
- Tightened the first-pass RBAC boundary for admin surfaces.
  - `/api/users*` is now admin-only when `RBAC_MODE=rbac_enforced`
  - `rbac_dry_run` logs would-be denials without blocking traffic
  - bootstrap creation of the first active user remains available when no active users exist
- Synced rollout/current-state documentation with the new probe, logging, and partial-RBAC behavior.
- Hardened manual order import recoverability around the shared import-job model.
  - `backend/app/service.py` now stores order-import `request_metadata` so redo can replay `supplier_id`, `supplier_name`, `default_order_date`, `row_overrides`, and `alias_saves`
  - order import jobs now support `undo` and `redo`, including quotation and supplier-alias recovery plus conflict detection when imported rows were modified later
  - added Alembic revision `008_import_job_request_metadata` for the new `import_jobs.request_metadata` column
- Organized the repo-side GCS lifecycle and Cloud SQL backup/restore operating contract in the rollout docs.
  - `documents/gcp_cloud_run_rollout/cloud_run_deployment_runbook.md` now records the expected prefix/retention contract plus DB/object restore decision rules
  - `documents/gcp_cloud_run_rollout/migration_checklist.md` and `security_and_cost_considerations.md` now distinguish documented recovery policy from still-pending live cloud enablement
- Extended the repo-side PITR preparation into backend diagnostics.
  - `/api/health` now includes a `recovery_policy` summary covering required Cloud SQL backup/PITR posture, GCS retention/versioning expectations, and post-restore validation targets
  - storage backend diagnostics now expose the retention/versioning and recovery-prefix contract directly

- Continued the Cloud Run cleanup on the frontend/backend runtime contract.
  - `frontend/nginx.conf` is now cloud-first and no longer proxies `/api` to `backend:8000`
  - added `frontend/nginx.local-proxy.conf` so local Docker Compose can keep same-origin `/api` behavior without preserving that proxy assumption in the built image
  - `docker-compose.yml` now mounts that local proxy config explicitly for the shared-server stack
- Separated local backend startup from the old inline migration command pattern.
  - base Docker Compose now relies on normal backend startup migration via `AUTO_MIGRATE_ON_STARTUP=1` instead of embedding `uv run alembic upgrade head` in the container command
  - this keeps local convenience behavior while making the container startup contract closer to Cloud Run
- Hardened generated artifact lookup against Cloud Run local-path compatibility fallback.
  - `backend/app/service.py` now ignores legacy raw filesystem artifact paths when runtime posture is Cloud Run
  - local/shared-server runtime still keeps that fallback for older local artifacts
- Removed unused order-import directory-scan helpers from the active code path.
  - `backend/app/order_import_paths.py` now keeps only the path helpers still used by active import flows
  - backend tests and fixtures were updated to match the reduced helper surface
- Removed the last runtime support for historical workspace and raw-path artifact migration behavior.
  - `backend/app/config.py` no longer migrates `quotations/`, `pending/`, or `processed/` legacy folders during startup
  - `backend/app/service.py` now expects generated artifacts to resolve through storage-backed refs only
- Implemented comprehensive End-to-End (E2E) test suite using Playwright.
  - Added read-only smoke tests for Layout, Users, Items, Orders, and Projects.
  - Added stateful CRUD tests verifying full lifecycles for Users, Projects, Items (CSV import), and Orders (CSV import).
  - Configured `afterAll` cleanup hooks for stateful tests to maintain database cleanliness.
  - Added `@types/node` and `tsconfig.e2e.json` to support Node.js APIs (e.g., `Buffer`) in tests.
- Isolated Playwright from the normal local Docker stack.
  - added `run-e2e.ps1` so Playwright runs against a dedicated Compose project on `http://127.0.0.1:8088` and always tears it down with `down -v`
  - `docker-compose.yml` now uses `NGINX_HOST_PORT` for the local frontend publish port, letting the isolated E2E stack bind `8088` without taking over the normal `:80` slot
  - `frontend/playwright.config.ts` now honors `PLAYWRIGHT_BASE_URL` and bootstraps an `e2e.admin` user through `frontend/e2e/global.setup.ts`
  - fixed the projects CRUD cleanup path so edited E2E project names are still deleted when the suite finishes
- Added an explicit local reset-on-start workflow.
  - `start-app.ps1 -ResetData` now clears the normal Docker Compose volumes before bringing the shared local stack back up

### Tests

- Backend:
  - `uv run --project backend python -m pytest backend/tests/test_runtime_config.py --import-mode=importlib -q`
  - `uv run --project backend python -m pytest backend/tests/test_runtime_config.py backend/tests/test_api_integration.py -k "test_liveness_and_readiness_endpoints or test_readiness_endpoint_reports_unavailable_database or test_auth_capabilities_endpoint_defaults_and_header or test_users_endpoint_requires_admin_role_when_rbac_is_enforced or test_users_endpoint_allows_anonymous_read or test_health_endpoint" --import-mode=importlib -x -vv`
  - `uv run python -m pytest tests/test_runtime_config.py tests/test_order_import_paths.py`
  - `uv run --project backend python -m pytest --import-mode=importlib backend/tests/test_document_url_migration.py`
  - `uv run --project backend python -m pytest backend/tests/test_document_url_migration.py -q --import-mode=importlib -k "undo or manual_order_import or generated_artifact_metadata_hides_workspace_paths or preview_rejects_non_https_document_url"`
  - `uv run --project backend python -m pytest backend/tests/test_service_transactions.py -q --import-mode=importlib -k "test_order_import_job_tracks_undecodable_csv_failures or test_order_import_job_rolls_back_partial_changes_on_unexpected_error"`
  - `uv run --project backend python -m pytest backend/tests/test_runtime_config.py backend/tests/test_api_integration.py -k "test_health_endpoint or test_cloud_run_runtime_defaults_to_tmp_app_data_root_and_port or test_runtime_config_honors_explicit_pool_and_cors_settings" --import-mode=importlib -q`
  - `docker compose -f docker-compose.test.yml up -d db-test`
- Frontend:
  - `npm run build`
  - `.\run-e2e.ps1`
 - Docker:
   - `docker compose -f docker-compose.yml up -d --build`
   - validated `http://127.0.0.1/` and `http://127.0.0.1/api/health`

## 2026-03-28

### Changed

- Simplified the browser item-registration workflow around one CSV import UI.
  - removed the Items-page missing-item resolver section and the dedicated missing-item batch-upload section
  - order-generated missing-item CSVs are now expected to be downloaded, edited, and re-imported through the normal Items preview/import flow
  - Orders preview/import now offers CSV download handoff instead of routing unresolved rows into a browser-side retry/resolver loop
  - removed the unused `POST /api/items/batch-upload` endpoint and its compatibility-only backend path now that the browser no longer depends on it
  - replaced the last browser dependency on `POST /api/register-missing/rows` with a dedicated alias upsert-by-supplier-name API, then removed both `POST /api/register-missing` and `POST /api/register-missing/rows`
- Simplified the Cloud Run-target Orders import contract.
  - order CSV rows now carry required `supplier` values instead of relying on a selected supplier outside the file
  - the Orders page now supports selecting multiple CSV files in one preview/import pass
  - browser-side retry-after-missing-items now replays the remaining selected files instead of one cached file plus a top-level supplier
- Removed the remaining repo-local item-batch compatibility path.
  - deleted `POST /api/items/register-unregistered-batch`
  - removed the Items-page `Run Existing Imported Batch` fallback
  - Cloud-facing missing-item registration is now upload-only through `POST /api/items/batch-upload`
- Removed the remaining archive-rescan behavior from item and order compatibility flows.
  - item import archives under `imports/items/registered/<YYYY-MM>/` are now stored as historical files without monthly consolidation rescans
  - order and quotation mutation flows no longer rescan or rewrite archived order CSV files after update/delete/split/merge actions
  - delete responses still expose `csv_sync`, but only as an explicit `enabled=false` compatibility marker
- Removed a remaining cloud-sensitive local staging dependency from the Items batch upload path.
  - `POST /api/items/batch-upload` now processes uploaded missing-item CSV bytes directly instead of writing them into a server-side staging directory first
  - successful batch-upload archives still flow through the durable storage boundary, so Cloud Run can keep the upload path stateless
- Added a concrete first-rollout Cloud Run deployment runbook.
  - `documents/gcp_cloud_run_rollout/cloud_run_deployment_runbook.md`
  - documents build/push, migration, deploy, environment, and post-deploy validation steps for frontend + backend Cloud Run services
- Completed the next Cloud Run-essential storage slice.
  - `backend/app/storage.py` now supports both `local://...` and `gcs://...` durable object refs
  - backend durable writes/moves can now target GCS when `STORAGE_BACKEND=gcs` with `GCS_BUCKET`
  - backend order/item durable archive flows now use that GCS-capable storage boundary instead of local-only assumptions
  - backend build dependencies now include `google-cloud-storage`
- Started turning the locked GCP rollout decisions into explicit runtime behavior instead of doc-only assumptions.
  - backend runtime now exposes Cloud SQL/GCS/public-URL deployment metadata through config and `/api/health`
  - `/api/health` and `/api/auth/capabilities` now describe the temporary pre-OIDC mutation model explicitly, including the initial admin/operator boundary
  - backend request handling now enforces the first-rollout upload ceiling via `MAX_UPLOAD_BYTES` and returns `413 REQUEST_TOO_LARGE` for oversized requests
  - frontend nginx upload limit now matches the same 32 MB first-rollout ceiling
  - selecting `STORAGE_BACKEND=gcs` now fails explicitly as not-yet-implemented instead of silently implying Cloud Run durable storage is already complete
- Extended runtime/deployment configuration docs and examples for the started Decision-track work.
  - `.env.example`, `README.md`, `backend/README.md`, `documents/technical_documentation.md`, and `documents/source_current_state.md` now include the rollout guardrail and deployment-metadata variables

- Continued the GCP Cloud Run rollout implementation on the runtime contract surfaces.
  - Cloud Run runtime now defaults `AUTO_MIGRATE_ON_STARTUP` to off while local runtime still defaults to startup migration unless explicitly disabled.
  - SQLAlchemy pool behavior is now environment-driven via `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_TIMEOUT`, and `DB_POOL_RECYCLE_SECONDS`.
  - Backend health output now reports migration strategy, configured CORS origins, and effective DB pool settings for deployment validation.
  - Backend CORS defaults are no longer wildcard-based: local runtime allows the common localhost origins, while Cloud Run defaults to no browser origins until `CORS_ALLOWED_ORIGINS` is set explicitly.
  - Frontend API base handling now normalizes `VITE_API_BASE` so split Cloud Run deployments can use an absolute backend `/api` URL cleanly.
- Continued the GCP Cloud Run rollout implementation on the storage boundary.
  - added `backend/app/storage.py` as the first persistent-storage abstraction surface
  - generated artifacts now persist through storage refs (`local://generated_artifacts/...`) instead of relying only on raw filesystem paths in `generated_artifacts.storage_path`
  - manual order-import missing-item responses now expose only `missing_artifact` publicly, not raw storage-location fields
  - manual item-import archive metadata now also goes through the storage boundary internally while the public API omits cleanup/storage-ref details
  - item batch-upload and batch-register responses now expose file names only, not staging/archive filesystem paths
  - default registered-item archive moves and default registered-order CSV/PDF moves now execute through the storage layer, with rollback preserved for the item batch-registration path
- Updated deployment/runtime documentation to match the new Cloud Run contract.
  - `.env.example`, `README.md`, `backend/README.md`, `documents/technical_documentation.md`, `documents/source_current_state.md`
  - `documents/gcp_cloud_run_rollout/environment_and_runtime_matrix.md`
  - `documents/gcp_cloud_run_rollout/migration_checklist.md`
- Locked the remaining first-rollout decisions that were still causing scope ambiguity in the GCP plan.
  - split frontend/backend Cloud Run services stay in place and the frontend keeps nginx for static delivery
  - Cloud SQL uses the Cloud SQL Connector / Unix socket model, with secrets sourced from Google Secret Manager
  - GCS uses one bucket per environment plus prefix-based class separation and lifecycle retention of 7-day staging, 30-day exports, 90-day artifacts, and non-expiring archives
  - the first rollout assumes `dev` / `staging` / `prod`, native `*.run.app` URLs, backend-mediated downloads, a public browser-reachable backend with temporary pre-OIDC mutations, a 32 MB upload ceiling, a roughly 60-second heavy-request target, and small-team / conservative-concurrency operation
  - rollout planning now also fixes the initial admin/operator boundary, audit scope, monitoring baseline, and production-index review scope, while still deferring stronger end-user auth
- Clarified checklist semantics in `documents/gcp_cloud_run_rollout/migration_checklist.md`.
  - added an explicit legend separating locked decisions from implementation/validation-complete items
  - converted decision-only entries from `[x]` to `[Decision]` so rollout progress no longer implies those items are already implemented

### Tests

- Added backend regression coverage for:
  - direct Items batch-upload archiving while the durable storage backend is set to GCS
  - GCS-backed storage write/read/move/delete behavior through the storage abstraction
- Added backend regression coverage for:
  - runtime parsing of upload-limit, concurrency, Cloud SQL, public-URL, and GCS/storage config
  - `/api/health` and `/api/auth/capabilities` rollout metadata fields
  - oversized upload rejection through the new request-size middleware
- Added backend runtime-config regression coverage for:
  - Cloud Run default migration/CORS/pool behavior
  - local default migration/CORS behavior
  - explicit DB pool and CORS override parsing
- Extended backend API health coverage to assert the new runtime contract fields.

## 2026-03-27

### Documentation

- Added a new GCP rollout documentation set under `documents/gcp_cloud_run_rollout/`.
  - `README.md`
  - `implementation_plan.md`
  - `migration_checklist.md`
  - `target_architecture.md`
  - `security_and_cost_considerations.md`
  - `task_breakdown_by_file.md`
  - `environment_and_runtime_matrix.md`
  - `implementation_slices.md`
- The new document set explicitly treats backward compatibility as out of scope for the planned Cloud Run + Cloud SQL + GCS rollout work.

### Fixed

- Hardened manual order import job tracking for failure paths.
  - order-import jobs now persist `error` finalization even when the API request exits through an exception path
  - unexpected exceptions during order import now roll back in-flight import writes before the job is finalized
  - undecodable order-import CSV bytes now still produce a tracked import job record instead of failing before job creation
- Shortened the newest Alembic revision ID so PostgreSQL test/bootstrap runs no longer overflow `alembic_version.version_num`.

### Changed

- Removed the remaining legacy order ZIP/PDF compatibility workflow now that backward compatibility is no longer required.
  - deleted `POST /api/orders/import-unregistered`, `POST /api/orders/batch-upload`, `POST /api/orders/retry-unregistered-file`, `GET /api/orders/legacy-batch-jobs`, and `GET /api/orders/legacy-batch-jobs/{import_job_id}`
  - removed the Orders-page legacy ZIP/PDF UI and the Items-page retry bridge that depended on compatibility batch jobs
  - tightened order-import path handling to canonical `csv_files/<supplier>/` layout only and removed typo/path-normalization helpers
  - removed the remaining quotation-path rewrite process because imported document URLs remain external references and do not need to change when records move between import states
  - removed the backend-only `orders_legacy_batch` service path and added a schema cleanup migration that drops `legacy_batch_staged_files` and restores `import_jobs.import_type` to `items|orders`
- Completed Phase 7 of the GCP + SharePoint migration plan.
  - backend runtime now distinguishes local vs Cloud Run mode through `APP_RUNTIME_TARGET`
  - Cloud Run mode defaults `APP_DATA_ROOT` to an ephemeral temp directory and skips legacy workspace/import folder migration on startup
  - backend container startup now honors Cloud Run `PORT` instead of relying on a fixed baked-in bind port
  - `/api/health` now reports runtime posture fields for deployment validation
  - local Docker Compose explicitly pins `APP_RUNTIME_TARGET=local`
- Completed Phase 6 of the GCP + SharePoint migration.
  - removed the legacy `quotations.pdf_link` schema field in favor of `quotation_document_url`
  - quotation update requests now use the typed document-URL contract instead of an open payload that could still carry `pdf_link`
  - legacy batch `pdf_link` remains input-only inside the compatibility importer and is no longer persisted back into quotation metadata
  - order-layout maintenance no longer rewrites archived CSV rows or quotation DB state solely to keep filesystem paths canonical
- Reduced remaining folder semantics in the legacy order-batch compatibility path.
  - generated artifacts are now registered in `generated_artifacts` and exposed through opaque DB-backed `artifact_id` values instead of path-derived IDs and folder-scan listing
  - legacy batch responses now include `import_job_id`
  - per-file retry references now use `file_id` instead of browser-visible `csv_path` / root fields
  - Orders and Items pages now persist retry context by job/file IDs rather than workspace paths
  - added `GET /api/orders/legacy-batch-jobs` and `GET /api/orders/legacy-batch-jobs/{import_job_id}` so compatibility jobs can be inspected without exposing internal path snapshots
  - server-root legacy batch imports (`POST /api/orders/import-unregistered`) now snapshot discovered CSV/PDF files into `legacy_batch_staged_files` and process CSV work from those staged-file rows rather than driving execution directly from folder scans
  - uploaded ZIP compatibility batches now record staged archive/CSV/PDF entries in `legacy_batch_staged_files`
  - uploaded ZIP batch processing is now driven from DB-tracked staged-file rows rather than scanning the extracted unregistered folder to discover CSV work
  - successful uploaded ZIP batches now update staged CSV/PDF rows with final move status and storage paths, so the DB reflects post-import file outcomes too
- Updated legacy batch compatibility behavior in the UI.
  - Orders page no longer asks the browser user to enter custom unregistered/registered root paths
  - the compatibility section runs against the configured server-side roots or a staged ZIP upload only
- Extended the GCP + SharePoint migration into DB-tracked manual order imports.
  - `POST /api/orders/import` now creates `import_jobs(import_type='orders')` records and returns `import_job_id`.
  - Added `GET /api/orders/import-jobs` and `GET /api/orders/import-jobs/{import_job_id}` for order-import job inspection.
  - Row-level order import outcomes are now stored in `import_job_effects` as `order_created`, `order_missing_item`, and `order_duplicate_quotation`.
  - Order import jobs reuse the shared import-job status vocabulary (`ok`, `partial`, `error`) even when the immediate import response remains `status="missing_items"`.
- Fixed order import-job API routing and status finalization.
  - `GET /api/orders/import-jobs` no longer collides with `GET /api/orders/{order_id}`.
  - Missing-item order imports now finalize job rows as `partial` instead of violating the shared import-job status constraint.
- Started the GCP + SharePoint migration implementation stream for order/quotation document handling.
  - Added `quotation_document_url` for quotations and `purchase_order_document_url` for orders.
  - Manual Orders CSV import now requires `quotation_document_url` and validates external `https://` document links instead of path-style `pdf_link` values.
  - Orders UI now presents quotation and purchase-order references as openable document links and updates quotation editing to use `quotation_document_url`.
  - Legacy ZIP/PDF batch handling remains in place only as a compatibility path.

### Documentation

- Updated migration-related contract notes in:
  - `specification.md`
  - `documents/technical_documentation.md`
  - `documents/source_current_state.md`
  - `documents/gcp_sharepoint_migration_plan/gcp_sharepoint_migration_plan.md`

### Tests

- Docker-backed backend pytest:
  - `uv run --project backend python -m pytest --import-mode=importlib backend/tests/test_document_url_migration.py`
    - result: `5 passed`
  - `uv run --project backend python -m pytest --import-mode=importlib backend/tests/test_api_integration.py -k "generated_artifact_endpoints_expose_missing_items_register_download or orders_batch_upload_endpoint_stages_zip_and_imports or orders_batch_upload_endpoint_normalizes_path_like_pdf_link_to_filename_contract or items_import_jobs_listing_endpoint"`
    - result: `4 passed, 98 deselected`
  - `uv run --project backend python -m pytest --import-mode=importlib backend/tests/test_document_url_migration.py backend/tests/test_api_integration.py -k "generated_artifact_endpoints_expose_missing_items_register_download or order_import_returns_missing_item_details or orders_batch_upload_endpoint_stages_zip_and_imports or retry_unregistered_file_endpoint or retry_unregistered_legacy_layout_returns_warnings or generated_artifact_metadata_hides_workspace_paths or manual_order_import_accepts_external_document_urls"`
    - result: `7 passed, 100 deselected`
  - `uv run --project backend python -m pytest --import-mode=importlib backend/tests/test_api_integration.py -k "generated_artifact_endpoints_expose_missing_items_register_download or orders_batch_upload_endpoint_stages_zip_and_imports"`
    - result: `2 passed, 100 deselected`
  - `uv run --project backend python -m pytest --import-mode=importlib backend/tests/test_api_integration.py -k "orders_batch_upload_endpoint_stages_zip_and_imports or generated_artifact_endpoints_expose_missing_items_register_download or retry_unregistered_file_endpoint"`
    - result: `3 passed, 99 deselected`

### Changed

- Continued the GCP + SharePoint migration cleanup in the Orders UI.
  - The ZIP/PDF batch flow is now explicitly hidden behind a legacy compatibility section.
  - Recent generated-file entries now show browser-facing metadata only (`filename`, timestamp, size) instead of workspace-relative paths.
- Tightened backend compatibility/API signaling for migration-era flows.
  - generated artifact metadata no longer exposes `relative_path` in the public response shape
  - legacy order batch responses now include explicit compatibility markers
- Updated repository guidance for Docker-backed backend pytest execution.
  - `AGENTS.md`, `README.md`, and `backend/README.md` now document the working `uv run --project backend ...` flow with `docker-compose.test.yml`, `TEST_DATABASE_URL`, `PYTHONPATH=backend`, and `--import-mode=importlib`.

## 2026-03-26

### Fixed

- Reservations provisional-allocation summary now revalidates immediately after reservation create/import/release/consume actions on the same page.
  - This keeps the `Provisional Allocation Summary` panel and its CSV export aligned with the refreshed Reservation List instead of showing stale totals until focus/refresh.
- Restored first-user bootstrap in shared-server mode.
  - `POST /api/users` is now allowed without an authenticated identity only when there are zero active users.
  - The Users page now allows first-user creation without an existing session and shows explicit bootstrap guidance when no active users exist.

### Tests

- Added backend API regression coverage for:
  - creating the first active user without an authenticated identity
  - rejecting anonymous user creation again after an active user exists

### Added

- Added `start-app.ps1` at the repository root.
  - Starts the Docker app stack on Windows using `docker-compose.yml` by default.
  - Checks `.env` and Docker availability before startup.
  - Supports `-IncludeDevOverride` for the local development override when explicitly requested.
- Added `stop-app.ps1` at the repository root.
  - Stops the same Docker app stack on Windows using the same compose-file selection rules.
  - Supports `-RemoveVolumes` when the operator explicitly wants `docker compose down -v`.

### Changed

- Reduced duplication between Items manual CSV import and missing-item batch registration.
  - Missing-item batch registration now normalizes batch CSV rows into the shared item/alias import write path instead of maintaining a separate create/upsert implementation.
  - Batch-specific semantics remain unchanged where they matter operationally: unresolved `new_item` rows can still be skipped, already-registered `new_item` rows remain no-op, and staged/unregistered files still move through the existing batch archive flow.
- Clarified Items page import wording so the two CSV paths read as different workflows instead of duplicates.
  - `Import Items CSV` is now labeled `General Items CSV Import`.
  - `Upload Batch CSVs` is now labeled `Register Missing-Item Batch CSVs`.
  - Helper text now explicitly routes hand-made/ad hoc CSVs to the general import path and reserves the batch path for generated missing-item registration files.

- Snapshot now supports an availability-basis selector instead of introducing a separate residual-items page.
  - `GET /api/inventory/snapshot` now accepts `basis=raw|net_available`.
  - `raw` preserves the existing physical location-state reconstruction behavior.
  - `net_available` returns residual free quantity for current/future snapshots by subtracting current active reservation allocations from on-hand inventory, then adding open orders due by the selected date.
  - `net_available` rows now also include a compact occupation summary: `allocated_quantity`, `active_reservation_count`, and `allocated_project_names`.
  - `mode=past` with `basis=net_available` now returns a controlled `422` because the current model does not support authoritative historical allocation-state reconstruction.
- Snapshot frontend now exposes `raw inventory` vs `net available` directly on the existing page, keeping the inventory-analysis UI consolidated instead of adding a duplicate feature surface.
- Improved provisional project-link UX on Reservations.
  - Reservation Entry now includes optional project selection in the main multi-row UI.
  - Batch create payload now submits optional `project_id` from that UI.
  - Reservation List now shows linked project name/id when present.
  - Backend reservation create now validates provided `project_id` and returns controlled `PROJECT_NOT_FOUND` when invalid.
  - Reservations project selector now loads all project pages (`apiGetAllPages`) so older projects are not silently omitted when total project count exceeds a single page.
- Started phase-2 provisional-allocation UX stream with an Orders-side entry path.
  - Orders `Order Details` now exposes `Create Provisional Reservation…`, which opens the Reservations page with prefilled draft fields (`item_id`, `quantity`, optional `project_id`, and source-order context) for faster stock-backed provisional linking.
- Implemented phase-3 provisional-allocation summary/export UX on Reservations.
  - Added `Provisional Allocation Summary` panel with project-level active provisional reservation totals/counts.
  - Added open incoming supply split metrics (`dedicated` vs `uncommitted`) based on open orders.
  - Added `Export Summary CSV` for provisional-allocation review handoff.

### Documentation

- Added phased rollout plan document for provisional allocation UX improvements:
  - `documents/provisional_allocation_plan.md`

### Tests

- Backend targeted snapshot regressions added for:
  - `basis=net_available` residual-stock calculation
  - rejection of `mode=past&basis=net_available`

## 2026-03-25

### Fixed

- Upload-first staging filename sanitization now preserves expected file suffixes (for example localized names such as `見積.csv` keep the `.csv` extension after sanitization), preventing valid CSV uploads from being rejected as `INVALID_CSV`.
- Orders ZIP staging now preserves distinct non-ASCII supplier directory names instead of collapsing them into `UNKNOWN`, preventing cross-supplier staging collisions during batch import.

### Tests

- Targeted backend API batch-upload regression command attempted:
  - `uv run python -m pytest backend/tests/test_api_integration.py -k "items_batch_upload_endpoint or orders_batch_upload_endpoint"`
  - Result in this environment: failed before test execution with `ModuleNotFoundError: No module named 'fastapi'` (missing backend dependency in runtime environment).

### Added

- Implemented Phase 1 of the shared-server adaptation plan.
  - Added frontend Users management page at `/users`.
  - Added browser-side create, edit, reactivate, and deactivate flows for shared-server user administration.
  - Added a shared frontend users-refresh signal so header user selection updates immediately after user mutations.

### Changed

- Extended `GET /api/users` with optional `include_inactive=true` so the frontend management screen can load inactive rows without changing its management workflow.

### Documentation

- Added the shared-server adaptation plan document (since removed).
  - This breaks the next shared-server readiness work into phased slices for frontend user management, upload-first batch imports, PDF filename resolution, and browser-delivered generated files.

### Added

- Added backend API regression coverage for PostgreSQL migration identity-resolution behavior.
  - `GET /api/users` now has explicit test coverage confirming anonymous reads remain allowed.
  - `GET /api/users/me` now has explicit test coverage for both missing-identity rejection and valid resolved-user reads.
  - Read requests that send an unknown identity now have explicit API coverage for the expected `USER_NOT_FOUND` error path.

### Fixed

- Aligned the PostgreSQL test Compose database user with the documented test connection string.
  - `docker-compose.test.yml` now uses `POSTGRES_USER=develop`, matching `TEST_DATABASE_URL=postgresql+psycopg://develop:test@localhost:5433/materials_test`.
  - This restores the documented `docker compose -f docker-compose.test.yml up -d` plus `uv run python -m pytest` workflow for PostgreSQL-backed backend tests.

### Tests

- Backend targeted API regression run:
  - `uv run python -m pytest backend/tests/test_api_integration.py -k "users_endpoint"`
- Backend targeted API regression run:
  - `uv run python -m pytest backend/tests/test_api_integration.py -k "users_endpoint_allows_anonymous_read or users_me_endpoint or unknown_user_header"`
- Backend full PostgreSQL suite:
  - `uv run python -m pytest`
  - Result: `170 passed`

## 2026-03-25 (shared-server adaptation phase 2)

### Added

- Implemented Phase 2 of the shared-server adaptation plan.
  - Added upload-first Items batch registration endpoint `POST /api/items/batch-upload`.
  - Added upload-first Orders ZIP endpoint `POST /api/orders/batch-upload`.
  - Added server-managed staging roots under:
    - `imports/staging/items/<job-id>/...`
    - `imports/staging/orders/<job-id>/...`
- Added backend staging adapters that reuse existing domain import logic instead of replacing it.
  - uploaded item registration CSVs are materialized into a staged `unregistered` folder and then passed to `register_unregistered_item_csvs(...)`
  - uploaded order ZIP contents are normalized into staged `csv_files/` and `pdf_files/` folders and then passed to `import_unregistered_order_csvs(...)`
- Added backend API regression coverage for:
  - Items batch upload success path
  - Orders batch ZIP success path
  - Orders batch ZIP validation failure when no CSV is present

### Changed

- Items page main batch action is now `Upload Batch CSVs`, with the old server-folder batch action kept as an explicit legacy fallback.
- Orders page main batch action is now `Upload Orders ZIP`, with the old server-folder batch action kept as an explicit legacy fallback / advanced path.
- Orders ZIP upload accepts both canonical `csv_files/...` and `pdf_files/...` package layouts and simpler supplier-subfolder package layouts, normalizing both into the existing import folder shape before import starts.

### Tests

- Backend targeted upload staging/API run:
  - `uv run python -m pytest tests/test_api_integration.py -k "orders_batch_upload_endpoint or items_batch_upload_endpoint or import_unregistered_endpoint"`
  - Result: `3 passed`
- Backend full PostgreSQL suite:
  - `uv run python -m pytest`
  - Result: `174 passed`
- Frontend type check:
  - `node .\\node_modules\\typescript\\bin\\tsc -b`
- Frontend tests:
  - `node .\\node_modules\\vitest\\vitest.mjs run`
  - Result: `29 passed`
- Frontend production build:
  - `node .\\node_modules\\vite\\bin\\vite.js build`

## 2026-03-25 (shared-server adaptation phase 3)

### Changed

- Implemented Phase 3 of the shared-server adaptation plan for Orders PDF handling.
  - Upload-first Orders ZIP imports now treat `pdf_link` as a filename-first browser contract.
  - Path-shaped `pdf_link` values inside uploaded ZIP CSVs are normalized down to filename semantics for compatibility before staged PDF resolution runs.
  - Legacy/manual server-path-compatible handling remains available for admin recovery and existing server-resident import flows.
- Updated the Orders page guidance so the primary shared-server instruction is now:
  - keep `pdf_link` blank, or
  - use filename-only such as `Q2026-0001.pdf`
  - use `Upload Orders ZIP` when the corresponding PDF file is part of the same browser upload

### Tests

- Backend targeted PDF-handling regression run:
  - `uv run python -m pytest tests/test_api_integration.py -k "orders_batch_upload_endpoint_normalizes_path_like_pdf_link_to_filename_contract or orders_batch_upload_endpoint_stages_zip_and_imports or orders_batch_upload_endpoint_rejects_zip_without_csv or test_order_import_rejects_unregistered_pdf_link_path"`
  - Result: `4 passed`
- Backend full PostgreSQL suite:
  - `uv run python -m pytest`
  - Result: `177 passed`
- Frontend type check:
  - `node .\\node_modules\\typescript\\bin\\tsc -b`
- Frontend tests:
  - `node .\\node_modules\\vitest\\vitest.mjs run`
  - Result: `29 passed`
- Frontend production build:
  - `node .\\node_modules\\vite\\bin\\vite.js build`

## 2026-03-25 (shared-server adaptation phase 4)

### Added

- Implemented Phase 4 of the shared-server adaptation plan for generated file delivery.
  - Added generated-artifact API endpoints:
    - `GET /api/artifacts`
    - `GET /api/artifacts/{artifact_id}`
    - `GET /api/artifacts/{artifact_id}/download`
  - Added lightweight filesystem-backed artifact metadata for generated missing-item register CSVs under `imports/items/unregistered/`.
- Orders import and batch-import responses now include managed artifact metadata for generated missing-item register CSVs instead of only raw filesystem paths.

### Changed

- Orders page now exposes browser download buttons for generated missing-item register CSVs and shows a recent generated-files list backed by the new artifact API.
- Shared-server artifact delivery now uses browser-download endpoints instead of asking users to interpret server paths printed in status text.

### Tests

- Backend targeted artifact/API regression run:
  - `uv run python -m pytest tests/test_api_integration.py -k "generated_artifact_endpoints_expose_missing_items_register_download or orders_batch_upload_endpoint_normalizes_path_like_pdf_link_to_filename_contract or orders_batch_upload_endpoint_stages_zip_and_imports"`
  - Result: `3 passed`
- Backend full PostgreSQL suite:
  - `uv run python -m pytest`
  - Result: `178 passed`
- Frontend type check:
  - `node .\\node_modules\\typescript\\bin\\tsc -b`
- Frontend tests:
  - `node .\\node_modules\\vitest\\vitest.mjs run`
  - Result: `29 passed`
- Frontend production build:
  - `node .\\node_modules\\vite\\bin\\vite.js build`

## 2026-03-25 (shared-server adaptation phase 5)

### Changed

- Implemented Phase 5 of the shared-server adaptation plan for UI deprecation and wording cleanup.
  - Items page fallback copy now describes server-resident CSV processing as an advanced path instead of the main workflow.
  - Orders page fallback copy now describes existing server-resident batch inputs as an advanced path, and the default batch button is labeled `Run Existing Imported Batch`.
  - Manual Orders import guidance now points browser users toward `Upload Orders ZIP` when the PDF belongs to the same upload, instead of suggesting folder-operated batch flows.

### Documentation

- Updated shared-server wording in:
  - `specification.md`
  - `documents/technical_documentation.md`
  - `documents/source_current_state.md`
  - `documents/change_log.md`

## 2026-03-24 (PostgreSQL migration foundation)

### Fixed

- `GET /api/users/me` now resolves correctly in the deployed FastAPI app.
  - The static `/api/users/me` route is now registered before `/api/users/{user_id}` so it is no longer misparsed as `user_id="me"` and rejected with a `422` validation error during runtime smoke tests.
- Read requests that provide an explicit identity now resolve `request.state.user` without forcing credentials for anonymous reads.
  - This restores the intended behavior of `GET /api/users/me`: anonymous reads remain allowed globally, while callers that send a valid identity can retrieve their active user identity on a read request.

### Documentation

- Added a consolidated rollout/status handoff document at `documents/postgresql_migration_plan/postgresql_migration_plan.md`.
  - This records completed migration work, verified runtime/test status, remaining operational tasks, and the exact steps required to finish the PostgreSQL/shared-server rollout.

### Added

- PostgreSQL-first backend bootstrap using SQLAlchemy engine management and Alembic baseline migration.
- Initial PostgreSQL schema under `backend/alembic/versions/001_initial_schema.py`, including `users` plus audit columns/triggers.
- Docker deployment artifacts:
  - `docker-compose.yml`
  - `docker-compose.override.yml`
  - `docker-compose.test.yml`
  - `.env.example`
  - `backend/Dockerfile`
  - `frontend/Dockerfile`
  - `frontend/nginx.conf`
- User management endpoints:
  - `GET /api/users`
  - `GET /api/users/{id}`
  - `GET /api/users/me`
  - `POST /api/users`
  - `PUT /api/users/{id}`
  - `DELETE /api/users/{id}`
- Windows Server deployment runbook: `documents/postgresql_windows_server_instructions.md`

### Changed

- Backend entrypoint is now server-only (`uv run main.py`); the legacy CLI flow is no longer the target path for the PostgreSQL/shared-server deployment.
- Frontend API client now uses `VITE_API_BASE` / `/api` directly instead of runtime port probing.
- Frontend mutations now require an explicit browser identity context.
- Header bar now includes an authentication control populated from runtime identity state.
- Vite dev server now binds to `0.0.0.0` and proxies `/api` to `http://backend:8000`.

### Tests

- Backend syntax/buildability smoke: `uv run python -m compileall app main.py tests`
- Frontend production build: `npm run build`

## 2026-03-24

### Fixed

- Orders page split editing now preserves an explicit `No project assignment` choice for already-assigned open orders.
  - When the edit keeps `split_quantity` but clears the project selection, the frontend now includes `project_id: null` in the split update so both resulting rows become generic instead of silently retaining the previous manual assignment.
- Confirm allocation no longer persists reservations or dedicated orders for `PLANNING` projects.
  - `POST /api/projects/{project_id}/confirm-allocation` still supports dry-run preview for draft projects.
  - Execute now fails with `PROJECT_CONFIRMATION_REQUIRED` until the project is `CONFIRMED` or `ACTIVE`, preventing hidden stock/order consumption outside the committed planning pipeline.
- Orders page split-plus-project editing now assigns only the consumed child order.
  - The frontend no longer sends `split_quantity` and `project_id` together in one `PUT /api/orders/{id}` payload.
  - It now performs the split request first and, when a project was selected, follows with a second update against the created child order so the postponed sibling remains generic.

### Tests

- Backend targeted tests added for draft-project confirm-allocation rejection at both service and API layers.
- Frontend Orders page regression test added for split-then-assign request sequencing.

## 2026-03-24

### Added

- Workspace planning board now supports confirm-allocation preview/execute workflow.
  - Added backend endpoint `POST /api/projects/{project_id}/confirm-allocation` with `dry_run` preview support.
  - Execution persists stock-backed generic coverage as project reservations and generic-order coverage as dedicated order rows.
  - Partial generic-order coverage now splits the order first, then assigns only the consumed child row to the project.
  - Preview/execute is guarded by `snapshot_signature`; stale confirms now fail with `PLANNING_SNAPSHOT_CHANGED`.

### Changed

- Orders page open-order editing now includes manual project assignment in the existing ETA/split flow.
  - Users can assign or clear `project_id` directly from the Orders page.
  - UI now surfaces clearer messages when an ORDERED RFQ/procurement link owns the order-project assignment.
- Workspace summary cards and project drawer counters now read current procurement counts from `procurement_summary`.
- Procurement page selected-batch detail now supports inline line editing for `status`, `finalized_quantity`, `supplier_name`, `expected_arrival`, `linked_order_id`, and `note`.
  - Linked-order options are loaded lazily for the active line using the same order-option pattern as the RFQ editor.

### Tests

- Backend full suite: `164 passed`.
- Frontend production build: `npm run build` succeeded.

## 2026-03-24

### Fixed

- Workspace planning recovery summaries and burndown rows now treat missing later-arrival dates as unknown instead of surfacing backend null placeholders such as `None`.
  - Recovery-source sorting now pushes undated sources to the end of the burndown sequence.
  - Summary copy now falls back to `unknown date` when recovery exists but no arrival date is available.

### Changed

- Workspace planning recovery UX now shows later-arrival impact more explicitly.
  - Planning-board `Recovered Later` cells now summarize outcome timing in compact text such as `Recovered by ...`, `Resolved on ...`, or `Still short ...`.
  - Item drawer planning cards now include a chronological recovery burndown table built from `recovery_sources_after_start`, showing each dated recovery step and the remaining start-date gap after that step.

## 2026-03-23 (batch item registration encoding fix)

### Fixed

- Batch item registration (`Run Unregistered Batch`) no longer fails when the batch CSV contains CP932-encoded Japanese supplier names mixed with otherwise UTF-8 content.
  - Root cause: `batch_missing_items_registration_*.csv` files containing `光響` (and other Japanese supplier names) can end up with Shift-JIS/CP932 bytes in the supplier columns while the rest of the file is UTF-8 (e.g. when the file is edited or re-saved by a tool using the Windows system encoding).
  - `_decode_csv_bytes()` helper added: tries UTF-8 first, falls back to CP932 on `UnicodeDecodeError`.
  - `_load_csv_rows_from_path`, `_load_csv_rows_with_fieldnames_from_path`, and `_load_csv_rows_from_content` all now use `_decode_csv_bytes()` so the fallback is applied consistently across all CSV-reading paths.
  - The existing corrupted CSV (`imports/items/unregistered/batch_missing_items_registration_20260323_193422.csv`) was repaired in-place by replacing the 8 CP932 `光響` byte sequences (`8C F5 8B BF`) with the correct UTF-8 encoding (`E5 85 89 E9 9F BF`).
- `Run Unregistered Batch` result message now shows per-file error details when any file fails, instead of only showing the opaque `failed=N` count.
  - The TypeScript response type was extended to include the `files` array.
  - Failed file paths and their error messages are displayed below the summary line.
  - The message element was changed from `<p>` to `<pre className="whitespace-pre-wrap">` so multi-line error output renders correctly.

### Tests

- Backend full suite: `161 passed`.
- Frontend TypeScript compile: no errors (`npx tsc -b --noEmit`).

## 2026-03-23 (project planning assembly requirement expansion fix)

### Fixed

- Restored assembly-backed project demand expansion in planning aggregation:
  - `_aggregate_project_required_by_item` now expands `assembly_id` requirements into component-level item demand (quantity × component quantity) instead of skipping non-`item_id` rows.
  - This fixes project gap-analysis totals and downstream project shortage follow-up flows (for example purchase-candidate creation) for projects that still carry assembly-based requirements.

### Tests

- Added backend regression coverage validating that assembly-only project requirements produce expected component shortages in project gap analysis and create the correct purchase candidate quantity.

## 2026-03-23

### Changed

- Began the redesign transition from RFQ and purchase-candidate flows to a unified procurement workflow.
  - Added backend procurement persistence via `procurement_batches` and `procurement_lines`, plus migration logic from legacy RFQ and purchase-candidate tables.
  - Added procurement API endpoints and a new frontend `Procurement` page.
  - Updated workspace, BOM, projects, and reservations UI paths toward the procurement-first route structure described in `temporary/redesign_specification.md`.
  - Simplified primary project requirement editing toward item-only requirements.

### Compatibility

- Kept temporary legacy API/service compatibility for RFQ, assembly, and purchase-candidate routes so existing callers and tests do not hard-fail during the redesign.
- Workspace summary and order-project ownership checks now recognize both legacy RFQ ownership and the new procurement ownership model during migration.

### Tests

- Frontend production build executed successfully: `npm run build`.
- Frontend TypeScript compile executed successfully: `npx tsc -b`.
- Backend full suite executed: `151 passed`, `3 failed`.
- Follow-up change: default `GET /projects/{id}/gap-analysis` without `target_date` now explicitly uses current stock only and does not project pending arrivals; explicit `target_date` still enables projection.

### Fixed

- Workspace multi-project CSV export now keeps `target_date` aligned with the selected planning analysis date instead of duplicating each row's `planned_start`.
  - Preview-inclusive exports now write the shared requested/effective board date on every row so downstream consumers can distinguish analysis date from project start date.
  - Committed-only exports leave `target_date` blank because there is no single selected preview date for the whole pipeline snapshot.
- Restored redesign compatibility gaps found during review.
  - Re-added the Location-page assembly assignment API route `PUT /api/locations/{location}/assemblies`.
  - Project detail/update flows now preserve legacy `project_requirements` rows stored with `assembly_id` and no `item_id`, while the item-only editor warns that those legacy rows are preserved but not editable there.
  - Workspace procurement creation can again confirm `PLANNING` projects and persist the active planning date when creating procurement from project shortages.
- Fixed follow-up regressions in the procurement-first transition.
  - `GET /api/rfq-batches` no longer fails from an adapter/service signature mismatch.
  - Procurement unlink sync now falls back to ORDERED RFQ ownership before clearing `orders.project_id`.
  - Reservations preview confirmation now sends `assembly_id` overrides when the user resolves a row to an assembly.
  - BOM shortage handoff now stops with a message instead of creating an empty procurement batch when no resolved shortage rows remain.

## 2026-03-12

### Fixed

- Orders page quotation review now loads the full `/orders` and `/quotations` datasets across API pages before computing `Imported Quotations` order counts or opening `Quotation Details`.
  - Older quotations such as `オーテックス / 0000001809` and `ミスミ / AA116E19FB` no longer show `Orders = 0` just because their linked orders fall outside the first `/orders?per_page=200` page.
  - `Imported Quotations -> View Orders` now opens a dedicated quotation panel that lists every linked order for the selected quotation instead of only one linked order.
- Rearranged Orders-page drill-down UX to separate quotation review from order drill-down.
  - `Order List -> Order Details` now opens a dedicated `Order Details` panel with selected-order metadata and same-item purchasing history.
  - `Imported Quotations -> View Orders` now opens a separate `Quotation Details` panel, removing the confusing shared `Order Context` behavior between the two tables.
- Improved Orders-page browse ergonomics for larger datasets.
  - `Imported Quotations` now supports the same inline collapse/expand pattern as `Order List` and starts collapsed to reduce long-scroll overhead.
  - Expanded `Order List` now includes a primary search plus secondary filter controls, mirroring the quotation review workflow.

### Added

- Automatic CSV consolidation for registered items imports: after each `register_unregistered_item_csvs()` batch run, small CSV files in `imports/items/registered/<YYYY-MM>/` subfolders are automatically merged into consolidated files via `consolidate_registered_item_csvs()`.
  - Consolidated file naming: `items_YYYY-MM_NNN.csv` (e.g., `items_2026-03_001.csv`, `items_2026-03_002.csv`)
  - Maximum 5,000 rows per consolidated file, configurable via `ITEMS_IMPORT_MAX_CONSOLIDATED_ROWS` in `config.py`
  - Files already matching the `items_YYYY-MM_NNN.csv` pattern are recognized as previously consolidated and included in merge passes
  - Original non-consolidated source CSVs are deleted after successful consolidation
  - Design decision: consolidated CSVs are **import-history archives only** — UI edits to item attributes affect the database, not the CSV archives

### Fixed

- Items manual CSV import now archives successful uploads into `imports/items/registered/<YYYY-MM>/` and reuses the monthly `items_YYYY-MM_NNN.csv` consolidation flow, so direct imports and batch registrations land in the same registered archive history.
- Items page `Import Items CSV` now accepts multiple CSV selections and runs preview/import across the selected files in one UI pass.
- Projects quick requirement unresolved-item CSV export now uses the reviewed preview snapshot when available, preventing preview/export drift if the textarea content changes before download.
- Projects quick requirement registration CSV export now also includes `needs_review` rows that only have fuzzy/non-exact suggestions, while still excluding duplicate/exact-review rows so likely new item numbers are easier to register from the Items tab.
- `migrate_orders_import_layout()` now also rewrites stale `pdf_link` values inside registered order CSV archives, not just unregistered CSVs/DB rows, so historical quotation links stay aligned after the `imports/orders/` path migration.
- `import_unregistered_order_csvs()` now rewrites each moved registered order CSV archive with the final registered `pdf_link` values, preserving the imported quantity/archive consistency for follow-up batch/retry workflows and avoiding stray fallback archive behavior.
- Hardened registered-item CSV consolidation safety.
  - `register_unregistered_item_csvs()` now skips automatic consolidation when any file in the batch fails, preventing partially failed runs from rewriting archives.
  - `consolidate_registered_item_csvs()` now stages replacement files and only swaps them into place after all chunk writes succeed, preserving existing consolidated archives when a write fails mid-run.
  - `register_unregistered_item_csvs()` now keeps each per-file savepoint open until report construction succeeds, so a post-move failure restores the CSV to `imports/items/unregistered/` and rolls back that file's DB changes.
  - `consolidate_registered_item_csvs()` now removes header-only registered CSV inputs without creating empty `items_YYYY-MM_NNN.csv` archives.
- Backend test fixtures now redirect workspace import/export roots into per-test temporary directories, preventing order-import/API test runs from contaminating `imports/items/unregistered/` with artifact CSVs.
- Items page `Resolve Missing Items From Orders` now shows a manufacturer column in addition to alias supplier context, matching Bulk Item Entry for new-item registration while keeping alias-supplier edits available.

### Tests

- Added frontend regression coverage for Orders page quotation counts, quotation-wide order listing, separated order-vs-quotation detail panels, Order List filtering, and Imported Quotations collapse/expand behavior.

## 2026-03-11

### Changed

- Path unification Phase 2: moved `quotations/` top-level directory under `imports/orders/`.
  - Directory paths: `quotations/` → `imports/orders/`, `quotations/registered/` → `imports/orders/registered/`, `quotations/unregistered/` → `imports/orders/unregistered/`
  - Config constants: `QUOTATIONS_ROOT` → `ORDERS_IMPORT_ROOT`, `QUOTATIONS_REGISTERED_ROOT` → `ORDERS_IMPORT_REGISTERED_ROOT`, `QUOTATIONS_UNREGISTERED_ROOT` → `ORDERS_IMPORT_UNREGISTERED_ROOT`, `QUOTATIONS_REGISTERED_CSV_ROOT` → `ORDERS_IMPORT_REGISTERED_CSV_ROOT`, `QUOTATIONS_REGISTERED_PDF_ROOT` → `ORDERS_IMPORT_REGISTERED_PDF_ROOT`, `QUOTATIONS_UNREGISTERED_CSV_ROOT` → `ORDERS_IMPORT_UNREGISTERED_CSV_ROOT`, `QUOTATIONS_UNREGISTERED_PDF_ROOT` → `ORDERS_IMPORT_UNREGISTERED_PDF_ROOT`
  - Module: `quotation_paths.py` → `order_import_paths.py`
  - Dataclass: `QuotationRoots` → `OrderImportRoots`
  - Service function: `migrate_quotations_layout` → `migrate_orders_import_layout`
  - CLI command: `migrate-quotations-layout` → `migrate-orders-layout` (old name kept as alias)
  - Backward-compatible migration: `ensure_workspace_layout()` auto-migrates legacy `quotations/` directories to `imports/orders/` on startup.

## 2026-03-10

### Changed

- Unified CSV import path terminology: renamed items import directories from `pending/processed` to `unregistered/registered` for consistency with the order/quotation import flow. Updated config constants, service functions, API endpoints, CLI commands, and frontend UI accordingly. Old CLI command names kept as aliases for backward compatibility. Legacy `pending`/`processed` directories are auto-migrated on startup via `ensure_workspace_layout()`.
  - Directory paths: `imports/items/pending/` → `imports/items/unregistered/`, `imports/items/processed/` → `imports/items/registered/`
  - Config constants: `ITEMS_IMPORT_PENDING_ROOT` → `ITEMS_IMPORT_UNREGISTERED_ROOT`, `ITEMS_IMPORT_PROCESSED_ROOT` → `ITEMS_IMPORT_REGISTERED_ROOT`
  - Service function: `register_pending_item_csvs` → `register_unregistered_item_csvs`
  - API endpoint: `/api/items/register-pending-batch` → `/api/items/register-unregistered-batch`
  - CLI command: `register-pending-items` → `register-unregistered-items` (old name kept as alias)
  - Schema: `PendingItemBatchRequest` → `UnregisteredItemBatchRequest`

## 2026-03-09

### Fixed

- Restored the CLI pending-item batch registration command after the service rename.
  - `backend/main.py register-pending-items` now calls `register_pending_item_csvs(...)`.
  - The legacy command name `register-unregistered-missing` remains as a compatibility alias while using the new pending/processed root arguments internally.
- Updated the root-level debug scripts to exercise the current pending-item workflow and current order import root layout instead of removed helpers/paths.

### Docs

- Updated `README.md`, `documents/technical_documentation.md`, and `documents/source_current_state.md` so the documented missing-item batch workflow points at `imports/items/pending/` and `imports/items/processed/<YYYY-MM>/`.

## 2026-03-08

### Fixed

- Reduced RFQ page render pressure by lazy-loading linked-order choices per active line instead of preloading and rendering the full order-option set for the entire batch.
- Preserved current linked-order selections in RFQ rows using saved line metadata so existing links remain visible before on-demand order options finish loading.
- Limited RFQ line-table rendering to a paged slice (25/50/100 rows) so large batches no longer keep the full editable grid mounted during client-side tab transitions.

### Docs

- Updated `documents/technical_documentation.md` and `documents/source_current_state.md` with the RFQ lazy linked-order loading and paged line-table behavior.

### Tests

- Added frontend helper coverage for RFQ linked-order option state and RFQ line pagination helpers.
- Frontend test suite executed: `npm run test` -> `8 passed` test files, `20 passed` tests.
- Frontend production build executed: `npm run build`.

## 2026-03-08

### Fixed

- Replaced the workspace unsaved-change route-leave guard from `unstable_usePrompt` to `useBlocker` with an explicit confirm/reset flow.
- Fixed a frontend navigation regression where opening RFQ after workspace interactions could leave client-side tab changes stuck until a full page refresh, even though the URL updated.

### Docs

- Updated `documents/technical_documentation.md` and `documents/source_current_state.md` with the blocker implementation change and the RFQ/tab-navigation regression note.

### Tests

- Frontend test suite executed: `npm run test` -> `8 passed` test files, `15 passed` tests.
- Frontend production build executed: `npm run build`.

## 2026-03-08

### Fixed

- Migrated the frontend bootstrap from plain `BrowserRouter` to a React Router data router (`createBrowserRouter` + `RouterProvider`) while preserving the existing route tree under `AppShell`.
- Restored the `/workspace` page so its unsaved-change prompt can use `unstable_usePrompt` without crashing on mount; opening the Workspace tab no longer produces a blank page from the router-context mismatch.

### Docs

- Updated `documents/technical_documentation.md` and `documents/source_current_state.md` with the data-router bootstrap and workspace blocker/runtime notes.

### Tests

- Added frontend regression coverage that mounts `/workspace` through a memory data router to verify the page renders without the previous blank-screen crash.
- Frontend test suite executed: `npm run test` -> `8 passed` test files, `15 passed` tests.
- Frontend production build executed: `npm run build`.

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
  - added `GET /api/workspace/planning-export-multi` for CSV export of the full planning pipeline, with optional selected-project preview inclusion
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
  - Projects page quick parser can now download unresolved rows as an Items import-compatible CSV for follow-up registration on the Items tab.
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

- Projects item target search now includes item descriptions in candidate summaries across catalog-backed requirement selection and project requirement preview suggestions.
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
  - Deleting an item referenced by a purchase candidate now returns controlled domain/API error handling (`ITEM_REFERENCED`) instead of bubbling raw FK errors.

### Tests

- Added backend service regression tests for BOM date-aware analysis and past-date validation.
- Added backend API integration tests for `/api/bom/analyze` with and without `target_date`.
- Added backend service/API regression coverage for project-gap `target_date` projection and purchase-candidate create/list/update flows.
- Replaced hardcoded near-future target dates in target-date tests with a deterministic far-future value to avoid time-dependent failures.
- Added backend service regression coverage for item deletion blocked by `purchase_candidates` references.

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

- Missing-item upload parity:
  - Fixed `POST /api/register-missing` so the content-based registration path now forwards `skip_unresolved`, matching path-based batch registration behavior.
  - Added backend regression coverage for default rejection vs explicit skip behavior on unresolved upload rows.

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
  - A single consolidated register CSV is generated per batch run under `imports/orders/unregistered/missing_item_registers/`.
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
  - Order batch import now explicitly skips files under `imports/orders/unregistered/missing_item_registers/`.
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
  - when a file returns `missing_items`, source CSV/PDF files remain under `imports/orders/unregistered/...`.
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
  - unregistered batch import with `imports/orders/unregistered/...` `pdf_link`
  - items import-jobs listing endpoint route behavior
  - slash-date order import acceptance
  - unresolved missing-item row rejection

## 2026-03-02 (UI order/quotation maintenance)

### Added

- Orders API endpoints:
  - `DELETE /api/orders/{order_id}`
  - `DELETE /api/quotations/{quotation_id}`
- Orders frontend UI actions:
  - delete order from `Order List`
  - edit quotation `issue_date` / `quotation_document_url`
  - delete quotation (and linked orders)

### Changed

- Quotation update flow now synchronizes matching source order CSV rows (`issue_date`, `quotation_document_url`) with DB updates.
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

## 2026-03-04 (CSV sibling-order bug fixes for split/merge)

### Fixed

- Fixed merge CSV synchronization to compute source/target sibling occurrence matchers before deleting source DB row, and adjusted target occurrence handling when source precedes target so merged quantity/ETA updates apply to the correct CSV row.
- Fixed split CSV insertion ordering so newly created split rows are appended after the existing sibling block (order-id occurrence order), preventing row-identity drift when splitting a non-final sibling row.

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

## Notes

- Formal semantic versioning and release tags can be adopted once GitHub release workflow is started.
- Recommended next step: map this log format to `vX.Y.Z` releases and attach migration notes per release.
