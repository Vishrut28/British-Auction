from datetime import UTC, datetime


def get_now() -> datetime:
    """The server clock. A FastAPI dependency, so tests can replace it."""
    return datetime.now(UTC)
