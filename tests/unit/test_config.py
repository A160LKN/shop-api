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
