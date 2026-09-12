import json
from types import SimpleNamespace

from app.analysis.limitup import aggregate_precursor_stats


def _fake_event(precursor):
    return SimpleNamespace(precursor_json=json.dumps(precursor, ensure_ascii=False))


def test_aggregate_with_no_events_returns_zero():
    stats = aggregate_precursor_stats([])
    assert stats == {"total_events": 0, "by_offset": {}}


def test_aggregate_computes_condition_rates_per_offset():
    event1 = _fake_event(
        [
            {"offset": -1, "score": 3, "reasons": ["거래량 급증(20일 평균 대비 1.5배 이상)"]},
            {"offset": 0, "score": 5, "reasons": ["거래량 급증(20일 평균 대비 1.5배 이상)", "최근 20일 신고가 경신"]},
        ]
    )
    event2 = _fake_event(
        [
            {"offset": -1, "score": 1, "reasons": []},
            {"offset": 0, "score": 4, "reasons": ["최근 20일 신고가 경신"]},
        ]
    )

    stats = aggregate_precursor_stats([event1, event2])

    assert stats["total_events"] == 2
    offset_minus1 = stats["by_offset"]["-1"]
    assert offset_minus1["sample_count"] == 2
    assert offset_minus1["avg_score"] == 2.0
    assert offset_minus1["condition_rates"]["거래량 급증(20일 평균 대비 1.5배 이상)"] == 50.0

    offset_0 = stats["by_offset"]["0"]
    assert offset_0["condition_rates"]["최근 20일 신고가 경신"] == 100.0
