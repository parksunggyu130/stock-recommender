from __future__ import annotations

import json
import logging

from pywebpush import WebPushException, webpush
from sqlalchemy.orm import Session

from ..config import settings
from ..models import PushSubscription

logger = logging.getLogger(__name__)


def is_configured() -> bool:
    return bool(settings.VAPID_PUBLIC_KEY and settings.VAPID_PRIVATE_KEY)


def send_push(subscription: PushSubscription, payload: dict) -> bool:
    subscription_info = {
        "endpoint": subscription.endpoint,
        "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth},
    }
    try:
        webpush(
            subscription_info=subscription_info,
            data=json.dumps(payload),
            vapid_private_key=settings.VAPID_PRIVATE_KEY,
            vapid_claims={"sub": settings.VAPID_CONTACT_EMAIL},
        )
        return True
    except WebPushException as exc:
        status = exc.response.status_code if exc.response is not None else None
        if status in (404, 410):
            return False  # 구독 만료 -> 호출부에서 삭제 처리
        logger.warning("푸시 발송 실패: %s", exc)
        return True  # 일시적 오류는 구독을 지우지 않음


def notify_all(db: Session, payload: dict) -> dict:
    if not is_configured():
        logger.info("VAPID 키 미설정 - 푸시 발송을 건너뜁니다")
        return {"sent": 0, "removed": 0, "skipped_reason": "vapid_not_configured"}

    subs = db.query(PushSubscription).all()
    sent = 0
    removed = 0
    for sub in subs:
        still_valid = send_push(sub, payload)
        if still_valid:
            sent += 1
        else:
            db.delete(sub)
            removed += 1
    db.commit()
    return {"sent": sent, "removed": removed}
