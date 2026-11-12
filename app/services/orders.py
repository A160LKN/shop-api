"""Операции с заказами. Каждая — одна транзакция: либо всё, либо ничего."""
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain import pricing
from app.domain.order_status import TransitionError, next_status
from app.errors import AppError, not_found
from app.models import Order, OrderItem, OrderStatus, Product, PromoCode, Role, User
from app.schemas import OrderIn
from app.services.payments import PaymentGateway, PaymentUnavailable


def _promo(row: PromoCode) -> pricing.Promo:
    return pricing.Promo(code=row.code, percent=row.percent, min_order_total=row.min_order_total,
                         max_uses=row.max_uses, used_count=row.used_count, expires_at=row.expires_at)


def create_order(db: Session, user: User, data: OrderIn, now: datetime | None = None) -> Order:
    now = now or datetime.now(UTC)
    ids = sorted(line.product_id for line in data.items)

    # SELECT … FOR UPDATE: строки товаров блокируются до конца транзакции.
    # Два покупателя не смогут одновременно купить последнюю единицу — второй подождёт
    # и увидит уже уменьшенный остаток. Порядок по id исключает взаимную блокировку (deadlock).
    products = {p.id: p for p in db.scalars(select(Product).where(Product.id.in_(ids))
                                            .order_by(Product.id).with_for_update())}

    lines = []
    for line in data.items:
        product = products.get(line.product_id)
        if product is None or not product.is_active:
            db.rollback()
            raise AppError(404, "product_not_found", f"Товар с id {line.product_id} не найден")
        if product.stock < line.quantity:
            db.rollback()
            raise AppError(409, "out_of_stock",
                           f"Недостаточно товара «{product.name}»: в наличии {product.stock}, в заказе {line.quantity}")
        lines.append((product, line.quantity))

    promo_row = None
    if data.promo_code:
        promo_row = db.scalar(select(PromoCode).where(PromoCode.code == data.promo_code).with_for_update())
        if promo_row is None:
            db.rollback()
            raise AppError(422, "promo_invalid", "Промокод не найден")
    try:
        totals = pricing.calculate([(p.price, q) for p, q in lines], _promo(promo_row) if promo_row else None, now)
    except pricing.PromoError as exc:
        db.rollback()
        raise AppError(422, "promo_invalid", str(exc)) from None

    for product, quantity in lines:
        product.stock -= quantity
    if promo_row is not None:
        promo_row.used_count += 1

    order = Order(user_id=user.id, subtotal=totals.subtotal, discount=totals.discount, total=totals.total,
                  promo_code=data.promo_code, created_at=now, updated_at=now,
                  items=[OrderItem(product_id=p.id, quantity=q, price=p.price) for p, q in lines])
    db.add(order)
    db.commit()
    return order


def get_order_for(db: Session, user: User, order_id: int, lock: bool = False) -> Order:
    """Заказ, который пользователь вправе видеть. Чужой заказ — 404, а не 403:
    так нельзя узнать, существует ли заказ с таким номером."""
    query = select(Order).where(Order.id == order_id)
    if lock:
        query = query.with_for_update()
    order = db.scalar(query)
    if order is None or (order.user_id != user.id and user.role != Role.admin):
        db.rollback()
        raise not_found("Заказ")
    return order


def _next(db: Session, order: Order, action: str) -> OrderStatus:
    try:
        return next_status(order.status, action)
    except TransitionError as exc:
        db.rollback()
        raise AppError(409, "invalid_status", str(exc)) from None


def _return_stock(db: Session, order: Order) -> None:
    ids = sorted(item.product_id for item in order.items)
    products = {p.id: p for p in db.scalars(select(Product).where(Product.id.in_(ids))
                                            .order_by(Product.id).with_for_update())}
    for item in order.items:
        products[item.product_id].stock += item.quantity


def pay_order(db: Session, user: User, order_id: int, card_token: str, gateway: PaymentGateway) -> Order:
    order = get_order_for(db, user, order_id, lock=True)  # блокировка: двойной клик «Оплатить» не спишет дважды
    if order.user_id != user.id:
        db.rollback()
        raise AppError(403, "forbidden", "Оплатить заказ может только покупатель")
    new_status = _next(db, order, "pay")  # статус меняем только после ответа шлюза

    try:
        result = gateway.charge(order.id, order.total, card_token)
    except PaymentUnavailable:
        db.rollback()
        raise AppError(502, "payment_unavailable",
                       "Платёжный сервис не отвечает. Деньги не списаны — попробуйте ещё раз позже") from None
    if not result.approved:
        db.rollback()
        raise AppError(402, "payment_declined", f"Оплата отклонена: {result.reason}")

    order.status = new_status
    order.payment_id = result.payment_id
    db.commit()
    return order


def cancel_order(db: Session, user: User, order_id: int, gateway: PaymentGateway) -> Order:
    order = get_order_for(db, user, order_id, lock=True)
    was_paid = order.status == OrderStatus.paid
    new_status = _next(db, order, "cancel")
    if was_paid:
        try:
            gateway.refund(order.payment_id, order.total)
        except PaymentUnavailable:
            db.rollback()
            raise AppError(502, "refund_unavailable",
                           "Не удалось вернуть деньги: платёжный сервис не отвечает. Заказ не отменён") from None
    order.status = new_status
    _return_stock(db, order)
    db.commit()
    return order


def advance_order(db: Session, order_id: int, action: str) -> Order:
    """Отправка и доставка — действия администратора."""
    order = db.scalar(select(Order).where(Order.id == order_id).with_for_update())
    if order is None:
        db.rollback()
        raise not_found("Заказ")
    order.status = _next(db, order, action)
    db.commit()
    return order
