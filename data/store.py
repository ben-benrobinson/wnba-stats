"""
Persists fetched data to SQLite and reads it back.
"""

import sqlite3
import pandas as pd
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "wnba.db"


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
