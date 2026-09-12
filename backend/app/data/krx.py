"""국내 상장 종목의 무료 공개 데이터 래퍼.

시세 스냅샷(시가총액/종가/등락률)과 종목별 일봉(OHLCV) 모두 네이버 증권 모바일
공개 API(m.stock.naver.com)를 사용한다. 로그인/키가 필요 없고, 커넥션을 재사용하는
`requests.Session`으로 호출하면 종목 수백 개도 몇 초 안에 처리된다.

(참고) 처음엔 일봉 조회에 `pykrx`를 썼으나 두 가지 문제로 걷어냈다:
1) KRX 정보데이터시스템의 일부 통계 API(`get_market_cap_by_ticker` 등)가 최근
   KRX 회원 로그인(KRX_ID/KRX_PW)을 요구하도록 바뀌어 시가총액 랭킹에 못 쓰게 됨.
2) PyInstaller로 패키징한 실행 파일에서 `pykrx`의 개별 종목 조회를 수백 번 반복하면
   (원인 미상의 프로세스별 오버헤드로) 급격히 느려져 사실상 멈추는 문제가 있었음.
   동일 작업을 아래 `get_recent_ohlcv`(순수 requests + 세션 재사용)로 바꾸니
   500종목 조회가 실행 파일 안에서도 10초 안팎으로 끝난다.

시세 API는 ETF/ETN도 함께 내려주므로 `stockEndType == "stock"` 인 것만 걸러서 쓴다.
"""
from __future__ import annotations

import pandas as pd
import requests

_HEADERS = {"User-Agent": "Mozilla/5.0"}
_MARKET_VALUE_URL = "https://m.stock.naver.com/api/stocks/marketValue/{market}"
_CHART_URL = "https://m.stock.naver.com/api/chart/domestic/item/{ticker}"
_PAGE_SIZE = 100
_MAX_PAGES = 60  # 안전장치 (시장당 최대 6000종목까지)

UPPER_LIMIT_THRESHOLD = 29.5  # 상한가(+30%) 판정 임계치 (반올림/오차 감안)

_session = requests.Session()
_session.headers.update(_HEADERS)


def _to_int(raw) -> int:
    try:
        return int(str(raw).replace(",", ""))
    except (TypeError, ValueError):
        return 0


def _to_float(raw) -> float:
    try:
        return float(str(raw).replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


def _fetch_market_value_page(market: str, page: int) -> list[dict]:
    url = _MARKET_VALUE_URL.format(market=market)
    resp = _session.get(url, params={"page": page, "pageSize": _PAGE_SIZE}, timeout=10)
    resp.raise_for_status()
    return resp.json().get("stocks", [])


def get_full_market_snapshot() -> list[dict]:
    """KOSPI+KOSDAQ 전 종목(ETF/ETN 제외)의 당일 시세 스냅샷을 반환한다.

    반환 항목: ticker, name, market_cap(원), trading_value(원),
    close_price(원), change_pct(%), local_traded_at
    """
    rows: list[dict] = []
    for market in ("KOSPI", "KOSDAQ"):
        page = 1
        while page <= _MAX_PAGES:
            items = _fetch_market_value_page(market, page)
            if not items:
                break
            for item in items:
                if item.get("stockEndType") != "stock":
                    continue  # ETF/ETN 등 제외
                rows.append(
                    {
                        "ticker": item["itemCode"],
                        "name": item["stockName"],
                        "market": market,
                        "market_cap": _to_int(item.get("marketValueRaw")),
                        "trading_value": _to_int(item.get("accumulatedTradingValueRaw")),
                        "close_price": _to_int(item.get("closePriceRaw")),
                        "change_pct": _to_float(item.get("fluctuationsRatio")),
                        "local_traded_at": item.get("localTradedAt", ""),
                    }
                )
            page += 1

    if not rows:
        raise RuntimeError("네이버 증권 시세 API에서 데이터를 가져오지 못했습니다")
    return rows


def get_universe(size: int, snapshot: list[dict] | None = None) -> list[dict]:
    """시가총액 상위 `size` 종목을 반환한다."""
    snapshot = snapshot if snapshot is not None else get_full_market_snapshot()
    return sorted(snapshot, key=lambda r: r["market_cap"], reverse=True)[:size]


def get_limit_up_stocks(snapshot: list[dict] | None = None) -> list[dict]:
    """당일 상한가(+30%) 근접 종목을 반환한다."""
    snapshot = snapshot if snapshot is not None else get_full_market_snapshot()
    return [r for r in snapshot if r["change_pct"] >= UPPER_LIMIT_THRESHOLD]


def get_latest_trading_date(snapshot: list[dict] | None = None) -> str:
    """가장 최근 거래일(YYYYMMDD)을 반환한다. 스냅샷의 localTradedAt을 활용한다."""
    snapshot = snapshot if snapshot is not None else get_full_market_snapshot()
    for row in snapshot:
        raw = row.get("local_traded_at", "")
        if raw:
            date_part = raw.split("T")[0]  # "2026-09-11"
            return date_part.replace("-", "")
    raise RuntimeError("최근 거래일 정보를 찾지 못했습니다")


def get_recent_ohlcv(ticker: str, trading_date: str | None = None, count: int = 90) -> pd.DataFrame:
    """최근 일봉(OHLCV)을 가져온다 (오름차순, columns: open/high/low/close/volume).

    화면/추천 로직상 기준은 '최근 1개월 일봉'이지만, RSI/MACD 같은 지표는 안정적인
    계산을 위해 그보다 긴 히스토리(기본 최근 90개 거래일 안팎)를 내부적으로 사용한다.
    `trading_date`는 현재 인터페이스상 사용하지 않는다(항상 최신 데이터 기준으로 조회됨).
    """
    try:
        resp = _session.get(
            _CHART_URL.format(ticker=ticker),
            params={"periodType": "dayCandle", "count": count},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError):
        return pd.DataFrame()

    rows = data.get("priceInfos") or []
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["localDate"], format="%Y%m%d")
    df = df.set_index("date").sort_index()
    return df.rename(
        columns={
            "openPrice": "open",
            "highPrice": "high",
            "lowPrice": "low",
            "closePrice": "close",
            "accumulatedTradingVolume": "volume",
        }
    )[["open", "high", "low", "close", "volume"]]
