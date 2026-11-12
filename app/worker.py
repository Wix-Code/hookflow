"""The delivery worker. Run it in its own terminal, next to the API:

    python -m app.worker              # keeps running; stop with Ctrl+C
    python -m app.worker --once       # sends everything that is due, then exits

You can run several copies at the same time. They share the work without sending anything twice.
"""

import argparse
import logging
import signal
import threading
from concurrent.futures import ThreadPoolExecutor

from app.core.config import get_settings
from app.services.dispatch import run_once

logger = logging.getLogger("hookflow.worker")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="HookFlow delivery worker")
    parser.add_argument("--once", action="store_true", help="process what is due, then exit")
    parser.add_argument("--concurrency", type=int, help="deliveries sent at the same time")
    parser.add_argument("--poll", type=float, help="seconds to sleep when nothing is due")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    # httpx logs every request URL at INFO. A webhook URL can carry a secret token, so keep it out of the logs.
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    settings = get_settings()
    concurrency = args.concurrency or settings.worker_concurrency
    poll = args.poll if args.poll is not None else settings.worker_poll_interval_seconds

    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())  # Ctrl+C: finish the current batch, then stop
    try:
        signal.signal(signal.SIGTERM, lambda *_: stop.set())
    except (ValueError, OSError):
        pass  # not available everywhere (for example some Windows setups)

    logger.info("worker started (concurrency=%s, poll=%ss, once=%s)", concurrency, poll, args.once)
    with ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="send") as pool:
        while not stop.is_set():
            try:
                handled = run_once(settings, limit=concurrency, executor=pool)
            except Exception:
                logger.exception("worker pass failed, will try again")
                handled = 0
                if args.once:
                    return 1
            if handled == 0:
                if args.once:
                    break
                stop.wait(poll)
    logger.info("worker stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())