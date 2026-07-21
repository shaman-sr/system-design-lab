# lab — a minimal system you can load-test and break

A hands-on lab for turning system-design theory into felt experience: build a
small service, put real load on it with [k6](https://k6.io/), watch it in
Prometheus + Grafana, then deliberately break it and see *what* breaks and *why*.

The "system under test" is a tiny **FastAPI + SQLModel** banking API backed by
**Postgres** — accounts and transactions in paise (INR minor units).

---

## Architecture

```mermaid
flowchart LR
  k6[k6 load generator] -->|HTTP| app
  k6 -.->|remote-write| prom[(Prometheus)]
  app[FastAPI app :8000] -->|SQL| db[(Postgres)]
  prom -->|scrape /metrics| app
  prom -->|scrape| pgexp[postgres-exporter]
  prom -->|scrape| cadvisor[cAdvisor]
  pgexp --> db
  graf[Grafana :3000] -->|query| prom
```

- **app** exposes business routes plus `/metrics` (via
  `prometheus-fastapi-instrumentator`) — request rate, latency histogram, status
  codes, and custom `bank_*` transaction counters.
- **Prometheus** scrapes the app, `postgres-exporter` (DB internals), and
  `cAdvisor` (per-container CPU/mem) every 5s. It also accepts k6's client-side
  metrics via remote-write.
- **Grafana** auto-provisions the Prometheus datasource and two dashboards.
- **k6** drives load and (optionally) streams its own metrics into Prometheus so
  you see client-side and server-side latency side by side.

---

## Endpoints

| Method | Path                              | Body / query                                             | Purpose |
|--------|-----------------------------------|----------------------------------------------------------|---------|
| POST   | `/api/account`                    | `{ "balance_paise": 100000 }` (optional, default 0)      | Create an account, returns `{id, balance_paise}` |
| GET    | `/api/account?account_id=<int>`   | —                                                        | Fetch an account (404 if missing) |
| GET    | `/api/transaction/?account_id=<int>` | —                                                     | List an account's transactions |
| POST   | `/api/transaction/`               | `{account_id, type:"credit"\|"debit", amount, description?, occured_at}` | Create a transaction; `credit` adds to balance, `debit` subtracts |
| GET    | `/metrics`                        | —                                                        | Prometheus exposition |
| GET    | `/docs`                           | —                                                        | Swagger UI |

---

## Quickstart

Prereqs: Docker + Docker Compose. (k6 is a separate install — see below.)

```bash
# From the repo root — build the app image and start the whole stack.
docker compose -f infra/docker-compose.yml up --build
```

That brings up, in dependency order: `db` → `app` → `prometheus` → `grafana`,
plus `postgres-exporter`, `cadvisor`, and `adminer`.

### Service URLs

| Service            | URL                        | Notes |
|--------------------|----------------------------|-------|
| App (FastAPI)      | http://localhost:8000      | `/docs` for Swagger, `/metrics` for Prometheus |
| Grafana            | http://localhost:3000      | anonymous access is on (Admin); admin login `admin` / `admin` |
| Prometheus         | http://localhost:9090      | check `/targets` — all should be **UP** |
| Adminer (DB UI)    | http://localhost:8080      | system `PostgreSQL`, server `db`, user `postgres`, pw `mysecretpassword`, db `bank` |
| cAdvisor           | http://localhost:8081      | container metrics UI |
| postgres-exporter  | internal (`postgres-exporter:9187`) | scraped by Prometheus on the compose network |

In Grafana, open the **FastAPI Lab** dashboard (RED + business + resource
panels) and the **k6** dashboard (client-side load metrics).

For the container CPU/memory panels to show real **names** (`infra-app-1`,
`infra-db-1`, …) instead of cgroup ids, run this once after startup — and again
after any `up --build app` (container ids change on rebuild):

```bash
uv run python ops/scripts/relabel_containers.py
```

### Smoke-check by hand

```bash
# create an account
curl -s -X POST localhost:8000/api/account \
  -H 'content-type: application/json' -d '{"balance_paise":100000}'
# -> {"id":1,"balance_paise":100000}

# post a transaction
curl -s -X POST localhost:8000/api/transaction/ \
  -H 'content-type: application/json' \
  -d '{"account_id":1,"type":"credit","amount":500,"occured_at":"2026-01-01T00:00:00"}'

# metrics are flowing
curl -s localhost:8000/metrics | grep -E 'http_requests_total|bank_transactions_created_total'
```

> **New to reading the dashboards?** See **[docs/READING-THE-DASHBOARD.md](docs/READING-THE-DASHBOARD.md)**
> — a plain-English, panel-by-panel decoder (normal vs alarming, what each line
> means, the container-ID cheat sheet, and "which panel reacts to which experiment").

---

## Load testing with k6

Install k6 locally (recommended on macOS — the brew binary hits `localhost:8000`
directly):

```bash
brew install k6
```

### Run a scenario

The single script `load_test/main.js` contains four scenarios, selected with
`-e SCENARIO=`. Its `setup()` creates its own account, so no manual seeding is
needed.

| Scenario | Shape | Question it answers |
|----------|-------|---------------------|
| `smoke`  | 1 VU, 1 min | Does everything work at all? |
| `load`   | ramp to 50 VUs, hold 5 min | How does it behave at expected traffic? |
| `stress` | staged 50→100→200→400 VUs | Where is the knee — when does it degrade? |
| `spike`  | jump to 300 VUs, hold, drop | How fast does it recover from a surge? |

```bash
# Terminal summary only:
k6 run -e SCENARIO=smoke load_test/main.js
```

### Stream k6 metrics into Grafana (remote-write)

Prometheus is started with `--web.enable-remote-write-receiver`, so k6 can push
its client-side metrics straight in:

```bash
K6_PROMETHEUS_RW_SERVER_URL=http://localhost:9090/api/v1/write \
K6_PROMETHEUS_RW_TREND_STATS="p(95),p(99),min,max" \
k6 run -o experimental-prometheus-rw -e SCENARIO=load load_test/main.js
```

Now the **k6** dashboard (client-side p95/p99, VUs, RPS) sits next to the
**FastAPI Lab** dashboard (server-side latency, errors, DB, containers) — the gap
between the two curves is queueing/network you can't see from either side alone.

Handy overrides: `-e BASE_URL=...`, `-e START_BALANCE_PAISE=...`. If the k6
dashboard panels stay empty, your k6 version may name remote-write series
differently — import Grafana dashboard **ID 19665** as an alternative.

---

## Breaking the system — experiments to try

The rig above is the point: it lets you *see* failures instead of guessing.
Start a `load` or `stress` run, then introduce a fault and watch the dashboards.
Track **RED** for the API (Rate, Errors, Duration) and **USE** for resources
(Utilization, Saturation, Errors).

- **Soak / endurance.** Run `load` (or a `constant-vus` variant) for hours. Watch
  the app container's memory (cAdvisor) and Postgres connection count for slow
  upward creep — the signature of a leak. Does p95 drift up over time?

- **Breakpoint / capacity.** Swap the executor to `ramping-arrival-rate` (fixed
  requests/sec, ramped up) instead of ramping VUs. This holds request *rate*
  independent of latency, so you cleanly find the RPS ceiling where the error
  rate crosses your threshold.

- **DB failure injection.** Mid-run: `docker compose -f infra/docker-compose.yml
  stop db`. DB errors are now caught and returned as **503** (logged with a full
  stack trace, counted in `bank_errors_total{type="database"}`), so the *Error
  rate* panel's 5xx line lights up. Then `start db` — the app reconnects on the
  next request (NullPool opens a fresh connection via PgBouncer), no restart
  needed; measure recovery time.

- **Resource limits.** Add `deploy.resources.limits` (`cpus`, `memory`) to the
  `app` service, or `docker update --cpus 0.5 --memory 256m <container>`, then
  re-run `load`. Watch CPU throttling / OOM kills against latency.

- **Connection-pool exhaustion / horizontal scaling.** The app connects through
  **PgBouncer** in `transaction` pooling mode and uses SQLAlchemy `NullPool`, so
  PgBouncer is the *single* pool for the whole stack. The throughput knob is
  therefore **`default_pool_size` in `ops/pgbouncer/pgbouncer.ini`** (currently
  90), *not* a per-replica SQLAlchemy pool. Two independent axes:
  - **App/HTTP tier** scales with replicas: `docker compose -f
    infra/docker-compose.yml up -d --no-deps --no-recreate --scale app=N app`
    (nginx and Prometheus discover the new replicas automatically). Re-run
    `uv run python ops/scripts/relabel_containers.py` afterwards so cAdvisor
    panels label the new containers.
  - **DB tier** scales with `default_pool_size`. Because every replica multiplexes
    onto this one pool, adding replicas alone will *not* raise DB throughput past
    the pool size — push VUs past it and requests queue in PgBouncer
    (`SHOW POOLS` → `cl_waiting`) while DB CPU stays low: saturation without
    utilization, the classic tell. Raise `default_pool_size` (keep Postgres
    `max_connections` in `infra/docker-compose.yml` above it) and correlate with
    p95. *Why not just remove PgBouncer to get per-replica pools back?* That only
    "scales" by letting replicas open direct connections until Postgres
    `max_connections` is exhausted (~6 replicas) and starts rejecting them —
    exactly the failure mode PgBouncer exists to prevent. Tune the pool instead.

- **Cold vs warm.** Compare the first seconds of a run (cold Postgres shared
  buffers, cold OS page cache) against steady state. Add a warm-up phase or
  discard the opening window when reading results.

**Where to look:** Rate = `http_requests_total`; Errors = 4xx/5xx share of
`http_requests_total` plus the domain-level `bank_errors_total{type}` (missing
account → 404/`account_not_found`, DB down → 503/`database`); Duration =
`http_request_duration_seconds` p50/p95/p99; container CPU/mem from cAdvisor; DB
connections & commit/rollback rate from `postgres-exporter`. Application failures
are also logged to stdout — `docker compose -f infra/docker-compose.yml logs app`.

---

## Project layout

```
lab/
├── infra/
│   ├── docker-compose.yml   # db, adminer, app, prometheus, grafana, postgres-exporter, cadvisor
│   └── Dockerfile           # app image (python:3.13 + uv)
├── ops/
│   ├── prometheus/prometheus.yml
│   └── grafana/provisioning/
│       ├── datasources/datasource.yml
│       └── dashboards/{dashboards.yml, fastapi.json, k6.json}
├── load_test/
│   ├── main.js              # k6 scenarios (smoke/load/stress/spike)
│   └── lib/{config.js, helpers.js}
└── src/app/
    ├── main.py              # app + instrumentator + /metrics
    ├── config/config.py     # engine/session (DATABASE_URL from env)
    ├── controllers/controller.py
    ├── services/service.py
    ├── models/model.py
    ├── schemas/schema.py
    └── observability/metrics.py   # custom bank_* metrics
```

## Running the app without Docker

```bash
uv sync
# point at a reachable Postgres (the default host `db` only resolves inside compose)
DATABASE_URL=postgresql://postgres:mysecretpassword@localhost:5432/bank \
  uv run uvicorn src.app.main:app --host 0.0.0.0 --port 8000
```

> Note: the downloaded `prometheus-3.13.1.darwin-amd64/` directory is **not** used
> — it's an incomplete, OS-specific binary drop. The stack runs Prometheus as a
> container. It's gitignored.
