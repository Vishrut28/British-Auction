"""Database work for the API and the closing job. Rules come from app.engine."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import engine as rules
from app.models import AuctionEvent, AuctionStatus, Bid, EventType, Rfq, Supplier, TriggerType
from app.schemas import BidCreate, RfqCreate, SupplierCreate


class NotFound(Exception):
    pass


class Conflict(Exception):
    pass


OPEN_STATUSES = (AuctionStatus.SCHEDULED, AuctionStatus.ACTIVE)

TRIGGER_DESCRIPTION = {
    TriggerType.BID_RECEIVED: "any bid received",
    TriggerType.ANY_RANK_CHANGE: "any supplier rank change",
    TriggerType.L1_CHANGE: "lowest bidder (L1) change",
}


# --- Suppliers ------------------------------------------------------------------------


def create_supplier(db: Session, data: SupplierCreate) -> Supplier:
    supplier = Supplier(name=data.name, email=data.email.lower())
    db.add(supplier)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise Conflict(f"A supplier with email {data.email} already exists.") from None
    return supplier


def list_suppliers(db: Session) -> list[Supplier]:
    return list(db.scalars(select(Supplier).order_by(Supplier.name)))


# --- RFQs -----------------------------------------------------------------------------


def create_rfq(db: Session, data: RfqCreate, now: datetime) -> Rfq:
    if data.bid_close_at <= now:
        raise ValueError("Bid close time must be in the future.")
    rfq = Rfq(
        reference_id=data.reference_id.strip(),
        name=data.name.strip(),
        pickup_date=data.pickup_date,
        bid_start_at=data.bid_start_at,
        bid_close_at=data.bid_close_at,
        current_close_at=data.bid_close_at,
        forced_close_at=data.forced_close_at,
        trigger_window_minutes=data.trigger_window_minutes,
        extension_minutes=data.extension_minutes,
        trigger_type=data.trigger_type,
        status=rules.compute_status(data.bid_start_at, data.bid_close_at, data.forced_close_at, now),
        extension_count=0,
    )
    db.add(rfq)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise Conflict(f"RFQ reference {data.reference_id} is already in use.") from None
    db.add(
        AuctionEvent(
            rfq_id=rfq.id,
            event_type=EventType.RFQ_CREATED,
            new_close_at=rfq.current_close_at,
            reason=(
                f"British auction created. Extends by Y = {data.extension_minutes} min on "
                f"{TRIGGER_DESCRIPTION[data.trigger_type]} in the last "
                f"X = {data.trigger_window_minutes} min before close."
            ),
            created_at=now,
        )
    )
    db.commit()
    return rfq


def get_rfq(db: Session, rfq_id: int, *, lock: bool = False) -> Rfq:
    stmt = select(Rfq).where(Rfq.id == rfq_id)
    if lock:
        stmt = stmt.with_for_update()
    rfq = db.scalar(stmt)
    if rfq is None:
        raise NotFound(f"RFQ {rfq_id} not found.")
    return rfq


def status_of(rfq: Rfq, now: datetime) -> AuctionStatus:
    """Always computed from the times; the stored status is only a cache."""
    return rules.compute_status(rfq.bid_start_at, rfq.current_close_at, rfq.forced_close_at, now)


def list_rfqs(db: Session, now: datetime) -> list[dict]:
    stats = (
        select(
            Bid.rfq_id,
            func.min(Bid.total_amount).label("lowest_bid"),
            func.count(Bid.id).label("bid_count"),
            func.count(func.distinct(Bid.supplier_id)).label("supplier_count"),
        )
        .group_by(Bid.rfq_id)
        .subquery()
    )
    rows = db.execute(
        select(Rfq, stats.c.lowest_bid, stats.c.bid_count, stats.c.supplier_count)
        .outerjoin(stats, stats.c.rfq_id == Rfq.id)
        .order_by(Rfq.created_at.desc(), Rfq.id.desc())
    ).all()
    # Every supplier's latest bid is also their lowest, so the overall minimum
    # is the current L1 price.
    return [
        _summary(rfq, now, lowest, bid_count or 0, supplier_count or 0)
        for rfq, lowest, bid_count, supplier_count in rows
    ]


def _summary(rfq: Rfq, now: datetime, lowest, bid_count: int, supplier_count: int) -> dict:
    return {
        "id": rfq.id,
        "reference_id": rfq.reference_id,
        "name": rfq.name,
        "pickup_date": rfq.pickup_date,
        "bid_start_at": rfq.bid_start_at,
        "bid_close_at": rfq.bid_close_at,
        "current_close_at": rfq.current_close_at,
        "forced_close_at": rfq.forced_close_at,
        "status": status_of(rfq, now),
        "lowest_bid": lowest,
        "bid_count": bid_count,
        "supplier_count": supplier_count,
        "extension_count": rfq.extension_count,
        "trigger_type": rfq.trigger_type,
    }


def _latest_bids(db: Session, rfq_id: int) -> list[Bid]:
    """Each supplier's latest bid on the RFQ."""
    return list(
        db.scalars(
            select(Bid)
            .where(Bid.rfq_id == rfq_id)
            .ext(distinct_on(Bid.supplier_id))
            .order_by(Bid.supplier_id, Bid.created_at.desc(), Bid.id.desc())
        )
    )


def _standing(bid: Bid) -> rules.Standing:
    return rules.Standing(bid.supplier_id, bid.total_amount, bid.created_at, bid.id)


def _bid_out(bid: Bid, names: dict[int, str]) -> dict:
    return {
        "id": bid.id,
        "supplier_id": bid.supplier_id,
        "supplier_name": names.get(bid.supplier_id, f"Supplier #{bid.supplier_id}"),
        "carrier_name": bid.carrier_name,
        "freight_charges": bid.freight_charges,
        "origin_charges": bid.origin_charges,
        "destination_charges": bid.destination_charges,
        "total_amount": bid.total_amount,
        "transit_time_days": bid.transit_time_days,
        "quote_valid_until": bid.quote_valid_until,
        "created_at": bid.created_at,
    }


def _names(db: Session) -> dict[int, str]:
    return dict(db.execute(select(Supplier.id, Supplier.name)).all())


def rfq_detail(db: Session, rfq_id: int, now: datetime) -> dict:
    rfq = get_rfq(db, rfq_id)
    names = _names(db)
    latest = {b.id: b for b in _latest_bids(db, rfq_id)}
    ranked = rules.rank([_standing(b) for b in latest.values()])
    ranking = [
        {**_bid_out(latest[s.bid_id], names), "rank": i + 1} for i, s in enumerate(ranked)
    ]
    bids = list(
        db.scalars(
            select(Bid)
            .where(Bid.rfq_id == rfq_id)
            .order_by(Bid.total_amount, Bid.created_at, Bid.id)
        )
    )
    events = list(
        db.scalars(
            select(AuctionEvent)
            .where(AuctionEvent.rfq_id == rfq_id)
            .order_by(AuctionEvent.created_at, AuctionEvent.id)
        )
    )
    lowest = ranking[0]["total_amount"] if ranking else None
    return {
        **_summary(rfq, now, lowest, len(bids), len(ranking)),
        "server_time": now,
        "config": {
            "trigger_window_minutes": rfq.trigger_window_minutes,
            "extension_minutes": rfq.extension_minutes,
            "trigger_type": rfq.trigger_type,
        },
        "ranking": ranking,
        "bids": [_bid_out(b, names) for b in bids],
        "events": events,
    }


# --- Bidding --------------------------------------------------------------------------


def place_bid(db: Session, rfq_id: int, data: BidCreate, now: datetime) -> dict:
    """Validate, rank, extend if triggered, and write it all in one transaction.

    The RFQ row stays locked until commit, so bids on the same RFQ are applied
    one at a time and each sees the close time the previous one left.
    """
    rfq = get_rfq(db, rfq_id, lock=True)
    supplier = db.get(Supplier, data.supplier_id)
    if supplier is None:
        raise NotFound(f"Supplier {data.supplier_id} not found.")

    if data.quote_valid_until < now.date():
        raise rules.BidRejected("Quote validity date cannot be in the past.")

    latest = _latest_bids(db, rfq_id)
    previous = next((b for b in latest if b.supplier_id == supplier.id), None)
    total = data.freight_charges + data.origin_charges + data.destination_charges
    rules.validate_bid(
        now=now,
        bid_start_at=rfq.bid_start_at,
        current_close_at=rfq.current_close_at,
        total=total,
        previous_total=previous.total_amount if previous else None,
    )

    names = _names(db)
    outcome = rules.evaluate_bid(
        now=now,
        standings=[_standing(b) for b in latest],
        new=rules.Standing(supplier.id, total, now, bid_id=2**62),  # placed last: ties go to others
        trigger_type=rfq.trigger_type,
        window_minutes=rfq.trigger_window_minutes,
        extension_minutes=rfq.extension_minutes,
        current_close_at=rfq.current_close_at,
        forced_close_at=rfq.forced_close_at,
        names=names,
    )

    bid = Bid(
        rfq_id=rfq.id,
        supplier_id=supplier.id,
        carrier_name=data.carrier_name.strip(),
        freight_charges=data.freight_charges,
        origin_charges=data.origin_charges,
        destination_charges=data.destination_charges,
        transit_time_days=data.transit_time_days,
        quote_valid_until=data.quote_valid_until,
        created_at=now,
    )
    db.add(bid)
    db.flush()  # assigns bid.id and the generated total

    rank = outcome.ranking_after.index(supplier.id) + 1
    ranking_details = {
        "ranking_before": [_label(names, sid) for sid in outcome.ranking_before],
        "ranking_after": [_label(names, sid) for sid in outcome.ranking_after],
    }
    db.add(
        AuctionEvent(
            rfq_id=rfq.id,
            event_type=EventType.BID_PLACED,
            bid_id=bid.id,
            supplier_id=supplier.id,
            reason=(
                f"{supplier.name} bid {_money(total)}"
                + (f" (was {_money(previous.total_amount)})" if previous else "")
                + f" and is now L{rank}."
            ),
            details={"total": str(total), "rank": rank, **ranking_details},
            created_at=now,
        )
    )

    if outcome.extended or outcome.blocked:
        db.add(
            AuctionEvent(
                rfq_id=rfq.id,
                event_type=EventType.TIME_EXTENDED if outcome.extended else EventType.EXTENSION_BLOCKED,
                bid_id=bid.id,
                supplier_id=supplier.id,
                previous_close_at=outcome.previous_close_at,
                new_close_at=outcome.new_close_at,
                reason=outcome.reason,
                details={"trigger_type": rfq.trigger_type.value, **ranking_details},
                created_at=now,
            )
        )
    if outcome.extended:
        rfq.current_close_at = outcome.new_close_at
        rfq.extension_count += 1
    rfq.status = status_of(rfq, now)
    db.commit()

    return {
        "bid": _bid_out(bid, names),
        "rank": rank,
        "extended": outcome.extended,
        "extension_blocked": outcome.blocked,
        "previous_close_at": outcome.previous_close_at,
        "current_close_at": rfq.current_close_at,
        "reason": outcome.reason,
    }


def _label(names: dict[int, str], sid: int) -> str:
    return names.get(sid, f"Supplier #{sid}")


def _money(amount: Decimal) -> str:
    return f"{amount:,.2f}"


# --- Closing --------------------------------------------------------------------------


def sync_statuses(db: Session, now: datetime, rfq_id: int | None = None) -> int:
    """Bring the cached status up to date, and log each auction's close once.

    Run by the background job, and before reads so the activity log is
    complete even when the job is not running. Safe to run repeatedly or
    concurrently: rows are locked, and rows another worker holds are skipped.
    Returns how many auctions were closed.
    """
    stmt = (
        select(Rfq)
        .where(Rfq.status.in_(OPEN_STATUSES))
        # Only rows whose status is due to change, so live auctions stay unlocked.
        .where(
            ((Rfq.status == AuctionStatus.SCHEDULED) & (Rfq.bid_start_at <= now))
            | (Rfq.current_close_at <= now)
        )
        .order_by(Rfq.id)
        .with_for_update(skip_locked=True)
    )
    if rfq_id is not None:
        stmt = stmt.where(Rfq.id == rfq_id)

    closed = 0
    names: dict[int, str] | None = None
    for rfq in db.scalars(stmt):
        status = status_of(rfq, now)
        if status == rfq.status:
            continue
        rfq.status = status
        if status in (AuctionStatus.CLOSED, AuctionStatus.FORCE_CLOSED):
            names = names if names is not None else _names(db)
            db.add(_close_event(db, rfq, status, names))
            closed += 1
    db.commit()
    return closed


def _close_event(db: Session, rfq: Rfq, status: AuctionStatus, names: dict[int, str]) -> AuctionEvent:
    ranked = rules.rank([_standing(b) for b in _latest_bids(db, rfq.id)])
    if ranked:
        winner = ranked[0]
        result = f"L1: {_label(names, winner.supplier_id)} at {_money(winner.total)}."
    else:
        result = "No bids were received."
    extended = (
        f" after {rfq.extension_count} extension{'s' if rfq.extension_count != 1 else ''}"
        if rfq.extension_count
        else ""
    )
    if status is AuctionStatus.FORCE_CLOSED:
        event_type = EventType.AUCTION_FORCE_CLOSED
        reason = f"Auction reached its forced close time{extended} and was force closed. {result}"
    else:
        event_type = EventType.AUCTION_CLOSED
        reason = f"Auction closed{extended}. {result}"
    return AuctionEvent(
        rfq_id=rfq.id,
        event_type=event_type,
        supplier_id=ranked[0].supplier_id if ranked else None,
        new_close_at=rfq.current_close_at,
        reason=reason,
        created_at=rfq.current_close_at,  # logged at the moment it closed
    )
