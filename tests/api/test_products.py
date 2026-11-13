import pytest

from app.models import Role
from tests.conftest import auth

pytestmark = pytest.mark.api

NEW = {"name": "Утюг Philips", "category": "home", "price": 19_990_00, "stock": 5}


@pytest.fixture
def admin(make_user):
    return make_user(role=Role.admin)


# ---------- Каталог: чтение ----------

def test_pagination(client, make_product):
    for i in range(5):
        make_product(name=f"Товар {i}")

    page = client.get("/products", params={"limit": 2, "offset": 2}).json()

    assert page["total"] == 5
    assert [p["name"] for p in page["items"]] == ["Товар 2", "Товар 3"]


@pytest.mark.parametrize(("limit", "code"), [(0, 422), (1, 200), (100, 200), (101, 422)])
def test_limit_boundaries(client, limit, code):
    assert client.get("/products", params={"limit": limit}).status_code == code


def test_negative_offset(client):
    assert client.get("/products", params={"offset": -1}).status_code == 422


def test_filter_by_category(client, make_product):
    make_product(name="Чайник", category="home")
    make_product(name="Наушники", category="electronics")

    items = client.get("/products", params={"category": "electronics"}).json()["items"]

    assert [p["name"] for p in items] == ["Наушники"]


def test_search_ignores_case(client, make_product):
    make_product(name="Чайник Xiaomi")
    make_product(name="Пылесос")

    items = client.get("/products", params={"q": "чАЙник"}).json()["items"]

    assert [p["name"] for p in items] == ["Чайник Xiaomi"]


@pytest.mark.parametrize("q", ["%", "_", "' OR 1=1 --", "'; DROP TABLE products; --"])
def test_special_characters_in_search_do_not_match_everything(client, make_product, q):
    make_product(name="Чайник")

    response = client.get("/products", params={"q": q})

    assert response.status_code == 200
    assert response.json()["total"] == 0
    assert client.get("/products").json()["total"] == 1  # таблица на месте


def test_get_product(client, make_product):
    product = make_product(name="Чайник", price=12_490_00)
    assert client.get(f"/products/{product.id}").json()["price"] == 12_490_00


@pytest.mark.parametrize("product_id", ["999999", "abc", "-1"])
def test_get_missing_product(client, product_id):
    assert client.get(f"/products/{product_id}").status_code in (404, 422)


def test_deleted_product_is_hidden(client, make_product):
    product = make_product(is_active=False)
    assert client.get(f"/products/{product.id}").status_code == 404
    assert client.get("/products").json()["total"] == 0


# ---------- Управление каталогом: права ----------

def test_admin_creates_product(client, admin):
    response = client.post("/products", json=NEW, headers=auth(admin))

    assert response.status_code == 201
    assert client.get(f"/products/{response.json()['id']}").json() == response.json()


def test_customer_cannot_manage_catalog(client, make_user, make_product):
    customer = auth(make_user())
    product = make_product()

    assert client.post("/products", json=NEW, headers=customer).status_code == 403
    assert client.patch(f"/products/{product.id}", json={"price": 1}, headers=customer).status_code == 403
    assert client.delete(f"/products/{product.id}", headers=customer).status_code == 403


def test_anonymous_cannot_manage_catalog(client):
    assert client.post("/products", json=NEW).status_code == 401


@pytest.mark.parametrize(
    ("field", "value"),
    [("price", 0), ("price", -100), ("price", "сто"), ("price", 10.5),
     ("stock", -1), ("name", ""), ("name", "x" * 201)],
)
def test_invalid_product(client, admin, field, value):
    assert client.post("/products", json={**NEW, field: value}, headers=auth(admin)).status_code == 422


def test_unknown_field_is_rejected(client, admin):
    assert client.post("/products", json={**NEW, "discount": 5}, headers=auth(admin)).status_code == 422


def test_patch_changes_only_given_fields(client, admin, make_product):
    product = make_product(name="Чайник", price=10_000_00, stock=3)

    body = client.patch(f"/products/{product.id}", json={"price": 9_000_00}, headers=auth(admin)).json()

    assert (body["name"], body["price"], body["stock"]) == ("Чайник", 9_000_00, 3)


def test_delete_is_soft(client, admin, make_product, db):
    product = make_product()

    assert client.delete(f"/products/{product.id}", headers=auth(admin)).status_code == 204
    assert client.get(f"/products/{product.id}").status_code == 404
    db.refresh(product)
    assert product.is_active is False  # запись осталась — на неё ссылаются старые заказы


def test_patch_and_delete_missing_product(client, admin):
    assert client.patch("/products/999999", json={"price": 100}, headers=auth(admin)).status_code == 404
    assert client.delete("/products/999999", headers=auth(admin)).status_code == 404


def test_categories_with_counts(client, make_product):
    make_product(category="home")
    make_product(category="home")
    make_product(category="electronics")
    make_product(category="hidden", is_active=False)

    assert client.get("/products/categories").json() == [
        {"name": "electronics", "count": 1},
        {"name": "home", "count": 2},
    ]


# ---------- Сортировка и фильтры ----------

@pytest.fixture
def assortment(make_product):
    make_product(name="Б-средний", price=5_000_00, stock=3)
    make_product(name="А-дорогой", price=9_000_00, stock=0)
    make_product(name="В-дешёвый", price=1_000_00, stock=10)


def names(client, **params):
    return [p["name"] for p in client.get("/products", params=params).json()["items"]]


@pytest.mark.parametrize(
    ("sort", "expected"),
    [
        ("default", ["Б-средний", "А-дорогой", "В-дешёвый"]),
        ("newest", ["В-дешёвый", "А-дорогой", "Б-средний"]),
        ("price_asc", ["В-дешёвый", "Б-средний", "А-дорогой"]),
        ("price_desc", ["А-дорогой", "Б-средний", "В-дешёвый"]),
        ("name", ["А-дорогой", "Б-средний", "В-дешёвый"]),
    ],
)
def test_sorting(client, assortment, sort, expected):
    assert names(client, sort=sort) == expected


def test_unknown_sort_is_rejected(client):
    assert client.get("/products", params={"sort": "random"}).status_code == 422


def test_only_in_stock(client, assortment):
    assert "А-дорогой" not in names(client, in_stock=True)


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"min_price": 5_000_00}, ["Б-средний", "А-дорогой"]),  # граница включается
        ({"max_price": 5_000_00}, ["Б-средний", "В-дешёвый"]),
        ({"min_price": 2_000_00, "max_price": 8_000_00}, ["Б-средний"]),
        ({"min_price": 5_000_00, "max_price": 5_000_00}, ["Б-средний"]),
    ],
)
def test_price_range(client, assortment, params, expected):
    assert names(client, **params) == expected


def test_price_range_upside_down(client):
    response = client.get("/products", params={"min_price": 2, "max_price": 1})
    assert response.status_code == 422
    assert response.json()["error"]["message"] == "Цена «от» больше цены «до»"


def test_filters_combine_with_search_and_total(client, assortment):
    body = client.get("/products", params={"q": "е", "in_stock": True, "sort": "price_desc"}).json()
    assert [p["name"] for p in body["items"]] == ["Б-средний", "В-дешёвый"]
    assert body["total"] == 2
