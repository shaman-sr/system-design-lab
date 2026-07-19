"""Application exception hierarchy.

Services raise these domain-level errors instead of leaking bare `ValueError`s
or database driver exceptions. `main.py` registers one handler per type that
logs the failure, increments the `bank_errors_total` metric, and returns the
right HTTP status code — so every failure ends up in both the logs and Grafana.
"""


class AppError(Exception):
    """Base class for all application errors. Carries a human-readable message
    and an `error_type` used as the Prometheus metric label."""

    error_type = "app_error"

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class AccountNotFoundError(AppError):
    """Raised when an operation references an account that does not exist."""

    error_type = "account_not_found"


class DatabaseError(AppError):
    """Raised when a database operation fails (DB unreachable, commit failed,
    integrity violation, ...). Wraps the underlying SQLAlchemy exception."""

    error_type = "database"
