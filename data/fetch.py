"""
Fetches WNBA data from basketball-reference.com via HTML scraping.
Be polite: sleep between requests to avoid rate limiting.
"""

import time
import requests
import pandas as pd
from io import StringIO

BASE_URL = "https://www.basketball-reference.com/wnba"
CURRENT_SEASON = "2026"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def _get_table(url: str, table_id: str, sleep: float = 1.5) -> pd.DataFrame:
    from bs4 import BeautifulSoup
    time.sleep(sleep)
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.content.decode("utf-8", errors="replace"), "html5lib")
    table = soup.find("table", id=table_id)
    if table is None:
        raise ValueError(f"Table '{table_id}' not found at {url}")
    df = pd.read_html(StringIO(str(table)))[0]
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = ["_".join(c).strip("_") for c in df.columns]
    # Drop separator rows injected by bref every 20 rows
    if "Player" in df.columns:
        df = df[df["Player"] != "Player"].reset_index(drop=True)
    return df


def fetch_player_per_game() -> pd.DataFrame:
    """Per-game averages for all players this season."""
    url = f"{BASE_URL}/years/{CURRENT_SEASON}_per_game.html"
    df = _get_table(url, "per_game")
    df["SEASON"] = CURRENT_SEASON
    return df


def fetch_player_totals() -> pd.DataFrame:
    """Season totals for all players."""
    url = f"{BASE_URL}/years/{CURRENT_SEASON}_totals.html"
    df = _get_table(url, "totals")
    df["SEASON"] = CURRENT_SEASON
    return df


def fetch_player_advanced() -> pd.DataFrame:
    """Advanced stats: WS, OWS, DWS, TS%, USG%, PER, ORtg, DRtg — pre-computed by bref."""
    url = f"{BASE_URL}/years/{CURRENT_SEASON}_advanced.html"
    df = _get_table(url, "advanced")
    df["SEASON"] = CURRENT_SEASON
    return df


def fetch_team_stats() -> pd.DataFrame:
    """Team per-game stats."""
    url = f"{BASE_URL}/years/{CURRENT_SEASON}.html"
    df = _get_table(url, "per_game-team")
    df["SEASON"] = CURRENT_SEASON
    return df
