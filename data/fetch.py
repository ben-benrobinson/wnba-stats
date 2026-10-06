"""
Fetches WNBA data from basketball-reference.com via HTML scraping.
Be polite: sleep between requests to avoid rate limiting.
"""

import logging
import time
import requests
import pandas as pd
from io import StringIO

from data.teams import clean_team_name

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
    Regular-season game-by-game log for a single player this season.
    Returns a cleaned DataFrame with one row per game played.
    """
    regular, _ = fetch_player_gamelogs_both(player_id, player_name)
    return regular


def fetch_player_gamelogs_both(player_id: str, player_name: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Regular-season and playoff game logs for a single player, from one page fetch.
    bref puts playoffs in a second table (wnba_pgl_basic_p) on the same page.
    """
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
        return pd.DataFrame(), pd.DataFrame()

    html = resp.content.decode("utf-8", errors="replace")
    regular = _parse_gamelog_table(_find_table(html, "wnba_pgl_basic"), player_id, player_name)
    playoffs = _parse_gamelog_table(_find_table(html, "wnba_pgl_basic_p"), player_id, player_name)
    return regular, playoffs


def _find_table(html: str, table_id: str):
    """Find a table by id, including ones bref hides inside HTML comments."""
    from bs4 import BeautifulSoup, Comment
    soup = BeautifulSoup(html, "html5lib")
    table = soup.find("table", id=table_id)
    if table is not None:
        return table
    marker = f'id="{table_id}"'
    for c in soup.find_all(string=lambda t: isinstance(t, Comment) and marker in t):
        table = BeautifulSoup(c, "html5lib").find("table", id=table_id)
        if table is not None:
            return table
    return None


def _parse_gamelog_table(table, player_id: str, player_name: str) -> pd.DataFrame:
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


def fetch_all_gamelogs(player_ids: dict[str, str]) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    """
    Fetches regular-season and playoff game logs for all players. Skips players that error.
    Returns (gamelogs_df, playoff_gamelogs_df, skipped_player_names).
    """
    frames, playoff_frames = [], []
    skipped = []
    total = len(player_ids)
    for i, (name, pid) in enumerate(player_ids.items(), 1):
        log.info("  gamelog [%d/%d] %s", i, total, name)
        try:
            df, po = fetch_player_gamelogs_both(pid, name)
            if not po.empty:
                playoff_frames.append(po)
            if not df.empty:
                frames.append(df)
            else:
                log.warning("  Empty gamelog returned for %s (%s)", name, pid)
                skipped.append(name)
        except Exception as e:
            log.warning("  Skipping %s (%s): %s", name, pid, e)
            skipped.append(name)
    result = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    playoffs = pd.concat(playoff_frames, ignore_index=True) if playoff_frames else pd.DataFrame()
    return result, playoffs, skipped


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
                # bref marks playoff teams with a trailing '*' — keep it as a flag,
                # not part of the name, so name → abbreviation lookups still work.
                if "Team" in df.columns:
                    df["Playoffs"] = df["Team"].astype(str).str.strip().str.endswith("*")
                    df["Team"] = df["Team"].map(clean_team_name)
                df["SEASON"] = CURRENT_SEASON
                return df
        except Exception:
            continue
    return pd.DataFrame()


# ── Playoffs ──────────────────────────────────────────────────────────────────

def _abbrev_from_href(href: str) -> str:
    # /wnba/teams/NYL/2026.html → NYL
    parts = href.strip("/").split("/")
    return parts[2] if len(parts) >= 3 and parts[1] == "teams" else ""


def fetch_playoff_series() -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Parses the playoffs bracket on the season page.
    Returns (series_df, games_df):
      series_df — one row per series: Round, Team A/B (abbrevs), wins, status text
      games_df  — one row per scheduled game: series id, game #, date, away/home, scores
    Unplayed games have NaN scores.
    """
    url = f"{BASE_URL}/years/{CURRENT_SEASON}.html"
    time.sleep(1.5)
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    table = _find_table(resp.content.decode("utf-8", errors="replace"), "all_playoffs")
    if table is None:
        return pd.DataFrame(), pd.DataFrame()

    series_rows, game_rows = [], []
    current = None
    for tr in table.find_all("tr"):
        if "toggleable" in (tr.get("class") or []):
            continue  # nested copy of the game rows below it
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"], recursive=False)]
        if not cells or not cells[0]:
            continue
        links = [a.get("href", "") for a in tr.find_all("a")]
        team_links = [_abbrev_from_href(h) for h in links if "/teams/" in h]

        if not cells[0].startswith("Game") and len(team_links) >= 2:
            # Series header, e.g. ["Semifinals", "New York Liberty trail Atlanta Dream (0-1)", "Series Stats"]
            series_link = next((h for h in links if "/playoffs/" in h), "")
            current = {
                "series_id": series_link.rstrip("/").split("/")[-1].replace(".html", "") or f"S{len(series_rows)}",
                "Round": cells[0],
                "Leader": team_links[0],
                "Trailer": team_links[1],
                "Status": cells[1] if len(cells) > 1 else "",
                "SEASON": CURRENT_SEASON,
            }
            series_rows.append(current)
        elif cells[0].startswith("Game") and current is not None:
            # ["Game 1", "Sun, October 4", "New York Liberty", "82", "@ Atlanta Dream", "92"]
            # Unplayed: ["Game 2", "Wed, October 7", "New York Liberty", "@ Atlanta Dream"]
            if len(team_links) < 2:
                continue
            nums = [c for c in cells[2:] if c.isdigit()]
            box = next((h for h in links if "/boxscores/" in h), "")
            game_rows.append({
                "series_id": current["series_id"],
                "Game": int(cells[0].split()[-1]),
                "Date": cells[1],
                "Away": team_links[0],
                "Home": team_links[1],
                "AwayPts": int(nums[0]) if len(nums) == 2 else None,
                "HomePts": int(nums[1]) if len(nums) == 2 else None,
                "Boxscore": box,
                "SEASON": CURRENT_SEASON,
            })

    series = pd.DataFrame(series_rows)
    games = pd.DataFrame(game_rows)
    if not series.empty and not games.empty:
        # Compute wins from scores rather than parsing the status sentence
        played = games.dropna(subset=["AwayPts", "HomePts"]).copy()
        played["Winner"] = played.apply(
            lambda r: r["Home"] if r["HomePts"] > r["AwayPts"] else r["Away"], axis=1)
        wins = played.groupby(["series_id", "Winner"]).size()
        series["LeaderWins"] = [int(wins.get((sid, t), 0)) for sid, t in zip(series["series_id"], series["Leader"])]
        series["TrailerWins"] = [int(wins.get((sid, t), 0)) for sid, t in zip(series["series_id"], series["Trailer"])]
        series["Complete"] = series["Status"].str.contains(r"\bover\b|\bdefeated\b", regex=True)
    return series, games
