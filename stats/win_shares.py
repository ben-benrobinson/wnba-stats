"""
Estimated Win Shares from box score data.

Win Shares is a single number answering: "how many wins has this player produced?"
We use a simplified box-score-based method adapted from basketball-reference's
approach, scaled for WNBA pace and scoring environment.

This is an *estimate* — without play-by-play we can't compute the full version.
It correlates well with more complex metrics and is interpretable.

Formula outline:
  Offensive Win Shares  ∝ points produced above a replacement-level threshold
  Defensive Win Shares  ∝ defensive box score contributions (reb, stl, blk)
  Win Shares = OWS + DWS, scaled so league total ≈ number of wins played

Reference: https://www.basketball-reference.com/about/ws.html (adapted)
"""

import numpy as np
import pandas as pd

WNBA_LEAGUE_PTS_PER_POSS = 1.03  # approx 2025 WNBA average
REPLACEMENT_LEVEL = 0.300         # win% below which a player adds 0 value
MINS_PER_TEAM_GAME = 200.0        # 5 players × 40 min


def _points_produced(row: pd.Series) -> float:
    """Estimated offensive points produced by the player."""
    pts = row["PTS"]
    ast_pts = 0.5 * row["AST"]             # assists credit share
    oreb_pts = 0.25 * row["OREB"] if "OREB" in row else 0.0
    tov_penalty = -WNBA_LEAGUE_PTS_PER_POSS * row["TOV"]
    return pts + ast_pts + oreb_pts + tov_penalty


def _marginal_offense(pp: float, mp: float, team_mp: float, team_pts: float) -> float:
    """Points produced above replacement threshold, per-minute scaled."""
    if team_mp <= 0:
        return 0.0
    pace_factor = mp / team_mp
    expected = REPLACEMENT_LEVEL * 2 * team_pts * pace_factor  # replacement baseline
    marginal = pp - expected
    return max(marginal, 0.0)


def _marginal_defense(row: pd.Series, team_dreb: float, team_stl: float, team_blk: float,
                      opp_pts: float) -> float:
    """Rough defensive contribution above replacement."""
    dreb = row.get("DREB", row.get("REB", 0) - row.get("OREB", 0))
    stl = row.get("STL", 0)
    blk = row.get("BLK", 0)

    dreb_pct = dreb / max(team_dreb, 1)
    stl_pct = stl / max(team_stl, 1)
    blk_pct = blk / max(team_blk, 1)

    defensive_impact = (dreb_pct * 0.5 + stl_pct * 1.5 + blk_pct * 1.0)
    return defensive_impact * opp_pts * 0.01


def compute_win_shares(player_agg: pd.DataFrame, team_logs: pd.DataFrame) -> pd.DataFrame:
    """
    Compute estimated win shares for each player.

    Args:
        player_agg: output of efficiency.aggregate_player_season()
        team_logs: raw team game logs from fetch.fetch_team_box_scores()
    """
    team_season = team_logs.copy()
    for col in ["PTS", "FGA", "FTA", "TOV", "REB", "STL", "BLK", "MIN"]:
        team_season[col] = pd.to_numeric(team_season.get(col, 0), errors="coerce").fillna(0)

    team_totals = team_season.groupby("TEAM_ABBREVIATION").agg(
        TEAM_PTS=("PTS", "sum"),
        TEAM_MIN=("MIN", "sum"),
        TEAM_DREB=("DREB", "sum") if "DREB" in team_season.columns else ("REB", "sum"),
        TEAM_STL=("STL", "sum"),
        TEAM_BLK=("BLK", "sum"),
        TEAM_GP=("GAME_ID", "count"),
    ).reset_index()

    # Use opponent points as a proxy for team defensive exposure
    # Without opponent data, approximate as league average * games
    team_totals["OPP_PTS"] = team_totals["TEAM_PTS"].mean()

    df = player_agg.merge(team_totals, on="TEAM_ABBREVIATION", how="left")

    for col in ["PTS", "AST", "TOV", "REB", "STL", "BLK", "MIN", "OREB", "DREB"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    df["PP"] = df.apply(_points_produced, axis=1)
    df["MARGINAL_OFF"] = df.apply(
        lambda r: _marginal_offense(r["PP"], r["MIN"], r.get("TEAM_MIN", MINS_PER_TEAM_GAME * r.get("GP", 1)), r.get("TEAM_PTS", 1)),
        axis=1,
    )
    df["MARGINAL_DEF"] = df.apply(
        lambda r: _marginal_defense(r, r.get("TEAM_DREB", 1), r.get("TEAM_STL", 1), r.get("TEAM_BLK", 1), r.get("OPP_PTS", 80)),
        axis=1,
    )

    pts_per_win = 30.0  # empirical: ~30 marginal points ≈ 1 win
    df["OWS"] = df["MARGINAL_OFF"] / pts_per_win
    df["DWS"] = df["MARGINAL_DEF"] / pts_per_win
    df["WIN_SHARES"] = (df["OWS"] + df["DWS"]).clip(lower=0)

    return df[["PLAYER_ID", "PLAYER_NAME", "TEAM_ABBREVIATION", "GP", "MIN",
               "OWS", "DWS", "WIN_SHARES"]].sort_values("WIN_SHARES", ascending=False)
