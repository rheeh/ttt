from datetime import date

from fastapi import APIRouter, HTTPException, Query, Request
from .jobs import CollectRequest, LakeSettings
from .reader import DATASETS

router = APIRouter(prefix="/api/data-lake", tags=["data-lake"])


@router.get("/status")
def status(request: Request):
    return request.app.state.lake_jobs.status()


@router.put("/settings")
def configure(payload: LakeSettings, request: Request):
    request.app.state.lake_jobs.store.configure(payload)
    return payload


@router.post("/collect", status_code=202)
def collect(payload: CollectRequest, request: Request):
    try:
        return request.app.state.lake_jobs.start(payload)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/records/{dataset}")
def records(dataset: str, request: Request, code: str | None = None, start: date | None = None,
            end: date | None = None, as_of: date | None = None, limit: int = Query(200, ge=1, le=1000)):
    if dataset not in DATASETS:
        raise HTTPException(status_code=404, detail="不支持的数据集")
    if start and end and start > end:
        raise HTTPException(status_code=422, detail="起始日期不能晚于结束日期")
    try:
        rows = request.app.state.lake.records(dataset, code=code, start=start, end=end, as_of=as_of, limit=limit)
        return {"dataset": dataset, "rows": rows, "limit": limit, "pit_mode": "best_effort" if dataset in {"financial_statement_items", "announcement_index"} else None}
    except (ValueError, OSError, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
