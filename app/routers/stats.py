from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from sqlalchemy import cast, func, select
from sqlalchemy.orm import Session
from sqlalchemy.types import Date

from app.config import settings
from app.db import get_db
from app.models import Order, OrderItem, OrderStatus, Product
from app.schemas import DayRevenue, LowStock, StatsOut, StatusCount, TopProduct
from app.security import admin_user

router = APIRouter(prefix="/stats", tags=["Сводка"], dependencies=[Depends(admin_user)])

# Деньги магазина — заказы, за которые заплатили: оплаченные, отправленные, доставленные
EARNED = (OrderStatus.paid, OrderStatus.shipped, OrderStatus.delivered)
LOW_STOCK = 5
DAYS = 7


@router.get("", response_model=StatsOut)
def stats(db: Session = Depends(get_db)):
    revenue, paid_orders = db.execute(
        select(func.coalesce(func.sum(Order.total), 0), func.count()).where(Order.status.in_(EARNED))
    ).one()

    by_status = dict(db.execute(select(Order.status, func.count()).group_by(Order.status)).all())

    # Выручка по дням в часовом поясе магазина: «сегодня» в Астане, а не по UTC
    tz = ZoneInfo(settings.timezone)
    today = datetime.now(tz).date()
    local_day = cast(func.timezone(settings.timezone, Order.created_at), Date)
    daily = {
        day: (amount, count)
        for day, amount, count in db.execute(
            select(local_day, func.sum(Order.total), func.count())
            .where(Order.status.in_(EARNED), Order.created_at >= datetime.now(UTC) - timedelta(days=DAYS + 1))
            .group_by(local_day)
        ).all()
    }
    revenue_by_day = [
        DayRevenue(day=day, revenue=daily.get(day, (0, 0))[0], orders=daily.get(day, (0, 0))[1])
        for day in (today - timedelta(days=DAYS - 1 - i) for i in range(DAYS))
    ]

    sold = func.sum(OrderItem.quantity)
    top = db.execute(
        select(Product.id, Product.name, sold, func.sum(OrderItem.quantity * OrderItem.price))
        .join(OrderItem, OrderItem.product_id == Product.id)
        .join(Order, Order.id == OrderItem.order_id)
        .where(Order.status != OrderStatus.cancelled)
        .group_by(Product.id, Product.name)
        .order_by(sold.desc(), Product.id)
        .limit(5)
    ).all()

    low = db.scalars(
        select(Product).where(Product.is_active, Product.stock <= LOW_STOCK).order_by(Product.stock, Product.id)
    ).all()

    return StatsOut(
        revenue=revenue,
        paid_orders=paid_orders,
        average_check=revenue // paid_orders if paid_orders else 0,
        orders_by_status=[StatusCount(status=s, count=by_status.get(s, 0)) for s in OrderStatus],
        revenue_by_day=revenue_by_day,
        top_products=[TopProduct(product_id=i, name=n, quantity=q, revenue=r) for i, n, q, r in top],
        low_stock=[LowStock(id=p.id, name=p.name, stock=p.stock) for p in low],
    )
