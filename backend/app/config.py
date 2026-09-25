import os
from pathlib import Path

from dotenv import load_dotenv

# 실행 파일(run.py -> .exe)로 패키징했을 때는 run.py가 APP_BASE_DIR을
# exe가 있는 폴더로 지정해준다. 그 외(개발 중 `uvicorn app.main:app`으로 실행)에는
# backend/ 디렉터리를 기준으로 삼는다.
BASE_DIR = Path(os.environ.get("APP_BASE_DIR", Path(__file__).resolve().parent.parent))

load_dotenv(BASE_DIR / ".env")


def _bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


class Settings:
    BASE_DIR: Path = BASE_DIR
    DATABASE_URL: str = os.getenv("DATABASE_URL") or f"sqlite:///{(BASE_DIR / 'data.db').as_posix()}"
    UNIVERSE_SIZE: int = int(os.getenv("UNIVERSE_SIZE", "500"))

    NAVER_CLIENT_ID: str = os.getenv("NAVER_CLIENT_ID", "")
    NAVER_CLIENT_SECRET: str = os.getenv("NAVER_CLIENT_SECRET", "")

    VAPID_PUBLIC_KEY: str = os.getenv("VAPID_PUBLIC_KEY", "")
    VAPID_PRIVATE_KEY: str = os.getenv("VAPID_PRIVATE_KEY", "")
    VAPID_CONTACT_EMAIL: str = os.getenv("VAPID_CONTACT_EMAIL", "mailto:example@example.com")

    # (선택) 디스코드 웹후크 URL — 설정하면 07시/16시 알림을 디스코드로도 보낸다.
    # 브라우저 푸시(VAPID)보다 설정이 훨씬 간단하고, HTTPS가 아니어도 동작한다.
    DISCORD_WEBHOOK_URL: str = os.getenv("DISCORD_WEBHOOK_URL", "")

    CRON_SECRET: str = os.getenv("CRON_SECRET", "change-this-secret")
    RUN_INPROCESS_SCHEDULER: bool = _bool("RUN_INPROCESS_SCHEDULER", True)

    # GitHub Actions가 `data` 브랜치에 커밋해두는 누적 data.db의 raw URL.
    # 승률/상한가 조짐 통계처럼 "누적"이 의미 있는 조회 API는 이 파일을 내려받아 읽는다
    # (Render 등 무료 호스팅의 로컬 DB는 재배포마다 초기화되어 누적 통계를 담을 수 없음).
    GITHUB_DATA_DB_URL: str = os.getenv(
        "GITHUB_DATA_DB_URL",
        "https://raw.githubusercontent.com/parksunggyu130/stock-recommender/data/data.db",
    )

    TOP_N_UNIVERSE_RESULT: int = 10
    TOP_N_FINAL: int = 3
    TECH_WEIGHT: float = 0.7
    NEWS_WEIGHT: float = 0.3


settings = Settings()
