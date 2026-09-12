from __future__ import annotations

import logging
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .db import init_db
from .routers import cron, eod, limitup, recommendations, subscriptions
from .scheduler import start_scheduler

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="주식 추천 앱")

app.include_router(recommendations.router)
app.include_router(subscriptions.router)
app.include_router(cron.router)
app.include_router(eod.router)
app.include_router(limitup.router)


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    start_scheduler()


if getattr(sys, "frozen", False):
    # PyInstaller로 패키징된 실행 파일: 번들된 리소스 경로(sys._MEIPASS) 기준
    FRONTEND_DIR = Path(sys._MEIPASS) / "frontend"  # type: ignore[attr-defined]
else:
    FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"

if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
