# British Auction RFQ

An RFQ (Request for Quotation) system where suppliers bid in a British
auction. Bids made close to the end extend the auction, up to a forced close
time it can never pass.

**Stack:** FastAPI · SQLAlchemy 2 · Alembic · PostgreSQL · React (in progress)

## Docs

- [Auction rules](docs/auction-rules.md): exactly when bids are accepted, how
  ranking works, and when and by how much an auction extends
- [Schema design](docs/schema.md): tables, ER diagram, constraints and indexes

## Run locally

Requirements: Docker, Python 3.12.

```bash
docker compose up -d db

cd backend
python -m venv .venv
.venv/Scripts/activate        # Windows; use `source .venv/bin/activate` on macOS/Linux
pip install -r requirements-dev.txt
cp .env.example .env
alembic upgrade head
uvicorn app.main:app --reload
```

Check it is up: <http://localhost:8000/api/health>. The API docs are at
<http://localhost:8000/docs>.

The Compose database listens on host port **5433**, so it doesn't clash with a
Postgres already running on 5432.
