import pandas as pd

from app.analysis.indicators import score_stock, MIN_ROWS


def _make_df(closes, volumes):
    n = len(closes)
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c * 1.01 for c in closes],
            "low": [c * 0.99 for c in closes],
            "close": closes,
            "volume": volumes,
        },
        index=pd.bdate_range(end=pd.Timestamp.today(), periods=n),
    )


def test_insufficient_data_returns_none():
    df = _make_df([100] * (MIN_ROWS - 1), [1000] * (MIN_ROWS - 1))
    assert score_stock(df) is None


def test_uptrend_with_volume_surge_scores_high():
    n = 40
    flat = [100.0] * 20
    rising = [100.0 + i * 1.5 for i in range(1, 21)]
    closes = flat + rising
    volumes = [1000] * (n - 1) + [3000]  # 마지막 날 거래량 급증

    df = _make_df(closes, volumes)
    result = score_stock(df)

    assert result is not None
    assert result["score"] >= 3
    assert "거래량 급증(20일 평균 대비 1.5배 이상)" in result["reasons"]
    assert "최근 20일 신고가 경신" in result["reasons"]
    assert result["close"] == closes[-1]


def test_flat_series_scores_low():
    n = 40
    closes = [100.0] * n
    volumes = [1000] * n

    df = _make_df(closes, volumes)
    result = score_stock(df)

    assert result is not None
    # 완전히 횡보하는 종목은 RSI(중립 50)와 '20일 신고가'(제자리도 동률로 신고가) 조건만
    # 우연히 걸릴 수 있어 0점은 아니지만, 상승추세/거래량급증/골든크로스 조건은 모두 걸리지 않아야 한다.
    assert result["score"] <= 2
    assert "정배열(5일선>20일선, 20일선 상승)" not in result["reasons"]
    assert "거래량 급증(20일 평균 대비 1.5배 이상)" not in result["reasons"]
    assert "MACD 골든크로스(최근 3거래일 내)" not in result["reasons"]
    assert result["rsi"] == 50.0
