from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from .config import DATABASE_PATH


def connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    con = sqlite3.connect(str(db_path or DATABASE_PATH))
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def rows_to_dicts(rows) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]

