# PostgreSQL / Windows Server Deployment Instructions

Last updated: 2026-03-25 (JST)

## Purpose

This runbook covers the server-side steps for deploying the application on the target Windows Server using Docker Compose.

## What Was Added In The Repository

- PostgreSQL-first backend bootstrap
- Alembic baseline migration under `backend/alembic/`
- Docker Compose files for production, development, and test DB
- Backend and frontend Dockerfiles
- nginx reverse-proxy config
- Header-based user selection flow (`X-User-Name`)

## Server Prerequisites

1. Install Docker Desktop or another Docker Engine setup supported on the Windows Server host.
2. Ensure Linux containers are available.
3. Open inbound TCP port `80` on the server if the UI should be reachable from other machines.
4. Confirm the server has enough persistent storage for:
   - PostgreSQL volume data
   - application import/export files under the mounted `appdata` volume

## Initial Server Setup

1. Copy the repository to the server.
2. Copy `.env.example` to `.env`.
3. Set at least:
   - `POSTGRES_PASSWORD`
   - `DATABASE_URL`
   - `CORS_ALLOWED_ORIGINS`
4. If you want application files outside the default Docker volume path, adjust `APP_DATA_ROOT` before first startup.

## First Startup

From the repository root on the server:

```powershell
docker compose up --build -d
```

Then verify:

```powershell
docker compose ps
docker compose logs -f db
docker compose logs -f backend
docker compose logs -f nginx
```

## Database Initialization

Alembic runs from the backend startup path, but you should also be able to run it explicitly during maintenance:

```powershell
docker compose exec backend uv run alembic upgrade head
```

## Seed Initial Users

Mutation requests require an active user in the `users` table. Before handing the system to operators, create at least one user.

Option A — Use the frontend `/users` page (recommended after first startup):

1. Open `http://<server>/users` in a browser.
2. Create a user with admin role.
3. Select that user in the header dropdown.

Option B — Create via backend shell:

```powershell
docker compose exec backend uv run python -c "from app.db import get_connection, init_db; from app import service; init_db(); conn=get_connection(); service.create_user(conn, {'username':'admin','display_name':'Admin','role':'admin','is_active':True}); conn.commit(); conn.close()"
```

Repeat for each operator who should be able to make changes.

## Operational Checks

1. Open `http://<server>/api/health`
2. Open `http://<server>/`
3. In the UI header, confirm the user dropdown lists the seeded users.
4. Test one read-only screen anonymously.
5. Select a user and test one mutation flow:
   - create supplier
   - create item
   - import or edit an order
6. Confirm uploaded/imported files appear in the mounted app-data volume.

## Backup Guidance

Minimum backup targets:

1. PostgreSQL data volume (`pgdata`)
2. Application data volume (`appdata`)
3. `.env`

If you need logical PostgreSQL backups:

```powershell
docker compose exec db pg_dump -U $env:POSTGRES_USER $env:POSTGRES_DB > materials_backup.sql
```

## Update Procedure

1. Pull the updated repository state onto the server.
2. Rebuild and restart:

```powershell
docker compose up --build -d
```

3. Check backend logs for Alembic upgrade output.
4. Re-run the operational checks above.

## Known Follow-Up Items

- The raw-SQL service layer is still in transition behind a PostgreSQL compatibility wrapper; broader runtime validation on the actual server is required.
- Full PostgreSQL-backed test-suite execution still depends on a reachable `TEST_DATABASE_URL` / Docker test DB.
- Role-based enforcement is not active yet; current trust model is still internal-network only.
