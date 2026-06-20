"""
Box-score efficiency metrics: True Shooting %, Usage Rate, and related.
"""

import pandas as pd
import numpy as np


def true_shooting_pct(pts: pd.Series, fga: pd.Series, fta: pd.Series) -> pd.Series:
    denom = 2 * (fga + 0.44 * fta)
    return pts / denom.replace(0, np.nan)


def usage_rate(fga: pd.Series, fta: pd.Series, tov: pd.Series,
               team_fga: pd.Series, team_fta: pd.Series, team_tov: pd.Series,
               mp: pd.Series, team_mp: pd.Series) -> pd.Series:
    """
    Percentage of team plays used by the player while on the floor.
    Standard formula from basketball-reference.
    """
    player_plays = fga + 0.44 * fta + tov
    team_plays = team_fga + 0.44 * team_fta + team_tov
    mp_fraction = mp / (team_mp / 5)
    return (player_plays * (team_mp / 5)) / (mp_fraction * team_plays)


def aggregate_player_season(game_logs: pd.DataFrame) -> pd.DataFrame:
    """
    Collapse per-game logs to season totals and compute efficiency metrics.
    Expects columns from stats.wnba.com playergamelogs endpoint.
    """
    agg = game_logs.groupby(["PLAYER_ID", "PLAYER_NAME", "TEAM_ABBREVIATION"]).agg(
        GP=("GAME_ID", "count"),
        MIN=("MIN", "sum"),
        PTS=("PTS", "sum"),
        FGA=("FGA", "sum"),
        FGM=("FGM", "sum"),
        FG3A=("FG3A", "sum"),
        FG3M=("FG3M", "sum"),
        FTA=("FTA", "sum"),
        FTM=("FTM", "sum"),
        REB=("REB", "sum"),
        AST=("AST", "sum"),
        TOV=("TOV", "sum"),
        STL=("STL", "sum"),
        BLK=("BLK", "sum"),
    ).reset_index()

    agg["TS_PCT"] = true_shooting_pct(agg["PTS"], agg["FGA"], agg["FTA"])
    agg["FG_PCT"] = agg["FGM"] / agg["FGA"].replace(0, np.nan)
    agg["FG3_PCT"] = agg["FG3M"] / agg["FG3A"].replace(0, np.nan)
    agg["FT_PCT"] = agg["FTM"] / agg["FTA"].replace(0, np.nan)
    agg["PTS_PER_GAME"] = agg["PTS"] / agg["GP"]
    agg["MIN_PER_GAME"] = agg["MIN"] / agg["GP"]

    return agg
