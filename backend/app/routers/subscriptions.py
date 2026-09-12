from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import PushSubscription

router = APIRouter(prefix="/api", tags=["subscriptions"])


class Keys(BaseModel):
    p256dh: str
    auth: str


class SubscriptionIn(BaseModel):
    endpoint: str
    keys: Keys


class UnsubscribeIn(BaseModel):
    endpoint: str


@router.get("/vapid-public-key")
def vapid_public_key():
    return {"publicKey": settings.VAPID_PUBLIC_KEY, "configured": bool(settings.VAPID_PUBLIC_KEY)}


@router.post("/subscribe")
def subscribe(payload: SubscriptionIn, db: Session = Depends(get_db)):
    existing = db.query(PushSubscription).filter_by(endpoint=payload.endpoint).first()
    if existing:
        existing.p256dh = payload.keys.p256dh
        existing.auth = payload.keys.auth
    else:
        db.add(
            PushSubscription(
                endpoint=payload.endpoint,
                p256dh=payload.keys.p256dh,
                auth=payload.keys.auth,
            )
        )
    db.commit()
    return {"status": "ok"}


@router.delete("/subscribe")
def unsubscribe(payload: UnsubscribeIn, db: Session = Depends(get_db)):
    db.query(PushSubscription).filter_by(endpoint=payload.endpoint).delete()
    db.commit()
    return {"status": "ok"}
