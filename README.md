# lab — a minimal system you can load-test and break

A hands-on lab for turning system-design theory into felt experience: build a
small service, put real load on it with [k6](https://k6.io/), watch it in
Prometheus + Grafana, then deliberately break it and see *what* breaks and *why*.

The "system under test" is a tiny **FastAPI + SQLModel** banking API — accounts
and transactions in paise (INR minor units) — fronted by an **nginx** load
balancer, pooled through **PgBouncer** onto **Postgres**, and cached in **Redis**.

---

## Architecture

```mermaid
flowchart LR
  k6[k6 load generator] -->|HTTP| lb[nginx app_lb :8000]
  k6 -.->|remote-write| prom[(Prometheus)]
  lb -->|round-robin| app[FastAPI app replicas]
  app -->|cache-aside| redis[(Redis)]
  app -->|SQL| pgb[PgBouncer :6432]
  pgb -->|transaction pooling| db[(Postgres)]
  prom -->|scrape /metrics| app
  prom -->|scrape| pgexp[postgres-exporter]
  prom -->|scrape| pgbexp[pgbouncer-exporter]
  prom -->|scrape| redisexp[redis-exporter]
  prom -->|scrape| cadvisor[cAdvisor]
  graf[Grafana :3000] -->|query| prom
```

- **nginx (`app_lb`)** publishes host `:8000` and round-robins across the `app`
  replicas (it re-resolves the `app` service name per request via Docker DNS, so
  `--scale app=N` is picked up live). The app replicas have no host port.
- **app** exposes business routes plus `/metrics` (via
  `prometheus-fastapi-instrumentator`) — request rate, latency histogram, status
  codes, and custom `bank_*` transaction counters.
- **Redis** is a cache-aside layer in front of Postgres for the GET paths
  (see [Caching](#caching)). Postgres stays the source of truth.
- **PgBouncer** multiplexes every app connection (transaction pooling) onto a
  small server pool, so scaling app replicas can't exhaust Postgres.
- **Prometheus** scrapes the app, `postgres-exporter`, `pgbouncer-exporter`,
  `redis-exporter`, and `cAdvisor` every 5s, and accepts k6's client-side metrics
  via remote-write.
- **Grafana** auto-provisions the datasource and two dashboards.

---

## Endpoints

| Method | Path                              | Body / query                                             | Purpose |
|--------|-----------------------------------|----------------------------------------------------------|---------|
| POST   | `/api/account`                    | `{ "balance_paise": 100000 }` (optional, default 0)      | Create an account, returns `{id, balance_paise}` |
| GET    | `/api/account?account_id=<int>`   | —                                                        | Fetch an account (404 if missing) — **cached** |
| GET    | `/api/transaction/?account_id=<int>` | —                                                     | List an account's transactions — **cached** |
| POST   | `/api/transaction/`               | `{account_id, type:"credit"\|"debit", amount, description?, occured_at}` | Create a transaction; updates the balance atomically and **invalidates** the account's caches |
| GET    | `/metrics`                        | —                                                        | Prometheus exposition |
| GET    | `/docs`                           | —                                                        | Swagger UI |

---

## Caching

The two GET endpoints use **cache-aside** on Redis; writes keep it correct.

- **Read**: check Redis (`account:{id}` / `transactions:{id}`) → hit returns
  without touching Postgres; miss reads the DB and populates the key with a
  **60s TTL**.
- **Write** (`POST /transaction/`): after the commit, the account's balance and
  transaction list changed, so both keys are **deleted** (invalidated).
- **Single-flight (stampede protection)**: when a hot key goes cold and many
  requests miss at once, only the **first** takes a short Redis lock and does the
  one DB read; the rest wait briefly and read the value it cached. This is a
  *distributed* lock (in Redis), so it coalesces across all app replicas — a
  50-way stampede on one key becomes **1** query, not 50 flooding PgBouncer's pool.
- **Why three mechanisms:** `maxmemory-policy allkeys-lru` (in `infra/redis.conf`)
  bounds *memory*; the **TTL** bounds *staleness* (LRU never evicts a hot key, so
  it can't be your correctness backstop); **invalidation** gives immediate
  freshness on the happy path. They are not substitutes — keep all three.
- All Redis calls degrade gracefully: a cache/lock failure logs a warning and
  falls back to Postgres, never a 500.

Knobs live in `src/app/services/service.py` (`CACHE_TTL_SECONDS`, `_LOCK_TIMEOUT`,
`_LOCK_WAIT`) and `infra/redis.conf` (`maxmemory`, eviction policy).

---

## Quickstart

Prereqs: Docker + Docker Compose. (k6 is a separate install — see below.)

```bash
# From the repo root — build the app image and start the whole stack.
docker compose -f infra/docker-compose.yml up --build
```

That brings up, in dependency order: `db` → `pgbouncer` / `redis` → `app` →
`app_lb` (nginx) → `prometheus` → `grafana`, plus `postgres-exporter`,
`pgbouncer-exporter`, `redis-exporter`, `cadvisor`, and `adminer`.

### Service URLs

| Service            | URL                        | Notes |
|--------------------|----------------------------|-------|
| App (via nginx LB) | http://localhost:8000      | `/docs` for Swagger, `/metrics` for Prometheus |
| Grafana            | http://localhost:3000      | anonymous access is on (Admin); admin login `admin` / `admin` |
| Prometheus         | http://localhost:9090      | check `/targets` — all should be **UP** |
| Adminer (DB UI)    | http://localhost:8080      | system `PostgreSQL`, server `db`, user `postgres`, pw `mysecretpassword`, db `bank` |
| cAdvisor           | http://localhost:8081      | container metrics UI |
| Redis              | localhost:6379             | password `MySecurePassword123` (`redis-cli -a …`) |
| PgBouncer          | internal (`pgbouncer:6432`)| admin console: `psql "postgresql://postgres:…@pgbouncer:6432/pgbouncer"` then `SHOW POOLS;` |
| Exporters          | internal (`:9187` pg, `:9127` pgbouncer, `:9121` redis) | scraped by Prometheus on the compose network |

In Grafana, open the **FastAPI Lab** dashboard (RED + business + resource +
**Cache & Pool** panels) and the **k6** dashboard (client-side load metrics).

For the container CPU/memory panels to show real **names** (`infra-app-1`,
`infra-db-1`, …) instead of cgroup ids, run this once after startup — and again
after any `up --build app` or `--scale app=N` (container ids change):

```bash
uv run python ops/scripts/relabel_containers.py
```

### Smoke-check by hand

```bash
# create an account
curl -s -X POST localhost:8000/api/account \
  -H 'content-type: application/json' -d '{"balance_paise":100000}'
# -> {"id":1,"balance_paise":100000}

# post a transaction (updates balance atomically, invalidates the account's cache)
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

The single script `load_test/main.js` selects a scenario with `-e SCENARIO=`. Its
`setup()` seeds **`NUM_ACCOUNTS`** accounts (default 100) and each request picks a
random one, so reads exercise many cache keys and writes don't all contend on a
single hot row.

| Scenario | Shape | Question it answers |
|----------|-------|---------------------|
| `smoke`  | 1 VU, 1 min | Does everything work at all? |
| `load`   | ramp to 50 VUs, hold 5 min | How does it behave at expected traffic? |
| `stress` | staged 50→100→200→400 VUs | Where is the knee — when does it degrade? |
| `spike`  | jump to 300 VUs, hold, drop | How fast does it recover from a surge? |
| `tier1`  | ramp 1→100 VUs, hold | Capacity band 1 |
| `tier2`  | ramp 100→500 VUs, hold | Capacity band 2 |
| `tier3`  | ramp 500→1000 VUs, hold | Capacity band 3 |

```bash
# Terminal summary only:
k6 run -e SCENARIO=smoke load_test/main.js

# Stepped capacity bands (bump NUM_ACCOUNTS to at least your peak VUs so writes
# spread out instead of recreating a single hot account):
k6 run -e SCENARIO=tier1 -e NUM_ACCOUNTS=200  load_test/main.js
k6 run -e SCENARIO=tier2 -e NUM_ACCOUNTS=500  load_test/main.js
k6 run -e SCENARIO=tier3 -e NUM_ACCOUNTS=1000 load_test/main.js
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
**FastAPI Lab** dashboard (server-side latency, errors, DB, cache, containers) —
the gap between the two curves is queueing/network you can't see from either side.

Handy overrides: `-e BASE_URL=...`, `-e START_BALANCE_PAISE=...`,
`-e NUM_ACCOUNTS=...`. If the k6 dashboard panels stay empty, your k6 version may
name remote-write series differently — import Grafana dashboard **ID 19665**.

---

## Breaking the system — experiments to try

The rig above is the point: it lets you *see* failures instead of guessing.
Start a run, then introduce a fault and watch the dashboards. Track **RED** for
the API (Rate, Errors, Duration) and **USE** for resources (Utilization,
Saturation, Errors).

- **Soak / endurance.** Run `load` for hours. Watch the app container's memory
  (cAdvisor) and Postgres connection count for slow upward creep — the signature
  of a leak. Does p95 drift up over time?

- **Breakpoint / capacity.** Run `tier1` → `tier2` → `tier3` in turn (or swap an
  executor to `ramping-arrival-rate` to hold a fixed RPS) and find the band where
  the error rate crosses your threshold.

- **DB failure injection.** Mid-run: `docker compose -f infra/docker-compose.yml
  stop db`. DB errors are caught and returned as **503** (counted in
  `bank_errors_total{type="database"}`), so the *Error rate* 5xx line lights up.
  Then `start db` — the app reconnects on the next request (NullPool opens a fresh
  connection via PgBouncer), no restart needed; measure recovery time.

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
    `relabel_containers.py` afterwards so cAdvisor panels label the new containers.
  - **DB tier** scales with `default_pool_size`. Because every replica multiplexes
    onto this one pool, adding replicas alone will *not* raise DB throughput past
    the pool size — push VUs past it and requests queue in PgBouncer
    (`SHOW POOLS` → `cl_waiting`, or the **Cache & Pool** dashboard row) while DB
    CPU stays low: saturation without utilization. Raise `default_pool_size` (keep
    Postgres `max_connections` in `infra/docker-compose.yml` above it) and
    correlate with p95. *Why not just remove PgBouncer to get per-replica pools
    back?* That only "scales" by letting replicas open direct connections until
    Postgres `max_connections` is exhausted (~6 replicas) and starts rejecting
    them — the exact failure mode PgBouncer exists to prevent. Tune the pool.

- **Cache stampede.** Warm a key, then invalidate it (POST a transaction for that
  account, or `redis-cli -a … DEL account:<id>`) under high VUs. On the **Cache &
  Pool** row, watch `misses/s`: with single-flight it's a thin blip (one rebuild)
  and `cl_waiting` stays calm; the stampede that *would* have flooded PgBouncer is
  collapsed to a single DB read. Raise `_LOCK_WAIT` / disable the lock to feel the
  difference.

- **Cold vs warm cache.** Compare the first seconds of a run (empty Redis, every
  read a miss → DB) against steady state (high **cache hit ratio**, `sv_active`
  near zero because reads never reach Postgres).

**Where to look:** Rate = `http_requests_total`; Errors = 4xx/5xx share plus the
domain-level `bank_errors_total{type}`; Duration = `http_request_duration_seconds`
p50/p95/p99; cache hit ratio & misses from `redis-exporter`; pool `cl_waiting` /
`sv_active` from `pgbouncer-exporter`; container CPU/mem from cAdvisor; DB
connections & commit/rollback from `postgres-exporter`. App failures are also
logged: `docker compose -f infra/docker-compose.yml logs app`.

---

## Project layout

```
lab/
├── infra/
│   ├── docker-compose.yml   # db, pgbouncer, redis, app, app_lb (nginx), prometheus,
│   │                        # grafana, {postgres,pgbouncer,redis}-exporter, cadvisor, adminer
│   ├── Dockerfile           # app image (python:3.13 + uv)
│   └── redis.conf           # cache config (maxmemory + allkeys-lru, requirepass)
├── ops/
│   ├── nginx/nginx.conf         # LB, per-request DNS re-resolve across app replicas
│   ├── pgbouncer/{pgbouncer.ini, userlist.txt}
│   ├── prometheus/prometheus.yml
│   ├── grafana/provisioning/
│   │   ├── datasources/datasource.yml
│   │   └── dashboards/{dashboards.yml, fastapi.json, k6.json}
│   └── scripts/relabel_containers.py   # map cAdvisor cgroup ids → container names
├── load_test/
│   ├── main.js              # k6 scenarios (smoke/load/stress/spike/tier1-3), multi-account
│   └── lib/{config.js, helpers.js}
└── src/app/
    ├── main.py              # app + instrumentator + /metrics
    ├── config/config.py     # async engine/session (NullPool → PgBouncer) + Redis client
    ├── controllers/controller.py
    ├── services/service.py  # atomic balance update, cache-aside + single-flight, invalidation
    ├── models/model.py      # Account, Transaction (account_id indexed)
    ├── schemas/schema.py
    └── observability/metrics.py   # custom bank_* metrics
```

## Running the app without Docker

```bash
uv sync
# point at a reachable Postgres and Redis (the default hosts `db`/`pgbouncer`/`redis`
# only resolve inside compose)
DATABASE_URL=postgresql://postgres:mysecretpassword@localhost:5432/bank \
REDIS_URL=redis://:MySecurePassword123@localhost:6379/0 \
  uv run uvicorn src.app.main:app --host 0.0.0.0 --port 8000
```

> Note: the downloaded `prometheus-3.13.1.darwin-amd64/` directory is **not** used
> — it's an incomplete, OS-specific binary drop. The stack runs Prometheus as a
> container. It's gitignored.
