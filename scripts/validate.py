"""
Post-nightly data quality checks.

Run automatically at the end of scripts/nightly — any issues are logged
as warnings so the nightly doesn't abort, but problems are clearly visible
in the log. Returns a list of issue strings (empty = all clear).
"""

import logging
import pandas as pd

log = logging.getLogger(__name__)

# A player with at least this many games in per_game should have gamelog rows.
MIN_GAMES_FOR_GAMELOG = 5

# A player's gamelog row count should be at least this fraction of their per_game G.
# (Some rows are legitimately missing — DNPs, bref data gaps — so we allow slack.)
GAMELOG_COVERAGE_THRESHOLD = 0.75


def check_gamelog_coverage(pg: pd.DataFrame, gl: pd.DataFrame) -> list[str]:
    """
    Every player with G >= MIN_GAMES_FOR_GAMELOG in per_game should have
    at least one row in player_gamelogs.
    """
    issues = []
    if pg.empty or gl.empty:
        if gl.empty:
            issues.append("player_gamelogs table is empty")
        return issues

    pg_active = pg[pd.to_numeric(pg["G"], errors="coerce") >= MIN_GAMES_FOR_GAMELOG]["Player"].dropna().unique()
    gl_players = set(gl["Player"].dropna().unique())

    missing = [p for p in pg_active if p not in gl_players]
    if missing:
        issues.append(
            f"{len(missing)} player(s) with {MIN_GAMES_FOR_GAMELOG}+ games in per_game "
            f"have NO rows in player_gamelogs: {', '.join(sorted(missing))}"
        )
    return issues


def check_gamelog_row_counts(pg: pd.DataFrame, gl: pd.DataFrame) -> list[str]:
    """
    Each player's gamelog row count should be at least GAMELOG_COVERAGE_THRESHOLD
    of their G in per_game. Flags players with suspiciously sparse gamelogs.
    """
    issues = []
    if pg.empty or gl.empty:
        return issues

    pg_num = pg.copy()
    pg_num["G"] = pd.to_numeric(pg_num["G"], errors="coerce")
    pg_num = pg_num[pg_num["G"] >= MIN_GAMES_FOR_GAMELOG].dropna(subset=["Player", "G"])

    gl_counts = gl.groupby("Player").size().rename("gl_rows")
    merged = pg_num[["Player", "G"]].merge(gl_counts, on="Player", how="left")
    merged["gl_rows"] = merged["gl_rows"].fillna(0)
    merged["coverage"] = merged["gl_rows"] / merged["G"]

    sparse = merged[merged["coverage"] < GAMELOG_COVERAGE_THRESHOLD]
    for _, row in sparse.iterrows():
        issues.append(
            f"{row['Player']}: {int(row['gl_rows'])} gamelog rows vs {int(row['G'])} games "
            f"in per_game ({row['coverage']:.0%} coverage)"
        )
    return issues


def check_standings_teams(standings: pd.DataFrame, gl: pd.DataFrame) -> list[str]:
    """All teams in standings should appear in player_gamelogs."""
    issues = []
    if standings.empty or gl.empty or "Tm" not in gl.columns:
        return issues

    from data.teams import TEAM_NAMES
    name_to_abbrev = {v: k for k, v in TEAM_NAMES.items()}
    standing_abbrevs = {
        name_to_abbrev.get(str(row.get("Team", "")), str(row.get("Team", "")))
        for _, row in standings.iterrows()
    }
    gl_teams = set(gl["Tm"].dropna().unique())
    missing = standing_abbrevs - gl_teams - {""}
    if missing:
        issues.append(f"Teams in standings with no gamelog data: {', '.join(sorted(missing))}")
    return issues


def check_table_freshness(gl: pd.DataFrame) -> list[str]:
    """
    The most recent game date in player_gamelogs should be within the last 5 days
    (accounts for off-days / All-Star breaks). Stale data is flagged.
    """
    issues = []
    if gl.empty or "Date" not in gl.columns:
        return issues

    dates = pd.to_datetime(gl["Date"], errors="coerce").dropna()
    if dates.empty:
        return issues

    most_recent = dates.max()
    days_old = (pd.Timestamp.now() - most_recent).days
    if days_old > 5:
        issues.append(
            f"Most recent game in player_gamelogs is {most_recent.date()} "
            f"({days_old} days ago) — data may be stale"
        )
    return issues


def run_all() -> list[str]:
    """Run all checks. Returns list of issue strings; empty list = all clear."""
    from data.store import load

    pg = load("player_per_game")
    gl = load("player_gamelogs")
    standings = load("team_standings")

    all_issues = []
    checks = [
        ("gamelog_coverage",    check_gamelog_coverage(pg, gl)),
        ("gamelog_row_counts",  check_gamelog_row_counts(pg, gl)),
        ("standings_teams",     check_standings_teams(standings, gl)),
        ("table_freshness",     check_table_freshness(gl)),
    ]

    for name, issues in checks:
        if issues:
            for issue in issues:
                log.warning("[validate:%s] %s", name, issue)
            all_issues.extend(issues)
        else:
            log.info("[validate:%s] OK", name)

    if all_issues:
        log.warning("=== %d validation issue(s) found ===", len(all_issues))
    else:
        log.info("=== All validation checks passed ===")

    return all_issues
