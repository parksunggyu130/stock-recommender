from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import services
from ..db import get_db

router = APIRouter(prefix="/api/limit-up", tags=["limit-up"])


@router.get("/today")
def limit_up_today(db: Session = Depends(get_db)):
    return {"events": services.get_limit_up_today(db)}


@router.get("/precursor-stats")
def precursor_stats(db: Session = Depends(get_db)):
    return services.get_precursor_stats(db)
