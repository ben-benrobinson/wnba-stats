"""
Nightly data refresh — run via cron at ~2am ET after games complete.

Cron entry (add with `crontab -e` on EC2):
  0 2 * * * cd /home/ec2-user/wnba-stats && /home/ec2-user/wnba-stats/venv/bin/python -m scripts.nightly >> /var/log/wnba-nightly.log 2>&1
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

    from data.fetch import fetch_player_box_scores, fetch_team_box_scores, fetch_all_on_off
    from data.store import save
    from stats.efficiency import aggregate_player_season
    from stats.win_shares import compute_win_shares

    log.info("Fetching player game logs...")
    player_logs = fetch_player_box_scores()
    save(player_logs, "player_game_logs")
    log.info("  %d rows saved", len(player_logs))

    log.info("Fetching team game logs...")
    team_logs = fetch_team_box_scores()
    save(team_logs, "team_game_logs")
    log.info("  %d rows saved", len(team_logs))

    log.info("Fetching on/off splits...")
    on_off = fetch_all_on_off()
    if not on_off.empty:
        save(on_off, "on_off_raw")
        log.info("  %d rows saved", len(on_off))
    else:
        log.warning("  No on/off data returned")

    log.info("Computing player aggregates...")
    agg = aggregate_player_season(player_logs)
    save(agg, "player_agg")
    log.info("  %d players aggregated", len(agg))

    log.info("Computing win shares...")
    ws = compute_win_shares(agg, team_logs)
    save(ws, "win_shares")
    log.info("  %d players with win shares", len(ws))

    log.info("=== Refresh complete ===")


if __name__ == "__main__":
    run()
