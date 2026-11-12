"""Демо-данные: администратор, товары и промокоды. Повторный запуск ничего не дублирует."""
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app.models import Product, PromoCode, Role, User
from app.security import hash_password

PRODUCTS = [
    ("Смартфон Samsung Galaxy A56", "electronics", 189_990_00, 25),
    ("Наушники JBL Tune 520BT", "electronics", 24_990_00, 60),
    ("Чайник Xiaomi Mi Kettle", "home", 12_490_00, 40),
    ("Пылесос Dreame T20", "home", 129_990_00, 8),
    ("Рюкзак городской 20 л", "accessories", 15_990_00, 30),
    ("Кофе в зёрнах 1 кг", "food", 9_990_00, 100),
]


def seed() -> None:
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.email == settings.admin_email)) is None:
            db.add(User(email=settings.admin_email, password_hash=hash_password(settings.admin_password),
                        role=Role.admin))
        if db.scalar(select(Product).limit(1)) is None:
            db.add_all(Product(name=n, category=c, price=p, stock=s) for n, c, p, s in PRODUCTS)
        if db.scalar(select(PromoCode).limit(1)) is None:
            year = datetime.now(UTC) + timedelta(days=365)
            db.add_all([
                PromoCode(code="WELCOME10", percent=10, min_order_total=0, max_uses=1000, expires_at=year),
                PromoCode(code="BIG20", percent=20, min_order_total=100_000_00, max_uses=100, expires_at=year),
            ])
        db.commit()


if __name__ == "__main__":
    seed()
    print("Демо-данные готовы")
