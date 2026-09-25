"""서버 없이(GitHub Actions 등) 10시 성과체크 작업(전 거래일 16시 추천 성과 계산 + 알림)을
1회 실행하는 진입점.

사용법 (backend 디렉터리에서):
    python -m app.scripts.run_morning_check
"""
import logging

from ..db import init_db
from ..services import run_morning_check_job


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    init_db()
    result = run_morning_check_job()
    logging.info("run_morning_check result: %s", result)


if __name__ == "__main__":
    main()
