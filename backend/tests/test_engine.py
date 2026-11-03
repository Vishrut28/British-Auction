"""Unit tests for the auction rules. Each rule maps to a section of
docs/auction-rules.md; the brief's own examples are reproduced as tests."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.engine import (
    BidRejected,
    Standing,
    compute_status,
    evaluate_bid,
    extended_close,
    in_trigger_window,
    l1_changed,
    ranking_ids,
    ranks_changed,
    trigger_fired,
    validate_bid,
    validate_rfq_times,
)
from app.models import AuctionStatus, TriggerType

A, B, C, D = 1, 2, 3, 4
NAMES = {A: "Supplier A", B: "Supplier B", C: "Supplier C", D: "Supplier D"}


def at(hh: int, mm: int, ss: int = 0) -> datetime:
    return datetime(2026, 11, 3, hh, mm, ss, tzinfo=UTC)


CLOSE = at(18, 0)  # brief: Bid Close Time 6:00 PM
FORCED = at(18, 30)
START = at(10, 0)


def s(supplier: int, total: str, placed: datetime, bid_id: int = 0) -> Standing:
    return Standing(supplier, Decimal(total), placed, bid_id)


def evaluate(standings, new, trigger, now, close=CLOSE, forced=FORCED, x=10, y=5):
    return evaluate_bid(
        now=now,
        standings=standings,
        new=new,
        trigger_type=trigger,
        window_minutes=x,
        extension_minutes=y,
        current_close_at=close,
        forced_close_at=forced,
        names=NAMES,
    )


# --- Ranking --------------------------------------------------------------------------


def test_lowest_total_is_l1():
    standings = [s(A, "500", at(11, 0)), s(B, "300", at(11, 5)), s(C, "400", at(11, 1))]
    assert ranking_ids(standings) == [B, C, A]


def test_tie_goes_to_whoever_reached_the_price_first():
    standings = [s(A, "300", at(11, 5)), s(B, "300", at(11, 0))]
    assert ranking_ids(standings) == [B, A]


# --- RFQ validation (brief section 7) -------------------------------------------------


def test_forced_close_must_be_after_bid_close():
    with pytest.raises(ValueError, match="Forced bid close"):
        validate_rfq_times(START, CLOSE, CLOSE)
    with pytest.raises(ValueError, match="Forced bid close"):
        validate_rfq_times(START, CLOSE, CLOSE - timedelta(minutes=1))
    validate_rfq_times(START, CLOSE, FORCED)


def test_close_must_be_after_start():
    with pytest.raises(ValueError, match="later than bid start"):
        validate_rfq_times(CLOSE, CLOSE, FORCED)


# --- Bid validation -------------------------------------------------------------------


def _validate(now, total, previous=None, close=CLOSE):
    validate_bid(
        now=now,
        bid_start_at=START,
        current_close_at=close,
        total=Decimal(total),
        previous_total=None if previous is None else Decimal(previous),
    )


def test_bid_before_start_is_rejected():
    with pytest.raises(BidRejected, match="not started"):
        _validate(at(9, 59), "100")


def test_bid_at_exact_close_is_rejected():
    with pytest.raises(BidRejected, match="closed"):
        _validate(CLOSE, "100")


def test_bid_at_extended_close_time_is_accepted_until_the_new_close():
    _validate(at(18, 3), "100", close=at(18, 5))


def test_supplier_must_lower_their_own_price():
    with pytest.raises(BidRejected, match="lower than your previous bid"):
        _validate(at(12, 0), "500", previous="500")
    _validate(at(12, 0), "499.99", previous="500")


def test_zero_total_is_rejected():
    with pytest.raises(BidRejected, match="greater than zero"):
        _validate(at(12, 0), "0")


# --- Trigger window (brief 6.1) -------------------------------------------------------


def test_window_is_last_x_minutes_before_close():
    # brief: close 6:00 PM, X = 10 -> monitors 5:50 PM to 6:00 PM
    assert not in_trigger_window(at(17, 49, 59), CLOSE, 10)
    assert in_trigger_window(at(17, 50), CLOSE, 10)
    assert in_trigger_window(at(17, 59, 59), CLOSE, 10)
    assert not in_trigger_window(CLOSE, CLOSE, 10)


def test_window_moves_with_the_extended_close():
    extended = at(18, 5)
    assert not in_trigger_window(at(17, 54), extended, 10)
    assert in_trigger_window(at(17, 55), extended, 10)


# --- Extension (brief 6.2) and the forced-close cap (brief section 7) ------------------


def test_extension_adds_y_to_the_close_time():
    # brief: Y = 5 -> 6:00 PM becomes 6:05 PM
    assert extended_close(CLOSE, FORCED, 5) == at(18, 5)


def test_extension_never_passes_forced_close():
    assert extended_close(at(18, 28), FORCED, 5) == FORCED
    assert extended_close(FORCED, FORCED, 5) == FORCED


# --- Rank comparisons -----------------------------------------------------------------


def test_ranks_changed_ignores_a_new_entrant_in_last_place():
    assert ranks_changed([A, B], [A, B, C]) == []


def test_ranks_changed_reports_suppliers_pushed_down():
    assert ranks_changed([A, B], [C, A, B]) == [A, B]


def test_l1_change_needs_an_existing_l1():
    assert not l1_changed([], [A])
    assert l1_changed([A, B], [B, A])
    assert not l1_changed([A, B], [A, C, B])


# --- Trigger types (brief 6.3) --------------------------------------------------------


def test_bid_received_trigger_extends_on_any_bid_in_window():
    # brief 6.3a: X = 10, bid at 5:55 PM -> extends by Y
    out = evaluate([s(A, "500", at(12, 0))], s(B, "900", at(17, 55)), TriggerType.BID_RECEIVED, at(17, 55))
    assert out.triggered and out.new_close_at == at(18, 5)
    assert "Bid received from Supplier B" in out.reason


def test_bid_outside_window_never_extends():
    for trigger in TriggerType:
        out = evaluate([s(A, "500", at(12, 0))], s(B, "100", at(17, 49)), trigger, at(17, 49))
        assert not out.triggered and out.new_close_at == CLOSE and out.reason is None


def test_rank_change_trigger_extends_when_underbid():
    # brief 6.3b: Supplier B underbids Supplier A at 5:58 PM -> extends by Y
    standings = [s(A, "400", at(12, 0)), s(B, "500", at(12, 1))]
    out = evaluate(standings, s(B, "350", at(17, 58)), TriggerType.ANY_RANK_CHANGE, at(17, 58))
    assert out.ranking_before == [A, B] and out.ranking_after == [B, A]
    assert out.triggered and out.new_close_at == at(18, 5)
    assert "Supplier A L1→L2" in out.reason


def test_rank_change_trigger_ignores_a_bid_that_moves_nobody():
    standings = [s(A, "400", at(12, 0)), s(B, "500", at(12, 1))]
    out = evaluate(standings, s(B, "450", at(17, 58)), TriggerType.ANY_RANK_CHANGE, at(17, 58))
    assert not out.triggered and out.new_close_at == CLOSE


def test_rank_change_trigger_fires_when_middle_ranks_swap():
    standings = [s(A, "100", at(12, 0)), s(B, "400", at(12, 1)), s(C, "500", at(12, 2))]
    out = evaluate(standings, s(C, "300", at(17, 58)), TriggerType.ANY_RANK_CHANGE, at(17, 58))
    assert out.triggered
    assert not trigger_fired(TriggerType.L1_CHANGE, out.ranking_before, out.ranking_after)


def test_l1_trigger_extends_only_when_lowest_bidder_changes():
    # brief 6.3c: Supplier C becomes the new lowest bidder at 5:59 PM -> extends by Y
    standings = [s(A, "400", at(12, 0)), s(B, "500", at(12, 1))]
    out = evaluate(standings, s(C, "390", at(17, 59)), TriggerType.L1_CHANGE, at(17, 59))
    assert out.triggered and out.new_close_at == at(18, 5)
    assert "L1 changed from Supplier A to Supplier C" in out.reason

    not_l1 = evaluate(standings, s(C, "450", at(17, 59)), TriggerType.L1_CHANGE, at(17, 59))
    assert not not_l1.triggered


def test_first_bid_only_triggers_bid_received():
    first = s(A, "500", at(17, 55))
    fired = {t: evaluate([], first, t, at(17, 55)).triggered for t in TriggerType}
    assert fired == {
        TriggerType.BID_RECEIVED: True,
        TriggerType.ANY_RANK_CHANGE: False,
        TriggerType.L1_CHANGE: False,
    }


def test_trigger_types_nest():
    """Every L1 change is a rank change, and every rank change is a bid received."""
    import random

    rng = random.Random(7)
    for _ in range(2000):
        n = rng.randint(0, 4)
        standings = [s(i + 1, str(rng.randint(1, 9) * 100), at(12, i)) for i in range(n)]
        new = s(rng.randint(1, 5), str(rng.randint(1, 9) * 100), at(17, 58))
        before = ranking_ids(standings)
        after = ranking_ids([x for x in standings if x.supplier_id != new.supplier_id] + [new])
        l1 = trigger_fired(TriggerType.L1_CHANGE, before, after)
        anyr = trigger_fired(TriggerType.ANY_RANK_CHANGE, before, after)
        assert not l1 or anyr
        assert not anyr or trigger_fired(TriggerType.BID_RECEIVED, before, after)


def test_extension_is_capped_and_says_so():
    out = evaluate([], s(A, "500", at(18, 27)), TriggerType.BID_RECEIVED, at(18, 27), close=at(18, 28))
    assert out.new_close_at == FORCED
    assert "Extended by 2 min instead of 5 min" in out.reason


def test_trigger_at_forced_close_is_blocked_and_logged():
    out = evaluate([], s(A, "500", at(18, 25)), TriggerType.BID_RECEIVED, at(18, 25), close=FORCED)
    assert out.triggered and out.blocked and not out.extended
    assert out.new_close_at == FORCED
    assert "not extended" in out.reason


def test_repeated_extensions_stop_at_forced_close():
    close = CLOSE
    for minute in range(55, 90, 3):  # a bid every 3 minutes from 5:55 PM
        now = at(17, 0) + timedelta(minutes=minute)
        if now >= close:
            break
        close = evaluate([], s(A, "1", now), TriggerType.BID_RECEIVED, now, close=close).new_close_at
        assert close <= FORCED
    assert close == FORCED


# --- Status ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("now", "close", "expected"),
    [
        (at(9, 0), CLOSE, AuctionStatus.SCHEDULED),
        (START, CLOSE, AuctionStatus.ACTIVE),
        (at(17, 59), CLOSE, AuctionStatus.ACTIVE),
        (CLOSE, CLOSE, AuctionStatus.CLOSED),
        (at(18, 10), at(18, 5), AuctionStatus.CLOSED),
        (FORCED, FORCED, AuctionStatus.FORCE_CLOSED),
    ],
)
def test_status(now, close, expected):
    assert compute_status(START, close, FORCED, now) == expected
