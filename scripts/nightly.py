"""
Nightly data refresh — run via cron at ~2am ET after games complete.

Cron entry (add with `crontab -e` on EC2):
  0 2 * * * cd /home/ubuntu/wnba-stats && /home/ubuntu/wnba-stats/venv/bin/python -m scripts.nightly >> /var/log/wnba-nightly.log 2>&1
"""

import logging
import sys
from datetime import datetime, timezone

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

# Max players to retry after initial gamelog fetch.
MAX_RETRY_PLAYERS = 20


def run():
    run_ts = datetime.now(timezone.utc).isoformat()
    log.info("=== WNBA nightly refresh started %s ===", run_ts)

    from data.fetch import (
        fetch_player_per_game,
        fetch_player_totals,
        fetch_player_advanced,
        fetch_team_stats,
        fetch_player_ids,
        fetch_all_gamelogs,
        fetch_player_gamelog,
        fetch_team_standings,
    )
    from data.store import (
        save, load,
        backup_tables, restore_tables,
        save_data_quality,
    )
    from scripts.validate import run_all, missing_gamelog_players, is_fatal

    # ── 1. Backup current tables before touching anything ─────────────────────
    log.info("Backing up current tables...")
    backup_tables()

    # ── 2. Fetch all data ─────────────────────────────────────────────────────
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
             len(player_ids), len(player_ids) * 4 // 60)
    gamelogs, skipped = fetch_all_gamelogs(player_ids)
    if not gamelogs.empty:
        save(gamelogs, "player_gamelogs")
        log.info("  %d game rows across %d players", len(gamelogs), gamelogs["Player"].nunique())
    else:
        log.warning("  No game log data returned")
    if skipped:
        log.warning("  %d player(s) skipped: %s", len(skipped), ", ".join(sorted(skipped)))

    # ── 3. Targeted retry for players missing from gamelogs ───────────────────
    players_retried = []
    missing = missing_gamelog_players(per_game, gamelogs)
    if missing:
        retryable = [p for p in missing if p in player_ids][:MAX_RETRY_PLAYERS]
        if retryable:
            log.info("Retrying gamelog fetch for %d missing player(s): %s",
                     len(retryable), ", ".join(retryable))
            retry_frames = [gamelogs] if not gamelogs.empty else []
            for name in retryable:
                pid = player_ids[name]
                try:
                    df = fetch_player_gamelog(pid, name)
                    if not df.empty:
                        retry_frames.append(df)
                        players_retried.append(name)
                        log.info("  Retry OK: %s (%d rows)", name, len(df))
                    else:
                        log.warning("  Retry empty: %s", name)
                except Exception as e:
                    log.warning("  Retry failed: %s — %s", name, e)

            if retry_frames:
                import pandas as pd
                gamelogs = pd.concat(retry_frames, ignore_index=True).drop_duplicates(
                    subset=["Player", "Date"]
                )
                save(gamelogs, "player_gamelogs")
                log.info("  After retry: %d game rows across %d players",
                         len(gamelogs), gamelogs["Player"].nunique())

    # ── 4. Validate ───────────────────────────────────────────────────────────
    log.info("Running post-refresh validation checks...")
    issues = run_all()

    # ── 5. Fatal check — restore backup if data is too broken to serve ────────
    fatal, fatal_reason = is_fatal(per_game, gamelogs, standings)
    action_taken = "none"

    if fatal:
        log.error("FATAL validation failure: %s", fatal_reason)
        log.error("Restoring last known good data from backup...")
        restored = restore_tables()
        action_taken = f"restored_backup:{','.join(restored)}"
        log.error("Restored tables: %s — dashboard will serve previous night's data", restored)
    elif issues:
        action_taken = f"warnings:{len(issues)}"
        if players_retried:
            action_taken = f"retried:{len(players_retried)},warnings:{len(issues)}"

    # ── 6. Record results ─────────────────────────────────────────────────────
    save_data_quality(run_ts, issues, fatal, action_taken, players_retried)

    if fatal:
        log.error("=== Refresh FAILED (backup restored) ===")
    elif issues:
        log.warning("=== Refresh complete with %d warning(s) ===", len(issues))
    else:
        log.info("=== Refresh complete — all checks passed ===")


if __name__ == "__main__":
    run()
