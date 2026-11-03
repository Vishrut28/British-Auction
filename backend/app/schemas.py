"""Request and response bodies for the REST API."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any

from pydantic import AwareDatetime, BaseModel, ConfigDict, EmailStr, Field, model_validator

from app.engine import validate_rfq_times
from app.models import AuctionStatus, EventType, TriggerType

# Up to 999,999,999.99 per charge, so the sum of three still fits the
# NUMERIC(12, 2) total column.
Money = Annotated[Decimal, Field(ge=0, max_digits=11, decimal_places=2)]
Minutes = Annotated[int, Field(ge=1, le=24 * 60)]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- Suppliers ------------------------------------------------------------------------


class SupplierCreate(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=200)]
    email: EmailStr


class SupplierOut(ORM):
    id: int
    name: str
    email: str


# --- RFQs -----------------------------------------------------------------------------


class RfqCreate(BaseModel):
    reference_id: Annotated[str, Field(min_length=1, max_length=50)]
    name: Annotated[str, Field(min_length=1, max_length=200)]
    pickup_date: date
    bid_start_at: AwareDatetime
    bid_close_at: AwareDatetime
    forced_close_at: AwareDatetime
    # The brief's "British Auction option". With it off, the RFQ closes at its
    # bid close time and is never extended; X, Y and the trigger are ignored.
    is_british_auction: bool = True
    trigger_window_minutes: Minutes | None = None  # X
    extension_minutes: Minutes | None = None  # Y
    trigger_type: TriggerType | None = None

    @model_validator(mode="after")
    def check(self) -> "RfqCreate":
        validate_rfq_times(self.bid_start_at, self.bid_close_at, self.forced_close_at)
        if self.is_british_auction:
            missing = [
                label
                for label, value in (
                    ("trigger window (X)", self.trigger_window_minutes),
                    ("extension duration (Y)", self.extension_minutes),
                    ("extension trigger", self.trigger_type),
                )
                if value is None
            ]
            if missing:
                raise ValueError(f"A British auction needs: {', '.join(missing)}.")
        else:
            self.trigger_window_minutes = self.extension_minutes = self.trigger_type = None
        return self


class AuctionConfig(BaseModel):
    is_british_auction: bool
    trigger_window_minutes: int | None
    extension_minutes: int | None
    trigger_type: TriggerType | None


class RfqSummary(BaseModel):
    """One row of the auction listing page."""

    id: int
    reference_id: str
    name: str
    pickup_date: date
    bid_start_at: datetime
    bid_close_at: datetime
    current_close_at: datetime
    forced_close_at: datetime
    status: AuctionStatus
    lowest_bid: Decimal | None
    bid_count: int
    supplier_count: int
    extension_count: int
    is_british_auction: bool
    trigger_type: TriggerType | None


class RfqList(BaseModel):
    server_time: datetime
    items: list[RfqSummary]


# --- Bids -----------------------------------------------------------------------------


class BidCreate(BaseModel):
    supplier_id: int
    carrier_name: Annotated[str, Field(min_length=1, max_length=200)]
    freight_charges: Money
    origin_charges: Money
    destination_charges: Money
    transit_time_days: Annotated[int, Field(ge=1, le=365)]
    quote_valid_until: date


class BidOut(ORM):
    id: int
    supplier_id: int
    supplier_name: str
    carrier_name: str
    freight_charges: Decimal
    origin_charges: Decimal
    destination_charges: Decimal
    total_amount: Decimal
    transit_time_days: int
    quote_valid_until: date
    created_at: datetime


class RankedBid(BidOut):
    rank: int  # 1 = L1


class BidResult(BaseModel):
    """What placing a bid did: the bid, its rank, and any change to the close time."""

    bid: BidOut
    rank: int
    extended: bool
    extension_blocked: bool
    previous_close_at: datetime
    current_close_at: datetime
    reason: str | None


# --- Activity log ---------------------------------------------------------------------


class EventOut(ORM):
    id: int
    event_type: EventType
    bid_id: int | None
    supplier_id: int | None
    previous_close_at: datetime | None
    new_close_at: datetime | None
    reason: str
    details: dict[str, Any] | None
    created_at: datetime


class RfqDetail(RfqSummary):
    server_time: datetime
    config: AuctionConfig
    ranking: list[RankedBid]  # each supplier's latest bid, L1 first
    bids: list[BidOut]  # every bid, lowest price first
    events: list[EventOut]  # oldest first
