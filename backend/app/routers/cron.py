from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException

from .. import services
from ..config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/cron", tags=["cron"])


def _run_recommend_background() -> None:
    try:
        result = services.run_recommend_job()
        logger.info("크론(daily) 작업 완료: %s", result)
    except Exception:
        logger.exception("크론(daily) 작업 실패")


def _run_morning_check_background() -> None:
    try:
        result = services.run_morning_check_job()
        logger.info("크론(eod) 작업 완료: %s", result)
    except Exception:
        logger.exception("크론(eod) 작업 실패")


@router.post("/daily")
def run_daily(background_tasks: BackgroundTasks, x_cron_secret: str | None = Header(default=None)):
    """외부 무료 크론(cron-job.org 등)이 매일 16:00 KST에 호출하는 엔드포인트
    (현재는 GitHub Actions 워크플로가 이 역할을 대신하며, 이 엔드포인트는 수동/백업용으로 남겨둠).

    무료 호스팅은 트래픽이 없으면 잠들 수 있어 인프로세스 스케줄러가 못 돌 수 있다.
    500종목 스캔은 배포 환경에 따라 수십 초 이상 걸릴 수 있어, 크론 클라이언트의
    응답 대기 타임아웃으로 연결이 끊겨도 작업이 중간에 끊기지 않도록 실제 계산은
    백그라운드로 돌리고 이 요청 자체는 즉시 응답한다.
    """
    if x_cron_secret != settings.CRON_SECRET:
        raise HTTPException(status_code=401, detail="잘못된 크론 시크릿입니다")
    background_tasks.add_task(_run_recommend_background)
    return {"status": "accepted"}


@router.post("/eod")
def run_eod(background_tasks: BackgroundTasks, x_cron_secret: str | None = Header(default=None)):
    """외부 무료 크론이 매일 10:00 KST(전 거래일 16시 추천 성과체크)에 호출하는 엔드포인트.
    (daily와 동일한 이유로 백그라운드 실행. 현재는 GitHub Actions가 이 역할을 대신함)
    """
    if x_cron_secret != settings.CRON_SECRET:
        raise HTTPException(status_code=401, detail="잘못된 크론 시크릿입니다")
    background_tasks.add_task(_run_morning_check_background)
    return {"status": "accepted"}
