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

# Fatal thresholds — if exceeded, the nightly restores from backup.
FATAL_MISSING_PLAYER_PCT = 0.10   # >10% of active players absent from gamelogs
FATAL_STANDINGS_DIVERGE_TEAMS = 3  # >3 teams with W gap > 5 vs gamelogs


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


def check_gamelog_stats_vs_per_game(pg: pd.DataFrame, gl: pd.DataFrame) -> list[str]:
    """
    A player's mean stat across gamelog rows should roughly match their per_game
    average. A large divergence means the gamelog has the wrong player's data or
    a parsing error. Tolerance is generous (40%) to allow for DNP filtering gaps.
    """
    issues = []
    if pg.empty or gl.empty:
        return issues

    TOLERANCE = 0.40
    CHECK_COLS = ["PTS", "TRB", "AST"]

    pg_num = pg.copy()
    pg_num["G"] = pd.to_numeric(pg_num["G"], errors="coerce")
    pg_num = pg_num[pg_num["G"] >= MIN_GAMES_FOR_GAMELOG].dropna(subset=["Player"])

    for col in CHECK_COLS:
        if col not in pg_num.columns or col not in gl.columns:
            continue
        pg_num[col] = pd.to_numeric(pg_num[col], errors="coerce")
        gl_col = pd.to_numeric(gl[col], errors="coerce")
        gl_avg = gl.assign(**{col: gl_col}).groupby("Player")[col].mean()

        merged = pg_num[["Player", col]].merge(gl_avg.rename("gl_avg"), on="Player", how="inner")
        merged = merged.dropna()
        # Only check players where per_game value is large enough to be meaningful
        merged = merged[merged[col] >= 2.0]

        for _, row in merged.iterrows():
            diff = abs(row["gl_avg"] - row[col])
            if row[col] > 0 and diff / row[col] > TOLERANCE:
                issues.append(
                    f"{row['Player']} {col}: per_game={row[col]:.1f}, "
                    f"gamelog_mean={row['gl_avg']:.1f} ({diff/row[col]:.0%} divergence)"
                )
    return issues


def check_standings_vs_gamelogs(standings: pd.DataFrame, gl: pd.DataFrame) -> list[str]:
    """
    Each team's W in standings should roughly match the number of Win results
    in their gamelogs (within 2 games, accounting for timing of the nightly run).
    """
    issues = []
    if standings.empty or gl.empty or "Tm" not in gl.columns or "Result" not in gl.columns:
        return issues

    from data.teams import TEAM_NAMES
    name_to_abbrev = {v: k for k, v in TEAM_NAMES.items()}

    # One row per (team, game date) to avoid double-counting from multiple players
    game_results = gl.drop_duplicates(["Tm", "Date"])[["Tm", "Result"]]
    gl_wins = game_results[game_results["Result"] == "W"].groupby("Tm").size()
    gl_losses = game_results[game_results["Result"] == "L"].groupby("Tm").size()

    for _, row in standings.iterrows():
        abbrev = name_to_abbrev.get(str(row.get("Team", "")), "")
        if not abbrev:
            continue
        st_w = pd.to_numeric(row.get("W"), errors="coerce")
        st_l = pd.to_numeric(row.get("L"), errors="coerce")
        if pd.isna(st_w) or pd.isna(st_l):
            continue

        gl_w = gl_wins.get(abbrev, 0)
        gl_l = gl_losses.get(abbrev, 0)

        if abs(gl_w - st_w) > 2:
            issues.append(
                f"{abbrev}: standings W={int(st_w)}, gamelog W={int(gl_w)} "
                f"(gap of {int(abs(gl_w - st_w))})"
            )
        if abs(gl_l - st_l) > 2:
            issues.append(
                f"{abbrev}: standings L={int(st_l)}, gamelog L={int(gl_l)} "
                f"(gap of {int(abs(gl_l - st_l))})"
            )
    return issues


def check_opponent_result_mirror(gl: pd.DataFrame) -> list[str]:
    """
    For every game, if team A beat team B, team B's gamelog should show a loss
    to team A on the same date. Mismatches indicate corrupted result data.
    """
    issues = []
    if gl.empty or not {"Tm", "Opp", "Date", "Result"}.issubset(gl.columns):
        return issues

    games = gl.drop_duplicates(["Tm", "Date"])[["Tm", "Opp", "Date", "Result"]].dropna()
    result_map = games.set_index(["Tm", "Date"])["Result"].to_dict()

    mismatches = []
    for _, row in games.iterrows():
        expected_opp_result = "L" if row["Result"] == "W" else "W"
        actual_opp_result = result_map.get((row["Opp"], row["Date"]))
        if actual_opp_result is not None and actual_opp_result != expected_opp_result:
            mismatches.append(f"{row['Date']} {row['Tm']} vs {row['Opp']}: "
                              f"{row['Tm']}={row['Result']}, {row['Opp']}={actual_opp_result}")

    # Deduplicate (each game appears twice)
    seen = set()
    for m in mismatches:
        parts = m.split(" ")
        key = tuple(sorted([parts[1], parts[2]]) + [parts[0]])
        if key not in seen:
            seen.add(key)
            issues.append(m)
    return issues


def check_duplicate_gamelog_rows(gl: pd.DataFrame) -> list[str]:
    """A player should not appear twice for the same game date."""
    issues = []
    if gl.empty or not {"Player", "Date"}.issubset(gl.columns):
        return issues

    dupes = gl[gl.duplicated(subset=["Player", "Date"], keep=False)]
    if not dupes.empty:
        dupe_pairs = dupes.groupby(["Player", "Date"]).size()
        for (player, date), count in dupe_pairs.items():
            issues.append(f"Duplicate gamelog rows: {player} on {date} ({count} rows)")
    return issues


def check_shooting_pct_range(pg: pd.DataFrame) -> list[str]:
    """FG%, 3P%, FT% must all be in [0, 1]. Values > 1 mean bref returned raw counts."""
    issues = []
    if pg.empty:
        return issues

    for col in ["FG%", "3P%", "FT%"]:
        if col not in pg.columns:
            continue
        vals = pd.to_numeric(pg[col], errors="coerce").dropna()
        out_of_range = pg[(pd.to_numeric(pg[col], errors="coerce") > 1.0) |
                          (pd.to_numeric(pg[col], errors="coerce") < 0.0)]
        for _, row in out_of_range.iterrows():
            issues.append(
                f"{row['Player']} {col}={row[col]} is outside [0, 1] — "
                f"possible parsing error (raw count instead of percentage?)"
            )
    return issues


def check_per_game_times_g_vs_totals(pg: pd.DataFrame, totals: pd.DataFrame) -> list[str]:
    """
    per_game_stat × G should roughly equal the season total (within 15% or 5 units).
    Catches column misalignment in the HTML scraper.
    """
    issues = []
    if pg.empty or totals.empty:
        return issues

    CHECK_COLS = ["PTS", "TRB", "AST"]
    TOLERANCE_PCT = 0.15
    TOLERANCE_ABS = 5  # ignore tiny absolute differences

    pg_num = pg.copy()
    pg_num["G"] = pd.to_numeric(pg_num["G"], errors="coerce")
    pg_num = pg_num[pg_num["G"] >= MIN_GAMES_FOR_GAMELOG].dropna(subset=["Player", "G"])

    tot_num = totals.copy()

    for col in CHECK_COLS:
        if col not in pg_num.columns or col not in tot_num.columns:
            continue
        pg_num[col] = pd.to_numeric(pg_num[col], errors="coerce")
        tot_num[col] = pd.to_numeric(tot_num[col], errors="coerce")

        merged = pg_num[["Player", "G", col]].merge(
            tot_num[["Player", col]].rename(columns={col: "total"}),
            on="Player", how="inner",
        ).dropna()
        merged["implied_total"] = merged[col] * merged["G"]
        merged["diff"] = (merged["implied_total"] - merged["total"]).abs()
        merged["pct_diff"] = merged["diff"] / merged["total"].replace(0, float("nan"))

        flagged = merged[(merged["diff"] > TOLERANCE_ABS) & (merged["pct_diff"] > TOLERANCE_PCT)]
        for _, row in flagged.iterrows():
            issues.append(
                f"{row['Player']} {col}: per_game×G={row['implied_total']:.0f}, "
                f"totals={row['total']:.0f} ({row['pct_diff']:.0%} divergence)"
            )
    return issues


def missing_gamelog_players(pg: pd.DataFrame, gl: pd.DataFrame) -> list[str]:
    """Return names of players with MIN_GAMES_FOR_GAMELOG+ games but no gamelog rows."""
    if pg.empty:
        return []
    active = pg[pd.to_numeric(pg["G"], errors="coerce") >= MIN_GAMES_FOR_GAMELOG]["Player"].dropna()
    gl_players = set(gl["Player"].dropna().unique()) if not gl.empty else set()
    return [p for p in active if p not in gl_players]


def is_fatal(pg: pd.DataFrame, gl: pd.DataFrame, standings: pd.DataFrame) -> tuple[bool, str]:
    """
    Returns (fatal, reason). Fatal means the nightly should restore from backup
    rather than serve the new (broken) data.
    """
    # Empty gamelogs is always fatal
    if gl.empty:
        return True, "player_gamelogs table is empty after fetch"

    # Too many players missing
    active_count = int((pd.to_numeric(pg.get("G", pd.Series()), errors="coerce") >= MIN_GAMES_FOR_GAMELOG).sum())
    missing_count = len(missing_gamelog_players(pg, gl))
    if active_count > 0 and missing_count / active_count > FATAL_MISSING_PLAYER_PCT:
        return True, (
            f"{missing_count} of {active_count} active players missing from gamelogs "
            f"({missing_count/active_count:.0%} > {FATAL_MISSING_PLAYER_PCT:.0%} threshold)"
        )

    # Too many teams with large W divergence
    if not standings.empty and "Tm" in gl.columns and "Result" in gl.columns:
        from data.teams import TEAM_NAMES
        name_to_abbrev = {v: k for k, v in TEAM_NAMES.items()}
        game_results = gl.drop_duplicates(["Tm", "Date"])[["Tm", "Result"]]
        gl_wins = game_results[game_results["Result"] == "W"].groupby("Tm").size()
        bad_teams = 0
        for _, row in standings.iterrows():
            abbrev = name_to_abbrev.get(str(row.get("Team", "")), "")
            st_w = pd.to_numeric(row.get("W"), errors="coerce")
            gl_w = gl_wins.get(abbrev, 0)
            if pd.notna(st_w) and abs(gl_w - st_w) > 5:
                bad_teams += 1
        if bad_teams >= FATAL_STANDINGS_DIVERGE_TEAMS:
            return True, f"{bad_teams} teams have W divergence >5 between standings and gamelogs"

    return False, ""


def run_all() -> list[str]:
    """Run all checks. Returns list of issue strings; empty list = all clear."""
    from data.store import load

    pg      = load("player_per_game")
    gl      = load("player_gamelogs")
    standings = load("team_standings")
    totals  = load("player_totals")

    all_issues = []
    checks = [
        # Existence checks
        ("gamelog_coverage",         check_gamelog_coverage(pg, gl)),
        ("gamelog_row_counts",       check_gamelog_row_counts(pg, gl)),
        ("standings_teams",          check_standings_teams(standings, gl)),
        ("table_freshness",          check_table_freshness(gl)),
        # Internal consistency checks
        ("gamelog_stats_vs_per_game",  check_gamelog_stats_vs_per_game(pg, gl)),
        ("standings_vs_gamelogs",      check_standings_vs_gamelogs(standings, gl)),
        ("opponent_result_mirror",     check_opponent_result_mirror(gl)),
        ("duplicate_gamelog_rows",     check_duplicate_gamelog_rows(gl)),
        ("shooting_pct_range",         check_shooting_pct_range(pg)),
        ("per_game_times_g_vs_totals", check_per_game_times_g_vs_totals(pg, totals)),
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
