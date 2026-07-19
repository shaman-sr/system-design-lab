import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator, metrics

from src.app.config.config import create_db_and_tables
from src.app.controllers.controller import router
from src.app.exceptions import AccountNotFoundError, AppError, DatabaseError
from src.app.observability.logging_config import configure_logging
from src.app.observability.metrics import APP_ERRORS
import src.app.observability.metrics  # noqa: F401 -- registers custom metrics on import

configure_logging()
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # create_db_and_tables() is now a coroutine, so it must be awaited inside the
    # running event loop — do it on startup via the lifespan, not at import time.
    await create_db_and_tables()
    yield


app = FastAPI(lifespan=lifespan)

app.include_router(router)


# --- Exception handlers ----------------------------------------------------
# Each one logs the failure, increments bank_errors_total{type=...}, and returns
# a clean status code the Prometheus instrumentator records (4xx/5xx). These run
# inside the instrumentator middleware, so the status is always observed.

@app.exception_handler(AccountNotFoundError)
def handle_account_not_found(request: Request, exc: AccountNotFoundError):
    log.warning("404 %s %s: %s", request.method, request.url.path, exc.message)
    APP_ERRORS.labels(type=exc.error_type).inc()
    return JSONResponse(status_code=404, content={"detail": exc.message})


@app.exception_handler(DatabaseError)
def handle_database_error(request: Request, exc: DatabaseError):
    log.error("503 %s %s: %s", request.method, request.url.path, exc.message)
    APP_ERRORS.labels(type=exc.error_type).inc()
    return JSONResponse(status_code=503, content={"detail": exc.message})


@app.exception_handler(Exception)
def handle_unexpected(request: Request, exc: Exception):
    # Catch-all for anything not modeled as an AppError. Log the full stack trace.
    log.exception("500 %s %s: unexpected error", request.method, request.url.path)
    error_type = exc.error_type if isinstance(exc, AppError) else "unexpected"
    APP_ERRORS.labels(type=error_type).inc()
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


# Attach the metrics middleware and expose GET /metrics. Do this AFTER the app
# exists and routers are included so the middleware wraps every registered route.
#
# We widen the default latency buckets: the library's default low-resolution
# buckets are only (0.1, 0.5, 1), which caps histogram_quantile() at 1s — you
# could never tell a 1s request from a 20s one on the dashboard. These buckets
# run out to 60s so the latency panel shows real severity under stress.
LATENCY_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 20, 30, 60)

instrumentator = Instrumentator()
instrumentator.add(metrics.default(latency_lowr_buckets=LATENCY_BUCKETS))
instrumentator.instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
