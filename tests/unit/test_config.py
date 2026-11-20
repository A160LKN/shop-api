"""Настройки: адрес базы от хостинга должен работать без ручной правки."""
import pytest

from app.config import Settings

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(("given", "expected"), [
    ("postgresql://u:p@ep-x.neon.tech/shop?sslmode=require",
     "postgresql+psycopg://u:p@ep-x.neon.tech/shop?sslmode=require"),
    ("postgres://u:p@host:5432/shop", "postgresql+psycopg://u:p@host:5432/shop"),
    ("postgresql+psycopg://u:p@localhost:5432/shop", "postgresql+psycopg://u:p@localhost:5432/shop"),
])
def test_database_url_from_hosting_uses_psycopg(given, expected):
    assert Settings(database_url=given).database_url == expected


@pytest.mark.parametrize("secret", ["dev-secret-change-me-in-production-32b", "short-but-not-default"])
def test_production_refuses_default_or_short_jwt_secret(secret):
    with pytest.raises(ValueError, match="JWT_SECRET"):
        Settings(environment="production", jwt_secret=secret)


def test_production_accepts_real_secret_and_dev_keeps_default():
    assert Settings(environment="production", jwt_secret="x" * 40).environment == "production"
    dev = Settings(environment="development", jwt_secret="dev-secret-change-me-in-production-32b")
    assert dev.jwt_secret.startswith("dev-"), "локально и в тестах значение по умолчанию работает"


def test_render_turns_on_live_site_defaults(monkeypatch):
    """На Render (он сам задаёт RENDER=true) прокси, Cloudflare и запрет секретов включаются без настройки в панели."""
    for name in ("ENVIRONMENT", "TRUST_PROXY", "PROXY_HOPS", "CLIENT_IP_HEADER", "JWT_SECRET"):
        monkeypatch.delenv(name, raising=False)  # JWT_SECRET задаёт conftest — здесь нужен секрет по умолчанию
    monkeypatch.setenv("RENDER", "true")
    live = Settings(jwt_secret="x" * 40)
    assert (live.environment, live.trust_proxy, live.proxy_hops, live.client_ip_header) == (
        "production", True, 2, "cf-connecting-ip")
    with pytest.raises(ValueError, match="JWT_SECRET"):
        Settings()  # секрет по умолчанию на живом сайте — сервер не стартует

    monkeypatch.setenv("CLIENT_IP_HEADER", "true-client-ip")
    assert Settings(jwt_secret="x" * 40).client_ip_header == "true-client-ip", "явная переменная важнее"


def test_without_render_headers_are_not_trusted(monkeypatch):
    monkeypatch.delenv("RENDER", raising=False)
    for name in ("ENVIRONMENT", "TRUST_PROXY", "PROXY_HOPS", "CLIENT_IP_HEADER"):
        monkeypatch.delenv(name, raising=False)
    local = Settings()
    assert (local.environment, local.trust_proxy, local.client_ip_header) == ("development", False, "")
