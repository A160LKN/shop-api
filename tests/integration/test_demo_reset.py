"""Сброс демо: пароль администратора публичный, и посетитель может испортить витрину.
Каждый старт сервера на Render возвращает каталог и промокоды к исходному виду."""
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app import seed
from app.models import Order, OrderItem, Product, PromoCode

pytestmark = pytest.mark.integration


def test_reset_restores_catalog_and_promos(db, make_product, make_promo, make_user):
    seed.reset_demo(db)  # исходный каталог на пустой базе
    kettle = db.scalar(select(Product).where(Product.name == "Чайник Xiaomi Mi Kettle"))

    # «Вандал» с паролем из README: обнулил цену, спрятал товар, добавил свой товар и промокод на 90 %
    kettle.price, kettle.stock = 1, 0
    hidden = db.scalar(select(Product).where(Product.name == "Пылесос Dreame T20"))
    hidden.is_active = False
    junk = make_product(name="Купите у меня дешевле", price=1)
    make_promo(code="FREE90", percent=90)
    # Заказ ссылается на добавленный товар — строку удалить нельзя, только скрыть
    buyer = make_user()
    db.add(Order(user_id=buyer.id, subtotal=1, total=1, items=[OrderItem(product_id=junk.id, quantity=1, price=1)]))
    db.commit()

    seed.reset_demo(db, now=datetime(2026, 1, 1, tzinfo=UTC))
    db.expire_all()

    assert (kettle.price, kettle.stock, kettle.is_active) == (12_490_00, 40, True)
    assert hidden.is_active
    assert not junk.is_active, "посторонний товар скрыт с витрины"
    assert db.scalar(select(Order).where(Order.user_id == buyer.id)) is not None, "заказы покупателей не тронуты"
    active = db.scalars(select(Product.name).where(Product.is_active)).all()
    assert sorted(active) == sorted(name for name, *_ in seed.PRODUCTS)
    promos = {p.code: p for p in db.scalars(select(PromoCode))}
    assert set(promos) == {"WELCOME10", "BIG20"}
    assert promos["WELCOME10"].used_count == 0
    assert promos["WELCOME10"].expires_at.year == 2027


def test_reset_is_idempotent(db):
    seed.reset_demo(db)
    seed.reset_demo(db)
    assert len(db.scalars(select(Product)).all()) == len(seed.PRODUCTS), "повторный сброс не плодит товары"


def test_renamed_product_is_recreated_and_hidden(db):
    seed.reset_demo(db)
    tea = db.scalar(select(Product).where(Product.name.startswith("Чай зелёный")))
    tea.name = "Переименовано вандалом"
    db.commit()
    seed.reset_demo(db)
    db.expire_all()
    assert not tea.is_active
    restored = db.scalar(select(Product).where(Product.name.startswith("Чай зелёный")))
    assert restored is not None and restored.is_active and restored.id != tea.id
