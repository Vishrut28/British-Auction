"""The auction rules as plain functions: no database, no web framework.

Every rule here is written up in docs/auction-rules.md. The service layer loads
data, calls these functions, and writes the results.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from app.models import AuctionStatus, TriggerType


class BidRejected(Exception):
    """A bid broke a rule. The message is safe to show to the supplier."""


@dataclass(frozen=True)
class Standing:
    """One supplier's position: the price of their latest bid, and when they placed it."""

    supplier_id: int
    total: Decimal
    placed_at: datetime
    bid_id: int = 0


def rank(standings: Sequence[Standing]) -> list[Standing]:
    """L1 first. Lower price ranks higher; on a tie, whoever got there first ranks higher."""
    return sorted(standings, key=lambda s: (s.total, s.placed_at, s.bid_id))


def ranking_ids(standings: Sequence[Standing]) -> list[int]:
    return [s.supplier_id for s in rank(standings)]


def with_new_bid(standings: Sequence[Standing], new: Standing) -> list[Standing]:
    """The standings after `new` replaces that supplier's previous bid."""
    return [s for s in standings if s.supplier_id != new.supplier_id] + [new]


# --- Status ---------------------------------------------------------------------------


def compute_status(
    bid_start_at: datetime, current_close_at: datetime, forced_close_at: datetime, now: datetime
) -> AuctionStatus:
    if now < bid_start_at:
        return AuctionStatus.SCHEDULED
    if now < current_close_at:
        return AuctionStatus.ACTIVE
    if current_close_at >= forced_close_at:
        return AuctionStatus.FORCE_CLOSED
    return AuctionStatus.CLOSED


# --- Validation -----------------------------------------------------------------------


def validate_rfq_times(
    bid_start_at: datetime, bid_close_at: datetime, forced_close_at: datetime
) -> None:
    if bid_close_at <= bid_start_at:
        raise ValueError("Bid close time must be later than bid start time.")
    if forced_close_at <= bid_close_at:
        raise ValueError("Forced bid close time must be later than bid close time.")


def validate_bid(
    *,
    now: datetime,
    bid_start_at: datetime,
    current_close_at: datetime,
    total: Decimal,
    previous_total: Decimal | None,
) -> None:
    if now < bid_start_at:
        raise BidRejected("Bidding has not started yet.")
    if now >= current_close_at:
        raise BidRejected("Bidding is closed for this RFQ.")
    if total <= 0:
        raise BidRejected("Total charges must be greater than zero.")
    if previous_total is not None and total >= previous_total:
        raise BidRejected(
            f"A new bid must be lower than your previous bid of {previous_total:.2f}."
        )


# --- Triggers -------------------------------------------------------------------------


def in_trigger_window(bid_at: datetime, current_close_at: datetime, window_minutes: int) -> bool:
    return current_close_at - timedelta(minutes=window_minutes) <= bid_at < current_close_at


def ranks_changed(before: Sequence[int], after: Sequence[int]) -> list[int]:
    """Suppliers who were already ranked and now hold a different rank."""
    after_pos = {sid: i for i, sid in enumerate(after)}
    return [sid for i, sid in enumerate(before) if after_pos.get(sid) != i]


def l1_changed(before: Sequence[int], after: Sequence[int]) -> bool:
    """A new supplier took L1 from an existing one. The first bid ever does not count."""
    return bool(before) and before[0] != after[0]


def trigger_fired(trigger_type: TriggerType, before: Sequence[int], after: Sequence[int]) -> bool:
    if trigger_type is TriggerType.BID_RECEIVED:
        return True
    if trigger_type is TriggerType.ANY_RANK_CHANGE:
        return bool(ranks_changed(before, after))
    if trigger_type is TriggerType.L1_CHANGE:
        return l1_changed(before, after)
    raise ValueError(f"Unknown trigger type: {trigger_type}")


# --- Extension ------------------------------------------------------------------------


def extended_close(current_close_at: datetime, forced_close_at: datetime, minutes: int) -> datetime:
    """Add Y minutes to the close time, never past the forced close."""
    return min(current_close_at + timedelta(minutes=minutes), forced_close_at)


@dataclass(frozen=True)
class BidOutcome:
    ranking_before: list[int]
    ranking_after: list[int]
    in_window: bool
    triggered: bool
    previous_close_at: datetime
    new_close_at: datetime  # equal to previous_close_at when nothing moved
    reason: str | None  # set when a trigger fired; None otherwise

    @property
    def extended(self) -> bool:
        return self.new_close_at > self.previous_close_at

    @property
    def blocked(self) -> bool:
        """A trigger fired, but the auction was already at its forced close."""
        return self.triggered and not self.extended


def evaluate_bid(
    *,
    now: datetime,
    standings: Sequence[Standing],
    new: Standing,
    trigger_type: TriggerType | None,
    window_minutes: int | None,
    extension_minutes: int | None,
    current_close_at: datetime,
    forced_close_at: datetime,
    names: Mapping[int, str] | None = None,
) -> BidOutcome:
    """Decide whether an accepted bid extends the auction, and explain why.

    `trigger_type` is None for a plain RFQ (British auction option off): the
    bid is ranked as usual but never extends anything.
    """
    before = ranking_ids(standings)
    after = ranking_ids(with_new_bid(standings, new))
    if trigger_type is None or window_minutes is None or extension_minutes is None:
        return BidOutcome(before, after, False, False, current_close_at, current_close_at, None)

    in_window = in_trigger_window(now, current_close_at, window_minutes)
    triggered = in_window and trigger_fired(trigger_type, before, after)

    new_close = current_close_at
    reason = None
    if triggered:
        new_close = extended_close(current_close_at, forced_close_at, extension_minutes)
        cause = _describe_trigger(trigger_type, before, after, new.supplier_id, names or {})
        cause = f"{cause} within the last {window_minutes} min before close"
        capped = current_close_at + timedelta(minutes=extension_minutes) > forced_close_at
        if new_close == current_close_at:
            reason = (
                f"{cause}, but the auction is already at its forced close time, "
                "so it was not extended."
            )
        elif capped:
            added = _format_duration(new_close - current_close_at)
            reason = (
                f"{cause}. Extended by {added} instead of {extension_minutes} min, "
                "because the forced close time caps it."
            )
        else:
            reason = f"{cause}. Extended by {extension_minutes} min."

    return BidOutcome(
        ranking_before=before,
        ranking_after=after,
        in_window=in_window,
        triggered=triggered,
        previous_close_at=current_close_at,
        new_close_at=new_close,
        reason=reason,
    )


def _format_duration(delta: timedelta) -> str:
    minutes, seconds = divmod(int(delta.total_seconds()), 60)
    if not seconds:
        return f"{minutes} min"
    return f"{minutes} min {seconds} s" if minutes else f"{seconds} s"


def _describe_trigger(
    trigger_type: TriggerType,
    before: Sequence[int],
    after: Sequence[int],
    bidder: int,
    names: Mapping[int, str],
) -> str:
    def name(sid: int) -> str:
        return names.get(sid, f"Supplier #{sid}")

    if trigger_type is TriggerType.BID_RECEIVED:
        return f"Bid received from {name(bidder)}"
    if trigger_type is TriggerType.L1_CHANGE:
        return f"L1 changed from {name(before[0])} to {name(after[0])}"
    moved = ranks_changed(before, after)
    parts = [f"{name(sid)} L{before.index(sid) + 1}→L{after.index(sid) + 1}" for sid in moved]
    return f"Supplier ranking changed ({', '.join(parts)})"
