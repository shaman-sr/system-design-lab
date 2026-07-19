from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

from src.app.config.config import create_db_and_tables
from src.app.controllers.controller import router
import src.app.observability.metrics  # noqa: F401 -- registers custom metrics on import

app = FastAPI()
create_db_and_tables()

app.include_router(router)

# Attach the metrics middleware and expose GET /metrics. Do this AFTER the app
# exists and routers are included so the middleware wraps every registered route.
Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
