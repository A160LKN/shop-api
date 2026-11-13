"""Заказ проходит весь путь через API — сквозной сценарий и переходы, запрещённые бизнес-правилами."""
import httpx
import pytest

from app.models import Role
from tests.conftest import auth

pytestmark = pytest.mark.api


@pytest.fixture
def parties(make_user):
    return make_user(), make_user(role=Role.admin)


@pytest.fixture
def order_id(client, parties, make_product):
    customer, _ = parties
    product = make_product(stock=5)
    return client.post("/orders", json={"items": [{"product_id": product.id, "quantity": 1}]},
                       headers=auth(customer)).json()["id"]


def act(client, user, order_id, action):
    body = {"card_token": "tok_visa"} if action == "pay" else None
    return client.post(f"/orders/{order_id}/{action}", json=body, headers=auth(user))


def test_full_path_from_order_to_delivery(client, gateway, parties, order_id):
    customer, admin = parties
    gateway.post("/payments").mock(return_value=httpx.Response(200, json={"status": "approved", "payment_id": "p1"}))

    assert act(client, customer, order_id, "pay").json()["status"] == "paid"
    assert act(client, admin, order_id, "ship").json()["status"] == "shipped"
    assert act(client, admin, order_id, "deliver").json()["status"] == "delivered"
    assert act(client, customer, order_id, "cancel").status_code == 409  # доставленный — уже не отменить


def test_customer_cannot_ship_or_deliver(client, parties, order_id):
    customer, _ = parties
    assert act(client, customer, order_id, "ship").status_code == 403
    assert act(client, customer, order_id, "deliver").status_code == 403


def test_unpaid_order_cannot_be_shipped(client, parties, order_id):
    _, admin = parties
    response = act(client, admin, order_id, "ship")

    assert response.status_code == 409
    assert response.json()["error"]["message"] == "Нельзя отправить заказ в статусе «создан»"


def test_cancelled_order_cannot_be_paid(client, gateway, parties, order_id):
    customer, _ = parties
    charge = gateway.post("/payments")
    act(client, customer, order_id, "cancel")

    assert act(client, customer, order_id, "pay").status_code == 409
    assert not charge.called


def test_admin_can_cancel_customer_order(client, parties, order_id):
    _, admin = parties
    assert act(client, admin, order_id, "cancel").json()["status"] == "cancelled"


def test_shipping_missing_order(client, parties):
    _, admin = parties
    assert act(client, admin, 999_999, "ship").status_code == 404


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_root_opens_api_docs(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/docs"
