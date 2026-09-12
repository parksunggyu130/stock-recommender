from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import services
from ..db import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["eod"])


@router.post("/eod/refresh")
def eod_refresh(db: Session = Depends(get_db)):
    """수동 '지금 마감 체크' — 성과 계산 + 상한가 스캔/기록. 알림은 보내지 않는다."""
    try:
        return services.eod_compute(db)
    except Exception as exc:
        logger.exception("마감 체크 실패")
        raise HTTPException(status_code=502, detail=f"마감 체크에 실패했습니다: {exc}") from exc


@router.get("/performance/today")
def performance_today(db: Session = Depends(get_db)):
    result = services.get_performance_today(db)
    if result is None:
        return {"available": False}
    return {"available": True, **result}
