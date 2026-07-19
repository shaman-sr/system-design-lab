"""Central logging configuration.

Call `configure_logging()` once at startup (from main.py). It sends app logs to
stdout with a consistent format so they show up in `docker compose logs app`.
Uvicorn does not attach a handler to the root logger, so our handler here does
not duplicate uvicorn's own access/error logs; our module loggers
(`logging.getLogger(__name__)`) propagate up to this root handler.
"""

import logging

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def configure_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(level=level, format=LOG_FORMAT, force=True)
