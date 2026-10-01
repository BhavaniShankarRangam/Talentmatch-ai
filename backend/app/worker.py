"""Standalone background worker: `python -m app.worker` (set TASK_MODE=worker on the API)."""
import logging
import signal
import time

from app.config import get_settings
from app.db import create_schema
from app.services.tasks import drain

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("talentmatch.worker")
_running = True


def _stop(*_):
    global _running
    _running = False


def main() -> None:
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    create_schema()
    poll = get_settings().worker_poll_seconds
    log.info("worker started")
    while _running:
        if drain(max_tasks=50) == 0:
            time.sleep(poll)
    log.info("worker stopped")


if __name__ == "__main__":
    main()
