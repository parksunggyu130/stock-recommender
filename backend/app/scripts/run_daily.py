"""서버 없이(GitHub Actions 등) 07시 작업(추천 계산 + 알림)을 1회 실행하는 진입점.

사용법 (backend 디렉터리에서):
    python -m app.scripts.run_daily
"""
import logging

from ..db import init_db
from ..services import run_daily_job


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    init_db()
    result = run_daily_job()
    logging.info("run_daily result: %s", result)


if __name__ == "__main__":
    main()
