"""
Nightly data refresh — run via cron at ~2am ET after games complete.

Cron entry (add with `crontab -e` on EC2):
  0 2 * * * cd /home/ubuntu/wnba-stats && /home/ubuntu/wnba-stats/venv/bin/python -m scripts.nightly >> /var/log/wnba-nightly.log 2>&1
"""

import logging
import sys
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)


def run():
    log.info("=== WNBA nightly refresh started %s ===", datetime.utcnow().isoformat())

    from data.fetch import (
        fetch_player_per_game,
        fetch_player_totals,
        fetch_player_advanced,
        fetch_team_stats,
        fetch_player_ids,
        fetch_all_gamelogs,
        fetch_team_standings,
    )
    from data.store import save

    log.info("Fetching per-game stats...")
    per_game = fetch_player_per_game()
    save(per_game, "player_per_game")
    log.info("  %d rows", len(per_game))

    log.info("Fetching season totals...")
    totals = fetch_player_totals()
    save(totals, "player_totals")
    log.info("  %d rows", len(totals))

    log.info("Fetching advanced stats...")
    advanced = fetch_player_advanced()
    save(advanced, "player_advanced")
    log.info("  %d rows", len(advanced))

    log.info("Fetching team stats...")
    teams = fetch_team_stats()
    save(teams, "team_stats")
    log.info("  %d rows", len(teams))

    log.info("Fetching team standings...")
    standings = fetch_team_standings()
    if not standings.empty:
        save(standings, "team_standings")
        log.info("  %d rows", len(standings))
    else:
        log.warning("  No standings data found — skipping")

    log.info("Fetching player IDs for game logs...")
    player_ids = fetch_player_ids()
    log.info("  %d players found", len(player_ids))

    log.info("Fetching game logs (~%d requests, ~%d min)...",
             len(player_ids), len(player_ids) * 2 // 60)
    gamelogs, skipped = fetch_all_gamelogs(player_ids)
    if not gamelogs.empty:
        save(gamelogs, "player_gamelogs")
        log.info("  %d game rows across %d players", len(gamelogs), gamelogs["Player"].nunique())
    else:
        log.warning("  No game log data returned")
    if skipped:
        log.warning("  %d player(s) skipped during gamelog fetch: %s",
                    len(skipped), ", ".join(sorted(skipped)))

    log.info("Running post-refresh validation checks...")
    from scripts.validate import run_all
    run_all()

    log.info("=== Refresh complete ===")


if __name__ == "__main__":
    run()
