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

# 상한가 "조짐" 매칭에 쓸 최소 누적 이벤트 수. 이보다 적으면 통계적으로 신뢰할 수 없어
# 후보를 아예 표시하지 않는다 (데이터가 쌓일수록 자동으로 켜진다).
MIN_EVENTS_FOR_PRECURSOR_MATCH = 30
# 상한가 하루 전(offset -1) 조건 발생률이 "오늘 전체 스캔 종목군의 평균 발생률"보다
# 이 값(퍼센트포인트) 이상 높아야 "상한가와 관련 있는 조건"으로 채택한다.
PRECURSOR_LIFT_THRESHOLD = 20.0
PRECURSOR_MATCH_OFFSET = -1
MAX_PRECURSOR_CANDIDATES = 5


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


def _baseline_condition_rates(scored_universe: list[dict]) -> dict[str, float]:
    """오늘 전체 스캔 종목군에서 각 조건이 얼마나 흔한지(기준선)를 계산한다.

    상한가 전날 통계가 이 기준선보다 뚜렷이 높아야("lift") 의미 있는 신호로 본다 —
    그렇지 않으면 원래 흔한 조건을 상한가 전조로 착각하게 된다.
    """
    total = len(scored_universe)
    if total == 0:
        return {label: 0.0 for label in CONDITION_LABELS}
    counts = {label: 0 for label in CONDITION_LABELS}
    for s in scored_universe:
        for reason in s.get("reasons", []):
            if reason in counts:
                counts[reason] += 1
    return {label: round(cnt / total * 100, 1) for label, cnt in counts.items()}


def find_precursor_candidates(
    scored_universe: list[dict],
    events: list,
    min_events: int = MIN_EVENTS_FOR_PRECURSOR_MATCH,
    lift_threshold: float = PRECURSOR_LIFT_THRESHOLD,
    max_candidates: int = MAX_PRECURSOR_CANDIDATES,
) -> dict:
    """상한가 하루 전(offset -1)에 흔했던 조건 조합을 오늘 종목 중에서 찾는다.

    누적 이벤트가 min_events 미만이면 통계적으로 신뢰할 수 없으므로 빈 결과(enabled=False)를
    반환한다 — 표본이 쌓일수록 자동으로 켜진다. 실제 인과관계를 보장하지 않는 참고용 신호다.
    """
    stats = aggregate_precursor_stats(events)
    total_events = stats["total_events"]
    base_result = {"enabled": False, "total_events": total_events, "min_events": min_events, "candidates": []}
    if total_events < min_events:
        return base_result

    offset_bucket = stats["by_offset"].get(str(PRECURSOR_MATCH_OFFSET))
    if not offset_bucket:
        return base_result

    baseline = _baseline_condition_rates(scored_universe)
    signal_conditions = [
        label
        for label, rate in offset_bucket["condition_rates"].items()
        if rate - baseline.get(label, 0.0) >= lift_threshold
    ]
    if not signal_conditions:
        return {**base_result, "enabled": True, "signal_conditions": []}

    candidates = []
    for s in scored_universe:
        matched = [c for c in signal_conditions if c in s.get("reasons", [])]
        if len(matched) == len(signal_conditions):  # 신호 조건을 전부 충족해야 후보로 인정
            candidates.append(
                {
                    "ticker": s["ticker"],
                    "name": s["name"],
                    "score": s["score"],
                    "matched_conditions": matched,
                }
            )
    candidates.sort(key=lambda c: c["score"], reverse=True)

    return {
        "enabled": True,
        "total_events": total_events,
        "signal_conditions": signal_conditions,
        "candidates": candidates[:max_candidates],
    }
