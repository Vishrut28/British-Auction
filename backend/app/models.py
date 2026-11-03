"""Database tables. docs/schema.md explains each one, and docs/auction-rules.md
explains the rules the constraints enforce."""

import enum
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

Money = Numeric(12, 2)
TimestampTZ = DateTime(timezone=True)


class TriggerType(str, enum.Enum):
    BID_RECEIVED = "BID_RECEIVED"
    ANY_RANK_CHANGE = "ANY_RANK_CHANGE"
    L1_CHANGE = "L1_CHANGE"


class AuctionStatus(str, enum.Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    FORCE_CLOSED = "FORCE_CLOSED"


class EventType(str, enum.Enum):
    RFQ_CREATED = "RFQ_CREATED"
    BID_PLACED = "BID_PLACED"
    TIME_EXTENDED = "TIME_EXTENDED"
    # A trigger fired, but the close time was already at the forced close.
    EXTENSION_BLOCKED = "EXTENSION_BLOCKED"
    AUCTION_CLOSED = "AUCTION_CLOSED"
    AUCTION_FORCE_CLOSED = "AUCTION_FORCE_CLOSED"


def str_enum(enum_cls: type[enum.Enum], name: str) -> Enum:
    # VARCHAR plus a CHECK constraint, not a native Postgres ENUM: adding a value
    # later is then a simple migration instead of ALTER TYPE.
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=32,
        values_callable=lambda e: [m.value for m in e],
    )


class Supplier(Base):
    __tablename__ = "suppliers"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(254), unique=True)
    created_at: Mapped[datetime] = mapped_column(TimestampTZ, server_default=func.now())

    bids: Mapped[list["Bid"]] = relationship(back_populates="supplier")


class Rfq(Base):
    __tablename__ = "rfqs"
    __table_args__ = (
        CheckConstraint("bid_close_at > bid_start_at", name="close_after_start"),
        CheckConstraint("forced_close_at > bid_close_at", name="forced_after_close"),
        # current_close_at only moves later, and never past the forced close.
        CheckConstraint("current_close_at >= bid_close_at", name="current_not_before_close"),
        CheckConstraint("current_close_at <= forced_close_at", name="current_within_forced"),
        CheckConstraint("trigger_window_minutes > 0", name="trigger_window_positive"),
        CheckConstraint("extension_minutes > 0", name="extension_positive"),
        CheckConstraint("extension_count >= 0", name="extension_count_non_negative"),
        # The closing job looks for open auctions whose close time has passed.
        Index("ix_rfqs_status_current_close_at", "status", "current_close_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    reference_id: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    pickup_date: Mapped[date] = mapped_column(Date)

    bid_start_at: Mapped[datetime] = mapped_column(TimestampTZ)
    bid_close_at: Mapped[datetime] = mapped_column(TimestampTZ)  # as set by the buyer
    current_close_at: Mapped[datetime] = mapped_column(TimestampTZ)  # after extensions
    forced_close_at: Mapped[datetime] = mapped_column(TimestampTZ)

    trigger_window_minutes: Mapped[int] = mapped_column(Integer)  # X
    extension_minutes: Mapped[int] = mapped_column(Integer)  # Y
    trigger_type: Mapped[TriggerType] = mapped_column(str_enum(TriggerType, "trigger_type"))

    # A cache for fast listing. The true status is computed from the times.
    status: Mapped[AuctionStatus] = mapped_column(
        str_enum(AuctionStatus, "auction_status"), default=AuctionStatus.SCHEDULED
    )
    extension_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    created_at: Mapped[datetime] = mapped_column(TimestampTZ, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TimestampTZ, server_default=func.now(), onupdate=func.now()
    )

    bids: Mapped[list["Bid"]] = relationship(back_populates="rfq", passive_deletes=True)
    events: Mapped[list["AuctionEvent"]] = relationship(
        back_populates="rfq", passive_deletes=True, order_by="AuctionEvent.id"
    )


class Bid(Base):
    __tablename__ = "bids"
    __table_args__ = (
        CheckConstraint("freight_charges >= 0", name="freight_non_negative"),
        CheckConstraint("origin_charges >= 0", name="origin_non_negative"),
        CheckConstraint("destination_charges >= 0", name="destination_non_negative"),
        CheckConstraint(
            "freight_charges + origin_charges + destination_charges > 0", name="total_positive"
        ),
        CheckConstraint("transit_time_days > 0", name="transit_time_positive"),
        # Latest bid per supplier on an RFQ, used for ranking.
        Index("ix_bids_rfq_supplier_created", "rfq_id", "supplier_id", "created_at"),
        Index("ix_bids_rfq_total", "rfq_id", "total_amount"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    rfq_id: Mapped[int] = mapped_column(ForeignKey("rfqs.id", ondelete="CASCADE"))
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id", ondelete="RESTRICT"))

    carrier_name: Mapped[str] = mapped_column(String(200))
    freight_charges: Mapped[Decimal] = mapped_column(Money)
    origin_charges: Mapped[Decimal] = mapped_column(Money)
    destination_charges: Mapped[Decimal] = mapped_column(Money)
    # Computed by Postgres, so the total can never disagree with its parts.
    total_amount: Mapped[Decimal] = mapped_column(
        Money, Computed("freight_charges + origin_charges + destination_charges", persisted=True)
    )
    transit_time_days: Mapped[int] = mapped_column(Integer)
    quote_valid_until: Mapped[date] = mapped_column(Date)

    # Set by the server from the same clock reading used for the auction rules.
    created_at: Mapped[datetime] = mapped_column(TimestampTZ, server_default=func.now())

    rfq: Mapped[Rfq] = relationship(back_populates="bids")
    supplier: Mapped[Supplier] = relationship(back_populates="bids")


class AuctionEvent(Base):
    """The activity log: bids, extensions with their reason, and closes."""

    __tablename__ = "auction_events"
    __table_args__ = (
        CheckConstraint(
            "event_type <> 'TIME_EXTENDED' OR new_close_at > previous_close_at",
            name="extension_moves_later",
        ),
        Index("ix_auction_events_rfq_created", "rfq_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    rfq_id: Mapped[int] = mapped_column(ForeignKey("rfqs.id", ondelete="CASCADE"))
    event_type: Mapped[EventType] = mapped_column(str_enum(EventType, "event_type"))
    bid_id: Mapped[int | None] = mapped_column(ForeignKey("bids.id", ondelete="SET NULL"))
    supplier_id: Mapped[int | None] = mapped_column(
        ForeignKey("suppliers.id", ondelete="SET NULL")
    )

    previous_close_at: Mapped[datetime | None] = mapped_column(TimestampTZ)
    new_close_at: Mapped[datetime | None] = mapped_column(TimestampTZ)
    reason: Mapped[str] = mapped_column(Text)
    # Extra context, such as the ranking before and after a bid.
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    created_at: Mapped[datetime] = mapped_column(TimestampTZ, server_default=func.now())

    rfq: Mapped[Rfq] = relationship(back_populates="events")
