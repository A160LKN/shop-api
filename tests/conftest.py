"""Общие фикстуры.

Тесты работают с настоящим PostgreSQL — отдельной базой shop_test.
Схема создаётся теми же миграциями Alembic, что и в продакшене: заодно проверяются и они.
"""
import os

# Адрес тестовой БД задаётся до импорта приложения: движок SQLAlchemy создаётся при импорте
os.environ["DATABASE_URL"] = os.getenv("TEST_DATABASE_URL", "postgresql+psycopg://shop:shop@localhost:5432/shop_test")
os.environ.setdefault("PAYMENT_GATEWAY_URL", "http://payments.test")

from datetime import UTC, datetime, timedelta  # noqa: E402
from itertools import count  # noqa: E402

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.db import SessionLocal, engine  # noqa: E402
from app.models import Product, PromoCode, Role, User  # noqa: E402
from app.security import create_token, hash_password  # noqa: E402

LEVELS = {"unit", "integration", "api"}


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items):
    """CI запускает тесты по уровням (-m unit, -m "integration or api"): тест без уровня молча не запустится нигде."""
    unmarked = [item.nodeid for item in items if not LEVELS & {m.name for m in item.iter_markers()}]
    if unmarked:
        raise pytest.UsageError("Тесты без уровня unit, integration или api не попадут в CI:\n" + "\n".join(unmarked))


TABLES = "order_items, orders, promo_codes, products, users"
PASSWORD = "secret-pass-123"
_ids = count(1)


@pytest.fixture(scope="session")
def database():
    """Чистая схема один раз на весь прогон: удалить всё и применить миграции."""
    # Предохранитель: тесты стирают базу целиком — рабочую базу по ошибке не тронем
    if "test" not in (engine.url.database or ""):
        pytest.exit(f"Тесты запускаются только на базе с «test» в имени, а указана «{engine.url.database}»",
                    returncode=2)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
    command.upgrade(Config("alembic.ini"), "head")
    yield engine
    engine.dispose()


@pytest.fixture
def clean_db(database):
    """Пустые таблицы перед каждым тестом — тесты не зависят друг от друга и от порядка запуска."""
    with database.begin() as conn:
        conn.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))


@pytest.fixture
def db(clean_db):
    with SessionLocal() as session:
        yield session


# ---------- Фабрики тестовых данных ----------

@pytest.fixture
def make_user(db):
    def make(role: Role = Role.customer, email: str | None = None) -> User:
        user = User(email=email or f"user{next(_ids)}@test.kz", password_hash=hash_password(PASSWORD), role=role)
        db.add(user)
        db.commit()
        return user
    return make


@pytest.fixture
def make_product(db):
    def make(name: str = "Чайник", category: str = "home", price: int = 10_000_00, stock: int = 10,
             is_active: bool = True) -> Product:
        product = Product(name=name, category=category, price=price, stock=stock, is_active=is_active)
        db.add(product)
        db.commit()
        return product
    return make


@pytest.fixture
def make_promo(db):
    def make(code: str = "SALE10", percent: int = 10, min_order_total: int = 0, max_uses: int = 100,
             used_count: int = 0, expires_at: datetime | None = None) -> PromoCode:
        promo = PromoCode(code=code, percent=percent, min_order_total=min_order_total, max_uses=max_uses,
                          used_count=used_count, expires_at=expires_at or datetime.now(UTC) + timedelta(days=30))
        db.add(promo)
        db.commit()
        return promo
    return make


def auth(user: User) -> dict[str, str]:
    """Заголовок авторизации для пользователя."""
    return {"Authorization": f"Bearer {create_token(user)}"}
