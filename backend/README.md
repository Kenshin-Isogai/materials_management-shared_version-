## Optical Component Inventory Management Backend

### Setup

```bash
uv sync
```

### Run API Server

```bash
uv run main.py
```

API base URL: `http://127.0.0.1:8000/api`

### Database Bootstrap

```bash
uv run alembic upgrade head
```

The backend is now PostgreSQL-first and expects `DATABASE_URL` to be set.

### Cloud Run Runtime

- Set `APP_RUNTIME_TARGET=cloud_run`
- `PORT` is used automatically for the listener port
- If `APP_DATA_ROOT` is not set, runtime file roots default under the OS temp directory
- In Cloud Run mode, startup skips legacy workspace/import folder migration and only creates the required empty runtime directories

### Docker

```bash
docker compose up --build
```

### Backend Tests (Docker PostgreSQL)

From the repository root:

```powershell
docker compose -f docker-compose.test.yml up -d db-test
$env:TEST_DATABASE_URL = "postgresql+psycopg://develop:test@localhost:5433/materials_test"
$env:PYTHONPATH = "backend"
uv run --project backend python -m pytest --import-mode=importlib
```

### Authentication

- Read-only endpoints can be called anonymously.
- Mutation endpoints require `X-User-Name` for an active user in the `users` table.
