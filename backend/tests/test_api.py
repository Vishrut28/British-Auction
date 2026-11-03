"""End-to-end tests through the HTTP API and a real Postgres database."""

import threading
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app import services
from app.db import SessionLocal
from app.main import app
from app.schemas import BidCreate


def iso(hh: int, mm: int) -> str:
    return datetime(2026, 11, 3, hh, mm, tzinfo=UTC).isoformat().replace("+00:00", "Z")


def make_suppliers(client, *names):
    return [
        client.post("/api/suppliers", json={"name": n, "email": f"{n.lower().replace(' ', '')}@example.com"}).json()["id"]
        for n in names
    ]


def make_rfq(client, trigger="BID_RECEIVED", x=10, y=5, close=(18, 0), forced=(18, 30), ref="RFQ-001"):
    r = client.post(
        "/api/rfqs",
        json={
            "reference_id": ref,
            "name": "Mumbai to Delhi, 2 x 40ft",
            "pickup_date": "2026-11-10",
            "bid_start_at": iso(10, 0),
            "bid_close_at": iso(*close),
            "forced_close_at": iso(*forced),
            "trigger_window_minutes": x,
            "extension_minutes": y,
            "trigger_type": trigger,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def bid(client, rfq_id, supplier_id, total, carrier="Carrier"):
    return client.post(
        f"/api/rfqs/{rfq_id}/bids",
        json={
            "supplier_id": supplier_id,
            "carrier_name": carrier,
            "freight_charges": str(total - 300),
            "origin_charges": "100",
            "destination_charges": "200",
            "transit_time_days": 3,
            "quote_valid_until": "2026-12-31",
        },
    )


# --- RFQ creation and validation ------------------------------------------------------


def test_create_rfq_and_read_it_back(client, clock):
    rfq_id = make_rfq(client)
    d = client.get(f"/api/rfqs/{rfq_id}").json()
    assert d["status"] == "SCHEDULED"
    assert d["current_close_at"] == d["bid_close_at"]
    assert d["config"] == {"trigger_window_minutes": 10, "extension_minutes": 5, "trigger_type": "BID_RECEIVED"}
    assert [e["event_type"] for e in d["events"]] == ["RFQ_CREATED"]


def test_forced_close_must_be_after_bid_close(client):
    r = client.post(
        "/api/rfqs",
        json={
            "reference_id": "BAD", "name": "x", "pickup_date": "2026-11-10",
            "bid_start_at": iso(10, 0), "bid_close_at": iso(18, 0), "forced_close_at": iso(18, 0),
            "trigger_window_minutes": 10, "extension_minutes": 5, "trigger_type": "L1_CHANGE",
        },
    )
    assert r.status_code == 422
    assert "Forced bid close time must be later than bid close time" in r.text


def test_reference_id_is_unique(client):
    make_rfq(client)
    r = client.post(
        "/api/rfqs",
        json={
            "reference_id": "RFQ-001", "name": "x", "pickup_date": "2026-11-10",
            "bid_start_at": iso(10, 0), "bid_close_at": iso(18, 0), "forced_close_at": iso(18, 30),
            "trigger_window_minutes": 10, "extension_minutes": 5, "trigger_type": "L1_CHANGE",
        },
    )
    assert r.status_code == 409


# --- Bidding --------------------------------------------------------------------------


def test_bid_before_start_is_rejected(client, clock):
    (a,) = make_suppliers(client, "Supplier A")
    rfq_id = make_rfq(client)
    r = bid(client, rfq_id, a, 1000)
    assert r.status_code == 409 and "not started" in r.json()["detail"]


def test_ranking_and_bids_sorted_by_price(client, clock):
    a, b, c = make_suppliers(client, "Supplier A", "Supplier B", "Supplier C")
    rfq_id = make_rfq(client)
    clock.set(11, 0)
    assert bid(client, rfq_id, a, 1000).status_code == 201
    assert bid(client, rfq_id, b, 900).status_code == 201
    assert bid(client, rfq_id, c, 950).status_code == 201
    assert bid(client, rfq_id, a, 800).json()["rank"] == 1

    d = client.get(f"/api/rfqs/{rfq_id}").json()
    assert [(r["rank"], r["supplier_name"], r["total_amount"]) for r in d["ranking"]] == [
        (1, "Supplier A", "800.00"),
        (2, "Supplier B", "900.00"),
        (3, "Supplier C", "950.00"),
    ]
    assert [x["total_amount"] for x in d["bids"]] == ["800.00", "900.00", "950.00", "1000.00"]
    assert d["lowest_bid"] == "800.00" and d["bid_count"] == 4
    assert d["ranking"][0]["freight_charges"] == "500.00"  # quote details are returned


def test_supplier_must_lower_own_bid(client, clock):
    (a,) = make_suppliers(client, "Supplier A")
    rfq_id = make_rfq(client)
    clock.set(11, 0)
    bid(client, rfq_id, a, 1000)
    r = bid(client, rfq_id, a, 1000)
    assert r.status_code == 409 and "lower than your previous bid" in r.json()["detail"]


def test_negative_charge_is_rejected(client, clock):
    (a,) = make_suppliers(client, "Supplier A")
    rfq_id = make_rfq(client)
    clock.set(11, 0)
    r = bid(client, rfq_id, a, 200)  # freight = 200 - 300 = -100
    assert r.status_code == 422


# --- Extensions -----------------------------------------------------------------------


def test_bid_in_window_extends_and_logs_reason(client, clock):
    (a,) = make_suppliers(client, "Supplier A")
    rfq_id = make_rfq(client, trigger="BID_RECEIVED")
    clock.set(17, 55)
    r = bid(client, rfq_id, a, 1000).json()
    assert r["extended"] and r["current_close_at"] == iso(18, 5)

    d = client.get(f"/api/rfqs/{rfq_id}").json()
    assert d["current_close_at"] == iso(18, 5) and d["bid_close_at"] == iso(18, 0)
    assert d["extension_count"] == 1
    ext = [e for e in d["events"] if e["event_type"] == "TIME_EXTENDED"]
    assert len(ext) == 1
    assert ext[0]["previous_close_at"] == iso(18, 0) and ext[0]["new_close_at"] == iso(18, 5)
    assert "Bid received from Supplier A" in ext[0]["reason"]


def test_bid_outside_window_does_not_extend(client, clock):
    (a,) = make_suppliers(client, "Supplier A")
    rfq_id = make_rfq(client)
    clock.set(17, 49)
    assert bid(client, rfq_id, a, 1000).json()["extended"] is False


def test_l1_trigger_ignores_bids_that_keep_l1(client, clock):
    a, b = make_suppliers(client, "Supplier A", "Supplier B")
    rfq_id = make_rfq(client, trigger="L1_CHANGE")
    clock.set(11, 0)
    bid(client, rfq_id, a, 800)
    clock.set(17, 58)
    assert bid(client, rfq_id, b, 900).json()["extended"] is False  # B is L2
    r = bid(client, rfq_id, b, 700).json()  # B takes L1
    assert r["extended"] and "L1 changed from Supplier A to Supplier B" in r["reason"]


def test_extensions_stop_at_forced_close_then_force_close(client, clock):
    a, b = make_suppliers(client, "Supplier A", "Supplier B")
    rfq_id = make_rfq(client, trigger="BID_RECEIVED", y=10, forced=(18, 15))
    clock.set(17, 55)
    assert bid(client, rfq_id, a, 1000).json()["current_close_at"] == iso(18, 10)
    clock.set(18, 5)
    r = bid(client, rfq_id, b, 900).json()
    assert r["current_close_at"] == iso(18, 15)  # capped, not 18:20
    assert "instead of 10 min" in r["reason"]
    clock.set(18, 10)
    r = bid(client, rfq_id, a, 800).json()
    assert r["extended"] is False and r["extension_blocked"] is True

    clock.set(18, 15)
    assert bid(client, rfq_id, b, 700).status_code == 409  # forced close: no more bids

    d = client.get(f"/api/rfqs/{rfq_id}").json()
    assert d["status"] == "FORCE_CLOSED"
    types = [e["event_type"] for e in d["events"]]
    assert types.count("TIME_EXTENDED") == 2
    assert types.count("EXTENSION_BLOCKED") == 1
    assert types[-1] == "AUCTION_FORCE_CLOSED"
    assert "L1: Supplier A at 800.00" in d["events"][-1]["reason"]


def test_close_without_extension_is_closed_not_force_closed(client, clock):
    (a,) = make_suppliers(client, "Supplier A")
    rfq_id = make_rfq(client)
    clock.set(11, 0)
    bid(client, rfq_id, a, 1000)
    clock.set(18, 0)
    listing = client.get("/api/rfqs").json()["items"]
    assert listing[0]["status"] == "CLOSED"
    assert listing[0]["lowest_bid"] == "1000.00"
    events = client.get(f"/api/rfqs/{rfq_id}/events").json()
    assert [e["event_type"] for e in events].count("AUCTION_CLOSED") == 1
    client.get(f"/api/rfqs/{rfq_id}")  # a second read must not log the close twice
    events = client.get(f"/api/rfqs/{rfq_id}/events").json()
    assert [e["event_type"] for e in events].count("AUCTION_CLOSED") == 1


# --- Concurrency ----------------------------------------------------------------------


@pytest.mark.parametrize("round_", range(3))
def test_simultaneous_bids_each_see_the_latest_close_time(client, clock, round_):
    """Two bids in the window at the same moment must extend twice, not once.

    Without the row lock both would read 18:00 and both would write 18:05.
    """
    a, b = make_suppliers(client, "Supplier A", "Supplier B")
    rfq_id = make_rfq(client, trigger="BID_RECEIVED")
    now = datetime(2026, 11, 3, 17, 58, tzinfo=UTC)
    barrier = threading.Barrier(2)
    errors = []

    def place(supplier_id, total):
        db = SessionLocal()
        try:
            barrier.wait()
            services.place_bid(
                db,
                rfq_id,
                BidCreate(
                    supplier_id=supplier_id, carrier_name="C", freight_charges=total,
                    origin_charges=0, destination_charges=0, transit_time_days=2,
                    quote_valid_until="2026-12-31",
                ),
                now,
            )
        except Exception as exc:  # pragma: no cover - reported below
            errors.append(exc)
        finally:
            db.close()

    threads = [threading.Thread(target=place, args=(a, 1000)), threading.Thread(target=place, args=(b, 900))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors

    clock.now = now
    d = client.get(f"/api/rfqs/{rfq_id}").json()
    assert d["extension_count"] == 2
    assert d["current_close_at"] == iso(18, 10)
    ext = [e for e in d["events"] if e["event_type"] == "TIME_EXTENDED"]
    assert [(e["previous_close_at"], e["new_close_at"]) for e in ext] == [
        (iso(18, 0), iso(18, 5)),
        (iso(18, 5), iso(18, 10)),
    ]


def test_openapi_lists_the_endpoints():
    paths = TestClient(app).get("/openapi.json").json()["paths"]
    assert {"/api/rfqs", "/api/rfqs/{rfq_id}", "/api/rfqs/{rfq_id}/bids", "/api/suppliers"} <= set(paths)
