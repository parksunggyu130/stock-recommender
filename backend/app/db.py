import logging
import os
import tempfile
from contextlib import contextmanager

import requests
from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker

from .config import settings

logger = logging.getLogger(__name__)

connect_args = {"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(settings.DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

# Base.metadata.create_all()은 없는 "테이블"만 새로 만들고, 이미 존재하는 테이블에 새
# 컬럼을 추가해주지는 않는다. Alembic 같은 별도 마이그레이션 도구 없이 SQLite를 쓰는
# 이 프로젝트 특성상, 기존 배포에 새 컬럼이 생길 때마다 여기에 추가해 기동 시 보정한다.
_SQLITE_COLUMN_MIGRATIONS = {
    "daily_recommendations": [
        ("precursor_candidates_json", "TEXT"),
        ("gap_top3_json", "TEXT"),
    ],
}


def _migrate_sqlite_columns() -> None:
    if not settings.DATABASE_URL.startswith("sqlite"):
        return
    with engine.begin() as conn:
        for table, columns in _SQLITE_COLUMN_MIGRATIONS.items():
            existing = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}
            for name, col_type in columns:
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {col_type}"))


def init_db() -> None:
    from . import models  # noqa: F401 (모델 등록을 위해 import)
    Base.metadata.create_all(bind=engine)
    _migrate_sqlite_columns()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def github_data_session():
    """GitHub `data` 브랜치에 누적된 최신 data.db를 내려받아 별도(임시) 읽기 전용 세션으로 연다.

    Render 등 무료 호스팅의 로컬 DB(`SessionLocal`이 쓰는 것)는 재배포마다 초기화되지만,
    GitHub Actions가 커밋해두는 이 파일은 계속 누적되므로 승률/상한가 조짐 통계처럼
    "누적"이 의미 있는 조회 API는 로컬 DB 대신 이걸 읽어야 정확하다. 앱 자체의 `engine`/
    `SessionLocal`과는 완전히 분리된 일회성 임시 엔진이라, 로컬 DB 상태에 영향을 주지 않는다.
    다운로드 실패(네트워크 오류, data 브랜치/파일이 아직 없음 등) 시 None을 yield한다 —
    호출부에서 로컬 DB로 폴백할지 결정한다.
    """
    tmp_path = None
    try:
        resp = requests.get(settings.GITHUB_DATA_DB_URL, timeout=15)
        if resp.status_code != 200 or not resp.content:
            yield None
            return

        fd, tmp_path = tempfile.mkstemp(suffix=".db")
        with os.fdopen(fd, "wb") as f:
            f.write(resp.content)

        remote_engine = create_engine(f"sqlite:///{tmp_path}", connect_args={"check_same_thread": False})
        RemoteSession = sessionmaker(bind=remote_engine, autoflush=False, autocommit=False)
        session = RemoteSession()
        try:
            yield session
        finally:
            session.close()
            remote_engine.dispose()
    except requests.RequestException:
        logger.warning("GitHub data.db 다운로드 실패 — 로컬 DB로 폴백")
        yield None
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)
