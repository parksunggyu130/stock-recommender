from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from .. import services
from ..config import settings
from ..db import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/cron", tags=["cron"])


@router.post("/daily")
def run_daily(db: Session = Depends(get_db), x_cron_secret: str | None = Header(default=None)):
    """외부 무료 크론(cron-job.org 등)이 매일 07:00 KST에 호출하는 엔드포인트.

    무료 호스팅은 트래픽이 없으면 잠들 수 있어 인프로세스 스케줄러가 못 돌 수 있다.
    이 엔드포인트를 호출하면 서버가 깨어나며 당일 추천을 계산/저장하고,
    (아직 발송 전이라면) 구독자에게 푸시 알림을 보낸다.
    """
    if x_cron_secret != settings.CRON_SECRET:
        raise HTTPException(status_code=401, detail="잘못된 크론 시크릿입니다")
    try:
        return services.run_and_notify(db)
    except Exception as exc:
        logger.exception("크론 실행 실패")
        raise HTTPException(status_code=502, detail=f"크론 실행 실패: {exc}") from exc


@router.post("/eod")
def run_eod(db: Session = Depends(get_db), x_cron_secret: str | None = Header(default=None)):
    """외부 무료 크론이 매일 16:00 KST에 호출하는 엔드포인트.

    당일 추천 top3의 마감 등락률을 계산하고, 상한가(+30%) 종목을 스캔해
    뉴스 기반 추정 사유와 사전 5거래일 지표(징조)를 기록한 뒤 푸시 알림을 보낸다.
    """
    if x_cron_secret != settings.CRON_SECRET:
        raise HTTPException(status_code=401, detail="잘못된 크론 시크릿입니다")
    try:
        return services.eod_run_and_notify(db)
    except Exception as exc:
        logger.exception("마감 크론 실행 실패")
        raise HTTPException(status_code=502, detail=f"마감 크론 실행 실패: {exc}") from exc
