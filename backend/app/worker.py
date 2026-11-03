"""Background jobs: Celery, with Redis as the broker.

Celery beat runs `close_due_auctions` every few seconds. It marks auctions
whose time is up as Closed or Force Closed and writes the close to the activity
log, so an auction closes on time even if nobody has its page open.

Run a worker with beat built in:

    celery -A app.worker worker --beat --loglevel=info
    # on Windows add: --pool=solo

The API stays correct without the worker: status is always computed from the
close times, and reads run the same sweep for the auction they show.
"""

from celery import Celery

from app.clock import get_now
from app.config import settings
from app.db import SessionLocal
from app.services import sync_statuses

celery_app = Celery("british_auction", broker=settings.redis_url)
celery_app.conf.update(
    timezone="UTC",
    task_ignore_result=True,
    # A sweep that misses its slot is simply replaced by the next one.
    task_acks_late=False,
    beat_schedule={
        "close-due-auctions": {
            "task": "app.worker.close_due_auctions",
            "schedule": settings.close_sweep_seconds,
            "options": {"expires": settings.close_sweep_seconds},
        },
    },
)


@celery_app.task(name="app.worker.close_due_auctions")
def close_due_auctions() -> int:
    """Close every auction whose close time has passed. Returns how many closed."""
    with SessionLocal() as db:
        return sync_statuses(db, get_now())
