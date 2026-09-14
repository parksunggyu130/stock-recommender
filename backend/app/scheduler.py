from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from .config import settings
from . import services

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def _daily_job() -> None:
    try:
        result = services.run_daily_job()
        logger.info("07시 스케줄 작업 완료: %s", result)
    except Exception:
        logger.exception("07시 스케줄 작업 실패")


def _eod_job() -> None:
    try:
        result = services.run_eod_job()
        logger.info("16시 마감 체크 작업 완료: %s", result)
    except Exception:
        logger.exception("16시 마감 체크 작업 실패")


def start_scheduler() -> BackgroundScheduler | None:
    global _scheduler
    if not settings.RUN_INPROCESS_SCHEDULER:
        logger.info("RUN_INPROCESS_SCHEDULER=false - 인프로세스 스케줄러를 시작하지 않습니다")
        return None
    if _scheduler is not None:
        return _scheduler

    _scheduler = BackgroundScheduler(timezone="Asia/Seoul")
    _scheduler.add_job(_daily_job, CronTrigger(hour=7, minute=0, timezone="Asia/Seoul"), id="daily_recommendation")
    _scheduler.add_job(_eod_job, CronTrigger(hour=16, minute=0, timezone="Asia/Seoul"), id="eod_check")
    _scheduler.start()
    logger.info("인프로세스 스케줄러 시작 (매일 07:00 추천 / 16:00 마감체크, Asia/Seoul)")
    return _scheduler
