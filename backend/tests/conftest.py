"""API tests run against a real Postgres database named rfq_test.

Set TEST_DATABASE_URL to point elsewhere. The database is created if missing,
migrated with Alembic, and emptied before each test.
"""

import os
from datetime import UTC, datetime

from sqlalchemy.engine import make_url

TEST_URL = make_url(
    os.environ.get("TEST_DATABASE_URL", "postgresql+psycopg://rfq:rfq@localhost:5433/rfq_test")
)
# Must be set before app.db creates its engine.
os.environ["DATABASE_URL"] = TEST_URL.render_as_string(hide_password=False)

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.exc import OperationalError  # noqa: E402

from app.clock import get_now  # noqa: E402
from app.db import engine  # noqa: E402
from app.main import app  # noqa: E402

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _create_database_if_missing() -> None:
    admin = create_engine(
        TEST_URL.set(database="postgres"),
        isolation_level="AUTOCOMMIT",
        connect_args={"connect_timeout": 5},
    )
    try:
        with admin.connect() as conn:
            exists = conn.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": TEST_URL.database}
            )
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{TEST_URL.database}"'))
    except OperationalError as exc:
        pytest.exit(
            f"Cannot reach Postgres at {TEST_URL.render_as_string()}. Start it with "
            f"`docker compose up -d db`, or set TEST_DATABASE_URL. ({exc.orig})",
            returncode=2,
        )
    finally:
        admin.dispose()


@pytest.fixture(scope="session", autouse=True)
def _migrated_database():
    _create_database_if_missing()
    cfg = Config(os.path.join(BACKEND_DIR, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(BACKEND_DIR, "alembic"))
    command.upgrade(cfg, "head")
    yield
    engine.dispose()


@pytest.fixture(autouse=True)
def _empty_tables(_migrated_database):
    with engine.begin() as conn:
        conn.execute(
            text("TRUNCATE auction_events, bids, rfqs, suppliers RESTART IDENTITY CASCADE")
        )


class Clock:
    """A clock the test moves by hand."""

    def __init__(self, now: datetime):
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def set(self, hh: int, mm: int, ss: int = 0) -> None:
        self.now = self.now.replace(hour=hh, minute=mm, second=ss, microsecond=0)


@pytest.fixture
def clock():
    c = Clock(datetime(2026, 11, 3, 9, 0, tzinfo=UTC))
    app.dependency_overrides[get_now] = c
    yield c
    app.dependency_overrides.pop(get_now, None)


@pytest.fixture
def client(clock):
    with TestClient(app) as c:
        yield c
