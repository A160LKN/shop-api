from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import AppError
from app.models import PromoCode
from app.schemas import PromoIn, PromoOut
from app.security import admin_user

router = APIRouter(prefix="/promo-codes", tags=["Промокоды"], dependencies=[Depends(admin_user)])


@router.get("", response_model=list[PromoOut])
def list_promos(db: Session = Depends(get_db)):
    """Все промокоды, новые — первыми."""
    return db.scalars(select(PromoCode).order_by(PromoCode.id.desc())).all()


@router.post("", response_model=PromoOut, status_code=status.HTTP_201_CREATED)
def create_promo(data: PromoIn, db: Session = Depends(get_db)):
    promo = PromoCode(**data.model_dump())
    db.add(promo)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise AppError(409, "promo_exists", f"Промокод {data.code} уже существует") from None
    return promo
