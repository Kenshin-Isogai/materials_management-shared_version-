

## Rule

### Executing Python code

Please use `uv run` instead of `python`. 

The python environment in this project folder is prepared using `uv`.

### Preferred Runtime And Validation Environment

This application should be treated as **Docker-first** for runtime validation.

- Preferred app startup:
  - `.\start-app.ps1`
  - or `.\start-app.ps1 -IncludeDevOverride` only when the dev override is explicitly needed
- Base stack:
  - `db` + `backend` + `nginx` from `docker-compose.yml`
- Default runtime URLs after `.\start-app.ps1`:
  - Frontend: `http://127.0.0.1/`
  - API: `http://127.0.0.1/api`
  - Swagger: `http://127.0.0.1/docs`

When validating user-facing behavior, prefer checking the running Docker stack over relying only on the local `uv` environment.

### Mutation Request Note

Even when auth mode is effectively open for reads, API mutation requests require `X-User-Name` for an active user in the `users` table.

- Anonymous reads are allowed.
- Writes without `X-User-Name` will fail.
- If runtime validation needs write access, first confirm an active user exists in the running environment.

### Required Context Documents (Read Before Implementing)

When implementing or modifying code, consult these documents first:

1. `specification.md` (source of truth for requirements and contracts)
2. `documents/technical_documentation.md` (architecture and maintenance guidance)
3. `documents/source_current_state.md` (current implementation snapshot)
4. `documents/change_log.md` (recent behavior and design changes)

If any conflict appears, follow precedence:

1. `specification.md`
2. `documents/technical_documentation.md`
3. current code behavior

### Tools During PDF/CSV Task

#### System tool

`Tesseract OCR` (installed via winget)
- Default path: `C:\Program Files\Tesseract-OCR\tesseract.exe`
- Installed language data: `eng` and `osd` only.

#### How to use (examples)

List available OCR languages:

```powershell
& "C:\Program Files\Tesseract-OCR\tesseract.exe" --list-langs
```

Note: If you need Japanese OCR, install `jpn` traineddata for Tesseract and set `TESSDATA_PREFIX` as needed.

### Application Update Workflow (Required)

When updating this application, follow this order:

1. Confirm scope and impacted areas (`backend`, `frontend`, DB schema, quotation file flow).
2. Implement the change in the domain layer first (`backend/app/service.py`), then wire adapters (`backend/app/api.py`, `backend/main.py`) and UI (`frontend/src`) as needed.
3. If schema/constraints change, update `backend/app/db.py` with idempotent migration-safe changes.
4. Prefer validation in the intended Docker environment:
   - Start the app stack with `.\start-app.ps1`
   - Use the running API/UI for changed user-flow validation
   - For mutation-path validation, include `X-User-Name` and ensure that user exists in the running DB
5. Run automated tests with `uv run` as available:
   - Full backend tests: `uv run python -m pytest`
   - Or targeted tests for touched behavior (for faster iteration), then run full suite before completion when the environment supports it
   - If local `uv` test execution is blocked by environment drift, dependency issues, or sandbox/runtime differences, record that clearly and continue with Docker runtime validation instead of guessing
6. Validate runtime behavior for changed user flows (API/CLI/UI path that was modified).
7. Update documentation in the same change set:
   - User-facing setup/usage: `README.md` (root and/or `backend/README.md`, `frontend/README.md` if relevant)
   - Architecture/data model/maintenance notes: `documents/technical_documentation.md`
   - Current-state snapshot updates: `documents/source_current_state.md` when structure/behavior changed
   - Change history updates: `documents/change_log.md` for meaningful changes
   - Requirements/spec updates: `specification.md` when behavior or contract changed
8. In your final report, always include:
   - What changed
   - What tests were run (and results)
   - What documentation was updated

