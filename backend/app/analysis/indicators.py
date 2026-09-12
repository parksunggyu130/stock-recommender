"""기술적 지표 계산 + 종목 스코어링.

'1개월 일봉' 기준 스크리닝을 위한 5가지 조건을 계산한다:
1. 정배열(5일선 > 20일선, 20일선 우상향)
2. RSI(14) 50~70 구간 (상승 모멘텀)
3. 최근 3거래일 내 MACD 골든크로스
4. 거래량이 20일 평균 대비 1.5배 이상 급증
5. 종가 기준 최근 20일 신고가 경신

조건 1개당 1점, 총 0~5점.
"""
from __future__ import annotations

import pandas as pd

MIN_ROWS = 35  # MACD(26)+signal(9) 안정적 계산을 위한 최소 데이터 길이

CONDITION_LABELS = (
    "정배열(5일선>20일선, 20일선 상승)",
    "RSI 상승 모멘텀 구간(50~70)",
    "MACD 골든크로스(최근 3거래일 내)",
    "거래량 급증(20일 평균 대비 1.5배 이상)",
    "최근 20일 신고가 경신",
)


def moving_average(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window=window).mean()


def rsi(series: pd.Series, window: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(window=window).mean()
    avg_loss = loss.rolling(window=window).mean()
    rs = avg_gain / avg_loss.replace(0, float("nan"))
    result = 100 - (100 / (1 + rs))
    return result.fillna(50.0)  # 데이터 부족/무변동 구간은 중립값 50


def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    return macd_line, signal_line


def volume_ratio(volume: pd.Series, window: int = 20) -> float:
    avg = volume.rolling(window=window).mean().iloc[-1]
    if not avg or avg == 0:
        return 0.0
    return float(volume.iloc[-1] / avg)


def is_new_high(close: pd.Series, window: int = 20) -> bool:
    recent = close.tail(window)
    return bool(close.iloc[-1] >= recent.max())


def macd_recent_golden_cross(macd_line: pd.Series, signal_line: pd.Series, lookback: int = 3) -> bool:
    diff = macd_line - signal_line
    tail = diff.tail(lookback + 1)
    for i in range(1, len(tail)):
        if tail.iloc[i - 1] <= 0 < tail.iloc[i]:
            return True
    return False


def score_stock(df: pd.DataFrame) -> dict | None:
    """OHLCV 데이터프레임(오름차순, columns: open/high/low/close/volume)을 받아 점수를 매긴다."""
    if df is None or len(df) < MIN_ROWS:
        return None

    close = df["close"]
    volume = df["volume"]

    ma5 = moving_average(close, 5)
    ma20 = moving_average(close, 20)
    rsi14 = rsi(close, 14)
    macd_line, signal_line = macd(close)
    vol_ratio = volume_ratio(volume, 20)
    new_high = is_new_high(close, 20)
    golden_cross = macd_recent_golden_cross(macd_line, signal_line, 3)

    trend_up = bool(ma5.iloc[-1] > ma20.iloc[-1] and ma20.iloc[-1] > ma20.iloc[-6])
    rsi_ok = bool(50 <= rsi14.iloc[-1] <= 70)
    volume_surge = bool(vol_ratio >= 1.5)

    conditions = dict(zip(CONDITION_LABELS, (trend_up, rsi_ok, golden_cross, volume_surge, new_high)))
    score = sum(1 for v in conditions.values() if v)
    reasons = [label for label, ok in conditions.items() if ok]

    return {
        "score": score,
        "reasons": reasons,
        "close": float(close.iloc[-1]),
        "rsi": round(float(rsi14.iloc[-1]), 1),
        "volume_ratio": round(vol_ratio, 2),
    }
