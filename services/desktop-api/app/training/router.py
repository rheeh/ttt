from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.training.service import TrainingError

router = APIRouter(prefix="/api/training", tags=["K线训练"])


class CreateTraining(BaseModel):
    pool: Literal["reference", "watchlist"] = "reference"
    steps: Literal[20, 40, 60] = 40


class TrainingAction(BaseModel):
    revision: int = Field(ge=0)
    action: Literal["buy", "sell", "hold", "finish"]
    fraction: Literal[.25, .5, 1] = 1
    note: str = Field(default="", max_length=160)


def call(operation, *args):
    try:
        return operation(*args)
    except TrainingError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc


@router.get("")
def overview(request: Request):
    return call(request.app.state.training.overview)


@router.post("/sessions")
def create(payload: CreateTraining, request: Request):
    return call(request.app.state.training.create, payload.pool, payload.steps)


@router.get("/sessions/{session_id}")
def get(session_id: str, request: Request):
    return call(request.app.state.training.get, session_id)


@router.post("/sessions/{session_id}/actions")
def act(session_id: str, payload: TrainingAction, request: Request):
    return call(request.app.state.training.act, session_id, payload.revision, payload.action, payload.fraction, payload.note)
