"""Склад и промокоды под одновременной нагрузкой — на настоящем PostgreSQL.

Такие баги не видны в ручном тестировании и в последовательных автотестах:
они появляются, только когда два запроса приходят одновременно.
"""
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.db import SessionLocal
from app.errors import AppError
from app.models import Order, Product, PromoCode
from app.schemas import OrderIn
from app.services.orders import create_order

pytestmark = pytest.mark.integration


def order_concurrently(user, data: OrderIn, attempts: int) -> list[str]:
    """Отправляет attempts одинаковых заказов одновременно, каждый — в своей сессии БД."""
    def attempt(_):
        with SessionLocal() as session:
            try:
                create_order(session, user, data)
                return "ok"
            except AppError as exc:
                return exc.code
    with ThreadPoolExecutor(max_workers=attempts) as pool:
        return list(pool.map(attempt, range(attempts)))


def test_last_items_are_not_oversold(db, make_user, make_product):
    """20 покупателей одновременно берут товар, которого осталось 5 штук."""
    user = make_user()
    product = make_product(stock=5)

    results = order_concurrently(user, OrderIn(items=[{"product_id": product.id, "quantity": 1}]), attempts=20)

    assert results.count("ok") == 5
    assert results.count("out_of_stock") == 15
    db.expire_all()
    assert db.get(Product, product.id).stock == 0
    assert db.scalar(select(func.count()).select_from(Order)) == 5


def test_promo_usage_limit_holds_under_load(db, make_user, make_product, make_promo):
    """Промокод на 3 использования, 10 одновременных заказов с ним."""
    user = make_user()
    product = make_product(stock=100)
    make_promo(code="ONLY3", max_uses=3)

    results = order_concurrently(
        user, OrderIn(items=[{"product_id": product.id, "quantity": 1}], promo_code="ONLY3"), attempts=10)

    assert results.count("ok") == 3
    assert results.count("promo_invalid") == 7
    db.expire_all()
    assert db.scalar(select(PromoCode.used_count).where(PromoCode.code == "ONLY3")) == 3


def test_order_is_all_or_nothing(db, make_user, make_product):
    """Второго товара не хватает — первый не должен списаться со склада."""
    user = make_user()
    enough = make_product(name="Есть", stock=10)
    short = make_product(name="Мало", stock=1)

    with pytest.raises(AppError) as error:
        create_order(db, user, OrderIn(items=[{"product_id": enough.id, "quantity": 3},
                                              {"product_id": short.id, "quantity": 2}]))

    assert error.value.code == "out_of_stock"
    db.expire_all()
    assert db.get(Product, enough.id).stock == 10
    assert db.scalar(select(func.count()).select_from(Order)) == 0


def test_database_refuses_negative_stock(db, make_product):
    """Последняя линия защиты: даже если код ошибётся, БД не даст уйти в минус."""
    product = make_product(stock=1)
    product.stock = -1
    with pytest.raises(IntegrityError, match="stock_not_negative"):
        db.commit()
    db.rollback()
