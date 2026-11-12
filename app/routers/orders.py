from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Order, Role, User
from app.schemas import OrderIn, OrderOut, PaymentIn
from app.security import admin_user, current_user
from app.services import orders as service
from app.services.payments import PaymentGateway, get_gateway

router = APIRouter(prefix="/orders", tags=["Заказы"])


@router.post("", response_model=OrderOut, status_code=status.HTTP_201_CREATED)
def create_order(data: OrderIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return service.create_order(db, user, data)


@router.get("", response_model=list[OrderOut])
def list_orders(db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Покупатель видит свои заказы, администратор — все."""
    query = select(Order).order_by(Order.id.desc())
    if user.role != Role.admin:
        query = query.where(Order.user_id == user.id)
    return db.scalars(query).all()


@router.get("/{order_id}", response_model=OrderOut)
def get_order(order_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return service.get_order_for(db, user, order_id)


@router.post("/{order_id}/pay", response_model=OrderOut)
def pay(order_id: int, data: PaymentIn, db: Session = Depends(get_db), user: User = Depends(current_user),
        gateway: PaymentGateway = Depends(get_gateway)):
    return service.pay_order(db, user, order_id, data.card_token, gateway)


@router.post("/{order_id}/cancel", response_model=OrderOut)
def cancel(order_id: int, db: Session = Depends(get_db), user: User = Depends(current_user),
           gateway: PaymentGateway = Depends(get_gateway)):
    return service.cancel_order(db, user, order_id, gateway)


@router.post("/{order_id}/ship", response_model=OrderOut, dependencies=[Depends(admin_user)])
def ship(order_id: int, db: Session = Depends(get_db)):
    return service.advance_order(db, order_id, "ship")


@router.post("/{order_id}/deliver", response_model=OrderOut, dependencies=[Depends(admin_user)])
def deliver(order_id: int, db: Session = Depends(get_db)):
    return service.advance_order(db, order_id, "deliver")
