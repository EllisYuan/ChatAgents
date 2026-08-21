# Alembic migrations

Start the local PostgreSQL service from the repository root:

```bash
docker compose up -d postgresql
```

The local development defaults are:

```text
postgresql+psycopg://root:Agent%40Dev_1@127.0.0.1:5432/chat_agents
```

Run migrations directly with:

```bash
uv run --project backend alembic -c backend/alembic.ini upgrade head
```

Or run the same migration through Compose:

```bash
docker compose run --rm migrate
```

Set `DATABASE_URL` to override the local connection string. The password contains `@`, so database URLs must use the encoded value `Agent%40Dev_1`.

A new PostgreSQL volume initializes `root` as the database superuser with `CREATEDB`, which is required by integration tests that create temporary databases. Deleting the volume removes all local data:

```bash
docker compose down --volumes --remove-orphans
```
