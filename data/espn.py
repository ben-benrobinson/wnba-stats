"""
Playoff data from ESPN's public JSON feed (site.api.espn.com).

Much fresher than basketball-reference: scores and series status update within
minutes of the final buzzer, so this backs the Playoffs page and is cheap enough
to poll every 30 minutes (see scripts/live.py).

The feed is unofficial — if it fails or changes shape, callers fall back to bref.
"""

import logging
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from data.fetch import CURRENT_SEASON, HEADERS
from data.teams import TEAM_NAMES

log = logging.getLogger(__name__)

SITE_API = "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba"
ET = ZoneInfo("America/New_York")
POSTSEASON = 3  # ESPN season type

# ESPN abbreviation → our (basketball-reference) abbreviation
ESPN_TO_BREF = {"GS": "GSV", "LA": "LAS", "LV": "LVA", "NY": "NYL", "PHX": "PHO", "WSH": "WAS"}

PLAYOFF_GAMELOG_TABLE = "player_playoff_gamelogs"


def _abbrev(espn_abbrev: str) -> str:
    return ESPN_TO_BREF.get(espn_abbrev, espn_abbrev)


def _get(path: str, **params) -> dict:
    resp = requests.get(f"{SITE_API}/{path}", params=params, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    return resp.json()


def fetch_playoff_events(season: str = CURRENT_SEASON) -> list[dict]:
    """All postseason events (played, live, and scheduled). The scoreboard only
    accepts single dates or whole months, so pull each month playoffs can span."""
    events: dict[str, dict] = {}
    for month in ("09", "10", "11"):
        data = _get("scoreboard", dates=f"{season}{month}")
        for e in data.get("events", []):
            if e.get("season", {}).get("type") == POSTSEASON:
                events[e["id"]] = e
    return sorted(events.values(), key=lambda e: e["date"])


def _parse_headline(headline: str) -> tuple[str, int | None, bool]:
    # "WNBA Semifinals - Game 4 If Necessary" → ("Semifinals", 4, True)
    text = re.sub(r"^WNBA\s+", "", headline or "").strip()
    rnd, _, rest = text.partition(" - ")
    m = re.search(r"Game\s+(\d+)", rest)
    return rnd.strip() or "Playoffs", int(m.group(1)) if m else None, "If Necessary" in rest


def build_playoff_tables(events: list[dict]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Returns (series_df, games_df) in the same shape the dashboard reads from bref,
    plus live-state columns (State, Detail, Tip, IfNecessary, EventId).
    """
    game_rows = []
    for e in events:
        comp = e["competitions"][0]
        notes = comp.get("notes") or [{}]
        rnd, game_no, if_nec = _parse_headline(notes[0].get("headline", ""))
        teams = {c["homeAway"]: c for c in comp["competitors"]}
        home, away = teams.get("home"), teams.get("away")
        if home is None or away is None:
            continue
        h, a = _abbrev(home["team"]["abbreviation"]), _abbrev(away["team"]["abbreviation"])
        status = e["status"]["type"]
        state = {"post": "final", "in": "live"}.get(status.get("state"), "scheduled")
        tip = datetime.fromisoformat(e["date"].replace("Z", "+00:00")).astimezone(ET)
        has_score = state in ("final", "live")
        pair = sorted([h, a])
        game_rows.append({
            "series_id": f"{CURRENT_SEASON}-{rnd}-{'-'.join(pair)}",
            "Round": rnd,
            "Game": game_no,
            "Date": tip.strftime("%a, %B %-d"),
            "IsoDate": tip.strftime("%Y-%m-%d"),
            # Unannounced tip times come through as midnight ET with timeValid=false
            "Tip": tip.strftime("%-I:%M %p ET") if comp.get("timeValid", True) else "time TBD",
            "Away": a,
            "Home": h,
            "AwayPts": int(away["score"]) if has_score and away.get("score") else None,
            "HomePts": int(home["score"]) if has_score and home.get("score") else None,
            "State": state,
            "Detail": status.get("shortDetail", ""),
            "IfNecessary": if_nec,
            "EventId": e["id"],
            "SeriesComplete": bool((comp.get("series") or {}).get("completed")),
            "Boxscore": "",
            "SEASON": CURRENT_SEASON,
        })

    games = pd.DataFrame(game_rows)
    if games.empty:
        return pd.DataFrame(), games

    series_rows = []
    for sid, g in games.groupby("series_id", sort=False):
        rnd = g["Round"].iloc[0]
        t1, t2 = sorted({*g["Home"], *g["Away"]})[:2] if len({*g["Home"], *g["Away"]}) >= 2 else ("TBD", "TBD")
        final = g[g["State"] == "final"]
        wins = {t1: 0, t2: 0}
        for _, r in final.iterrows():
            winner = r["Home"] if r["HomePts"] > r["AwayPts"] else r["Away"]
            wins[winner] = wins.get(winner, 0) + 1
        leader, trailer = (t1, t2) if wins[t1] >= wins[t2] else (t2, t1)
        lw, tw = wins[leader], wins[trailer]
        complete = bool(g["SeriesComplete"].any())
        if "TBD" in (t1, t2):
            status = f"Series starts {_short(g['Date'].iloc[0])}"
        else:
            ln, tn = TEAM_NAMES.get(leader, leader), TEAM_NAMES.get(trailer, trailer)
            if complete:
                status = f"{ln} over {tn} ({lw}-{tw})"
            elif lw == tw:
                status = f"Series tied {lw}-{tw}" if lw else "Series not started"
            else:
                status = f"{ln} lead {tn} ({lw}-{tw})"
        series_rows.append({
            "series_id": sid, "Round": rnd, "Leader": leader, "Trailer": trailer,
            "Status": status, "SEASON": CURRENT_SEASON,
            "LeaderWins": lw, "TrailerWins": tw, "Complete": complete,
        })
    return pd.DataFrame(series_rows), games.drop(columns=["SeriesComplete"])


def _short(date_str: str) -> str:
    # "Sat, October 17" → "Sat Oct 17"
    try:
        dow, rest = date_str.split(", ", 1)
        month, day = rest.split()
        return f"{dow} {month[:3]} {day}"
    except ValueError:
        return date_str


# ── Box scores ────────────────────────────────────────────────────────────────

def _split_made(val: str) -> tuple[float, float]:
    try:
        made, att = val.split("-")
        return float(made), float(att)
    except (ValueError, AttributeError):
        return float("nan"), float("nan")


def fetch_box_score(game: dict) -> pd.DataFrame:
    """Per-player lines for one finished game, in player_gamelogs column names."""
    data = _get("summary", event=game["EventId"])
    rows = []
    home_won = game["HomePts"] > game["AwayPts"]
    for team in data.get("boxscore", {}).get("players", []):
        tm = _abbrev(team["team"]["abbreviation"])
        is_home = tm == game["Home"]
        opp = game["Away"] if is_home else game["Home"]
        won = home_won if is_home else not home_won
        for block in team.get("statistics", []):
            keys = block.get("keys", [])
            for ath in block.get("athletes", []):
                if ath.get("didNotPlay") or not ath.get("stats"):
                    continue
                s = dict(zip(keys, ath["stats"]))
                fg, fga = _split_made(s.get("fieldGoalsMade-fieldGoalsAttempted"))
                tp, tpa = _split_made(s.get("threePointFieldGoalsMade-threePointFieldGoalsAttempted"))
                ft, fta = _split_made(s.get("freeThrowsMade-freeThrowsAttempted"))
                num = lambda k: pd.to_numeric(s.get(k), errors="coerce")
                row = {
                    "Date": game["IsoDate"], "Tm": tm, "Opp": opp,
                    "HomeAway": "Home" if is_home else "Away", "Result": "W" if won else "L",
                    "GS": int(bool(ath.get("starter"))),
                    "MP": num("minutes"), "FG": fg, "FGA": fga, "3P": tp, "3PA": tpa,
                    "FT": ft, "FTA": fta, "ORB": num("offensiveRebounds"),
                    "DRB": num("defensiveRebounds"), "TRB": num("rebounds"),
                    "AST": num("assists"), "STL": num("steals"), "BLK": num("blocks"),
                    "TOV": num("turnovers"), "PF": num("fouls"), "PTS": num("points"),
                    "Player": ath["athlete"]["displayName"],
                    "player_id": f"espn:{ath['athlete']['id']}",
                    "EventId": game["EventId"], "SEASON": CURRENT_SEASON,
                }
                # Hollinger Game Score, same formula bref uses
                row["GmSc"] = (row["PTS"] + 0.4 * fg - 0.7 * fga - 0.4 * (fta - ft)
                               + 0.7 * row["ORB"] + 0.3 * row["DRB"] + row["STL"]
                               + 0.7 * row["AST"] + 0.7 * row["BLK"] - 0.4 * row["PF"] - row["TOV"])
                rows.append(row)
    return pd.DataFrame(rows)


def refresh_playoffs() -> dict:
    """
    Pull bracket + schedule from ESPN and box scores for any newly finished games.
    Writes playoff_series, playoff_games, player_playoff_gamelogs, refresh_meta.
    Raises on failure so callers can fall back to bref.
    """
    from data.store import load, save, set_refresh_meta

    series, games = build_playoff_tables(fetch_playoff_events())
    if series.empty:
        log.info("ESPN: no postseason events yet")
        return {"series": 0, "games": 0, "new_box_scores": 0}

    # Box scores: only fetch finals we don't already have (ESPN-sourced rows carry EventId)
    existing = load(PLAYOFF_GAMELOG_TABLE)
    if existing.empty or "EventId" not in existing.columns:
        existing = pd.DataFrame()
        have = set()
    else:
        existing["EventId"] = existing["EventId"].astype(str)
        have = set(existing["EventId"])
    finals = games[games["State"] == "final"]
    todo = [g for g in finals.to_dict("records") if str(g["EventId"]) not in have]
    frames = [existing] if not existing.empty else []
    for g in todo:
        box = fetch_box_score(g)
        if box.empty:
            log.warning("ESPN: empty box score for event %s", g["EventId"])
            continue
        frames.append(box)
        log.info("ESPN: box score %s %s @ %s (%d players)", g["EventId"], g["Away"], g["Home"], len(box))

    save(series, "playoff_series")
    save(games, "playoff_games")
    if frames:
        save(pd.concat(frames, ignore_index=True), PLAYOFF_GAMELOG_TABLE)
    set_refresh_meta("playoffs", "ESPN", datetime.now(timezone.utc).isoformat())
    return {"series": len(series), "games": len(games), "new_box_scores": len(todo)}
