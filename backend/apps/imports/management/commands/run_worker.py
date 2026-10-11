"""Background worker: queued employee imports and share-expiry notifications.

A small database-backed loop instead of a message broker: the work is low-volume and already lives in
PostgreSQL. Several workers can run side by side (jobs are claimed with SELECT ... FOR UPDATE SKIP LOCKED).

    manage.py run_worker            # loop until SIGTERM / Ctrl+C
    manage.py run_worker --once     # one pass (cron-style)
"""

import logging
import signal
import time

from django.core.management.base import BaseCommand
from django.db import close_old_connections, connection

from apps.imports.services import run_queued
from apps.sharing.services import process_expiry

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Process queued imports and share-expiry notifications."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Run a single pass and exit.")
        parser.add_argument("--interval", type=float, default=5.0, help="Seconds between passes.")

    def handle(self, *args, once, interval, **options):
        stopping = {"now": False}

        def stop(signum, frame):
            stopping["now"] = True

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        self.stdout.write("Worker started.")
        while True:
            if not connection.in_atomic_block:  # never inside a caller's transaction (e.g. tests)
                close_old_connections()  # drop stale connections between passes of a long-running loop
            try:
                imports = run_queued()
                expiry = process_expiry()
                if imports or expiry["expiring"] or expiry["expired"]:
                    self.stdout.write(f"imports={imports} expiring={expiry['expiring']} expired={expiry['expired']}")
            except Exception:
                logger.exception("Worker pass failed; continuing")
            if once or stopping["now"]:
                break
            time.sleep(interval)
        self.stdout.write("Worker stopped.")
