"""추천 계산 결과의 저장/조회/알림 발송을 담당하는 공용 서비스 레이어.

라우터(recommendations/cron)와 스케줄러가 동일한 로직을 재사용한다.
"""
from __future__ import annotations

import datetime
import json
import logging
import zoneinfo

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .analysis import limitup
from .analysis.screener import run_daily_pipeline
from .data import krx, news
from .db import SessionLocal
from .models import DailyRecommendation, LimitUpEvent
from .notify import discord, push

logger = logging.getLogger(__name__)

_KST = zoneinfo.ZoneInfo("Asia/Seoul")
SIMULATION_SEED_KRW = 10_000_000  # 가상 투자 시뮬레이션 시드 금액 (1,000만원)


def _simulate_virtual_portfolio(results: list[dict]) -> dict | None:
    """오늘 추천 3종목을 07시 기준가에 '가상으로 매수'해서 16시 종가에 '매도'했다면
    1,000만원이 얼마가 됐을지 계산한다 (수수료·세금·슬리피지 미반영, 종목별 균등 배분).
    """
    if not results:
        return None

    budget_per_stock = SIMULATION_SEED_KRW / len(results)
    holdings = []
    total_cost = 0
    total_value = 0
    for r in results:
        buy_price = r["rec_price"]
        sell_price = r["current_price"]
        if not buy_price:
            continue
        shares = int(budget_per_stock // buy_price)
        cost = shares * buy_price
        value = shares * sell_price
        total_cost += cost
        total_value += value
        holdings.append(
            {
                "ticker": r["ticker"],
                "name": r["name"],
                "shares": shares,
                "buy_price": buy_price,
                "sell_price": sell_price,
                "cost": int(cost),
                "value": int(value),
            }
        )

    leftover_cash = SIMULATION_SEED_KRW - total_cost  # 주가가 배분액보다 커서 못 산 잔액
    final_value = int(total_value + leftover_cash)
    profit = final_value - SIMULATION_SEED_KRW

    return {
        "seed": SIMULATION_SEED_KRW,
        "final_value": final_value,
        "profit": profit,
        "profit_pct": round(profit / SIMULATION_SEED_KRW * 100, 2),
        "holdings": holdings,
    }


def _notify(db: Session, payload: dict) -> dict:
    """웹푸시(VAPID) 구독자 + (설정된 경우) 디스코드 웹후크로 함께 발송한다."""
    result = push.notify_all(db, payload)
    if discord.is_configured():
        result["discord_sent"] = discord.send(payload)
    return result


def _kst_today() -> datetime.date:
    """서버가 어느 시간대(UTC 등)에서 돌아가든 한국 날짜 기준으로 '오늘'을 계산한다."""
    return datetime.datetime.now(_KST).date()


def _is_weekend(day: datetime.date) -> bool:
    return day.weekday() >= 5  # 5=토요일, 6=일요일


def _today_str() -> str:
    return _kst_today().isoformat()


def _row_to_dict(row: DailyRecommendation) -> dict:
    return {
        "date": row.date,
        "trading_date": row.trading_date,
        "top10": json.loads(row.top10_json),
        "top3": json.loads(row.top3_json),
        "notified": bool(row.notified),
    }


def _save(db: Session, result: dict, existing: DailyRecommendation | None) -> DailyRecommendation:
    if existing is None:
        row = DailyRecommendation(
            date=result["date"],
            trading_date=result["trading_date"],
            top10_json=json.dumps(result["top10"], ensure_ascii=False),
            top3_json=json.dumps(result["top3"], ensure_ascii=False),
            notified=0,
        )
        db.add(row)
        try:
            db.commit()
        except IntegrityError:
            # 동시에 들어온 다른 요청이 같은 날짜 행을 먼저 만든 경우: 그 결과를 그대로 사용
            db.rollback()
            row = db.query(DailyRecommendation).filter_by(date=result["date"]).first()
            if row is None:
                raise
            return row
    else:
        row = existing
        row.trading_date = result["trading_date"]
        row.top10_json = json.dumps(result["top10"], ensure_ascii=False)
        row.top3_json = json.dumps(result["top3"], ensure_ascii=False)
        db.commit()
    db.refresh(row)
    return row


def get_today(db: Session) -> dict:
    """오늘자 추천을 반환. 없으면 새로 계산해서 저장한다 (알림은 보내지 않음)."""
    existing = db.query(DailyRecommendation).filter_by(date=_today_str()).first()
    if existing:
        return _row_to_dict(existing)
    result = run_daily_pipeline()
    row = _save(db, result, None)
    return _row_to_dict(row)


def force_refresh(db: Session) -> dict:
    """사용자가 '지금 추천받기'를 누른 경우: 항상 재계산. 알림은 보내지 않는다."""
    existing = db.query(DailyRecommendation).filter_by(date=_today_str()).first()
    result = run_daily_pipeline()
    row = _save(db, result, existing)
    return _row_to_dict(row)


def run_and_notify(db: Session) -> dict:
    """매일 07:00 스케줄러 / 외부 크론이 호출: 계산 + 아직 안 보냈으면 푸시 발송.

    주말(토/일)에는 새로 열리는 장이 없어 알림을 보내지 않고 건너뛴다.
    ("지금 추천받기" 수동 버튼은 주말에도 직전 거래일 데이터를 그대로 보여준다.)
    """
    if _is_weekend(_kst_today()):
        return {"status": "skipped_weekend", "date": _today_str()}

    existing = db.query(DailyRecommendation).filter_by(date=_today_str()).first()
    if existing is None:
        result = run_daily_pipeline()
        row = _save(db, result, None)
    else:
        row = existing

    if row.notified:
        return {"status": "already_notified", "date": row.date}

    top3 = json.loads(row.top3_json)
    names = ", ".join(f"{s['name']}({s['ticker']})" for s in top3)
    payload = {
        "title": "오늘의 추천 종목 3",
        "body": f"{names}\n※ 투자 참고용, 투자 권유 아님",
        "url": "/",
    }
    notify_result = _notify(db, payload)

    row.notified = 1
    db.commit()

    return {"status": "notified", "date": row.date, **notify_result}


def run_daily_job() -> dict:
    """DB 세션을 직접 열고 닫으며 07시 작업을 실행한다.

    인프로세스 스케줄러와 크론 엔드포인트의 백그라운드 태스크가 공용으로 쓴다
    (요청 스코프 세션에 의존하지 않아야, 백그라운드로 넘어가도 안전하게 동작한다).
    """
    db = SessionLocal()
    try:
        return run_and_notify(db)
    finally:
        db.close()


# ---- 16:00 마감 체크: 추천 성과 + 상한가 스캔/사유 분석/징조 기록 ----


def _event_to_dict(ev: LimitUpEvent) -> dict:
    return {
        "ticker": ev.ticker,
        "name": ev.name,
        "close_price": ev.close_price,
        "change_pct": ev.change_pct,
        "headlines": json.loads(ev.reason_headlines_json),
        "keywords": json.loads(ev.reason_keywords_json),
    }


def _check_performance(db: Session, snapshot: list[dict], trading_date: str) -> dict | None:
    rec = db.query(DailyRecommendation).filter_by(date=_today_str()).first()
    if rec is None:
        return None

    snap_by_ticker = {r["ticker"]: r for r in snapshot}
    top3 = json.loads(rec.top3_json)
    results = []
    for s in top3:
        cur = snap_by_ticker.get(s["ticker"])
        if not cur:
            continue
        rec_price = s["close"]  # 07시 추천 당시 기준가(직전 거래일 종가)
        current_price = cur["close_price"]
        # 스냅샷의 fluctuationsRatio(전일 대비 등락률)가 아니라, 추천가 대비로 직접 계산해야
        # "추천 시점 대비 등락률"이라는 의미와 항상 정확히 일치한다.
        change_pct = round((current_price - rec_price) / rec_price * 100, 2) if rec_price else 0.0
        results.append(
            {
                "ticker": s["ticker"],
                "name": s["name"],
                "rec_price": rec_price,
                "current_price": current_price,
                "change_pct": change_pct,
            }
        )

    simulation = _simulate_virtual_portfolio(results)
    performance = {"trading_date": trading_date, "results": results, "simulation": simulation}
    rec.eod_json = json.dumps(performance, ensure_ascii=False)
    db.commit()
    return performance


def _scan_limit_up(db: Session, snapshot: list[dict], trading_date: str) -> list[dict]:
    summaries = []
    for row in krx.get_limit_up_stocks(snapshot):
        existing = (
            db.query(LimitUpEvent)
            .filter_by(trading_date=trading_date, ticker=row["ticker"])
            .first()
        )
        if existing:
            summaries.append(_event_to_dict(existing))
            continue

        reason = news.find_reason(row["name"])
        precursor = limitup.compute_precursor(row["ticker"], trading_date)
        event = LimitUpEvent(
            date=_today_str(),
            trading_date=trading_date,
            ticker=row["ticker"],
            name=row["name"],
            close_price=row["close_price"],
            change_pct=row["change_pct"],
            reason_headlines_json=json.dumps(reason["headlines"], ensure_ascii=False),
            reason_keywords_json=json.dumps(reason["keywords"], ensure_ascii=False),
            precursor_json=json.dumps(precursor, ensure_ascii=False),
        )
        db.add(event)
        try:
            db.commit()
        except IntegrityError:
            # 동시에 들어온 다른 요청이 같은 이벤트를 먼저 기록한 경우: 그 결과를 그대로 사용
            db.rollback()
            existing = (
                db.query(LimitUpEvent)
                .filter_by(trading_date=trading_date, ticker=row["ticker"])
                .first()
            )
            if existing is None:
                raise
            summaries.append(_event_to_dict(existing))
            continue
        db.refresh(event)
        summaries.append(_event_to_dict(event))
    return summaries


def _build_eod_payload(performance: dict | None, limit_up: list[dict]) -> dict:
    if performance and performance["results"]:
        perf_text = ", ".join(f"{r['name']} {r['change_pct']:+.2f}%" for r in performance["results"])
    else:
        perf_text = "오늘 추천 기록 없음"

    sim_text = ""
    sim = performance.get("simulation") if performance else None
    if sim:
        sign = "+" if sim["profit"] >= 0 else ""
        sim_text = (
            f"\n💰 1,000만원 가상 투자 시뮬레이션(수수료 미반영): "
            f"{sign}{sim['profit']:,}원 ({sign}{sim['profit_pct']}%) "
            f"→ 평가금액 {sim['final_value']:,}원"
        )

    limitup_text = ""
    if limit_up:
        names = ", ".join(e["name"] for e in limit_up[:5])
        limitup_text = f"\n🚀 오늘 상한가: {names}"

    return {
        "title": "오늘 마감 결과",
        "body": f"[내 추천 등락률] {perf_text}{sim_text}{limitup_text}",
        "url": "/",
    }


def eod_compute(db: Session) -> dict:
    """마감 체크(성과 계산 + 상한가 스캔/사유분석/징조기록). 알림은 보내지 않는다."""
    snapshot = krx.get_full_market_snapshot()
    trading_date = krx.get_latest_trading_date(snapshot)

    performance = _check_performance(db, snapshot, trading_date)
    limit_up = _scan_limit_up(db, snapshot, trading_date)

    return {"trading_date": trading_date, "performance": performance, "limit_up": limit_up}


def eod_run_and_notify(db: Session) -> dict:
    """매일 16:00 스케줄러 / 외부 크론이 호출: 마감 체크 + 아직 안 보냈으면 푸시 발송.

    주말(토/일)에는 마감 자체가 없어 알림을 보내지 않고 건너뛴다.
    """
    if _is_weekend(_kst_today()):
        return {"status": "skipped_weekend", "date": _today_str()}

    result = eod_compute(db)

    rec = db.query(DailyRecommendation).filter_by(date=_today_str()).first()
    if rec is None:
        return {"status": "no_recommendation_today", **result}
    if rec.eod_notified:
        return {"status": "already_notified", **result}

    payload = _build_eod_payload(result["performance"], result["limit_up"])
    notify_result = _notify(db, payload)

    rec.eod_notified = 1
    db.commit()

    return {"status": "notified", **result, **notify_result}


def run_eod_job() -> dict:
    """DB 세션을 직접 열고 닫으며 16시 마감 작업을 실행한다 (run_daily_job과 동일한 이유)."""
    db = SessionLocal()
    try:
        return eod_run_and_notify(db)
    finally:
        db.close()


def get_performance_today(db: Session) -> dict | None:
    rec = db.query(DailyRecommendation).filter_by(date=_today_str()).first()
    if rec is None or not rec.eod_json:
        return None
    return json.loads(rec.eod_json)


def get_limit_up_today(db: Session) -> list[dict]:
    today = _today_str()
    events = db.query(LimitUpEvent).filter_by(date=today).all()
    return [_event_to_dict(ev) for ev in events]


def get_precursor_stats(db: Session) -> dict:
    events = db.query(LimitUpEvent).all()
    return limitup.aggregate_precursor_stats(events)
