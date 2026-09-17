from sqlalchemy import Column, Integer, String, Text, DateTime, Float, UniqueConstraint
from sqlalchemy.sql import func

from .db import Base


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"

    id = Column(Integer, primary_key=True)
    endpoint = Column(String(1024), unique=True, nullable=False)
    p256dh = Column(String(512), nullable=False)
    auth = Column(String(512), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class DailyRecommendation(Base):
    __tablename__ = "daily_recommendations"
    __table_args__ = (UniqueConstraint("date", name="uq_daily_recommendation_date"),)

    id = Column(Integer, primary_key=True)
    date = Column(String(10), nullable=False, index=True)  # YYYY-MM-DD
    trading_date = Column(String(8), nullable=False)  # YYYYMMDD (실제 데이터 기준일)
    top10_json = Column(Text, nullable=False)
    top3_json = Column(Text, nullable=False)
    notified = Column(Integer, default=0)  # 0/1, 오늘자 07시 알림 발송 여부
    eod_json = Column(Text, nullable=True)  # 16시 마감 체크 결과 (top3 등락률 등)
    eod_notified = Column(Integer, default=0)  # 0/1, 16시 마감 알림 발송 여부
    precursor_candidates_json = Column(Text, nullable=True)  # 07시 "상한가 조짐" 후보 (data/analysis/limitup.py)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class LimitUpEvent(Base):
    """상한가(+30%) 종목 이벤트 기록. 오래 쌓일수록 '징조' 통계 분석이 정교해진다."""

    __tablename__ = "limit_up_events"
    __table_args__ = (UniqueConstraint("trading_date", "ticker", name="uq_limit_up_event"),)

    id = Column(Integer, primary_key=True)
    date = Column(String(10), nullable=False, index=True)  # YYYY-MM-DD
    trading_date = Column(String(8), nullable=False, index=True)  # YYYYMMDD
    ticker = Column(String(16), nullable=False)
    name = Column(String(64), nullable=False)
    close_price = Column(Integer, nullable=False)
    change_pct = Column(Float, nullable=False)
    reason_headlines_json = Column(Text, nullable=False, default="[]")
    reason_keywords_json = Column(Text, nullable=False, default="[]")
    precursor_json = Column(Text, nullable=False, default="[]")  # 상한가 이전 최대 5거래일 지표 스냅샷
    created_at = Column(DateTime(timezone=True), server_default=func.now())
