"""Demo data: a few suppliers, and with --demo a live auction that already has bids.

    python -m app.seed           # suppliers only
    python -m app.seed --demo    # suppliers + an auction closing in about 6 minutes

Safe to run more than once.
"""

import argparse
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select

from app import services
from app.clock import get_now
from app.db import SessionLocal
from app.models import Rfq, Supplier, TriggerType
from app.schemas import BidCreate, RfqCreate

SUPPLIERS = [
    ("Apex Logistics", "bids@apex-logistics.example"),
    ("BlueLine Carriers", "quotes@blueline.example"),
    ("Coastal Freight Co", "rfq@coastalfreight.example"),
    ("Delta Movers", "sales@deltamovers.example"),
]


def seed_suppliers(db) -> dict[str, int]:
    existing = {s.email: s for s in db.scalars(select(Supplier))}
    for name, email in SUPPLIERS:
        if email not in existing:
            db.add(Supplier(name=name, email=email))
    db.commit()
    return {s.name: s.id for s in db.scalars(select(Supplier))}


def seed_demo_auction(db, ids: dict[str, int]) -> Rfq:
    now = get_now().replace(microsecond=0)
    start = now - timedelta(minutes=30)
    ref = f"RFQ-DEMO-{now:%H%M%S}"
    rfq = services.create_rfq(
        db,
        RfqCreate(
            reference_id=ref,
            name="Mumbai → Delhi, 2 × 40ft containers",
            pickup_date=date.today() + timedelta(days=5),
            bid_start_at=start,
            bid_close_at=now + timedelta(minutes=6),
            forced_close_at=now + timedelta(minutes=15),
            trigger_window_minutes=5,
            extension_minutes=2,
            trigger_type=TriggerType.ANY_RANK_CHANGE,
        ),
        start,
    )
    valid = date.today() + timedelta(days=30)
    opening = [
        ("Apex Logistics", "Apex Road Lines", "82000", "4500", "5200", 4, 25),
        ("BlueLine Carriers", "BlueLine Express", "79500", "5000", "6000", 3, 20),
        ("Coastal Freight Co", "Coastal Haulage", "84000", "3800", "4100", 5, 15),
        ("BlueLine Carriers", "BlueLine Express", "77000", "5000", "6000", 3, 10),
    ]
    for supplier, carrier, freight, origin, dest, transit, minutes_ago in opening:
        services.place_bid(
            db,
            rfq.id,
            BidCreate(
                supplier_id=ids[supplier],
                carrier_name=carrier,
                freight_charges=Decimal(freight),
                origin_charges=Decimal(origin),
                destination_charges=Decimal(dest),
                transit_time_days=transit,
                quote_valid_until=valid,
            ),
            now - timedelta(minutes=minutes_ago),
        )
    return rfq


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--demo", action="store_true", help="also create a live demo auction")
    args = parser.parse_args()
    with SessionLocal() as db:
        ids = seed_suppliers(db)
        print(f"Suppliers: {', '.join(ids)}")
        if args.demo:
            rfq = seed_demo_auction(db, ids)
            close = f"{rfq.current_close_at:%H:%M:%S} UTC"
            print(f"Demo auction {rfq.reference_id} (id {rfq.id}) closes at {close}")


if __name__ == "__main__":
    main()
