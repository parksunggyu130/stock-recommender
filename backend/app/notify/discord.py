"""디스코드 웹후크로 알림을 보낸다.

브라우저 푸시(VAPID)는 HTTPS + 알림 권한 허용 + PWA 설치가 필요해 설정이 번거롭다.
디스코드 웹후크는 URL 하나만 있으면 되고, 디스코드 모바일 앱이 알아서 폰에 푸시를
띄워주므로 훨씬 간단하다. 설정하면 두 채널(웹푸시+디스코드) 모두로 발송한다.
"""
from __future__ import annotations

import logging

import requests

from ..config import settings

logger = logging.getLogger(__name__)


def is_configured() -> bool:
    return bool(settings.DISCORD_WEBHOOK_URL)


def send(payload: dict) -> bool:
    """payload: {"title": str, "body": str, ...}. 성공 여부를 반환한다."""
    if not is_configured():
        return False
    content = f"**{payload.get('title', '알림')}**\n{payload.get('body', '')}"
    try:
        resp = requests.post(settings.DISCORD_WEBHOOK_URL, json={"content": content}, timeout=10)
        if resp.status_code >= 300:
            logger.warning("디스코드 웹후크 발송 실패: %s %s", resp.status_code, resp.text[:200])
            return False
        return True
    except requests.RequestException as exc:
        logger.warning("디스코드 웹후크 발송 오류: %s", exc)
        return False
