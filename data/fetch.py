"""
Fetches WNBA box score data from the unofficial stats.wnba.com API.
No API key required — same infrastructure as nba_api.
"""

import requests
import pandas as pd
import time

BASE_URL = "https://stats.wnba.com/stats"

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://www.wnba.com/",
    "Origin": "https://www.wnba.com",
    "Accept": "application/json",
    "x-nba-stats-origin": "stats",
    "x-nba-stats-token": "true",
}

CURRENT_SEASON = "2025"
SEASON_TYPE = "Regular Season"


def _get(endpoint: str, params: dict) -> dict:
    url = f"{BASE_URL}/{endpoint}"
    resp = requests.get(url, headers=HEADERS, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _to_df(response: dict, result_set_index: int = 0) -> pd.DataFrame:
    rs = response["resultSets"][result_set_index]
    return pd.DataFrame(rs["rowSet"], columns=rs["headers"])


def fetch_player_box_scores() -> pd.DataFrame:
    """Per-game box scores for all players this season."""
    data = _get("playergamelogs", {
        "Season": CURRENT_SEASON,
        "SeasonType": SEASON_TYPE,
        "LeagueID": "10",  # 10 = WNBA
    })
    return _to_df(data)


def fetch_team_box_scores() -> pd.DataFrame:
    """Per-game box scores for all teams this season."""
    data = _get("teamgamelogs", {
        "Season": CURRENT_SEASON,
        "SeasonType": SEASON_TYPE,
        "LeagueID": "10",
    })
    return _to_df(data)


def fetch_player_on_off(team_id: int) -> pd.DataFrame:
    """On/off splits for all players on a given team."""
    data = _get("teamplayeronoffdetails", {
        "Season": CURRENT_SEASON,
        "SeasonType": SEASON_TYPE,
        "LeagueID": "10",
        "TeamID": team_id,
        "MeasureType": "Advanced",
        "PerMode": "PerPossession",
        "PaceAdjust": "N",
        "PlusMinus": "N",
        "Rank": "N",
        "DateFrom": "",
        "DateTo": "",
        "GameSegment": "",
        "LastNGames": 0,
        "Location": "",
        "Month": 0,
        "Outcome": "",
        "Period": 0,
        "SeasonSegment": "",
        "VsConference": "",
        "VsDivision": "",
        "OpponentTeamID": 0,
    })
    on_df = _to_df(data, 0)
    on_df["ON_OFF"] = "ON"
    off_df = _to_df(data, 1)
    off_df["ON_OFF"] = "OFF"
    return pd.concat([on_df, off_df], ignore_index=True)


def fetch_all_teams() -> pd.DataFrame:
    """All WNBA teams with IDs."""
    data = _get("commonteamyears", {
        "LeagueID": "10",
    })
    df = _to_df(data)
    return df[df["MAX_YEAR"] == CURRENT_SEASON].reset_index(drop=True)


def fetch_all_on_off() -> pd.DataFrame:
    """On/off data across all teams. Sleeps between requests to be polite."""
    teams = fetch_all_teams()
    frames = []
    for _, row in teams.iterrows():
        try:
            df = fetch_player_on_off(int(row["TEAM_ID"]))
            df["TEAM_ABBREVIATION"] = row["ABBREVIATION"]
            frames.append(df)
            time.sleep(0.6)
        except Exception as e:
            print(f"Warning: failed on/off fetch for team {row['TEAM_ID']}: {e}")
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
