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

### Docker

```bash
docker compose up --build
```

### Authentication

- Read-only endpoints can be called anonymously.
- Mutation endpoints require `X-User-Name` for an active user in the `users` table.
