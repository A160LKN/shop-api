"""Операции с заказами. Каждая — одна транзакция: либо всё, либо ничего. Исключение — оплата (см. pay_order)."""
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.domain import pricing
from app.domain.order_status import TransitionError, next_status
from app.errors import AppError, not_found
from app.models import Order, OrderItem, OrderStatus, Product, PromoCode, Role, User
from app.schemas import OrderIn
from app.services.payments import PaymentGateway, PaymentUnavailable


def _promo(row: PromoCode) -> pricing.Promo:
    return pricing.Promo(code=row.code, percent=row.percent, min_order_total=row.min_order_total,
                         max_uses=row.max_uses, used_count=row.used_count, expires_at=row.expires_at)


def _prepare(db: Session, data: OrderIn, now: datetime, lock: bool):
    """Проверяет товары, остатки и промокод и считает сумму. Ничего не записывает.

    lock=True — для настоящего заказа: SELECT … FOR UPDATE блокирует строки товаров до конца транзакции.
    Два покупателя не смогут одновременно купить последнюю единицу — второй подождёт
    и увидит уже уменьшенный остаток. Порядок по id исключает взаимную блокировку (deadlock).
    lock=False — для расчёта стоимости: блокировки не нужны, ведь ничего не меняется.
    """
    ids = sorted(line.product_id for line in data.items)
    query = select(Product).where(Product.id.in_(ids)).order_by(Product.id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    products = {p.id: p for p in db.scalars(query)}

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
        promo_query = select(PromoCode).where(PromoCode.code == data.promo_code)
        promo_row = db.scalar(promo_query.with_for_update() if lock else promo_query)
        if promo_row is None:
            db.rollback()
            raise AppError(422, "promo_invalid", "Промокод не найден")
    try:
        totals = pricing.calculate([(p.price, q) for p, q in lines], _promo(promo_row) if promo_row else None, now)
    except pricing.PromoError as exc:
        db.rollback()
        raise AppError(422, "promo_invalid", str(exc)) from None
    return lines, promo_row, totals


def quote_order(db: Session, data: OrderIn, now: datetime | None = None) -> pricing.Totals:
    """Сколько будет стоить заказ — с теми же проверками, что при создании, но без резерва и без промокода."""
    _, _, totals = _prepare(db, data, now or datetime.now(UTC), lock=False)
    db.rollback()
    return totals


def create_order(db: Session, user: User, data: OrderIn, now: datetime | None = None) -> Order:
    now = now or datetime.now(UTC)
    lines, promo_row, totals = _prepare(db, data, now, lock=True)

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
    """Возвращает товар на склад. populate_existing обязателен: товары могли загрузиться вместе
    с заказом ещё до блокировки, и без него SQLAlchemy оставит в сессии старый остаток
    вместо свежего из заблокированной строки — списание параллельного заказа потеряется (BUG-09)."""
    ids = sorted(item.product_id for item in order.items)
    query = (select(Product).where(Product.id.in_(ids)).order_by(Product.id)
             .with_for_update().execution_options(populate_existing=True))
    products = {p.id: p for p in db.scalars(query)}
    for item in order.items:
        products[item.product_id].stock += item.quantity


def _payment_window() -> timedelta:
    """Сколько считать оплату «идущей». Дольше любого ответа шлюза: если сервер упал посреди оплаты,
    отметка устареет, и заказ снова можно будет оплатить или отменить."""
    return timedelta(seconds=settings.payment_timeout_seconds * 3)


def _payment_in_progress(db: Session, order: Order, now: datetime) -> None:
    if order.payment_started_at is not None and order.payment_started_at > now - _payment_window():
        db.rollback()
        raise AppError(409, "payment_in_progress", "Оплата заказа уже идёт — дождитесь результата")


def _lock_order(db: Session, order_id: int) -> Order:
    return db.scalar(select(Order).where(Order.id == order_id).with_for_update()
                     .execution_options(populate_existing=True))


def pay_order(db: Session, user: User, order_id: int, card_token: str, gateway: PaymentGateway,
              now: datetime | None = None) -> Order:
    """Оплата в три шага, и строка заказа ни разу не заблокирована на время запроса к шлюзу.

    1. Короткая транзакция: проверить заказ и отметить «оплата началась». Двойной клик «Оплатить»
       или отмена в этот момент получат 409 — двойного списания нет.
    2. Запрос к шлюзу без блокировок: шлюз может думать до таймаута, остальные запросы к заказу не ждут
       и не занимают соединения с базой.
    3. Короткая транзакция: записать результат и снять отметку.
    """
    now = now or datetime.now(UTC)
    order = get_order_for(db, user, order_id, lock=True)
    if order.user_id != user.id:
        db.rollback()
        raise AppError(403, "forbidden", "Оплатить заказ может только покупатель")
    _next(db, order, "pay")  # заказ можно оплатить; сам статус меняется только после ответа шлюза
    _payment_in_progress(db, order, now)
    order.payment_started_at = now
    attempt, amount = order.payment_attempt, order.total
    db.commit()

    try:
        result = gateway.charge(order_id, amount, card_token, attempt=attempt)
    except PaymentUnavailable:
        # Итог неизвестен: номер попытки тот же, и повтор с тем же ключом не спишет деньги второй раз
        order = _lock_order(db, order_id)
        order.payment_started_at = None
        db.commit()
        raise AppError(502, "payment_unavailable",
                       "Платёжный сервис не отвечает. Деньги не списаны — попробуйте ещё раз позже") from None

    order = _lock_order(db, order_id)
    order.payment_started_at = None
    if not result.approved:
        order.payment_attempt = attempt + 1  # другая карта — новая попытка с новым ключом
        db.commit()
        raise AppError(402, "payment_declined", f"Оплата отклонена: {result.reason}")
    order.status = _next(db, order, "pay")
    order.payment_id = result.payment_id
    db.commit()
    return order


def cancel_order(db: Session, user: User, order_id: int, gateway: PaymentGateway) -> Order:
    order = get_order_for(db, user, order_id, lock=True)
    _payment_in_progress(db, order, datetime.now(UTC))  # иначе деньги спишутся за уже отменённый заказ
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
