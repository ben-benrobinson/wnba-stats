"""
Fast playoff refresh from ESPN — bracket, scores, and box scores for newly
finished games. Takes a few seconds (~3 requests when nothing new has
finished), so it can run often — live scores are only as fresh as the last run.

Cron entry (every 10 min):
  */10 * * * * cd /home/ubuntu/wnba-stats && /home/ubuntu/wnba-stats/venv/bin/python -m scripts.live >> /var/log/wnba-live.log 2>&1
"""

import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)


def run() -> int:
    from data.espn import refresh_playoffs
    try:
        result = refresh_playoffs()
    except Exception as e:
        log.error("ESPN playoff refresh failed: %s", e)
        return 1
    log.info("ESPN playoff refresh: %s", result)
    return 0


if __name__ == "__main__":
    sys.exit(run())
