from __future__ import annotations

from typing import Any

from .autorec_inference import predict_autorec_scores
from .cold_start import cold_start_recommend, ensure_user
from .config import AUTOREC_WEIGHT, COLD_START_WEIGHT
from .interactions import log_interaction


def recommend_doctors(
    user_query: str,
    user_id: str | None = None,
    specialty_slug: str | None = None,
    area: str | None = None,
    max_fee_egp: int | None = None,
    max_wait_minutes: int | None = None,
    top_k: int = 5,
    use_autorec: bool = True,
    log_results: bool = True,
) -> list[dict[str, Any]]:
    """Main function to import into your bigger project.

    It uses cold-start ranking always, then blends AutoRec predictions when a trained
    model and a known user vector exist.
    """
    user_id = ensure_user(user_id, specialty_slug, area, max_fee_egp, max_wait_minutes) if user_id else None
    # Pull a wider cold-start candidate set, then blend.
    candidates = cold_start_recommend(
        user_query=user_query,
        user_id=user_id,
        specialty_slug=specialty_slug,
        area=area,
        max_fee_egp=max_fee_egp,
        max_wait_minutes=max_wait_minutes,
        top_k=max(30, top_k),
        log_results=False,
    )
    if not candidates:
        return []
    autorec_scores = predict_autorec_scores(user_id, top_n=200) if (use_autorec and user_id) else {}
    cold_w = COLD_START_WEIGHT
    auto_w = AUTOREC_WEIGHT if autorec_scores else 0.0
    if not autorec_scores:
        cold_w = 1.0
    norm = cold_w + auto_w or 1.0
    for row in candidates:
        doctor_id = int(row["doctor_cache_id"])
        row["autorec_score"] = float(autorec_scores.get(doctor_id, 0.0))
        row["hybrid_score"] = (cold_w * float(row.get("cold_start_score") or 0.0) + auto_w * row["autorec_score"]) / norm
        row["ranking_mode"] = "hybrid_autorec" if autorec_scores else "cold_start_only"
    ranked = sorted(candidates, key=lambda r: r["hybrid_score"], reverse=True)[:top_k]

    if log_results and user_id:
        for r in ranked:
            try:
                log_interaction(user_id, int(r["doctor_cache_id"]), "impression", source="hybrid_recommender", metadata={"score": r["hybrid_score"]})
            except Exception:
                pass
    return ranked
