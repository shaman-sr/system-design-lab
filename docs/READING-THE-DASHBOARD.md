# Reading the dashboard (plain-English decoder)

You said the dashboard looks cool but you can't decode it. This doc fixes that.
Keep it open next to Grafana (`http://localhost:3000` → **FastAPI Lab**).

Every panel in Grafana now also has an **ℹ️ info icon** (top-left of the panel) —
hover it for a one-line version of what's below.

---

## 30-second mental model

Two questions, two frameworks. That's the whole dashboard.

- **Is the API healthy?** → **RED**: **R**ate (how much traffic), **E**rrors (how
  much is failing), **D**uration (how slow). *These describe what users feel.*
- **Is a resource maxed out?** → **USE**: **U**tilization (how busy), **S**aturation
  (how much is queued/waiting). *These describe why.*

When something feels wrong: **RED tells you there's a problem, USE tells you which
box caused it.**

---

## How to read a percentile (this unlocks everything)

The latency panel shows **p50 / p95 / p99**, not an average. Why:

> Sort every request by how long it took. **p95 = the request 95% of the way up
> the list.** "p95 = 2s" means *95% of requests were faster than 2s, and the
> slowest 5% were worse.*

- **p50** = the *typical* request (the median).
- **p99** = the *near-worst* request. This is what your unluckiest users feel.
- **Averages lie**: 99 fast requests + 1 twenty-second request can still show a
  low average, while p99 correctly screams. Always read the tail.

**The tell you'll see most:** p50 stays low but p99 shoots up → *most* requests are
fine, but a growing minority are queueing behind something. That "something" is
usually in the USE panels (CPU pegged, or the DB connection pool full).

---

## Panel-by-panel

### API — RED signals

| Panel | What it shows | Normal | Alarming → what it means |
|---|---|---|---|
| **Request rate by handler** | requests/sec per endpoint | tracks your load; flat 0.2/s on `/metrics` is just Prometheus scraping itself | line **drops to 0** mid-test = app stopped serving (crash/overload) |
| **Error rate (4xx/5xx %)** | fraction of requests failing | flat at 0 | **5xx line** = *server's* fault (bug, DB down) — the serious one. **4xx line** = *client's* fault (missing account) — usually benign |
| **Latency p50/p95/p99** | request duration | tens of ms | **p99 rising** = slow tail forming. **p50 also rising** = everything is slow (systemic) |
| **Requests/s by status class** | traffic split by 2xx/4xx/5xx | one 2xx line | a **5xx line appears** = failures; a **4xx line** = clients hitting missing resources |

> Ignore the flat orange `/metrics` line everywhere — it's monitoring overhead, not real traffic.

### Business — your custom metrics
| Panel | What it shows | Watch for |
|---|---|---|
| **Transactions created /s** | successful writes, credit vs debit | drops to 0 while POSTs continue = writes failing → check error panels |
| **Money throughput (paise/s)** | business volume in money terms | — |

### Resources — USE
| Panel | What it shows | Alarming → what it means |
|---|---|---|
| **Container CPU cores** | CPU per container (1.0 = one full core) | a line pinned near its limit = that container is **CPU-bound**. *This answers "is it the DB or the app that's pegged?"* |
| **Container memory** | RAM per container | the **app's** line climbing forever = **memory leak**. (Prometheus using lots of RAM is normal — it stores metrics in memory.) |
| **Postgres active connections** | open DB connections. All app replicas multiplex through PgBouncer onto its `default_pool_size` (currently **90**) server pool, so this tops out near 90 regardless of replica count | **pinned near 90** while latency climbs = the PgBouncer pool is saturated (requests queue in PgBouncer — check `SHOW POOLS.cl_waiting`). Raise `default_pool_size`, not the replica count, to lift the ceiling |
| **Postgres commits/rollbacks** | DB write success vs failure | **rollback spike** = transactions failing at the DB |

### Errors — application (the "why")
| Panel | What it shows | Note |
|---|---|---|
| **App errors /s by type** | failures labelled by *cause* | `account_not_found`→404, `database`→503, `unexpected`→500. The status panel says *that* it failed; this says *why* |
| **Total app errors (cumulative)** | running scoreboard per cause | resets on app restart |

---

## Container names on the CPU/memory panels

The CPU and memory legends show real container names — `infra-app-1` (your app),
`infra-db-1` (Postgres), `infra-prometheus-1`, etc. The two you'll watch most:

- **`infra-app-1`** = your FastAPI app.
- **`infra-db-1`** = Postgres.

**How this works (and the one command you need):** cAdvisor on Docker Desktop/macOS
can't resolve container names itself (it runs in a VM without the containerd
socket), so it only emits a raw cgroup `id`. Prometheus relabeling maps each `id`
→ name. Container IDs **change every time you rebuild** (`up --build app`), so after
a rebuild the app's line falls back to a 12-char id until you refresh the mapping:

```bash
uv run python ops/scripts/relabel_containers.py
```

That reads `docker ps`, rewrites the mapping in `ops/prometheus/prometheus.yml`,
and hot-reloads Prometheus — names reappear within one scrape (~5s). Run it once
after `docker compose up`, and again after any `up --build app`.

**Also works right now:** hover any line on a CPU/memory panel — Grafana's tooltip
shows the full ID, and the first 12 chars match the table above. (A future Prometheus
metric-relabel could map IDs→names automatically; for now this table + hover is the way.)

---

## "I'm running experiment X — where do I look?"

| Experiment | Panels that react, and how |
|---|---|
| **Baseline `load`/`stress`** | Rate rises; watch **latency p95/p99** and **error rate** for where they bend upward — that VU count is your ceiling |
| **Kill the DB** (`stop db`) | **5xx error line** jumps, **app errors → `database`** appears, **Postgres connections** drops, **rollbacks** may spike |
| **Missing account** (bad `account_id`) | **4xx line** + **app errors → `account_not_found`** (NOT 5xx — it's a client error) |
| **Starve CPU** (`docker update --cpus 0.25`) | app's **CPU line** pins at 0.25; **latency** climbs; error rate may follow |
| **Pool exhaustion** (high VUs) | **Postgres connections pin near `default_pool_size` (90)**, **latency climbs**, but **DB CPU stays low** = requests queueing in PgBouncer, not compute. Adding app replicas won't help — raise `default_pool_size` |
| **Memory leak / soak** (hours) | app's **memory line** creeps up and never recovers |

**The skill:** fault → *which panel moved first* → *why* → fix → re-run and confirm
the panel behaves. Each loop teaches one failure signature.

---

## The two "gotchas" that were confusing you (now fixed)

1. **Latency looked stuck at 1s.** The metric's buckets only went `0.1, 0.5, 1s`,
   so the math literally couldn't report higher — a 20s request looked like a 1s
   request. Buckets now run to **60s**, so severity is visible. (`src/app/main.py`,
   `LATENCY_BUCKETS`.)
2. **cAdvisor legends were unreadable hashes.** Now show real container names
   (`infra-app-1`, `infra-db-1`, …) via Prometheus relabeling. Refresh after a
   rebuild with `uv run python ops/scripts/relabel_containers.py`.
