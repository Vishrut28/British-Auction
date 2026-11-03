# British Auction RFQ

An RFQ (Request for Quotation) system where suppliers bid in a **British
auction**: bids made close to the end extend the auction, so nobody can win with
a last-second bid. A **forced close** time caps every extension.

**Stack:** FastAPI · SQLAlchemy 2 · Alembic · PostgreSQL · Celery + Redis · React 19 + TypeScript (Vite) · Docker Compose · GitHub Actions

## Deliverables

| Deliverable | Where |
|---|---|
| HLD with architecture diagram | [docs/hld.md](docs/hld.md) |
| Schema design | [docs/schema.md](docs/schema.md) (ER diagram, constraints, indexes) · migration in [backend/alembic/versions](backend/alembic/versions) |
| Backend code | [backend/](backend) |
| Frontend code | [frontend/](frontend) |
| Auction rules, decided case by case | [docs/auction-rules.md](docs/auction-rules.md) |

## How the brief maps to the code

| Brief | Implemented |
|---|---|
| §5 RFQ creation: name/reference, bid start, bid close, forced close, pickup date | `POST /api/rfqs` · *New RFQ* page |
| §5 Quote: carrier, freight / origin / destination charges, transit time, validity | `POST /api/rfqs/{id}/bids` · *Submit a quote* panel |
| §5 Never extend beyond the forced close | `min(close + Y, forced)` in [engine.py](backend/app/engine.py), plus a database CHECK constraint |
| §6.1 Trigger window X · §6.2 Extension Y | Per-RFQ config; the window is measured from the *current* close time |
| §6.3 a/b/c Triggers: bid received / any rank change / L1 change | `trigger_fired()` in [engine.py](backend/app/engine.py), with each brief example as a test |
| §7 Forced close > bid close; extensions never past forced close | Validated in the API and the form, and enforced by the database |
| §8 Listing: RFQ, current lowest bid, current close, forced close, status (Active / Closed / Force Closed) | `/` page, live countdown |
| §8 Details: bids sorted by price, L1/L2/L3 ranks, quote details, X and Y, activity log with reason for each extension | `/rfqs/:id` page |

## Run it with Docker

```bash
docker compose up --build
```

Then, in a second terminal, add demo suppliers and a live auction that closes in about 6 minutes:

```bash
docker compose exec backend python -m app.seed --demo
```

- App: <http://localhost:8080>
- API docs (Swagger): <http://localhost:8000/docs>

Compose runs Postgres, Redis, the API (which applies migrations on start), the
Celery worker that closes auctions on time, and the frontend on nginx.
If a host port is taken, override it: `DB_PORT`, `REDIS_PORT`, `API_PORT`,
`WEB_PORT` (for example `REDIS_PORT=6380 docker compose up --build`).

### Try the extension rules

1. Open the demo auction. Its trigger is *any rank change*, with X = 5 min and Y = 2 min.
2. Pick **Delta Movers** under *Bidding as* and submit a total below the current L1.
3. Inside the last 5 minutes, the close time moves 2 minutes later. The
   activity log says which ranks changed and shows the old and new close time.
4. Keep bidding: extensions stop at the forced close, and the auction ends as
   **Force Closed**.

## Local development

You need Python 3.12, Node 22, and Postgres and Redis (the Compose services are easiest):

```bash
docker compose up -d db redis
```

Backend:

```bash
cd backend
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env
alembic upgrade head
python -m app.seed --demo
uvicorn app.main:app --reload
```

Worker, in another terminal (add `--pool=solo` on Windows, and run `celery -A app.worker beat` separately there):

```bash
celery -A app.worker worker --beat --loglevel=info
```

Frontend, in another terminal. Vite forwards `/api` to `localhost:8000`:

```bash
cd frontend
npm install
npm run dev
```

Open <http://localhost:5173>.

## Tests

```bash
cd backend
pytest
```

49 tests. The engine tests cover every rule in
[auction-rules.md](docs/auction-rules.md), including each example from the
brief. The API tests run against a real Postgres database (`rfq_test`, created
automatically; set `TEST_DATABASE_URL` to change it). They cover validation,
ranking, extensions, the forced-close cap, closing, and a race: two
simultaneous bids in the trigger window must extend twice, which only holds
because of the row lock.

CI ([.github/workflows/ci.yml](.github/workflows/ci.yml)) runs the backend tests
on Postgres, plus the frontend lint and build, on every push.

## Assumptions

The brief leaves some details open. Each choice is written down in
[docs/auction-rules.md](docs/auction-rules.md). The main ones:

- A supplier's new bid must be lower than their own previous bid. It does not have to beat L1.
- Rank is by each supplier's latest bid. On equal prices, whoever got there first ranks higher.
- *Rank change* means a supplier who was already ranked moved. *L1 change* means a different supplier took L1 from someone. A first bid only triggers *bid received*.
- **Force Closed** means extensions pushed the auction all the way to the forced close.
- Login is out of scope: the UI picks which supplier is bidding.
