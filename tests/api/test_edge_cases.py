"""Крайние случаи, на которых API отвечал 500 вместо понятной ошибки (BUG-02 … BUG-05).

Каждый тест сначала падал, потом баг исправлен. 500 — это всегда баг: сервер не должен
падать от любого запроса клиента, даже бессмысленного.
"""
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from sqlalchemy.exc import TimeoutError as PoolTimeout

from app.config import settings
from app.db import get_db
from app.main import app
from app.models import Role
from tests.conftest import auth

pytestmark = pytest.mark.api

TOO_BIG_ID = 2_147_483_648  # на 1 больше максимума INTEGER в PostgreSQL


@pytest.fixture
def admin(make_user):
    return make_user(role=Role.admin)


# ---------- BUG-02: деньги не помещались в INTEGER ----------

@pytest.mark.parametrize("price", [2_147_483_648, 100_000_000_000], ids=["21.5M-tenge", "1B-tenge-max"])
def test_expensive_product(client, admin, price):
    response = client.post("/products", json={"name": "Авто", "category": "auto", "price": price, "stock": 1},
                           headers=auth(admin))
    assert response.status_code == 201
    assert response.json()["price"] == price


def test_price_above_limit(client, admin):
    response = client.post("/products", json={"name": "X", "category": "x", "price": 100_000_000_001, "stock": 1},
                           headers=auth(admin))
    assert response.status_code == 422


def test_order_total_above_two_billion_tiyn(client, make_user, make_product):
    product = make_product(price=1_000_000_000, stock=5)  # 10 млн ₸

    response = client.post("/orders", json={"items": [{"product_id": product.id, "quantity": 3}]},
                           headers=auth(make_user()))

    assert response.status_code == 201
    assert response.json()["total"] == 3_000_000_000


# ---------- BUG-03: id и offset за пределами INTEGER ----------

@pytest.mark.parametrize("url", [f"/products/{TOO_BIG_ID}", f"/orders/{TOO_BIG_ID}", "/products/0",
                                 "/products?offset=99999999999999999999"])
def test_out_of_range_numbers_in_url(client, make_user, url):
    assert client.get(url, headers=auth(make_user())).status_code == 422


def test_out_of_range_product_id_in_order(client, make_user):
    response = client.post("/orders", json={"items": [{"product_id": TOO_BIG_ID, "quantity": 1}]},
                           headers=auth(make_user()))
    assert response.status_code == 422


# ---------- BUG-04: токен с верной подписью, но без нужных полей ----------

@pytest.mark.parametrize("claims", [{}, {"sub": "abc"}, {"sub": 5}, {"sub": "-1"}, {"sub": str(TOO_BIG_ID)}],
                         ids=["no-sub", "text-sub", "number-sub", "negative-sub", "huge-sub"])
def test_token_with_broken_claims(client, claims):
    token = jwt.encode({**claims, "exp": datetime.now(UTC) + timedelta(minutes=5)}, settings.jwt_secret)

    response = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401


# ---------- BUG-05: PATCH с null в обязательном поле ----------

@pytest.mark.parametrize("field", ["name", "category", "price", "stock"])
def test_patch_with_null(client, admin, make_product, field):
    product = make_product()

    response = client.patch(f"/products/{product.id}", json={field: None}, headers=auth(admin))

    assert response.status_code == 422
    assert client.get(f"/products/{product.id}").status_code == 200  # товар не пострадал


# ---------- Промокоды: дата окончания ----------

@pytest.mark.parametrize(
    "expires_at",
    ["2020-01-01T00:00:00Z", "2030-01-01T00:00:00", "2030-01-01", "завтра"],
    ids=["in-past", "no-timezone", "date-only", "text"],
)
def test_promo_expiry_must_be_future_with_timezone(client, admin, expires_at):
    body = {"code": "DATES", "percent": 10, "max_uses": 1, "expires_at": expires_at}
    assert client.post("/promo-codes", json=body, headers=auth(admin)).status_code == 422


def test_promo_expiry_in_almaty_time(client, admin):
    body = {"code": "ASTANA", "percent": 10, "max_uses": 1, "expires_at": "2030-01-01T00:00:00+05:00"}
    response = client.post("/promo-codes", json=body, headers=auth(admin))
    assert response.status_code == 201


# ---------- Перегрузка: пул соединений с БД исчерпан (найдено нагрузочным тестом) ----------

def test_exhausted_db_pool_gives_503_not_500(client):
    def no_free_connections():
        raise PoolTimeout("QueuePool limit reached")
        yield  # pragma: no cover — делает функцию генератором, как настоящую get_db

    app.dependency_overrides[get_db] = no_free_connections
    try:
        response = client.get("/products")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.headers["Retry-After"] == "5"
    assert response.json()["error"]["code"] == "overloaded"
