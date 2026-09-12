"""네이버 검색(뉴스) 오픈 API 클라이언트 + 간단 키워드 감성 스코어.

무료 발급 (https://developers.naver.com/apps) 이 필요하지만, 키가 없어도
앱이 동작하도록 키 미설정 시 항상 점수 0을 반환하는 폴백을 포함한다.
"""
from __future__ import annotations

import re
from email.utils import parsedate_to_datetime
import datetime

import requests

from ..config import settings

NAVER_NEWS_URL = "https://openapi.naver.com/v1/search/news.json"

POSITIVE_KEYWORDS = [
    "호재", "급등", "강세", "신고가", "수주", "계약 체결", "실적 개선", "흑자전환",
    "목표주가 상향", "매수", "최대 실적", "역대 최대", "성장", "기대감", "돌파",
]
NEGATIVE_KEYWORDS = [
    "급락", "약세", "적자", "소송", "유상증자", "하락", "부진", "리콜",
    "목표주가 하향", "매도", "우려", "감사의견", "거래정지", "횡령", "배임",
]

_TAG_RE = re.compile(r"<[^>]+>")


def _strip_tags(text: str) -> str:
    return _TAG_RE.sub("", text or "")


def _is_recent(pub_date: str, within_hours: int = 48) -> bool:
    try:
        dt = parsedate_to_datetime(pub_date)
    except Exception:
        return True  # 날짜 파싱 실패 시 배제하지 않음
    if dt.tzinfo is not None:
        now = datetime.datetime.now(dt.tzinfo)
    else:
        now = datetime.datetime.now()
    return (now - dt) <= datetime.timedelta(hours=within_hours)


def is_configured() -> bool:
    return bool(settings.NAVER_CLIENT_ID and settings.NAVER_CLIENT_SECRET)


def search_news(query: str, display: int = 20) -> list[dict]:
    if not is_configured():
        return []
    headers = {
        "X-Naver-Client-Id": settings.NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": settings.NAVER_CLIENT_SECRET,
    }
    params = {"query": query, "display": display, "sort": "date"}
    try:
        resp = requests.get(NAVER_NEWS_URL, headers=headers, params=params, timeout=5)
        resp.raise_for_status()
        return resp.json().get("items", [])
    except Exception:
        return []


def find_reason(name: str) -> dict:
    """상한가 등 급등 종목의 원인 추정: 최근 뉴스에서 헤드라인과 매칭 키워드를 뽑는다.

    실제 인과관계를 보장하지 않는 '뉴스 검색 기반 추정'이며, 화면에도 그렇게 표기한다.
    """
    if not is_configured():
        return {"headlines": [], "keywords": []}

    items = search_news(f"{name} 급등", display=10) or search_news(f"{name} 상한가", display=10)
    keywords_found: set[str] = set()
    headlines: list[str] = []
    for item in items:
        if not _is_recent(item.get("pubDate", ""), within_hours=72):
            continue
        title = _strip_tags(item.get("title", ""))
        text = title + " " + _strip_tags(item.get("description", ""))
        for kw in POSITIVE_KEYWORDS:
            if kw in text:
                keywords_found.add(kw)
        if title:
            headlines.append(title)

    return {"headlines": headlines[:5], "keywords": sorted(keywords_found)}


def news_score_for(name: str) -> dict:
    """종목명으로 최근 48시간 뉴스를 검색해 (점수, 헤드라인 몇 개)를 반환."""
    if not is_configured():
        return {"score": 0, "headlines": []}

    items = search_news(f"{name} 주가")
    score = 0
    headlines = []
    for item in items:
        if not _is_recent(item.get("pubDate", "")):
            continue
        text = _strip_tags(item.get("title", "")) + " " + _strip_tags(item.get("description", ""))
        pos = sum(1 for kw in POSITIVE_KEYWORDS if kw in text)
        neg = sum(1 for kw in NEGATIVE_KEYWORDS if kw in text)
        score += pos - neg
        if pos or neg:
            headlines.append(_strip_tags(item.get("title", "")))

    return {"score": score, "headlines": headlines[:3]}
