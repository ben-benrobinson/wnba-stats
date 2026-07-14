"""
Persists fetched data to SQLite and reads it back.
"""

import json
import logging
import sqlite3
import pandas as pd
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "wnba.db"

log = logging.getLogger(__name__)

# Tables that get backed up before each nightly run and restored on fatal failure.
BACKED_UP_TABLES = ["player_per_game", "player_gamelogs", "team_standings", "player_totals"]


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(DB_PATH)


def save(df: pd.DataFrame, table: str) -> None:
    with _conn() as conn:
        df.to_sql(table, conn, if_exists="replace", index=False)


def load(table: str) -> pd.DataFrame:
    with _conn() as conn:
        try:
            return pd.read_sql(f"SELECT * FROM {table}", conn)
        except Exception:
            return pd.DataFrame()


def table_exists(table: str) -> bool:
    with _conn() as conn:
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
        )
        return cur.fetchone() is not None


def backup_tables() -> None:
    """Snapshot each production table to <table>_backup before the nightly run."""
    with _conn() as conn:
        for table in BACKED_UP_TABLES:
            try:
                exists = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
                ).fetchone()
                if exists is None:
                    continue
                conn.execute(f"DROP TABLE IF EXISTS {table}_backup")
                conn.execute(f"CREATE TABLE {table}_backup AS SELECT * FROM {table}")
                log.info("Backed up %s", table)
            except Exception as e:
                log.warning("Could not back up %s: %s", table, e)


def restore_tables() -> list[str]:
    """
    Restore production tables from their _backup copies.
    Called when fatal validation failures are detected.
    Returns list of successfully restored table names.
    """
    restored = []
    with _conn() as conn:
        for table in BACKED_UP_TABLES:
            backup = f"{table}_backup"
            try:
                has_backup = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (backup,)
                ).fetchone()
                if has_backup is None:
                    log.warning("No backup found for %s — cannot restore", table)
                    continue
                conn.execute(f"DROP TABLE IF EXISTS {table}")
                conn.execute(f"ALTER TABLE {backup} RENAME TO {table}")
                restored.append(table)
                log.info("Restored %s from backup", table)
            except Exception as e:
                log.error("Failed to restore %s: %s", table, e)
    return restored


def save_data_quality(
    run_ts: str,
    issues: list[str],
    fatal: bool,
    action_taken: str,
    players_retried: list[str],
) -> None:
    """Append a validation run record; keep only the last 30."""
    df = pd.DataFrame([{
        "run_timestamp": run_ts,
        "issues_json": json.dumps(issues),
        "issue_count": len(issues),
        "fatal": int(fatal),
        "action_taken": action_taken,
        "players_retried_json": json.dumps(players_retried),
    }])
    with _conn() as conn:
        df.to_sql("data_quality", conn, if_exists="append", index=False)
        conn.execute("""
            DELETE FROM data_quality WHERE rowid NOT IN (
                SELECT rowid FROM data_quality ORDER BY run_timestamp DESC LIMIT 30
            )
        """)


def load_data_quality() -> dict | None:
    """Return the most recent validation run record, or None if no records exist."""
    with _conn() as conn:
        try:
            df = pd.read_sql(
                "SELECT * FROM data_quality ORDER BY run_timestamp DESC LIMIT 1", conn
            )
            if df.empty:
                return None
            row = df.iloc[0].to_dict()
            row["issues"] = json.loads(row.get("issues_json") or "[]")
            row["players_retried"] = json.loads(row.get("players_retried_json") or "[]")
            return row
        except Exception:
            return None
