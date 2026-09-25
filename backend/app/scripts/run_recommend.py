"""서버 없이(GitHub Actions 등) 16시 추천 작업(스크리닝 + 상한가 스캔 + 알림)을 1회 실행하는 진입점.

사용법 (backend 디렉터리에서):
    python -m app.scripts.run_recommend
"""
import logging

from ..db import init_db
from ..services import run_recommend_job


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    init_db()
    result = run_recommend_job()
    logging.info("run_recommend result: %s", result)


if __name__ == "__main__":
    main()
