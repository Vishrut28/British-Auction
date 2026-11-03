from datetime import datetime

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import services
from app.clock import get_now
from app.config import settings
from app.db import get_db
from app.engine import BidRejected
from app.schemas import (
    BidCreate,
    BidResult,
    EventOut,
    RfqCreate,
    RfqDetail,
    RfqList,
    SupplierCreate,
    SupplierOut,
)

app = FastAPI(
    title="British Auction RFQ",
    description="RFQs with British auction bidding: auto-extension near close, capped by a forced close.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(services.NotFound)
def _not_found(_: Request, exc: services.NotFound) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": str(exc)})


@app.exception_handler(services.Conflict)
def _conflict(_: Request, exc: services.Conflict) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_409_CONFLICT, content={"detail": str(exc)})


@app.exception_handler(BidRejected)
def _bid_rejected(_: Request, exc: BidRejected) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_409_CONFLICT, content={"detail": str(exc)})


@app.get("/api/health")
def health(db: Session = Depends(get_db)) -> dict[str, str]:
    db.execute(text("SELECT 1"))
    return {"status": "ok"}


@app.get("/api/time")
def server_time(now: datetime = Depends(get_now)) -> dict[str, datetime]:
    """The server clock, so the UI countdown can correct for a wrong local clock."""
    return {"server_time": now}


# --- Suppliers ------------------------------------------------------------------------


@app.get("/api/suppliers", response_model=list[SupplierOut])
def list_suppliers(db: Session = Depends(get_db)):
    return services.list_suppliers(db)


@app.post("/api/suppliers", response_model=SupplierOut, status_code=status.HTTP_201_CREATED)
def create_supplier(data: SupplierCreate, db: Session = Depends(get_db)):
    return services.create_supplier(db, data)


# --- RFQs -----------------------------------------------------------------------------


@app.get("/api/rfqs", response_model=RfqList)
def list_rfqs(db: Session = Depends(get_db), now: datetime = Depends(get_now)):
    services.sync_statuses(db, now)
    return {"server_time": now, "items": services.list_rfqs(db, now)}


@app.post("/api/rfqs", response_model=RfqDetail, status_code=status.HTTP_201_CREATED)
def create_rfq(data: RfqCreate, db: Session = Depends(get_db), now: datetime = Depends(get_now)):
    try:
        rfq = services.create_rfq(db, data, now)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    return services.rfq_detail(db, rfq.id, now)


@app.get("/api/rfqs/{rfq_id}", response_model=RfqDetail)
def get_rfq(rfq_id: int, db: Session = Depends(get_db), now: datetime = Depends(get_now)):
    services.sync_statuses(db, now, rfq_id)
    return services.rfq_detail(db, rfq_id, now)


@app.get("/api/rfqs/{rfq_id}/events", response_model=list[EventOut])
def list_events(rfq_id: int, db: Session = Depends(get_db), now: datetime = Depends(get_now)):
    services.sync_statuses(db, now, rfq_id)
    return services.rfq_detail(db, rfq_id, now)["events"]


@app.post("/api/rfqs/{rfq_id}/bids", response_model=BidResult, status_code=status.HTTP_201_CREATED)
def place_bid(
    rfq_id: int, data: BidCreate, db: Session = Depends(get_db), now: datetime = Depends(get_now)
):
    return services.place_bid(db, rfq_id, data, now)
