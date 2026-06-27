from __future__ import annotations

import math
import uuid
from typing import Any

import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from .db import connect


def ensure_user(
    user_id: str | None,
    preferred_specialty_slug: str | None = None,
    preferred_area: str | None = None,
    max_fee_egp: int | None = None,
    max_wait_minutes: int | None = None,
) -> str:
    user_id = user_id or f"anon_{uuid.uuid4().hex[:12]}"
    with connect() as con:
        con.execute(
            """
            INSERT INTO user_profiles(user_id, preferred_specialty_slug, preferred_area, max_fee_egp, max_wait_minutes)
            VALUES (?,?,?,?,?)
            ON CONFLICT(user_id) DO UPDATE SET
              preferred_specialty_slug=COALESCE(excluded.preferred_specialty_slug, user_profiles.preferred_specialty_slug),
              preferred_area=COALESCE(excluded.preferred_area, user_profiles.preferred_area),
              max_fee_egp=COALESCE(excluded.max_fee_egp, user_profiles.max_fee_egp),
              max_wait_minutes=COALESCE(excluded.max_wait_minutes, user_profiles.max_wait_minutes)
            """,
            (user_id, preferred_specialty_slug, preferred_area, max_fee_egp, max_wait_minutes),
        )
    return user_id


def create_session(
    user_query: str,
    user_id: str | None = None,
    specialty_slug: str | None = None,
    area: str | None = None,
    max_fee_egp: int | None = None,
    max_wait_minutes: int | None = None,
    channel: str = "api",
    claude_model: str | None = None,
) -> str:
    session_id = f"sess_{uuid.uuid4().hex}"
    with connect() as con:
        con.execute(
            """
            INSERT INTO recommendation_sessions(
              session_id, user_id, channel, user_query, inferred_specialty_slug,
              requested_area, max_fee_egp, max_wait_minutes, claude_model
            ) VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (session_id, user_id, channel, user_query, specialty_slug, area, max_fee_egp, max_wait_minutes, claude_model),
        )
    return session_id


def _load_doctors() -> pd.DataFrame:
    with connect() as con:
        return pd.read_sql_query("SELECT * FROM v_doctor_features", con)


def _user_history_score(user_id: str | None) -> dict[int, float]:
    if not user_id:
        return {}
    with connect() as con:
        rows = con.execute(
            """
            SELECT doctor_cache_id, interaction_score
            FROM v_autorec_matrix_entries
            WHERE user_id = ?
            """,
            (user_id,),
        ).fetchall()
    if not rows:
        return {}
    max_score = max(float(r["interaction_score"] or 0.0) for r in rows) or 1.0
    return {int(r["doctor_cache_id"]): float(r["interaction_score"] or 0.0) / max_score for r in rows}


def cold_start_recommend(
    user_query: str,
    user_id: str | None = None,
    specialty_slug: str | None = None,
    area: str | None = None,
    max_fee_egp: int | None = None,
    max_wait_minutes: int | None = None,
    top_k: int = 5,
    log_results: bool = False,
    session_id: str | None = None,
) -> list[dict[str, Any]]:
    """Metadata recommender that works with zero user history."""
    df = _load_doctors()
    if df.empty:
        return []

    if specialty_slug:
        exact = df[df["specialty_slug"] == specialty_slug]
        if not exact.empty:
            df = exact.copy()

    if max_fee_egp is not None:
        affordable = df[(df["fees_egp"].isna()) | (df["fees_egp"] <= max_fee_egp)]
        if not affordable.empty:
            df = affordable.copy()

    if max_wait_minutes is not None:
        fast = df[(df["waiting_time_minutes"].isna()) | (df["waiting_time_minutes"] <= max_wait_minutes)]
        if not fast.empty:
            df = fast.copy()

    text = (df["profile_text"].fillna("").astype(str)).tolist()
    query = (user_query or "doctor appointment alexandria").lower()
    vectorizer = TfidfVectorizer(ngram_range=(1, 2), min_df=1)
    tfidf = vectorizer.fit_transform(text + [query])
    qv = tfidf[-1]
    docv = tfidf[:-1]
    profile_scores = cosine_similarity(qv, docv).ravel()
    df = df.copy()
    df["profile_match_score"] = profile_scores
    df["specialty_match_score"] = df["specialty_slug"].apply(lambda s: 1.0 if specialty_slug and s == specialty_slug else 0.35 if specialty_slug else 0.5)
    if area:
        area_l = area.lower()
        df["area_match_score"] = df["area"].fillna("").str.lower().apply(lambda a: 1.0 if area_l in a or a in area_l else 0.0)
    else:
        df["area_match_score"] = 0.5

    def fee_score(fee):
        if max_fee_egp is None or pd.isna(fee):
            return 0.7
        fee = float(fee)
        if fee <= max_fee_egp:
            return 1.0
        return max(0.0, 1.0 - ((fee - max_fee_egp) / max(max_fee_egp, 1)))

    df["fee_score"] = df["fees_egp"].apply(fee_score)
    history = _user_history_score(user_id)
    df["interaction_score"] = df["doctor_cache_id"].map(history).fillna(0.0)
    df["cold_start_score"] = (
        0.26 * df["profile_match_score"].fillna(0)
        + 0.20 * df["specialty_match_score"].fillna(0)
        + 0.13 * df["area_match_score"].fillna(0)
        + 0.13 * df["public_listing_score"].fillna(0)
        + 0.10 * df["rating_count_score"].fillna(0)
        + 0.08 * df["waiting_time_score"].fillna(0)
        + 0.07 * df["fee_score"].fillna(0)
        + 0.03 * df["interaction_score"].fillna(0)
    )
    ranked = df.sort_values("cold_start_score", ascending=False).head(top_k).copy()
    out_cols = [
        "doctor_cache_id", "specialty_slug", "specialty_name", "name", "headline", "area",
        "address_short", "fees_egp", "rating_count", "waiting_time_minutes", "source_url",
        "profile_match_score", "specialty_match_score", "area_match_score", "public_listing_score",
        "rating_count_score", "waiting_time_score", "fee_score", "interaction_score", "cold_start_score",
    ]
    results = ranked[out_cols].to_dict(orient="records")

    if log_results and user_id:
        if not session_id:
            session_id = create_session(user_query, user_id, specialty_slug, area, max_fee_egp, max_wait_minutes)
        with connect() as con:
            for pos, r in enumerate(results, start=1):
                con.execute(
                    """
                    INSERT INTO recommendation_logs(
                      session_id, user_id, doctor_cache_id, rank_position, profile_match_score,
                      specialty_match_score, area_match_score, public_listing_score, rating_count_score,
                      waiting_time_score, fee_score, interaction_score, final_score
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        session_id, user_id, int(r["doctor_cache_id"]), pos,
                        float(r["profile_match_score"]), float(r["specialty_match_score"]),
                        float(r["area_match_score"]), float(r["public_listing_score"]),
                        float(r["rating_count_score"]), float(r["waiting_time_score"]),
                        float(r["fee_score"]), float(r["interaction_score"]),
                        float(r["cold_start_score"]),
                    ),
                )
    return results

