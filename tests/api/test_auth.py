from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.config import settings
from tests.conftest import PASSWORD, auth

pytestmark = pytest.mark.api


def register(client, email="aibol@mail.kz", password="strong-pass-1"):
    return client.post("/auth/register", json={"email": email, "password": password})


def test_register(client):
    response = register(client)

    assert response.status_code == 201
    body = response.json()
    assert body == {"id": body["id"], "email": "aibol@mail.kz", "role": "customer"}  # без пароля и хеша


def test_email_is_unique_regardless_of_case(client):
    register(client, email="aibol@mail.kz")
    response = register(client, email="  AIBOL@Mail.KZ ")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "email_taken"


def test_cannot_register_as_admin(client):
    response = client.post("/auth/register", json={"email": "x@y.kz", "password": "strong-pass-1", "role": "admin"})
    assert response.status_code == 422  # лишние поля запрещены — роль через регистрацию не подменить


@pytest.mark.parametrize("email", ["", "aibol", "aibol@", "@mail.kz", "aibol@mail", "ai bol@mail.kz"])
def test_invalid_email(client, email):
    assert register(client, email=email).status_code == 422


@pytest.mark.parametrize(
    ("password", "code"),
    # Границы длины — на надёжных паролях: простые вроде «12345678» теперь отклоняются отдельной проверкой
    [("k7#mq2z", 422), ("k7#mq2zp", 201), ("k7#m" * 32, 201), ("k7#m" * 32 + "q", 422)],
    ids=["7-chars", "8-chars", "128-chars", "129-chars"],
)
def test_password_length_boundaries(client, password, code):
    assert register(client, password=password).status_code == code


def test_login_returns_working_token(client):
    register(client)
    login = client.post("/auth/login", json={"email": "aibol@mail.kz", "password": "strong-pass-1"})

    assert login.status_code == 200
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {login.json()['access_token']}"})
    assert me.json()["email"] == "aibol@mail.kz"


@pytest.mark.parametrize(
    ("email", "password"),
    [("aibol@mail.kz", "wrong-pass-1"), ("nobody@mail.kz", "strong-pass-1")],
    ids=["wrong-password", "unknown-email"],
)
def test_login_failure_does_not_reveal_which_part_is_wrong(client, email, password):
    register(client)
    response = client.post("/auth/login", json={"email": email, "password": password})

    assert response.status_code == 401
    assert response.json()["error"]["message"] == "Неверный email или пароль"


def test_me_requires_token(client):
    response = client.get("/auth/me")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def token_for(user_id: int, secret: str = settings.jwt_secret, algorithm: str = "HS256", minutes: int = 5) -> str:
    now = datetime.now(UTC)
    payload = {"sub": str(user_id), "role": "admin", "iat": now, "exp": now + timedelta(minutes=minutes)}
    return jwt.encode(payload, None if algorithm == "none" else secret, algorithm=algorithm)


@pytest.mark.parametrize(
    ("make_token", "code"),
    [
        (lambda uid: "not-a-jwt", "invalid_token"),
        (lambda uid: token_for(uid, secret="another-secret-of-thirty-two-bytes"), "invalid_token"),
        (lambda uid: token_for(uid, minutes=-1), "token_expired"),
        (lambda uid: token_for(uid, algorithm="none"), "invalid_token"),
        (lambda uid: token_for(999_999), "invalid_token"),
    ],
    ids=["garbage", "foreign-signature", "expired", "alg-none", "deleted-user"],
)
def test_bad_tokens_are_rejected(client, make_user, make_token, code):
    user = make_user()
    response = client.get("/auth/me", headers={"Authorization": f"Bearer {make_token(user.id)}"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == code


def test_role_in_token_cannot_be_forged(client, make_user):
    """Роль берётся из БД, а не из токена: покупатель с «role: admin» в токене админом не станет."""
    user = make_user()  # покупатель; token_for пишет в токен role=admin
    response = client.post("/products", json={"name": "X", "category": "c", "price": 100, "stock": 1},
                           headers={"Authorization": f"Bearer {token_for(user.id)}"})
    assert response.status_code == 403


def test_auth_helper_works(client, make_user):
    user = make_user()
    assert client.get("/auth/me", headers=auth(user)).status_code == 200
    assert client.post("/auth/login", json={"email": user.email, "password": PASSWORD}).status_code == 200
