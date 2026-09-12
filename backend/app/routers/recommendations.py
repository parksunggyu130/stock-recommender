from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import services
from ..db import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/recommendations", tags=["recommendations"])


@router.get("/today")
def get_today(db: Session = Depends(get_db)):
    try:
        return services.get_today(db)
    except Exception as exc:
        logger.exception("추천 조회 실패")
        raise HTTPException(status_code=502, detail=f"추천 데이터를 가져오지 못했습니다: {exc}") from exc


@router.post("/refresh")
def refresh(db: Session = Depends(get_db)):
    try:
        return services.force_refresh(db)
    except Exception as exc:
        logger.exception("추천 재계산 실패")
        raise HTTPException(status_code=502, detail=f"추천 재계산에 실패했습니다: {exc}") from exc
