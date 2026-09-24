"""서버 없이(GitHub Actions 등) 16시 마감 체크 작업을 1회 실행하는 진입점.

사용법 (backend 디렉터리에서):
    python -m app.scripts.run_eod
"""
import logging

from ..db import init_db
from ..services import run_eod_job


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    init_db()
    result = run_eod_job()
    logging.info("run_eod result: %s", result)


if __name__ == "__main__":
    main()
