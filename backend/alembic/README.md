# Alembic migrations

Run migrations from the repository root with:

```bash
uv run --project backend alembic -c backend/alembic.ini upgrade head
```

Set `DATABASE_URL` to override the local PostgreSQL connection string.
