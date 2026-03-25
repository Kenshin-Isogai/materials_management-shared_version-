# Team Onboarding Guide

Last updated: 2026-03-25 (JST)

## 1. Who This Is For

This guide is for team members setting up the application on their local machine for development and testing.

Assumed environment:

- Windows 10/11
- Git available
- Docker Desktop available (Docker Compose v2)
- Node.js + npm available
- Python 3.10+ available
- `uv` recommended for Python environment/dependency management

## 2. First-Time Setup

### Step 1: Choose local workspace directory

Example:

```powershell
cd C:\Users\<your_user>\Documents
mkdir Yaqumo
cd Yaqumo
```

### Step 2: Clone the repository

Replace `<REMOTE_REPO_URL>` with your GitHub repository URL.

```powershell
git clone <REMOTE_REPO_URL>
cd materials_management
```

### Step 3: Install `uv` (recommended)

Install `uv` using the official instructions:

- https://docs.astral.sh/uv/getting-started/installation/

Verify installation:

```powershell
uv --version
```

### Step 4: Verify Node.js / npm

```powershell
node --version
npm --version
```

If missing, install Node.js LTS and re-open your terminal.

## 3. Project Dependency Setup

### Step 5: Install backend dependencies (with `uv`)

```powershell
cd backend
uv sync
cd ..
```

### Step 6: Install frontend dependencies (`npm`)

```powershell
cd frontend
npm install
cd ..
```

## 4. Initialize and Run

### Step 7: Configure environment and start database

```powershell
copy .env.example .env
# Edit .env if you need to change default database credentials or ports
docker compose up -d db
```

Wait a few seconds for PostgreSQL to become ready. The database schema is managed by Alembic — migrations run automatically when the backend starts. To run them manually:

```powershell
docker compose exec backend uv run alembic upgrade head
```

> **Note:** The application uses PostgreSQL 16+ via Docker Compose. There is no local SQLite database.

### Step 8 (recommended): Start full stack with Docker Compose

```powershell
docker compose up --build -d
```

For dev mode with live reload (uses `docker-compose.override.yml`):

```powershell
docker compose -f docker-compose.yml -f docker-compose.override.yml up --build
```

Expected access points:

- Frontend (nginx): `http://localhost/`
- Frontend (Vite dev): `http://127.0.0.1:5173`
- Backend API (nginx): `http://localhost/api`
- Backend API (direct): `http://127.0.0.1:8000/api`

To stop:

```powershell
docker compose down
```

### Step 8 (local alternative): Start with helper script

```powershell
.\start-dev.bat
```

Expected:

- Frontend: `http://127.0.0.1:5173`
- Backend API: first free port in `8000, 8001, 8010, 18000`

To stop:

```powershell
.\stop-dev.bat
```

> **Note:** Even with `start-dev.bat`, the PostgreSQL database must be running (`docker compose up -d db`).

## 5. Verify the Setup

### Step 9: Backend health check

Open in browser:

- Through nginx: `http://localhost/api/health`
- Direct: `http://127.0.0.1:8000/api/health`
- Swagger docs: `http://127.0.0.1:8000/docs`

### Step 9b: Create your first user

After the app is running, create at least one user:

- Open the `/users` page in the UI and add a user, or
- Call the API directly (e.g., `POST /api/users`)

Mutations (create, update, delete) require the `X-User-Name` header. In the UI, select a user from the header dropdown before making changes. Read operations work without a user.

### Step 10: Run backend tests

Backend tests run against a dedicated PostgreSQL test instance:

```powershell
docker compose -f docker-compose.test.yml up -d
cd backend
$env:TEST_DATABASE_URL='postgresql+psycopg://develop:test@localhost:5433/materials_test'
uv run python -m pytest
```

To stop the test database afterward:

```powershell
docker compose -f docker-compose.test.yml down
```

### Step 11: Run frontend production build check

```powershell
cd frontend
npm.cmd run build
```

Note: On some Windows PowerShell setups, `npm run ...` may be blocked by execution policy. Use `npm.cmd run ...` instead.

## 6. Daily Update Workflow

After you already cloned once:

```powershell
cd <your_local_path>\materials_management
git pull
docker compose up -d          # ensure containers (db, backend, frontend) are running
cd backend
uv sync
cd ..\frontend
npm install
cd ..
```

Then run tests and start the app as usual.

## 7. Where To Read Before Making Changes

Before implementing code changes, read in this order:

1. `specification.md`
2. `documents/technical_documentation.md`
3. `documents/source_current_state.md`
4. `documents/change_log.md`

This order matches the precedence policy used in this repository.
