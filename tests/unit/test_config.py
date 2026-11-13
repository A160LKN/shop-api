"""Настройки: адрес базы от хостинга должен работать без ручной правки."""
import pytest

from app.config import Settings


@pytest.mark.parametrize(("given", "expected"), [
    ("postgresql://u:p@ep-x.neon.tech/shop?sslmode=require",
     "postgresql+psycopg://u:p@ep-x.neon.tech/shop?sslmode=require"),
    ("postgres://u:p@host:5432/shop", "postgresql+psycopg://u:p@host:5432/shop"),
    ("postgresql+psycopg://u:p@localhost:5432/shop", "postgresql+psycopg://u:p@localhost:5432/shop"),
])
def test_database_url_from_hosting_uses_psycopg(given, expected):
    assert Settings(database_url=given).database_url == expected
