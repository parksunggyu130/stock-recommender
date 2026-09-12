"""상한가 종목의 사전 징조(precursor) 계산 + 누적 통계.

상한가가 발생한 날(offset 0)부터 이전 4거래일(offset -1~-4, 총 '일주일'
영업일 기준 5일치)의 기술 지표 스냅샷을 저장해 두면, 이벤트가 쌓일수록
"상한가 며칠 전부터 거래량이 급증하는 경우가 몇 %였다" 같은 통계를 낼 수 있다.
"""
from __future__ import annotations

import json
from collections import defaultdict

from ..data import krx
from .indicators import CONDITION_LABELS, score_stock

LOOKBACK_DAYS = 5  # offset 0(당일) ~ -4 까지 총 5거래일


def compute_precursor(ticker: str, trading_date: str) -> list[dict]:
    df = krx.get_recent_ohlcv(ticker, trading_date)
    if df.empty:
        return []

    n = len(df)
    results = []
    for offset in range(LOOKBACK_DAYS - 1, -1, -1):  # -4, -3, -2, -1, 0 순서로 계산
        idx = n - 1 - offset
        if idx < 0:
            continue
        sub = df.iloc[: idx + 1]
        feat = score_stock(sub)
        if feat is None:
            continue
        date_val = sub.index[-1]
        results.append(
            {
                "offset": -offset,
                "date": str(getattr(date_val, "date", lambda: date_val)()),
                **feat,
            }
        )
    return results


def aggregate_precursor_stats(events: list) -> dict:
    """LimitUpEvent ORM 행 목록을 받아 offset별 통계를 낸다."""
    total = len(events)
    if total == 0:
        return {"total_events": 0, "by_offset": {}}

    buckets: dict[int, dict] = defaultdict(
        lambda: {"count": 0, "score_sum": 0.0, "condition_counts": {label: 0 for label in CONDITION_LABELS}}
    )
    for ev in events:
        try:
            precursor = json.loads(ev.precursor_json)
        except (TypeError, ValueError):
            continue
        for day in precursor:
            offset = day["offset"]
            bucket = buckets[offset]
            bucket["count"] += 1
            bucket["score_sum"] += day.get("score", 0)
            for reason in day.get("reasons", []):
                bucket["condition_counts"][reason] += 1

    by_offset = {}
    for offset in sorted(buckets.keys(), reverse=True):  # 0, -1, -2, ...
        bucket = buckets[offset]
        count = bucket["count"]
        by_offset[str(offset)] = {
            "sample_count": count,
            "avg_score": round(bucket["score_sum"] / count, 2) if count else 0,
            "condition_rates": {
                cond: round(cnt / count * 100, 1) for cond, cnt in bucket["condition_counts"].items()
            },
        }

    return {"total_events": total, "by_offset": by_offset}
