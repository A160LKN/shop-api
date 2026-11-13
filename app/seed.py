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
    ("Смарт-часы Xiaomi Watch S4", "electronics", 64_990_00, 14),
    ("Портативная колонка Marshall Emberton III", "electronics", 89_990_00, 4),
    ("Электронная книга PocketBook Verse Pro", "electronics", 79_990_00, 9),
    ("Powerbank Anker 20000 мА·ч", "electronics", 19_990_00, 0),
    ("Чайник Xiaomi Mi Kettle", "home", 12_490_00, 40),
    ("Пылесос Dreame T20", "home", 129_990_00, 8),
    ("Кофеварка De'Longhi Dedica EC685", "home", 119_990_00, 3),
    ("Увлажнитель воздуха Xiaomi Humidifier 2", "home", 22_990_00, 18),
    ("Набор посуды Tefal Ingenio, 10 предметов", "home", 74_990_00, 11),
    ("Рюкзак городской 20 л", "accessories", 15_990_00, 30),
    ("Термокружка Stanley 470 мл", "accessories", 17_490_00, 22),
    ("Зонт складной автоматический", "accessories", 8_990_00, 35),
    ("Кофе в зёрнах 1 кг", "food", 9_990_00, 100),
    ("Чай зелёный жасминовый, 100 пакетиков", "food", 3_490_00, 70),
    ("Мёд горный алтайский, 500 г", "food", 5_990_00, 26),
    ("Курт солёный, 300 г", "food", 2_490_00, 45),
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
