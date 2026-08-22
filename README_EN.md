# Yuan's ChatAgents

<div align="center">

**A ReAct agent that folds trace, token, and evals into the chat surface itself**

![Python](https://img.shields.io/badge/Python-3.11--3.12-blue.svg)
![React](https://img.shields.io/badge/React-19-61DAFB.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-0.109+-green.svg)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-18.4-336791.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)

**English** | [简体中文](./README.md)

</div>

---

## What this is

A conversational agent that can search the web — but what it actually sets out to demonstrate is not "it can search." It is **LLM application engineering**: execution you can observe, compression decisions you can explain, metrics you can reproduce, and model access you can swap out.

There is exactly one surface. Run details grow in place underneath each answer — not a drawer, not a sidebar, not an "engineer mode" toggle. A casual visitor sees one line, `▸ 2 steps · 1.8k tok · 3.1s`; a technical reader expands it and walks all the way down to the span tree, the tool result cards, and the prompt version this particular run used. That trade-off is recorded in [ADR-0028](./docs/adr/0028-the-chat-surface-is-the-only-console.md).

> This repository keeps its full git history: it started as a Streamlit + LangGraph demo and is now what this document describes. "Evolving from a demo into engineering-grade" is itself part of the portfolio.

## Three things that are actually different

Every agent project claims "multi-model support, tracing, and evals." The three below are things this project does that most others do not, and each points at something verifiable in the repository.

### 1. Compression decisions are observable end to end

Context bloat never comes from conversational text. It comes from tool result bodies — a single `web_reader` return can be hundreds of times the size of the user message in the same turn. And on this site sessions are publicly shared and any visitor can continue one, so **growth has no natural endpoint**.

The mechanism is **observation masking** ([ADR-0019](./docs/adr/0019-old-observations-are-masked-not-summarized.md)): when rebuilding the model input sequence, only the most recent N tool call/result pairs keep their full bodies. Earlier results are replaced by a structured reference — tool name, arguments, source titles and URLs — with no body text. Masking applies to the projection only; **the message table is untouched**. The pairing between tool calls and their results is never broken, so masking cannot create dangling tool calls.

What it does **not** do is summarize. Summarization replaces the original text with a paraphrase, and citations the model then writes correspond to no real passage — citation faithfulness collapses on the spot.

Multi-layer compression elsewhere is opaque to the user: you cannot see which layer is active, what got cleared, or how much was saved. Here you can:

| Fact | Where it surfaces |
|---|---|
| Retention window for this run | `RunDetail.retention_window` → the "run configuration" block in run details |
| How many completed runs have been pruned so far | `RunDetail.pruned_run_count` → same block |
| Which observation pairs were masked, and which sources survived | `MaskingProjection.attributes` in `conversation/masking.py` |

> **Stating the gap honestly**: whole-run pruning (`pruned_run_count`) is wired up and rendered. The **per-observation masking marker has no data source yet**, so the "the model now only sees the title and URL" annotation does not appear in the run details. See [#77](https://github.com/EllisYuan/ChatAgents/issues/77).

### 2. Compression strength is an eval independent variable

The first value of the retention window N **was picked, not derived**. Precisely because it was picked, there has to be a way to calibrate it — and calibrating it means knowing how much citation faithfulness drops, and how much cost falls, as you compress harder.

So N is not a hardcoded constant; it is a **sweep axis**. Pushing a release tag triggers the `release-eval` job in `ci.yml`, which runs the grid `N ∈ {1, 2, 3, 5, 8}` over the same dataset with the same judge, producing a "compression strength × citation faithfulness × cost" curve, served to the site's `/evals` page via `GET /api/evals/summary`.

No one else has published a reproducible version of that curve.

### 3. The token estimator calibrates itself

There is exactly **one** token yardstick in the whole project: the input token count reported by the upstream response ([ADR-0020](./docs/adr/0020-there-is-one-token-yardstick.md)).

That phrasing has consequences. It means the local estimator's job is **not "count tokens" but "predict what upstream will count"** — so its correctness criterion is "close to the usage upstream reports," not "conforms to some tokenizer specification."

Why not an exact local tokenizer? Because no such thing exists. Anthropic does not publish one; the official counting endpoint's own documentation says "The token count is an **estimate**"; the same text can differ by roughly thirty percent between adjacent model generations; and only one of the three protocols has a counting endpoint at all.

The ground truth is better because it is not an approximation — it *is* the bill. The estimator only covers what the ground truth cannot reach (this turn's increment), so **the error is confined to the increment rather than applied to the whole**.

And the estimator calibrates itself: the observability side already records the measured input token count of every call, so grouping by model and computing "measured ÷ estimated" yields that model's bias factor — `compute_calibration_factors()` in `token_estimation.py`. **The calibration data comes from this project's own traces**: zero extra network calls, zero tokenizer dependencies.

One yardstick, two uses: the section threshold in `web_reader` (pure calibrated estimate — that text has never been through a model) and the retention window budget (last turn's ground truth plus this turn's estimated increment). Both read the same ruler, which is exactly what makes them comparable.

---

## Architecture

### Five capability modules and how they depend on each other

The backend is split by **capability**, not by technical layer ([ADR-0007](./docs/adr/0007-backend-is-split-by-capability-not-by-layer.md)). The criterion is testability: with `api/ + services/ + repositories/`, the rule "business modules must not depend on observability" becomes invisible in the directory tree and can only be enforced by code review. Split by capability, it degrades into a plain import rule.

The diagram below shows the **direct import edges that actually exist in the code**:

```mermaid
graph TD
    main["main.py<br/>FastAPI wiring · where the triple wrapping is assembled"]

    subgraph caps["Five capability modules"]
        conv["conversation/<br/>sessions · messages · input rebuild · observation masking"]
        agent["agent/<br/>ReAct loop · tool executor · prompt and toolset versioning"]
        obs["observability/<br/>span writes · trace queries · usage aggregation"]
        llm["llm/<br/>endpoint profiles · ModelPort · three adapters · discovery · replay"]
        tools["tools/<br/>web_search · web_reader"]
    end

    subgraph edge["Boundaries and shared leaves"]
        transport["transport/<br/>AG-UI over SSE encoding"]
        evals["eval_summary/<br/>site-level eval surface"]
        db["db/ · database.py<br/>ORM · the app and obs schemas"]
        leaf["token_estimation.py · validation.py<br/>error_codes.py · exceptions.py · model_catalog.py"]
    end

    main --> conv
    main --> agent
    main --> obs
    main --> llm
    main --> transport
    main --> evals
    main --> db

    conv --> agent
    conv --> llm
    conv --> db
    agent --> llm
    agent --> tools
    agent --> db
    obs --> agent
    obs --> llm
    obs --> db
    transport --> agent
    transport --> llm
    evals --> llm
    db --> llm

    llm --> leaf
    tools --> leaf
    conv --> leaf
    agent --> leaf
    transport --> leaf
```

Three properties worth calling out:

- **`llm/` does not know about agent / conversation / observability.** The three-protocol contract tests are therefore fully standalone: no database, no FastAPI.
- **The direction is one-way: `observability/ → agent/`, never the reverse.** Observability is droppable, business data is not; the moment business code depends on observability, the rule "an observability write failure must not affect business writes" is void.
- **The module is named `llm/`, not `models/`.** In the Python web ecosystem `models` conventionally means ORM; taking that name would mislead every new reader exactly once. The ORM therefore keeps its usual spot at `<module>/models.py`.

Within a module there are four layers: `router.py` (HTTP ↔ domain types, no business logic) → `service.py` (rules, orchestration, transaction boundaries) → `repository.py` (queries, no rules, opens no transactions) → `models.py` (ORM).

> 📌 The dependency-direction paragraph in `docs/adr/0007` disagrees with the current implementation (it states `agent/ ─→ conversation`; the real edge runs the other way). The diagram above follows the code. The discrepancy is tracked separately — a documentation change is not the place to quietly rewrite either the code or the decision.

### The triple wrapping

A run's event stream passes through three layers from the inside out, each with a single responsibility and a distinct failure semantic. This shape is taken verbatim from `backend/src/chat_agents/main.py`:

```
encode_sse(              # transport/       domain events → AG-UI wire format
  observe(               # observability/   write spans, own transaction, failures only log
    persist(             # conversation/    write messages, business transaction, failures raise
      runner.run(messages, ...))))
         ▲
         └── agent/  a pure ReAct loop: no database, no HTTP, unaware SSE exists
```

| Layer | What it does | On write failure |
|---|---|---|
| `runner.run` | Runs ReAct iterations, emits **domain events** (no wire format) | Turns into a `RunFailed` event |
| `persist` | Writes a message as soon as each model call completes, never batching to the end | **Raises** — losing the user's words must be an error |
| `observe` | Writes each span on close, each write in its own short transaction | **Logs only** — one missing observation must not take down business writes |
| `encode_sse` | Translates into AG-UI events | Collapses into a single `RUN_ERROR` and ends the stream |

Two points that are not obvious but matter:

**"An observability write failure cannot affect business writes" holds structurally, not by memory.** Business writes and observability writes each open their own `async with session_factory()`, so they physically cannot commit in the same transaction.

**Failures after the stream opens always travel as a `RUN_ERROR` event; the HTTP status can no longer change.** Once the first byte is out, HTTP is already 200. `encode_sse` is the single place that enforces this — it wraps everything in a `try/except`, and any exception surfacing from the three inner layers is collapsed there rather than propagating. Only failures **before** the stream opens (profile validation, unknown session, empty message) take normal HTTP status codes, served as RFC 9457 `application/problem+json`. The same failure takes **the same error code** on both paths (`error_codes.py` is the single code table).

### What happens during a run

```mermaid
sequenceDiagram
    participant U as Browser
    participant API as main.py
    participant C as conversation/
    participant R as agent/ AgentRunner
    participant M as llm/ ModelPort
    participant T as agent/ ToolExecutor
    participant O as observability/

    U->>API: POST /api/runs
    API->>C: persist the user message (business transaction)
    C-->>API: rebuild model input (observation masking happens here)
    API->>R: run(messages, profile, effort)

    loop each iteration (bounded by the effort tier's hard cap)
        R->>M: stream(messages, tools, system_prompt)
        M-->>R: TextDelta / ReasoningDelta / ToolCall
        R-->>U: SSE: STEP_STARTED · TEXT_MESSAGE · REASONING
        opt the model issued a tool call
            R->>T: execute (timeout, retry, error classification all live here)
            T-->>R: ToolStarted / ToolFinished
            R-->>U: SSE: TOOL_CALL · chatagents.tool_result
        end
        R-->>O: write spans and usage (independent transaction)
        R-->>U: SSE: chatagents.usage · chatagents.span
    end

    R-->>U: SSE: RUN_FINISHED (or RUN_ERROR)
```

**The tool executor is the only entry point for calling a tool.** Timeout, retry, error classification, span recording, and result rendering all live in that one place; a tool itself is just a clean async function. A new tool registered in `tools/registry.py` inherits the whole cross-cutting set automatically — **it is structurally impossible to forget**.

Tool failures split into two kinds, and the distinction is hard: an **external failure** (timeout, rate limit, unreachable target, provider error) does not raise. It is handed back to the model as a tool result and the model decides what to do next. A **programmatic error** (argument validation failure, a bug, a missing key) aborts the run and is reported — it is never disguised as a tool result and fed to the model.

### Two schemas

Business data and observability data share one PostgreSQL instance across two schemas ([ADR-0002](./docs/adr/0002-business-and-observability-share-a-database.md)). Sharing the database physically preserves cross-table joins — trace is this project's centerpiece, and the frontend has to open the execution detail of a message right there in the chat surface. Splitting the schema logically makes the boundary visible in code.

```mermaid
erDiagram
    SESSION ||--o{ MESSAGE : "within app"
    SESSION ||--o{ RUN : "obs points at app"
    MESSAGE ||--o{ RUN : "trigger_message_id"
    PROMPT_VERSIONS ||--o{ RUN : "obs points at app"
    TOOL_SCHEMA_VERSIONS ||--o{ RUN : "obs points at app"
    RUN ||--o{ SPAN : "within obs"
    SPAN ||--o{ SPAN : "parent_span_id"

    SESSION {
        uuid id PK "generated by the frontend, UUIDv7"
        text title "nullable: written by the auxiliary model"
        timestamp deleted_at "soft delete marker"
    }
    MESSAGE {
        uuid id PK
        int seq "monotonic within a session"
        text role
        jsonb content "the complete model-view sequence"
    }
    PROMPT_VERSIONS {
        text version_id PK "content hash, never hand-incremented"
    }
    TOOL_SCHEMA_VERSIONS {
        text version_id PK "granularity is the toolset, not one tool"
    }
    RUN {
        uuid id PK
        uuid trigger_message_id FK "lower bound of the message range"
        int last_message_seq "upper bound of the message range"
        jsonb attributes "retention window · prune count"
    }
    SPAN {
        uuid id PK
        text kind "llm or tool"
        text usage_status "complete / partial / unavailable"
        int input_tokens "ground truth: the upstream yardstick"
    }
```

**Foreign keys may only run `obs` → `app`, one way.** That constraint has a non-obvious consequence: **the message table cannot carry a `run_id`**. "Which run does this message belong to" can only be determined from the observability side, by looking up `trigger_message_id` plus `last_message_seq` (the messages a single run produces are necessarily contiguous within a session).

Three related modeling rules:

- **There is no cost column.** Cost is derived (it moves with pricing configuration), not an observed fact, so it is stored separately from token counts.
- **Missing usage is never represented as 0.** Usage has three states — `complete` / `partial` / `unavailable` — and there is no fourth.
- **Session deletion is a soft delete.** The site has no authentication and the session list is publicly shared; a hard delete would either cascade and destroy the trace along with it (any passerby erasing the centerpiece with one click) or leave a pile of orphaned spans.

### Model access: three protocols side by side, never translated into each other

`llm/` has zero business dependencies on the rest of the project, and `ModelPort` is its only entry and exit:

```
                   ┌─ openai_responses         ─┐
ModelPort.stream ──┼─ openai_chat_completions  ─┼──→ one unified ModelEvent stream
                   └─ anthropic_messages       ─┘
```

A few of the design trade-offs:

- **The protocol is a property of the endpoint profile, not of the model.** `ModelPort` takes no "vendor" parameter, so there is no room in the signature to infer a protocol from a model identifier. The same base URL can back several profiles, each declaring a different protocol.
- **The model catalog is discovered at runtime; neither the backend nor the frontend hardcodes it** ([ADR-0016](./docs/adr/0016-the-model-list-is-discovered-and-persisted.md)). The catalog **does not promise availability** — an identifier in it can still fail on an unpaid account, a cooling-down credential, or an upstream retirement. A discovery failure is informational, not fatal: the service keeps running and the UI switches to letting the user type an identifier.
- **Upstream errors pass through verbatim, unclassified.** There is no error-code mapping table: whatever upstream says is what you get, because those are not this project's words.
- **Replay happens at the `ModelPort` boundary, not at the HTTP transport** ([ADR-0025](./docs/adr/0025-replay-happens-at-the-model-port-not-the-http-transport.md)). What gets recorded is the `ModelEvent` the adapter already produced — no HTTP frames, no chunk timing, no credentials — which makes the replay layer immune to "which HTTP client library did the upstream SDK switch to." That is not theoretical fastidiousness: `openai` 3.x has moved to `httpx2` while `anthropic` is still on `httpx`, and both libraries coexisting in one process is the expected state.

### Tools: capability and implementation are separate

There are exactly two tools, and the set is **locked**:

| Tool | What it does | Current provider |
|---|---|---|
| `web_search` | Search relevant pages | Tavily |
| `web_reader` | Read the body of a page or PDF | Jina Reader |

**A tool's identity is three things — name, description, argument schema — and that identity belongs to the contract; it does not change with whoever actually does the work** ([ADR-0004](./docs/adr/0004-tools-are-capabilities-providers-are-implementations.md)). Replacing Tavily does not change what `web_search` is. Each tool is cut into three layers internally: contract (`contract.py`), port (`port.py`, the only place that touches the network), and orchestration (`orchestration.py`, a pure function).

Long documents are not injected wholesale: `web_reader` first returns the document's structure (title and section list), and the model asks for specific sections on demand (**progressive disclosure**, [ADR-0005](./docs/adr/0005-long-documents-use-progressive-disclosure.md)). One level only — no multi-level routing, no RAG.

### Execution control: effort tiers

The user picks a tier per run, and it sets both the **hard cap** (a ceiling the execution layer enforces and the model cannot cross) and the **soft budget** (the allowance written into the system prompt and told to the model). The soft budget sits below the hard cap so that hitting the cap is an anomaly rather than routine.

| Tier | Soft budget | Hard cap |
|---|---|---|
| `low` | 3 | 4 |
| `medium` | 6 | 8 |
| `high` | 10 | 13 |
| `xhigh` | 16 | 20 |

The retention window is **orthogonal to the effort tier** and does not move with it — the best value of N is driven by citation faithfulness while the tier is driven by task complexity. They are not the same independent variable, and coupling them would make it impossible to sweep that dimension on its own.

---

## Getting started

### Requirements

- **Python** 3.11–3.12, with [uv](https://docs.astral.sh/uv/) installed
- **Node** 22 (frontend)
- **Docker** with the compose plugin (for the local PostgreSQL)
- **API keys**: [Anthropic](https://console.anthropic.com/) or [OpenAI](https://platform.openai.com/) (at least one), plus [Tavily](https://tavily.com/). Jina Reader is optional — it works unauthenticated, just with a lower quota.

### 1. Install dependencies

```bash
git clone https://github.com/EllisYuan/ChatAgents.git
cd ChatAgents
uv sync --project backend
npm --prefix frontend ci
```

### 2. Start the database

**Start the local PostgreSQL before running the tests for the first time** — the integration tests hit a real database; there is no in-memory stand-in:

```bash
docker compose up -d postgresql
```

> ⚠️ The compose service is named **`postgresql`**, not `postgres`.

Local defaults (each can be overridden by the environment variable of the same name):

| Item | Default |
|---|---|
| Compose service | `postgresql` |
| Container | `chatagent-postgresql` |
| Database | `chat_agents` |
| User | `root` |
| Password | `Agent@Dev_1` |
| Listening on | `127.0.0.1:5432` |
| Volume | `chatagent_postgres-data` |

When the password goes into a connection URL, `@` must be encoded as `%40`:

```text
postgresql+psycopg://root:Agent%40Dev_1@127.0.0.1:5432/chat_agents
```

Compose runs the `migrate` service before backend starts. To initialize the database on its own:

```bash
docker compose run --rm migrate
```

### 3. Configure environment variables

```bash
cp .env.sample .env
```

### 4. Run it

```bash
# Terminal 1: backend
uv run --project backend python -m uvicorn chat_agents.main:app --app-dir backend/src --reload

# Terminal 2: frontend
npm --prefix frontend run dev
```

| Entry point | Address |
|---|---|
| Frontend | http://localhost:5173 |
| Backend (run directly) | http://localhost:8080 |
| Backend (container port mapping) | http://127.0.0.1:19180 |
| OpenAPI docs | `<backend address>/docs` |

To bring up the database and backend with compose while the frontend still runs on the host:

```bash
docker compose up -d --build
VITE_BACKEND_ORIGIN=http://127.0.0.1:19180 npm --prefix frontend run dev
```

## Configuration

### Environment variables

| Variable | Description | Required |
|---|---|---|
| `ANTHROPIC_API_KEY` | Anthropic key, for the `anthropic-official` profile | at least one of the two |
| `OPENAI_API_KEY` | OpenAI key, for the `openai-official` profile | at least one of the two |
| `TAVILY_API_KEY` | Used by `web_search` | ✅ |
| `JINA_API_KEY` | Used by `web_reader`; works without it, just a lower quota | ❌ |
| `DATABASE_URL` | Full connection string; compose assembles one from `POSTGRES_*` | ❌ |
| `POSTGRES_DB` / `POSTGRES_USER` / `POSTGRES_PASSWORD` | Used by compose | ❌ |
| `POSTGRES_PASSWORD_URLENCODED` | Same, but with `@` written as `%40` | ❌ |
| `CHATAGENTS_ENDPOINTS_CONFIG_PATH` | Where the endpoint profile YAML lives | ❌ |
| `CHATAGENTS_EVAL_REPORTS_DIR` | Eval output directory, defaults to `.eval-reports/` | ❌ |
| `APP_VERSION` | The git tag injected at build time; `dev` locally | ❌ |
| `VITE_BACKEND_ORIGIN` | Which backend the frontend dev server proxies to | ❌ |

### Endpoint profiles

Profiles are defined in `backend/config/endpoints.yaml`, which **stores the environment variable name of a key, never the key itself**. This file is application configuration: it travels with the repository and is baked into the image ([ADR-0032](./docs/adr/0032-app-config-lives-in-the-repo-machine-config-does-not.md)):

```yaml
default_profile: anthropic-official

endpoints:
  - name: anthropic-official
    protocol: anthropic_messages
    base_url: https://api.anthropic.com
    auth_field: x-api-key
    auth_secret_ref: ANTHROPIC_API_KEY
    main_model: claude-sonnet-4-5-20250929
```

`base_url` can point at any relay — "support a custom base URL" is a hard requirement here, not a bonus feature. `auth_field` is configurable because different relays expect different header names.

### Versioning

**The git tag is the only source of the version number**, and `version` in `backend/pyproject.toml` is permanently pinned to `0.0.0` ([ADR-0030](./docs/adr/0030-the-git-tag-is-the-only-version.md)). At build time `ARG APP_VERSION` stamps the tag into the image; the backend exposes it through `/health` and the frontend receives it through Vite's `define` into `import.meta.env`.

> Seeing `0.0.0` in `pyproject.toml` while production `/health` returns `v1.4.2` reads like an oversight. **The `0.0.0` is deliberate** — `uv_build` does not support VCS-derived package versions, and leaving that field at an obviously meaningless value beats leaving it at a value that looks meaningful and will eventually lie.

---

## Deployment

### The request path

```
                    ┌───────────────────────────────────────────────┐
                    │  host nginx (aaPanel owns TLS and renewal)    │
Browser ─ HTTPS ──▶ │                                               │
                    │  location /      root .../frontend/current    │──▶ served from disk
                    │                  try_files → index.html       │    (frontend is not containerized)
                    │                                               │
                    │  location /api/  proxy_pass 127.0.0.1:19180   │──┐
                    │                  proxy_buffering off          │  │
                    └───────────────────────────────────────────────┘  │
                                                                       ▼
                                          ┌──────────────────────────────────┐
                                          │  backend container (ghcr.io)     │
                                          │  uvicorn :8080                   │
                                          └──────────────┬───────────────────┘
                                                         │ backend-network
                                          ┌──────────────▼───────────────────┐
                                          │  postgresql container (18.4)     │
                                          │  app schema + obs schema         │
                                          └──────────────────────────────────┘
```

### ⚠️ Editing nginx in the aaPanel UI will be overwritten by the next deploy

`deploy/nginx/site.conf` is versioned along with `git checkout <tag>`, so **hand edits made in the panel do not survive** — the next deploy's `git checkout` restores the file.

The criterion is "is this a property of the machine or of the application?" ([ADR-0032](./docs/adr/0032-app-config-lives-in-the-repo-machine-config-does-not.md)):

| Owned by the panel | Owned by `deploy/nginx/site.conf` |
|---|---|
| TLS parameters, certificate paths, renewal, listening ports | `location` routing, `proxy_buffering off`, timeouts, the `root` and `try_files` for static assets |

**Whatever still holds on a different server is a property of the application — change the file in the repository and deploy.**

### SSE can only traverse one nginx layer (a structural requirement)

`X-Accel-Buffering` belongs to the `X-Accel-*` family, which **only takes effect at the layer closest to the user — once the first layer consumes it, it is not passed down**. If `/api/` goes through two nginx layers (for example another one inside a container), one of them will buffer as usual.

**And the failure is silent**: the streaming response does not error, it just accumulates and dumps all at once. A single-layer local environment can never reproduce it.

The fix is not "configure `proxy_buffering off` on both layers" but to let `/api/` **traverse exactly one** — the host nginx connects to the backend directly, and static assets take a separate `location`. **This is one of the reasons the frontend is not containerized.**

### One-time server preparation (done by a human; CD cannot)

1. Create the site `agent.ellisyuan.com` and issue a certificate (in the aaPanel UI)
2. `git clone` into `/www/chatagents/repo`
3. Write `/www/chatagents/.env` **outside** the clone directory and `chmod 600` it — CD only reads it and **never writes it**
4. Add one line to the panel's site configuration:
   ```nginx
   include /www/chatagents/repo/deploy/nginx/site.conf;
   ```
5. Configure the SSH deploy key and the server IP allowlist for GitHub Actions

### Releasing and rolling back

Pushing a `v*` tag triggers `release.yml`: build the backend image and push it to ghcr.io → build the frontend bundle → publish a GitHub Release → SSH to the server and run `deploy.sh`.

**A rollback is the same script with an older tag**:

```bash
./scripts/deploy.sh v1.4.2
```

It does not depend on CI being available. Everything a tag ships — the backend image, the frontend bundle, the compose and nginx configuration — **moves together**. There is no compatibility matrix: "backend v1.4 with frontend v1.3" is not a combination that exists.

### Required after every deploy: test with `curl -N`

This is **the only way to detect silently batched SSE**, and it does not belong to CI (a CI environment has no real nginx):

```bash
curl -N https://agent.ellisyuan.com/api/runs -X POST \
  -H "Content-Type: application/json" \
  -d '{"session_id":"...", "message":"hello"}'
# Events should print one by one, not stall and then dump everything at once
```

Two more things to verify:

```bash
curl https://agent.ellisyuan.com/health
# {"status":"ok","version":"v1.4.2"} — the version comes from this deploy's git tag

curl -I https://agent.ellisyuan.com/s/00000000-0000-0000-0000-000000000000
# Refreshing a frontend route must not 404 — this relies on try_files in site.conf
```

---

## Testing and CI gates

**Tests and evals are two systems** ([ADR-0026](./docs/adr/0026-tests-and-evals-are-two-systems.md)). The former is deterministic and gates merges; the latter is non-deterministic, costs money, and only warns.

### Local checks before you push

```bash ci-command
uv sync --project backend --locked
uv run --project backend pytest backend/tests
uv run --project backend pytest backend/tests/contract_test.py -m contract --maxfail=1
uv run --project backend ruff check --config=backend/pyproject.toml backend
uv run --project backend ruff format --check --config=backend/pyproject.toml backend
uv run --project backend mypy --config-file=backend/pyproject.toml backend
```

Frontend (run inside `frontend/`):

```bash ci-command
npm ci
npm run lint
npm run typecheck
npm run build
```

> Both blocks are tagged `ci-command`, and `scripts/check-readme-ci-commands.sh` asserts that every line appears **verbatim** in `.github/workflows/ci.yml`. **CI is the authority** — documentation drift turns that check red.

### Gates versus warnings

| Check | Blocks merge | Notes |
|---|---|---|
| Ruff · mypy · backend tests | ✅ | Runs against a real PostgreSQL, not an in-memory database |
| REST contract test | ✅ | Hits FastAPI in-process, deterministic |
| Frontend lint · tsc · build | ✅ | These three are the frontend's entire gate |
| README command consistency | ✅ | The assertion described above |
| Prompt / toolset change evals | ⚠️ warning | Only runs when the model input actually changed |
| Upstream contract tests | ⚠️ not in CI | Hits the real network, non-deterministic |

The distinction is not about importance — **it is about whether the signal is deterministic. A flaky signal does not become a gate.**

### Replay: no network, no database

A recorded run-event sequence drives a complete run. The recording is taken at the `ModelPort` boundary rather than from HTTP responses, which is what makes it independent of whichever HTTP client library the upstream SDK uses.

### Evals

Seven metrics: five zero-cost deterministic ones plus two scored by a judge model.

| Metric | How it is computed |
|---|---|
| Citation faithfulness | Sources cited in the answer ∩ sources actually observed, divided by sources cited |
| Tool trigger rate | Went online when it should have, stayed offline when it should not have |
| Trajectory efficiency | Mean of three sub-signals: hard-cap hits, re-reading the same URL, answering after searching without reading |
| Argument compliance | Share of tool calls whose arguments pass that tool's JSON Schema |
| System constraint adherence | How well the actual iteration count respects the soft budget |
| Factual hallucination rate | Scored by the judge model |
| Task completion | Scored by the judge model |

**There is no "tool misselection rate"** — with two semantically orthogonal tools, that rate is a constant and carries no signal.

On a pull request evals fire **only when the model input actually changed**: the `eval-trigger` job compares the prompt and toolset content hashes between the current checkout and the base revision. It judges by content rather than file path, so a change to the variable-assembly logic triggers it too. When triggered, the old and new versions **both run in the same CI job over the same dataset with the same judge**; historical scores are never used as a baseline — swapping judges makes historical scores incomparable, which is why every result carries a **judge snapshot**.

```bash
# Evals do not run by default
uv run --project backend pytest backend/tests

# Run them explicitly
uv run --project backend pytest -m eval backend/tests/evals
```

Tool providers are replaced by **frozen fixtures** during evals (both the Tavily and Jina ports), but `ModelPort` is not — **the model under evaluation stays live**, otherwise you would not be measuring the model at all.

---

## Repository layout

```
ChatAgents/
├── backend/
│   ├── src/chat_agents/
│   │   ├── main.py              # FastAPI wiring · the one place the triple wrapping is assembled
│   │   ├── conversation/        # sessions · messages · input rebuild · observation masking
│   │   ├── agent/               # ReAct loop · tool executor · versioning
│   │   ├── llm/                 # ModelPort · three adapters · discovery · replay
│   │   ├── tools/               # web_search · web_reader
│   │   ├── observability/       # span writes · trace queries · usage aggregation
│   │   ├── transport/           # AG-UI over SSE encoding
│   │   ├── eval_summary/        # site-level eval surface
│   │   ├── db/                  # ORM: the app and obs schemas
│   │   └── token_estimation.py  # the project's single token estimator
│   ├── alembic/                 # migrations (additive only)
│   ├── config/endpoints.yaml    # endpoint profiles
│   └── tests/
│       ├── evals/               # evals (marker-isolated, excluded from the default run)
│       └── integration/         # hits a real PostgreSQL
├── frontend/                    # React 19 + Vite + TanStack Query + Zustand
│   └── src/features/            # session · sessions · trace · evals
├── deploy/nginx/site.conf       # the application half of the nginx configuration
├── docs/adr/                    # 33 architecture decision records
├── scripts/deploy.sh            # release / rollback
├── compose.yaml                 # local
├── compose.prod.yaml            # production overlay (switches to ghcr.io images)
└── CONTEXT.md                   # glossary: what each term means, nothing about implementation
```

## The contract

The shape of the interface between frontend and backend comes from **two sources**, and there is no third ([ADR-0021](./docs/adr/0021-the-contract-has-two-sources.md)):

- **The envelope of streaming events** comes from the AG-UI schema (a version-pinned `@ag-ui/core`)
- **The non-streaming REST surface and this project's own event payloads** come from the OpenAPI document generated from backend code

Frontend types are generated by `openapi-typescript` from the schema the backend exports; **no type copies are committed** — a hand-written type copy is not the contract, it is a duplicate of it.

Main endpoints:

| Endpoint | Description |
|---|---|
| `POST /api/runs` | Start a run, returns an AG-UI over SSE stream |
| `GET /api/sessions` | Session list (composite cursor pagination) |
| `GET /api/sessions/{session_id}/messages` | Messages in a session |
| `GET /api/sessions/{session_id}/runs` | Runs in that session, for the client to merge with the message sequence |
| `GET /api/runs/{run_id}` | Run detail: span tree · usage aggregate · run configuration |
| `GET /api/models` · `POST /api/models/refresh` | Model catalog and refresh |
| `GET /api/evals/summary` | The four numbers on the site's eval surface |
| `GET /health` | The single exit for the version number |

**There is no version in the URL** ([ADR-0024](./docs/adr/0024-there-is-no-url-versioning.md)) — frontend and backend ship on the same tag and move together, and versioning something that will never evolve independently is just ceremony.

---

## Troubleshooting

### Refreshing `/s/<uuid>` returns 404

`try_files` is not in effect — either the panel's site configuration is missing that `include` line, or `root` points somewhere other than the current release.

```bash
nginx -T | grep -A3 "location /"
readlink -f /www/chatagents/frontend/current
```

### Streaming replies arrive in one lump

`/api/` is going through more than one nginx layer, or one of them is missing `proxy_buffering off`. See "SSE can only traverse one nginx layer" above, and confirm event-by-event delivery with `curl -N`.

### `/api/` returns 404

A trailing slash on `proxy_pass` truncated the `/api/` prefix:

```nginx
proxy_pass http://127.0.0.1:19180/;  # ❌ trailing slash → path gets truncated
proxy_pass http://127.0.0.1:19180;   # ✓ keeps the full path
```

### Integration tests cannot reach the database

Confirm `docker compose up -d postgresql` is up, and that `@` in the connection string is encoded as `%40`.

### The session list will not return a second page

The cursor is **composite**: `(before_updated_at, before_id)`. The first page omits both; every later page **must send both**. Query parameters have no JSON `null`, so a client should **omit** empty values rather than sending `before_id=null`.

### Session history disappeared

`compose.yaml` persists data in a named volume; a normal restart must not pass `-v`:

```bash
docker compose down          # ✓
docker compose down -v       # ❌ permanently deletes chatagent_postgres-data
```

Backup:

```bash
docker compose exec postgresql pg_dump -U root -d chat_agents > chat_agents.sql
```

### Reading logs

```bash
docker compose logs backend --tail 100 -f
docker compose logs postgresql --tail 100 -f
```

> The streaming path emits **zero to one log lines per run**, not one per token — and **model output text is never written to logs**. "What happened inside a run" belongs to spans; logs only record system events that span runs. To see what a run did, look at the trace, not the log.

---

## Documentation

| File | Contents |
|---|---|
| [`CONTEXT.md`](./CONTEXT.md) | Glossary — defines **what** each term is, never how it is implemented |
| [`docs/adr/`](./docs/adr/) | 33 architecture decision records, including rejected options and why |
| [`docs/research/`](./docs/research/) | Research reports from the technology selection phase |
| [`frontend/src/features/trace/SPEC.md`](./frontend/src/features/trace/SPEC.md) | Client-side merge rules for the span tree |

A few ADRs worth reading first:

- [ADR-0001](./docs/adr/0001-messages-are-the-single-source-of-truth.md) Messages are the single source of truth
- [ADR-0007](./docs/adr/0007-backend-is-split-by-capability-not-by-layer.md) The backend is split by capability, not by layer
- [ADR-0019](./docs/adr/0019-old-observations-are-masked-not-summarized.md) Old observations are masked, not summarized or dropped
- [ADR-0020](./docs/adr/0020-there-is-one-token-yardstick.md) There is one token yardstick
- [ADR-0028](./docs/adr/0028-the-chat-surface-is-the-only-console.md) The chat surface is the only console

## Contributing

1. Fork and branch
2. **Start the database first**: `docker compose up -d postgresql`
3. Run the self-check blocks above
4. Open a pull request

Code comments and ADRs are written in Chinese; code identifiers and commit messages in English; the README in both.

## License

[MIT](./LICENSE)

## Author

**Yuan** — [GitHub @EllisYuan](https://github.com/EllisYuan) · [yuan.sn@outlook.com](mailto:yuan.sn@outlook.com)

## Acknowledgements

[FastAPI](https://fastapi.tiangolo.com/) · [AG-UI](https://github.com/ag-ui-protocol/ag-ui) · [SQLAlchemy](https://www.sqlalchemy.org/) · [React](https://react.dev/) · [Vite](https://vite.dev/) · [Anthropic](https://www.anthropic.com/) · [OpenAI](https://openai.com/) · [Tavily](https://tavily.com/) · [Jina Reader](https://jina.ai/reader/)
