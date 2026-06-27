from __future__ import annotations

import json
from typing import Any

from .db import connect

VALID_EVENTS = {"impression", "shortlist", "click", "view_profile", "book_intent", "booked", "cancelled", "rating"}


def log_interaction(
    user_id: str,
    doctor_cache_id: int,
    event_type: str,
    session_id: str | None = None,
    event_value: float | None = None,
    rating_value: float | None = None,
    source: str = "api",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if event_type not in VALID_EVENTS:
        raise ValueError(f"Invalid event_type: {event_type}. Valid: {sorted(VALID_EVENTS)}")
    if event_type == "rating" and rating_value is None:
        raise ValueError("rating_value is required when event_type='rating'")
    with connect() as con:
        con.execute("INSERT OR IGNORE INTO user_profiles(user_id) VALUES (?)", (user_id,))
        cur = con.execute(
            """
            INSERT INTO interaction_events(
              user_id, session_id, doctor_cache_id, event_type, event_value,
              rating_value, source, is_synthetic, metadata_json
            ) VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (user_id, session_id, doctor_cache_id, event_type, event_value, rating_value, source, 0, json.dumps(metadata or {})),
        )
        return {
            "ok": True,
            "interaction_id": cur.lastrowid,
            "user_id": user_id,
            "doctor_cache_id": doctor_cache_id,
            "event_type": event_type,
        }

