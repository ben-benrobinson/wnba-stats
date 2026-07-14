"""
Fetches WNBA data from basketball-reference.com via HTML scraping.
Be polite: sleep between requests to avoid rate limiting.
"""

import logging
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

log = logging.getLogger(__name__)


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
    # bref's per_game table has two columns named "MP" (season total) and "G"
    # (also duplicated); pandas renames the second occurrence to "MP.1" / "G.1".
    # The ".1" versions are the actual per-game figures we want — drop the totals.
    if "MP.1" in df.columns:
        df = df.drop(columns=["MP"]).rename(columns={"MP.1": "MP"})
    if "G.1" in df.columns:
        df = df.drop(columns=["G.1"])
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


# ── Game log fetching ─────────────────────────────────────────────────────────

def fetch_player_ids() -> dict[str, str]:
    """
    Scrapes the per-game page and extracts each player's bref ID from their
    href link. Returns {player_name: bref_id}, e.g. {"Caitlin Clark": "clarkca01w"}.
    Players with multiple team rows (trades) appear once.
    """
    from bs4 import BeautifulSoup
    url = f"{BASE_URL}/years/{CURRENT_SEASON}_per_game.html"
    time.sleep(1.5)
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.content.decode("utf-8", errors="replace"), "html5lib")
    table = soup.find("table", id="per_game")
    ids: dict[str, str] = {}
    if table is None:
        return ids
    for row in table.find_all("tr"):
        # Player name is in a <th data-stat="player">, not a <td>
        th = row.find("th", {"data-stat": "player"})
        if th is None:
            continue
        a = th.find("a")
        if not a:
            continue
        href = a.get("href", "")
        # href: /wnba/players/c/clarkca01w.html
        player_id = href.rstrip("/").split("/")[-1].replace(".html", "")
        name = a.text.strip()
        # Only store first occurrence (avoids duplicate from TOT + team rows)
        if player_id and name and name not in ids:
            ids[name] = player_id
    return ids


def fetch_player_gamelog(player_id: str, player_name: str) -> pd.DataFrame:
    """
    Game-by-game log for a single player this season.
    Returns a cleaned DataFrame with one row per game played.
    """
    from bs4 import BeautifulSoup
    first = player_id[0]
    url = f"{BASE_URL}/players/{first}/{player_id}/gamelog/{CURRENT_SEASON}/"
    # Polite delay + retry on 429
    for attempt in range(3):
        time.sleep(3 + attempt * 10)
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)
            if resp.status_code == 429:
                log.warning("  429 on %s, waiting 60s before retry %d", player_id, attempt + 1)
                time.sleep(60)
                continue
            resp.raise_for_status()
            break
        except requests.HTTPError:
            if attempt == 2:
                raise
    else:
        return pd.DataFrame()

    soup = BeautifulSoup(resp.content.decode("utf-8", errors="replace"), "html5lib")

    table = soup.find("table", id="wnba_pgl_basic")
    if table is None:
        return pd.DataFrame()

    df = pd.read_html(StringIO(str(table)))[0]

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = ["_".join(c).strip("_") for c in df.columns]

    # Drop repeated header rows
    if "Rk" in df.columns:
        df = df[pd.to_numeric(df["Rk"], errors="coerce").notna()].reset_index(drop=True)

    # Drop rows where player didn't play (MP is non-numeric like "Did Not Play")
    if "MP" in df.columns:
        df = df[pd.to_numeric(df["MP"].astype(str).str.replace(":", "."), errors="coerce").notna()].reset_index(drop=True)

    # MP is "MM:SS" (e.g. "30:18") — convert to decimal minutes
    if "MP" in df.columns:
        def _mp_to_minutes(val):
            s = str(val).strip()
            if ":" in s:
                mins, secs = s.split(":", 1)
                try:
                    return int(mins) + int(secs) / 60
                except ValueError:
                    return None
            try:
                return float(s)
            except ValueError:
                return None
        df["MP"] = df["MP"].apply(_mp_to_minutes)

    # Unnamed: 4 = home/away (NaN = home, "@" = away)
    if "Unnamed: 4" in df.columns:
        df["HomeAway"] = df["Unnamed: 4"].apply(lambda x: "Away" if str(x).strip() == "@" else "Home")
        df = df.drop(columns=["Unnamed: 4"])

    # Unnamed: 6 = result ("W (+13)", "L (-4)")
    if "Unnamed: 6" in df.columns:
        df["Result"] = df["Unnamed: 6"].apply(lambda x: "W" if str(x).startswith("W") else "L")
        df = df.drop(columns=["Unnamed: 6"])

    df["Player"] = player_name
    df["player_id"] = player_id
    df["SEASON"] = CURRENT_SEASON
    return df


def fetch_all_gamelogs(player_ids: dict[str, str]) -> tuple[pd.DataFrame, list[str]]:
    """
    Fetches game logs for all players. Skips players that error.
    Returns (gamelogs_df, skipped_player_names).
    """
    frames = []
    skipped = []
    total = len(player_ids)
    for i, (name, pid) in enumerate(player_ids.items(), 1):
        log.info("  gamelog [%d/%d] %s", i, total, name)
        try:
            df = fetch_player_gamelog(pid, name)
            if not df.empty:
                frames.append(df)
            else:
                log.warning("  Empty gamelog returned for %s (%s)", name, pid)
                skipped.append(name)
        except Exception as e:
            log.warning("  Skipping %s (%s): %s", name, pid, e)
            skipped.append(name)
    result = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return result, skipped


def fetch_team_standings() -> pd.DataFrame:
    """
    Team W-L standings. Used to classify opponents as above/below .500.
    Tries multiple known bref table IDs for the standings table.
    """
    url = f"{BASE_URL}/years/{CURRENT_SEASON}.html"
    for table_id in ["wnba_standings", "standings_e", "standings_w"]:
        try:
            df = _get_table(url, table_id, sleep=1.5)
            if "W" in df.columns and "L" in df.columns:
                df["SEASON"] = CURRENT_SEASON
                return df
        except Exception:
            continue
    return pd.DataFrame()
