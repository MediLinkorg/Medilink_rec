from __future__ import annotations
from typing import Optional

from fastapi import FastAPI
from pydantic import BaseModel, Field

from .cold_start import ensure_user
from .hybrid_recommender import recommend_doctors, log_interaction
from .train_autorec import train_autorec

app = FastAPI(title="Vezeeta Alexandria AutoRec")


class UserRequest(BaseModel):
    user_id: Optional[str] = None
    preferred_specialty_slug: Optional[str] = None
    preferred_area: Optional[str] = None
    max_fee_egp: Optional[int] = None
    max_wait_minutes: Optional[int] = None


class RecommendRequest(BaseModel):
    user_query: str
    user_id: Optional[str] = None
    specialty_slug: Optional[str] = None
    area: Optional[str] = None
    max_fee_egp: Optional[int] = None
    max_wait_minutes: Optional[int] = None
    top_k: int = Field(default=5, ge=1, le=10)
    use_autorec: bool = True
    log_results: bool = True


class InteractionRequest(BaseModel):
    user_id: str
    doctor_cache_id: int
    event_type: str
    rating_value: Optional[float] = None
    event_value: Optional[float] = None
    source: str = "api"


class TrainRequest(BaseModel):
    include_synthetic: bool = True
    hidden_dim: int = 64
    epochs: int = 80
    lr: float = 1e-3


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/users")
def users(req: UserRequest):
    return {"user_id": ensure_user(**req.model_dump())}


@app.post("/recommend")
def recommend(req: RecommendRequest):
    return {"results": recommend_doctors(**req.model_dump())}


@app.post("/interaction")
def interaction(req: InteractionRequest):
    return log_interaction(**req.model_dump())


@app.post("/train-autorec")
def train(req: TrainRequest):
    return train_autorec(**req.model_dump())

