from datetime import UTC, datetime, timedelta

import pytest

from app.models import Product, Role
from tests.conftest import auth

pytestmark = pytest.mark.api


def order(client, user, items, promo_code=None):
    body = {"items": [{"product_id": p.id, "quantity": q} for p, q in items]}
    if promo_code is not None:
        body["promo_code"] = promo_code
    return client.post("/orders", json=body, headers=auth(user))


def stock(db, product):
    db.expire_all()
    return db.get(Product, product.id).stock


# ---------- Создание заказа ----------

def test_order_is_created_and_stock_is_reserved(client, db, make_user, make_product):
    kettle = make_product(price=12_490_00, stock=10)
    bag = make_product(name="Рюкзак", price=15_990_00, stock=3)

    response = order(client, make_user(), [(kettle, 2), (bag, 1)])

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "created"
    assert (body["subtotal"], body["discount"], body["total"]) == (40_970_00, 0, 40_970_00)
    assert (stock(db, kettle), stock(db, bag)) == (8, 2)


def test_buying_exactly_the_last_items(client, db, make_user, make_product):
    product = make_product(stock=3)
    assert order(client, make_user(), [(product, 3)]).status_code == 201
    assert stock(db, product) == 0


def test_not_enough_stock(client, db, make_user, make_product):
    product = make_product(name="Пылесос", stock=3)

    response = order(client, make_user(), [(product, 4)])

    assert response.status_code == 409
    assert response.json()["error"]["message"] == "Недостаточно товара «Пылесос»: в наличии 3, в заказе 4"
    assert stock(db, product) == 3


def test_missing_and_deleted_products(client, make_user, make_product):
    deleted = make_product(is_active=False)
    user = make_user()

    assert client.post("/orders", json={"items": [{"product_id": 999, "quantity": 1}]},
                       headers=auth(user)).status_code == 404
    assert order(client, user, [(deleted, 1)]).status_code == 404


@pytest.mark.parametrize(
    "items",
    [[], [{"product_id": 1, "quantity": 0}], [{"product_id": 1, "quantity": 101}], [{"product_id": 1, "quantity": -1}],
     [{"product_id": 1, "quantity": 1}, {"product_id": 1, "quantity": 2}]],
    ids=["empty", "zero", "over-100", "negative", "duplicate-product"],
)
def test_invalid_order_body(client, make_user, make_product, items):
    make_product()
    assert client.post("/orders", json={"items": items}, headers=auth(make_user())).status_code == 422


def test_order_requires_login(client):
    assert client.post("/orders", json={"items": [{"product_id": 1, "quantity": 1}]}).status_code == 401


def test_price_in_order_does_not_change_with_catalog(client, db, make_user, make_product):
    user = make_user()
    product = make_product(price=10_000_00)
    order_id = order(client, user, [(product, 1)]).json()["id"]

    product.price = 15_000_00
    db.commit()

    assert client.get(f"/orders/{order_id}", headers=auth(user)).json()["total"] == 10_000_00


# ---------- Промокоды ----------

def test_promo_code(client, make_user, make_product, make_promo):
    make_promo(code="SALE10", percent=10)
    product = make_product(price=50_000_00)

    body = order(client, make_user(), [(product, 1)], promo_code=" sale10 ").json()

    assert (body["discount"], body["total"], body["promo_code"]) == (5_000_00, 45_000_00, "SALE10")


@pytest.mark.parametrize(
    ("promo", "message"),
    [
        ({"expires_at": datetime.now(UTC) - timedelta(minutes=1)}, "истёк"),
        ({"max_uses": 5, "used_count": 5}, "лимит"),
        ({"min_order_total": 100_000_00}, "от 100000 ₸"),
    ],
    ids=["expired", "limit-reached", "below-minimum"],
)
def test_promo_cannot_be_applied(client, db, make_user, make_product, make_promo, promo, message):
    make_promo(code="PROMO", **promo)
    product = make_product(price=50_000_00, stock=5)

    response = order(client, make_user(), [(product, 1)], promo_code="PROMO")

    assert response.status_code == 422
    assert message in response.json()["error"]["message"]
    assert stock(db, product) == 5  # заказ не создан — склад не тронут


def test_unknown_promo(client, make_user, make_product):
    response = order(client, make_user(), [(make_product(), 1)], promo_code="NOPE")
    assert response.json()["error"] == {"code": "promo_invalid", "message": "Промокод не найден"}


def test_admin_creates_promo(client, make_user):
    body = {"code": "NEWYEAR", "percent": 25, "max_uses": 50, "expires_at": "2027-01-10T00:00:00Z"}
    admin = auth(make_user(role=Role.admin))

    assert client.post("/promo-codes", json=body, headers=admin).status_code == 201
    assert client.post("/promo-codes", json=body, headers=admin).status_code == 409
    assert client.post("/promo-codes", json=body, headers=auth(make_user())).status_code == 403


@pytest.mark.parametrize(("percent", "code"), [(0, 422), (1, 201), (90, 201), (91, 422)])
def test_promo_percent_boundaries(client, make_user, percent, code):
    body = {"code": f"PCT{percent}", "percent": percent, "max_uses": 1, "expires_at": "2027-01-10T00:00:00Z"}
    assert client.post("/promo-codes", json=body, headers=auth(make_user(role=Role.admin))).status_code == code


# ---------- Доступ к заказам ----------

def test_customer_sees_only_own_orders(client, make_user, make_product):
    alice, bob = make_user(), make_user()
    product = make_product()
    order(client, alice, [(product, 1)])
    bob_order = order(client, bob, [(product, 1)]).json()

    assert [o["id"] for o in client.get("/orders", headers=auth(bob)).json()] == [bob_order["id"]]


def test_foreign_order_looks_like_missing(client, make_user, make_product):
    """IDOR: чужой заказ по прямому id — 404, как будто его нет. Ответ не выдаёт, что такой заказ существует."""
    alice, bob = make_user(), make_user()
    alice_order = order(client, alice, [(make_product(), 1)]).json()

    for url in (f"/orders/{alice_order['id']}", "/orders/999999"):
        response = client.get(url, headers=auth(bob))
        assert response.status_code == 404
        assert response.json()["error"]["message"] == "Заказ не найден"


def test_admin_sees_all_orders(client, make_user, make_product):
    customer = make_user()
    created = order(client, customer, [(make_product(), 1)]).json()
    admin = auth(make_user(role=Role.admin))

    assert client.get(f"/orders/{created['id']}", headers=admin).status_code == 200
    assert len(client.get("/orders", headers=admin).json()) == 1
