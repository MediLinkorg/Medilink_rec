from __future__ import annotations
from veez_autorec_agent.vezeeta_live_booking import get_live_availability, book_selected_slot
from veez_autorec_agent.booking_automation import BookingRequest, book_on_vezeeta
from typing import Optional

from fastapi import FastAPI
from pydantic import BaseModel, Field

from .claude_agent import run_claude_agent
from .cold_start import ensure_user
from .hybrid_recommender import recommend_doctors, log_interaction
from .train_autorec import train_autorec

app = FastAPI(title="Vezeeta Alexandria AutoRec + Claude/OpenClue Agent")


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



class BookingStartRequest(BaseModel):
    doctor_url: str
    patient_name: str
    patient_phone: str
    preferred_day_text: str | None = None
    preferred_time_text: str | None = None
    dry_run: bool = True
    user_confirmed_final: bool = False

class AgentRequest(BaseModel):
    message: str
    user_id: Optional[str] = None


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


@app.post("/agent")
def agent(req: AgentRequest):
    return {"response": run_claude_agent(req.message, user_id=req.user_id)}



@app.post("/booking/start")
def booking_start(req: BookingStartRequest):
    booking_req = BookingRequest(
        doctor_url=req.doctor_url,
        patient_name=req.patient_name,
        patient_phone=req.patient_phone,
        preferred_day_text=req.preferred_day_text,
        preferred_time_text=req.preferred_time_text,
        dry_run=req.dry_run,
        user_confirmed_final=req.user_confirmed_final,
    )
    return book_on_vezeeta(booking_req)


class BookingAvailabilityRequest(BaseModel):
    user_id: str
    doctor_url: str
    headless: bool = False


class BookingConfirmRequest(BaseModel):
    user_id: str
    doctor_url: str
    selected_time_text: str
    patient_name: str
    patient_phone: str
    doctor_cache_id: int | None = None
    dry_run: bool = True
    user_confirmed_final: bool = False
    headless: bool = False


@app.post("/booking/availability")
def booking_availability(req: BookingAvailabilityRequest):
    return get_live_availability(
        user_id=req.user_id,
        doctor_url=req.doctor_url,
        headless=req.headless,
    )


@app.post("/booking/confirm")
def booking_confirm(req: BookingConfirmRequest):
    return book_selected_slot(
        user_id=req.user_id,
        doctor_url=req.doctor_url,
        selected_time_text=req.selected_time_text,
        patient_name=req.patient_name,
        patient_phone=req.patient_phone,
        doctor_cache_id=req.doctor_cache_id,
        dry_run=req.dry_run,
        user_confirmed_final=req.user_confirmed_final,
        headless=req.headless,
    )
