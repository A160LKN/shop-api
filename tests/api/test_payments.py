"""Оплата и возврат через внешний шлюз. Шлюз заменён моком (respx):
можно проверить отказ, таймаут и падение шлюза — на настоящем сервисе такое не воспроизвести по заказу."""
import json

import httpx
import pytest

from app.models import Product, Role
from tests.conftest import auth

pytestmark = pytest.mark.api

APPROVED = httpx.Response(200, json={"status": "approved", "payment_id": "pay_123"})


@pytest.fixture
def customer(make_user):
    return make_user()


@pytest.fixture
def new_order(client, customer, make_product):
    product = make_product(price=25_000_00, stock=5)
    body = client.post("/orders", json={"items": [{"product_id": product.id, "quantity": 2}]},
                       headers=auth(customer)).json()
    return body["id"], product


def pay(client, user, order_id, card_token="tok_visa"):
    return client.post(f"/orders/{order_id}/pay", json={"card_token": card_token}, headers=auth(user))


def status_of(client, user, order_id):
    return client.get(f"/orders/{order_id}", headers=auth(user)).json()["status"]


def stock(db, product):
    db.expire_all()
    return db.get(Product, product.id).stock


# ---------- Оплата ----------

def test_successful_payment(client, gateway, customer, new_order):
    order_id, _ = new_order
    charge = gateway.post("/payments").mock(return_value=APPROVED)

    response = pay(client, customer, order_id)

    assert response.status_code == 200
    assert response.json()["status"] == "paid"
    sent = charge.calls.last.request
    assert json.loads(sent.content) == {"order_id": order_id, "amount": 50_000_00, "currency": "KZT",
                                        "card_token": "tok_visa"}
    assert sent.headers["Idempotency-Key"] == f"order-{order_id}-charge"


def test_declined_payment_keeps_order_and_allows_retry(client, gateway, customer, new_order):
    order_id, _ = new_order
    gateway.post("/payments").mock(side_effect=[
        httpx.Response(200, json={"status": "declined", "reason": "недостаточно средств"}),
        APPROVED,
    ])

    declined = pay(client, customer, order_id, card_token="tok_empty")
    assert declined.status_code == 402
    assert declined.json()["error"]["message"] == "Оплата отклонена: недостаточно средств"
    assert status_of(client, customer, order_id) == "created"

    assert pay(client, customer, order_id).json()["status"] == "paid"  # с другой картой — получилось


@pytest.mark.parametrize(
    "failure",
    [httpx.ReadTimeout("timeout"), httpx.ConnectError("refused"), httpx.Response(500), httpx.Response(503)],
    ids=["timeout", "connection-refused", "500", "503"],
)
def test_gateway_failure(client, gateway, customer, new_order, failure):
    order_id, _ = new_order
    route = gateway.post("/payments")
    route.mock(side_effect=failure) if isinstance(failure, Exception) else route.mock(return_value=failure)

    response = pay(client, customer, order_id)

    assert response.status_code == 502
    assert "Деньги не списаны" in response.json()["error"]["message"]
    assert status_of(client, customer, order_id) == "created"


def test_paid_order_cannot_be_paid_again(client, gateway, customer, new_order):
    order_id, _ = new_order
    charge = gateway.post("/payments").mock(return_value=APPROVED)

    pay(client, customer, order_id)
    second = pay(client, customer, order_id)

    assert second.status_code == 409
    assert charge.call_count == 1  # в шлюз ушёл ровно один запрос — двойного списания нет


def test_cannot_pay_foreign_order(client, gateway, make_user, new_order):
    order_id, _ = new_order
    charge = gateway.post("/payments").mock(return_value=APPROVED)

    assert pay(client, make_user(), order_id).status_code == 404
    assert not charge.called


def test_admin_cannot_pay_for_customer(client, gateway, make_user, new_order):
    order_id, _ = new_order
    gateway.post("/payments").mock(return_value=APPROVED)
    assert pay(client, make_user(role=Role.admin), order_id).status_code == 403


@pytest.mark.parametrize("card_token", ["", "ab", "x" * 65])
def test_invalid_card_token(client, customer, new_order, card_token):
    order_id, _ = new_order
    assert pay(client, customer, order_id, card_token).status_code == 422


# ---------- Отмена и возврат ----------

def test_cancel_unpaid_order_returns_stock_without_gateway(client, db, gateway, customer, new_order):
    order_id, product = new_order
    refund = gateway.post(path__regex=r"/payments/.+/refund")

    response = client.post(f"/orders/{order_id}/cancel", headers=auth(customer))

    assert response.json()["status"] == "cancelled"
    assert stock(db, product) == 5
    assert not refund.called


def test_cancel_paid_order_refunds_money(client, db, gateway, customer, new_order):
    order_id, product = new_order
    gateway.post("/payments").mock(return_value=APPROVED)
    refund = gateway.post("/payments/pay_123/refund").mock(return_value=httpx.Response(200, json={"status": "ok"}))
    pay(client, customer, order_id)

    response = client.post(f"/orders/{order_id}/cancel", headers=auth(customer))

    assert response.json()["status"] == "cancelled"
    assert json.loads(refund.calls.last.request.content) == {"amount": 50_000_00}
    assert stock(db, product) == 5


@pytest.mark.parametrize("failure", [httpx.ReadTimeout("timeout"), httpx.Response(409)], ids=["timeout", "rejected"])
def test_failed_refund_keeps_order_paid(client, db, gateway, customer, new_order, failure):
    order_id, product = new_order
    gateway.post("/payments").mock(return_value=APPROVED)
    route = gateway.post("/payments/pay_123/refund")
    route.mock(side_effect=failure) if isinstance(failure, Exception) else route.mock(return_value=failure)
    pay(client, customer, order_id)

    response = client.post(f"/orders/{order_id}/cancel", headers=auth(customer))

    assert response.status_code == 502
    assert status_of(client, customer, order_id) == "paid"
    assert stock(db, product) == 3  # товар не вернулся на склад: деньги ведь тоже не вернулись
