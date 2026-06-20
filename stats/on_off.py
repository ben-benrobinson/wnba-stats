"""
On/off net rating splits with confidence intervals.

Net rating = points scored per 100 possessions - points allowed per 100 possessions.
On/Off delta = net rating with player ON minus net rating with player OFF.

A large positive delta means the team is meaningfully better with the player
on the floor. But we must not overstate certainty at small sample sizes.

We use a normal approximation to compute 90% CIs on the delta:
  SE(delta) = sqrt(SE_on^2 + SE_off^2)

Each net rating's SE is approximated as ~12 / sqrt(possessions), which is a
standard empirical estimate for NBA/WNBA data (sigma ≈ 12 pts/100 poss).
"""

import numpy as np
import pandas as pd
from scipy.stats import norm

NET_RATING_SIGMA = 12.0  # empirical std dev of net rating per possession


def _net_rating_se(possessions: pd.Series) -> pd.Series:
    return NET_RATING_SIGMA / np.sqrt(possessions.clip(lower=1))


def compute_on_off_deltas(on_off_df: pd.DataFrame) -> pd.DataFrame:
    """
    Takes the raw on/off DataFrame from fetch.py and computes:
      - NET_RATING delta (ON minus OFF)
      - 90% CI on that delta
      - A 'signal' flag: CI excludes zero

    Expected columns from stats.wnba.com teamplayeronoffdetails:
      PLAYER_ID, PLAYER_NAME, ON_OFF, NET_RATING, MIN, GP
    """
    on = on_off_df[on_off_df["ON_OFF"] == "ON"].copy()
    off = on_off_df[on_off_df["ON_OFF"] == "OFF"].copy()

    merged = on.merge(
        off,
        on=["PLAYER_ID", "PLAYER_NAME", "TEAM_ABBREVIATION"],
        suffixes=("_ON", "_OFF"),
    )

    merged["NET_ON"] = pd.to_numeric(merged["NET_RATING_ON"], errors="coerce")
    merged["NET_OFF"] = pd.to_numeric(merged["NET_RATING_OFF"], errors="coerce")
    merged["POSS_ON"] = pd.to_numeric(merged.get("POSS_ON", merged.get("MIN_ON", 1)), errors="coerce")
    merged["POSS_OFF"] = pd.to_numeric(merged.get("POSS_OFF", merged.get("MIN_OFF", 1)), errors="coerce")

    merged["DELTA"] = merged["NET_ON"] - merged["NET_OFF"]

    se_on = _net_rating_se(merged["POSS_ON"])
    se_off = _net_rating_se(merged["POSS_OFF"])
    se_delta = np.sqrt(se_on**2 + se_off**2)

    z = norm.ppf(0.95)
    merged["DELTA_CI_LOW"] = merged["DELTA"] - z * se_delta
    merged["DELTA_CI_HIGH"] = merged["DELTA"] + z * se_delta
    merged["SIGNAL"] = (merged["DELTA_CI_LOW"] > 0) | (merged["DELTA_CI_HIGH"] < 0)

    cols = [
        "PLAYER_ID", "PLAYER_NAME", "TEAM_ABBREVIATION",
        "NET_ON", "NET_OFF", "DELTA", "DELTA_CI_LOW", "DELTA_CI_HIGH", "SIGNAL",
        "MIN_ON", "MIN_OFF",
    ]
    return merged[[c for c in cols if c in merged.columns]].reset_index(drop=True)
