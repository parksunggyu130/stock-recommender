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
        "gap_top3": json.loads(row.gap_top3_json) if row.gap_top3_json else [],
        "notified": bool(row.notified),
        "precursor_candidates": (
            json.loads(row.precursor_candidates_json)
            if row.precursor_candidates_json
            else {"enabled": False, "candidates": []}
        ),
    }


def _compute_precursor_candidates_json(db: Session, result: dict) -> str:
    """오늘 전체 스캔 결과와 누적된 상한가 이벤트를 비교해 '상한가 조짐' 후보를 찾는다.

    표본(상한가 이벤트)이 limitup.MIN_EVENTS_FOR_PRECURSOR_MATCH 미만이면 통계적으로
    신뢰할 수 없어 자동으로 빈 결과를 낸다 — 데이터가 쌓일수록 자연히 켜진다.
    """
    events = db.query(LimitUpEvent).all()
    candidates = limitup.find_precursor_candidates(result.get("universe_scored", []), events)
    return json.dumps(candidates, ensure_ascii=False)


def _save(db: Session, result: dict, existing: DailyRecommendation | None) -> DailyRecommendation:
    precursor_json = _compute_precursor_candidates_json(db, result)
    gap_top3_json = json.dumps(result.get("gap_top3", []), ensure_ascii=False)
    if existing is None:
        row = DailyRecommendation(
            date=result["date"],
            trading_date=result["trading_date"],
            top10_json=json.dumps(result["top10"], ensure_ascii=False),
            top3_json=json.dumps(result["top3"], ensure_ascii=False),
            gap_top3_json=gap_top3_json,
            notified=0,
            precursor_candidates_json=precursor_json,
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
        row.gap_top3_json = gap_top3_json
        row.precursor_candidates_json = precursor_json
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


def _format_precursor_section(precursor_candidates_json: str | None) -> str:
    """07시 알림에 붙일 '상한가 조짐' 후보 섹션. 표본 부족 등으로 꺼져있으면 빈 문자열."""
    if not precursor_candidates_json:
        return ""
    data = json.loads(precursor_candidates_json)
    candidates = data.get("candidates") or []
    if not candidates:
        return ""
    names = ", ".join(f"{c['name']}({c['ticker']})" for c in candidates)
    return (
        f"\n\n🔮 상한가 조짐 후보(참고용, top3와 별개 — 과거 상한가 전날 패턴과 유사, "
        f"표본 {data.get('total_events')}건 기반 추정): {names}"
    )


def _format_top3_with_reasons(top3: list[dict], reasons_key: str = "reasons") -> str:
    lines = []
    for i, s in enumerate(top3, start=1):
        reasons = ", ".join(s.get(reasons_key) or []) or "조건 없음"
        lines.append(f"{i}. {s['name']}({s['ticker']}) — {reasons}")
    return "\n".join(lines)


def _format_gap_section(gap_top3: list[dict]) -> str:
    """16시 알림에 붙일 '익일 갭상승 후보' 섹션(메인 top3와 별개 스코어링). 후보가 없으면 빈 문자열."""
    if not gap_top3:
        return ""
    return "\n\n📈 익일 갭상승 후보(오늘 캔들 특징 기반, top3와 별개):\n" + _format_top3_with_reasons(
        gap_top3, reasons_key="gap_reasons"
    )


def run_and_notify(db: Session) -> dict:
    """매일 16:00 스케줄러 / 외부 크론이 호출: 그날 종가 기준 스크리닝(시간외매매 매수 가능)
    + 상한가 스캔/기록 + 아직 안 보냈으면 푸시 발송.

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

    # 상한가 스캔/조짐 기록은 알림 발송 여부와 무관하게 항상 최신 상태로 유지한다
    # (재실행돼도 이미 기록된 이벤트는 건드리지 않음 — _scan_limit_up이 자체적으로 멱등).
    snapshot = krx.get_full_market_snapshot()
    trading_date = krx.get_latest_trading_date(snapshot)
    limit_up = _scan_limit_up(db, snapshot, trading_date)

    if row.notified:
        return {"status": "already_notified", "date": row.date, "limit_up": limit_up}

    top3 = json.loads(row.top3_json)
    gap_top3 = json.loads(row.gap_top3_json) if row.gap_top3_json else []
    top3_text = _format_top3_with_reasons(top3)
    payload = {
        "title": "오늘 16시 종가 기준 추천 (시간외매매 매수 가능)",
        "body": (
            f"{top3_text}\n※ 투자 참고용, 투자 권유 아님"
            f"{_format_gap_section(gap_top3)}"
            f"{_format_limit_up_section(limit_up)}"
            f"{_format_precursor_section(row.precursor_candidates_json)}"
        ),
        "url": "/",
    }
    notify_result = _notify(db, payload)

    row.notified = 1
    db.commit()

    return {"status": "notified", "date": row.date, "limit_up": limit_up, **notify_result}


def run_recommend_job() -> dict:
    """DB 세션을 직접 열고 닫으며 16시 추천 작업을 실행한다.

    인프로세스 스케줄러와 GitHub Actions 워크플로가 공용으로 쓴다
    (요청 스코프 세션에 의존하지 않아야, 백그라운드로 넘어가도 안전하게 동작한다).
    """
    db = SessionLocal()
    try:
        return run_and_notify(db)
    finally:
        db.close()


# ---- 16:00 상한가 스캔/사유 분석/징조 기록 (recommend 잡에서 공용으로 씀) ----


def _event_to_dict(ev: LimitUpEvent) -> dict:
    return {
        "ticker": ev.ticker,
        "name": ev.name,
        "close_price": ev.close_price,
        "change_pct": ev.change_pct,
        "headlines": json.loads(ev.reason_headlines_json),
        "keywords": json.loads(ev.reason_keywords_json),
    }


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


def _compute_set_performance(snap_by_ticker: dict, items: list[dict]) -> list[dict]:
    """추천 종목 리스트(top3 또는 gap_top3)의 현재가 기준 등락률을 계산한다."""
    results = []
    for s in items:
        cur = snap_by_ticker.get(s["ticker"])
        if not cur:
            continue
        rec_price = s["close"]  # 16시 추천 당시 기준가(그날 종가)
        current_price = cur["close_price"]
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
    return results


def _format_perf_set(label: str, perf_set: dict) -> str:
    results = perf_set["results"]
    if not results:
        return f"[{label}] 기록 없음"
    text = ", ".join(f"{r['name']} {r['change_pct']:+.2f}%" for r in results)
    sim = perf_set.get("simulation")
    sim_text = ""
    if sim:
        sign = "+" if sim["profit"] >= 0 else ""
        sim_text = f" → 1,000만원 투자 시 {sign}{sim['profit']:,}원({sign}{sim['profit_pct']}%)"
    return f"[{label}] {text}{sim_text}"


def _build_morning_check_payload(performance: dict) -> dict:
    body = (
        f"{performance['recommended_date']} 16시 추천 성과 (오늘 10시 기준)\n"
        f"{_format_perf_set('메인 top3', performance['main'])}\n"
        f"{_format_perf_set('갭상승 후보', performance['gap'])}"
    )
    return {"title": "어제 추천 성과 체크", "body": body, "url": "/"}


def _format_limit_up_section(limit_up: list[dict], max_stocks: int = 5) -> str:
    """상한가 종목별 뉴스 기반 추정 사유(키워드/헤드라인)를 디스코드용 텍스트로 정리한다."""
    if not limit_up:
        return ""

    lines = [f"\n🚀 오늘 상한가 ({len(limit_up)}종목):"]
    for e in limit_up[:max_stocks]:
        keywords = ", ".join(e["keywords"][:3]) if e["keywords"] else "관련 키워드 없음"
        if e["headlines"]:
            headline = e["headlines"][0]
            if len(headline) > 40:
                headline = headline[:40] + "…"
            headline_part = f'\n  "{headline}"'
        else:
            headline_part = ""
        lines.append(f"· {e['name']}({e['ticker']}) {e['change_pct']:+.2f}% — {keywords}{headline_part}")

    if len(limit_up) > max_stocks:
        lines.append(f"…외 {len(limit_up) - max_stocks}종목 (앱에서 전체 확인)")
    lines.append("(뉴스 검색 기반 추정 사유이며 실제 원인과 다를 수 있음)")
    return "\n".join(lines)


def _find_pending_morning_check(db: Session) -> DailyRecommendation | None:
    """아직 성과체크(eod_notified) 안 된, 오늘 이전 날짜 중 가장 최근 추천 행을 찾는다.

    "오늘 이전 중 가장 최근"으로 찾기 때문에 주말/공휴일로 며칠 비어도, 혹은 체크가
    하루 밀려도 자연스럽게 "그다음으로 아직 안 본 가장 최근 추천"을 찾아준다.
    """
    return (
        db.query(DailyRecommendation)
        .filter(DailyRecommendation.date < _today_str(), DailyRecommendation.eod_notified == 0)
        .order_by(DailyRecommendation.date.desc())
        .first()
    )


def eod_compute(db: Session) -> dict:
    """수동 '지금 성과 체크': 가장 최근 추천(메인 top3 + 갭상승 후보)의 현재가 기준 성과 +
    상한가 스캔/기록. 알림은 보내지 않고, 성과체크 완료 처리(eod_notified)도 하지 않는다
    (자동 잡의 멱등성에 영향을 주지 않기 위함 — "지금 마감 체크"는 언제든 눌러도 안전해야 함)."""
    snapshot = krx.get_full_market_snapshot()
    trading_date = krx.get_latest_trading_date(snapshot)
    snap_by_ticker = {r["ticker"]: r for r in snapshot}

    rec = _find_pending_morning_check(db) or (
        db.query(DailyRecommendation).order_by(DailyRecommendation.date.desc()).first()
    )
    performance = None
    if rec is not None:
        top3 = json.loads(rec.top3_json)
        gap_top3 = json.loads(rec.gap_top3_json) if rec.gap_top3_json else []
        main_results = _compute_set_performance(snap_by_ticker, top3)
        gap_results = _compute_set_performance(snap_by_ticker, gap_top3)
        performance = {
            "recommended_date": rec.date,
            "main": {"results": main_results, "simulation": _simulate_virtual_portfolio(main_results)},
            "gap": {"results": gap_results, "simulation": _simulate_virtual_portfolio(gap_results)},
        }

    limit_up = _scan_limit_up(db, snapshot, trading_date)

    return {"trading_date": trading_date, "performance": performance, "limit_up": limit_up}


def morning_check_and_notify(db: Session) -> dict:
    """매일 10:00 스케줄러 / GitHub Actions가 호출: 전 거래일 16시 추천(top3 + 갭상승 후보)의
    현재가 기준 성과 + 1,000만원 가상투자 시뮬레이션을 계산해 아직 안 보냈으면 푸시 발송.

    주말(토/일)에는 새로 볼 장이 없어 알림을 보내지 않고 건너뛴다 — 금요일 16시 추천은
    자동으로 다음 거래일인 월요일 10시에 체크된다(_find_pending_morning_check 참고).
    """
    if _is_weekend(_kst_today()):
        return {"status": "skipped_weekend", "date": _today_str()}

    rec = _find_pending_morning_check(db)
    if rec is None:
        return {"status": "no_pending_recommendation"}

    snapshot = krx.get_full_market_snapshot()
    snap_by_ticker = {r["ticker"]: r for r in snapshot}
    top3 = json.loads(rec.top3_json)
    gap_top3 = json.loads(rec.gap_top3_json) if rec.gap_top3_json else []

    main_results = _compute_set_performance(snap_by_ticker, top3)
    gap_results = _compute_set_performance(snap_by_ticker, gap_top3)
    performance = {
        "recommended_date": rec.date,
        "main": {"results": main_results, "simulation": _simulate_virtual_portfolio(main_results)},
        "gap": {"results": gap_results, "simulation": _simulate_virtual_portfolio(gap_results)},
    }
    rec.eod_json = json.dumps(performance, ensure_ascii=False)
    db.commit()

    payload = _build_morning_check_payload(performance)
    notify_result = _notify(db, payload)

    rec.eod_notified = 1
    db.commit()

    return {"status": "notified", **performance, **notify_result}


def run_morning_check_job() -> dict:
    """DB 세션을 직접 열고 닫으며 10시 성과체크 작업을 실행한다 (run_recommend_job과 동일한 이유)."""
    db = SessionLocal()
    try:
        return morning_check_and_notify(db)
    finally:
        db.close()


def get_performance_latest(db: Session) -> dict | None:
    """가장 최근에 성과체크가 완료된 추천의 결과(메인 top3 + 갭상승 후보)를 반환한다."""
    rec = (
        db.query(DailyRecommendation)
        .filter(DailyRecommendation.eod_json.isnot(None))
        .order_by(DailyRecommendation.date.desc())
        .first()
    )
    if rec is None:
        return None
    return json.loads(rec.eod_json)


def _summarize_win_rate(results: list[dict]) -> dict:
    wins = sum(1 for r in results if r["change_pct"] > 0)
    losses = sum(1 for r in results if r["change_pct"] < 0)
    flat = sum(1 for r in results if r["change_pct"] == 0)
    decided = wins + losses
    win_rate = round(wins / decided * 100, 1) if decided else None
    return {"wins": wins, "losses": losses, "flat": flat, "total": len(results), "win_rate": win_rate}


def get_win_rate_stats(db: Session) -> dict:
    """지금까지 누적된 성과체크 결과로 메인 top3 / 갭상승 후보 각각의 승률을 계산한다.

    승 = 등락률 > 0, 패 = 등락률 < 0. 등락률이 정확히 0%인 건(주로 휴장일 등 데이터 특성)은
    무승부로 집계만 하고 승률(win_rate) 계산에서는 제외한다(분모를 왜곡하지 않기 위함).
    """
    rows = (
        db.query(DailyRecommendation)
        .filter(DailyRecommendation.eod_json.isnot(None))
        .order_by(DailyRecommendation.date.asc())
        .all()
    )

    main_results: list[dict] = []
    gap_results: list[dict] = []
    for row in rows:
        perf = json.loads(row.eod_json)
        main_results.extend(perf.get("main", {}).get("results", []))
        gap_results.extend(perf.get("gap", {}).get("results", []))

    return {
        "sample_days": len(rows),
        "main": _summarize_win_rate(main_results),
        "gap": _summarize_win_rate(gap_results),
    }


def get_limit_up_today(db: Session) -> list[dict]:
    today = _today_str()
    events = db.query(LimitUpEvent).filter_by(date=today).all()
    return [_event_to_dict(ev) for ev in events]


def get_precursor_stats(db: Session) -> dict:
    events = db.query(LimitUpEvent).all()
    return limitup.aggregate_precursor_stats(events)
