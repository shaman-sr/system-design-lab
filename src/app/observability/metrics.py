"""Custom (business-level) Prometheus metrics.

These live at module scope so each metric is created exactly once, at import
time. Creating a metric inside a request handler would raise a duplicate
timeseries error on the second call. Import this module once (from main.py) so
the metrics register on the default collector registry that
prometheus-fastapi-instrumentator exposes at /metrics.

The instrumentator already gives us the generic HTTP RED signals
(http_requests_total, http_request_duration_seconds, ...). The metrics here are
domain-specific: they answer "how much money moved through the system", which no
generic HTTP metric can.
"""

from prometheus_client import Counter

# Count of transactions successfully committed, split by type (credit/debit).
TRANSACTIONS_CREATED = Counter(
    "bank_transactions_created_total",
    "Number of transactions successfully created, by type",
    ["type"],
)

# Running sum of transaction amounts (in paise), split by type. Lets you graph
# monetary throughput (rupees/sec) with rate() alongside request throughput.
TRANSACTION_AMOUNT_PAISE = Counter(
    "bank_transaction_amount_paise_total",
    "Cumulative sum of transaction amounts in paise, by type",
    ["type"],
)
