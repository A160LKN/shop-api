"""Расчёт стоимости до заказа и сводка для администратора."""
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.models import Product, PromoCode, Role
from tests.conftest import auth

pytestmark = pytest.mark.api


def quote(client, user, items, promo_code=None):
    body = {"items": [{"product_id": p.id, "quantity": q} for p, q in items], "promo_code": promo_code}
    return client.post("/orders/quote", json=body, headers=auth(user))


# ---------- Расчёт стоимости ----------

def test_quote_shows_discount_without_creating_order(client, db, make_user, make_product, make_promo):
    product = make_product(price=50_000_00, stock=5)
    make_promo(code="SALE10", percent=10, max_uses=1)

    response = quote(client, make_user(), [(product, 2)], "sale10")

    assert response.status_code == 200
    assert response.json() == {"subtotal": 100_000_00, "discount": 10_000_00, "total": 90_000_00,
                               "promo_code": "SALE10"}
    db.expire_all()
    assert db.get(Product, product.id).stock == 5  # ничего не зарезервировано
    assert db.query(PromoCode).one().used_count == 0  # промокод не израсходован — можно считать сколько угодно


def test_quote_without_promo(client, make_user, make_product):
    body = quote(client, make_user(), [(make_product(price=1_000_00), 3)]).json()
    assert body == {"subtotal": 3_000_00, "discount": 0, "total": 3_000_00, "promo_code": None}


@pytest.mark.parametrize(
    ("promo", "code", "status"),
    [
        (None, "NOPE", 422),
        ({"expires_at": datetime.now(UTC) - timedelta(minutes=1)}, "OLD", 422),
        ({"min_order_total": 1_000_000_00}, "BIG", 422),
    ],
    ids=["unknown", "expired", "below-minimum"],
)
def test_quote_promo_errors_match_order_errors(client, make_user, make_product, make_promo, promo, code, status):
    if promo is not None:
        make_promo(code=code, **promo)
    response = quote(client, make_user(), [(make_product(), 1)], code)
    assert response.status_code == status
    assert response.json()["error"]["code"] == "promo_invalid"


def test_quote_reports_missing_stock(client, make_user, make_product):
    response = quote(client, make_user(), [(make_product(stock=1), 2)])
    assert response.status_code == 409


def test_quote_requires_login(client, make_product):
    product = make_product()
    response = client.post("/orders/quote", json={"items": [{"product_id": product.id, "quantity": 1}]})
    assert response.status_code == 401


# ---------- Сводка ----------

@pytest.fixture
def admin(make_user):
    return make_user(role=Role.admin)


def test_stats_only_for_admin(client, make_user, admin):
    assert client.get("/stats").status_code == 401
    assert client.get("/stats", headers=auth(make_user())).status_code == 403
    assert client.get("/stats", headers=auth(admin)).status_code == 200


def test_empty_shop_stats(client, admin):
    body = client.get("/stats", headers=auth(admin)).json()
    assert (body["revenue"], body["paid_orders"], body["average_check"]) == (0, 0, 0)
    assert len(body["revenue_by_day"]) == 7
    assert all(day["revenue"] == 0 for day in body["revenue_by_day"])
    assert {s["status"]: s["count"] for s in body["orders_by_status"]} == dict.fromkeys(
        ["created", "paid", "shipped", "delivered", "cancelled"], 0)


def test_stats_count_only_paid_money(client, gateway, make_user, make_product, admin):
    gateway.post("/payments").mock(return_value=httpx.Response(200, json={"status": "approved", "payment_id": "p"}))
    gateway.post("/payments/p/refund").mock(return_value=httpx.Response(200, json={"status": "ok"}))
    buyer = make_user()
    kettle = make_product(name="Чайник", price=10_000_00, stock=50)
    coffee = make_product(name="Кофе", price=2_000_00, stock=3)

    def place(product, quantity, pay=True):
        order_id = client.post("/orders", json={"items": [{"product_id": product.id, "quantity": quantity}]},
                               headers=auth(buyer)).json()["id"]
        if pay:
            client.post(f"/orders/{order_id}/pay", json={"card_token": "tok_visa"}, headers=auth(buyer))
        return order_id

    place(kettle, 2)                 # оплачен: 20 000 ₸
    place(coffee, 1)                 # оплачен: 2 000 ₸
    place(kettle, 1, pay=False)      # не оплачен — в выручку не идёт
    cancelled = place(kettle, 5)
    client.post(f"/orders/{cancelled}/cancel", headers=auth(buyer))  # отменён — тоже нет

    body = client.get("/stats", headers=auth(admin)).json()

    assert body["revenue"] == 22_000_00
    assert body["paid_orders"] == 2
    assert body["average_check"] == 11_000_00
    statuses = {s["status"]: s["count"] for s in body["orders_by_status"]}
    assert (statuses["paid"], statuses["created"], statuses["cancelled"]) == (2, 1, 1)
    assert body["revenue_by_day"][-1]["revenue"] == 22_000_00  # сегодня
    assert body["revenue_by_day"][-1]["orders"] == 2
    # отменённые продажи не считаются: чайник — 2 + 1 (неоплаченный, но заказанный) = 3
    assert [(p["name"], p["quantity"]) for p in body["top_products"]] == [("Чайник", 3), ("Кофе", 1)]
    assert [(p["name"], p["stock"]) for p in body["low_stock"]] == [("Кофе", 2)]
