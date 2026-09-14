from __future__ import annotations

import datetime
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from ..config import settings
from ..data import krx, news
from .indicators import score_stock

logger = logging.getLogger(__name__)

# 종목별 OHLCV 조회는 네트워크 대기가 대부분이라, 병렬로 호출해야 500종목 스캔이
# (특히 원격 서버 배포 환경에서) 수 분이 아니라 수십 초 안에 끝난다.
MAX_WORKERS = 20


def _score_one(stock_info: dict, trading_date: str) -> dict | None:
    ticker = stock_info["ticker"]
    try:
        df = krx.get_recent_ohlcv(ticker, trading_date)
        result = score_stock(df)
    except Exception as exc:  # 개별 종목 실패는 건너뛰고 계속 진행
        logger.warning("스코어링 실패 %s(%s): %s", stock_info["name"], ticker, exc)
        return None
    if result is None:
        return None
    return {**stock_info, **result}


def _score_universe(universe: list[dict], trading_date: str) -> list[dict]:
    scored = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(_score_one, stock_info, trading_date) for stock_info in universe]
        for future in as_completed(futures):
            result = future.result()
            if result is not None:
                scored.append(result)
    return scored


def _rank_top_n(scored: list[dict], n: int) -> list[dict]:
    return sorted(
        scored,
        key=lambda s: (s["score"], s.get("trading_value", 0)),
        reverse=True,
    )[:n]


def _attach_news(top10: list[dict]) -> list[dict]:
    max_score = max((s["score"] for s in top10), default=1) or 1
    enriched = []
    for s in top10:
        news_info = news.news_score_for(s["name"])
        # 기술점수를 0~1로 정규화하고, 뉴스점수는 -3~+3 범위를 0~1로 클램프해 정규화
        tech_norm = s["score"] / max_score
        news_norm = max(0.0, min(1.0, (news_info["score"] + 3) / 6))
        final_score = settings.TECH_WEIGHT * tech_norm + settings.NEWS_WEIGHT * news_norm
        enriched.append(
            {
                **s,
                "news_score": news_info["score"],
                "headlines": news_info["headlines"],
                "final_score": round(final_score, 4),
            }
        )
    return sorted(enriched, key=lambda s: s["final_score"], reverse=True)


def run_daily_pipeline() -> dict:
    snapshot = krx.get_full_market_snapshot()
    universe = krx.get_universe(settings.UNIVERSE_SIZE, snapshot=snapshot)
    trading_date = krx.get_latest_trading_date(snapshot)
    scored = _score_universe(universe, trading_date)
    if not scored:
        raise RuntimeError("스크리닝 결과가 없습니다 (데이터 소스 확인 필요)")

    top10 = _rank_top_n(scored, settings.TOP_N_UNIVERSE_RESULT)
    top10_with_news = _attach_news(top10)
    top3 = top10_with_news[: settings.TOP_N_FINAL]

    return {
        "date": datetime.date.today().isoformat(),
        "trading_date": trading_date,
        "top10": top10_with_news,
        "top3": top3,
        "news_enabled": news.is_configured(),
    }
