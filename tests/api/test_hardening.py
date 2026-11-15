"""Безопасность: подбор пароля, слабые пароли, заголовки, ID запроса, размер тела, ошибки без подробностей."""
import pytest

from app.config import settings
from app.main import app
from tests.conftest import PASSWORD

pytestmark = pytest.mark.api


@pytest.fixture
def trust_proxy(monkeypatch):
    monkeypatch.setattr(settings, "trust_proxy", True)


def login(client, email: str, password: str, ip: str = "10.0.0.1"):
    return client.post("/auth/login", json={"email": email, "password": password},
                       headers={"X-Forwarded-For": ip})


def test_five_wrong_passwords_lock_login_for_this_email_and_ip(client, make_user, trust_proxy):
    user = make_user()
    for _ in range(5):
        assert login(client, user.email, "wrong-password").status_code == 401
    r = login(client, user.email, PASSWORD)
    assert r.status_code == 429, "даже верный пароль не пускает"
    assert r.json()["error"]["code"] == "too_many_attempts"
    assert 0 < int(r.headers["Retry-After"]) <= 15 * 60
    assert login(client, user.email, PASSWORD, ip="10.0.0.2").status_code == 200, "с другого адреса можно"


def test_successful_login_resets_the_counter(client, make_user, trust_proxy):
    user = make_user()
    for _ in range(4):
        login(client, user.email, "wrong-password")
    assert login(client, user.email, PASSWORD).status_code == 200
    for _ in range(4):
        assert login(client, user.email, "wrong-password").status_code == 401


def test_spoofed_ips_still_hit_the_per_email_limit(client, make_user, trust_proxy):
    """Даже с доверием к прокси новые IP в каждом запросе не дают перебирать пароль бесконечно."""
    user = make_user()
    for n in range(20):
        login(client, user.email, "wrong-password", ip=f"7.7.{n // 250}.{n % 250}")
    assert login(client, user.email, PASSWORD, ip="8.8.8.8").status_code == 429


def test_forwarded_for_is_ignored_without_trust(client, make_user):
    """Без доверия к прокси подделанный X-Forwarded-For не обходит лимит."""
    user = make_user()
    for n in range(5):
        login(client, user.email, "wrong-password", ip=f"1.1.1.{n}")
    assert login(client, user.email, PASSWORD, ip="9.9.9.9").status_code == 429


def test_registration_is_limited_per_ip(client, trust_proxy):
    for n in range(settings.registrations_per_hour):
        r = client.post("/auth/register", json={"email": f"spam{n}@test.kz", "password": PASSWORD},
                        headers={"X-Forwarded-For": "6.6.6.6"})
        assert r.status_code == 201
    r = client.post("/auth/register", json={"email": "spam-last@test.kz", "password": PASSWORD},
                    headers={"X-Forwarded-For": "6.6.6.6"})
    assert r.status_code == 429


@pytest.mark.parametrize("password", ["12345678", "password", "aaaaaaaa", "abababab", "user@test.kz"])
def test_weak_passwords_are_rejected(client, password):
    r = client.post("/auth/register", json={"email": "user@test.kz", "password": password})
    assert (r.status_code, r.json()["error"]["code"]) == (422, "weak_password")


def test_security_headers_on_every_response(client):
    for r in (client.get("/health"), client.get("/auth/me"), client.get("/nope")):
        assert r.headers["X-Content-Type-Options"] == "nosniff"
        assert r.headers["X-Frame-Options"] == "DENY"
        assert r.headers["Referrer-Policy"] == "no-referrer"
        assert "max-age=" in r.headers["Strict-Transport-Security"]
        assert r.headers["Content-Security-Policy"].startswith("default-src 'none'")


def test_docs_page_still_works_with_its_own_csp(client):
    r = client.get("/docs")
    assert r.status_code == 200 and "cdn.jsdelivr.net" in r.headers["Content-Security-Policy"]


def test_request_id_is_returned_and_unsafe_ids_are_replaced(client):
    assert len(client.get("/health").headers["X-Request-ID"]) == 16
    assert client.get("/health", headers={"X-Request-ID": "abc-123"}).headers["X-Request-ID"] == "abc-123"
    evil = client.get("/health", headers={"X-Request-ID": "x\" injected=1"}).headers["X-Request-ID"]
    assert evil != "x\" injected=1" and evil.isalnum()


def test_huge_body_is_rejected_before_parsing(client):
    r = client.post("/auth/login", content=b"{" + b" " * 300_000 + b"}", headers={"Content-Type": "application/json"})
    assert (r.status_code, r.json()["error"]["code"]) == (413, "payload_too_large")


def test_unexpected_error_hides_details_but_gives_request_id(client):
    @app.get("/boom-for-test")
    def boom():
        raise RuntimeError("секрет из базы")

    try:
        r = client.get("/boom-for-test")
    finally:
        app.router.routes = [rt for rt in app.router.routes if getattr(rt, "path", "") != "/boom-for-test"]
    assert r.status_code == 500
    assert r.json()["error"] == {"code": "internal_error", "message": "Внутренняя ошибка сервера",
                                 "request_id": r.headers["X-Request-ID"]}
    assert "секрет" not in r.text
