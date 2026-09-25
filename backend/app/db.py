from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker

from .config import settings

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
