"""Демо-данные: администратор, товары и промокоды. Повторный запуск ничего не дублирует.

Пароль администратора демо опубликован в README, поэтому на живом сайте любой посетитель — администратор.
С DEMO_RESET=true (так на Render) каждый старт возвращает витрину к исходному виду: цены, остатки,
видимость товаров и промокоды. Бесплатный сервер засыпает после простоя, так что сброс происходит
регулярно, а испорченный каталог живёт не дольше одной «сессии» сервера.
Заказы покупателей не трогаются. Пользователей тоже: сменить пароль или выдать роль администратора
через API нельзя.
"""
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

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

# (код, скидка %, минимальная сумма заказа в тиынах, лимит использований)
PROMOS = [
    ("WELCOME10", 10, 0, 1000),
    ("BIG20", 20, 100_000_00, 100),
]


def _promo_rows(now: datetime) -> list[PromoCode]:
    year = now + timedelta(days=365)
    return [PromoCode(code=c, percent=p, min_order_total=m, max_uses=u, expires_at=year) for c, p, m, u in PROMOS]


def seed() -> None:
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.email == settings.admin_email)) is None:
            db.add(User(email=settings.admin_email, password_hash=hash_password(settings.admin_password),
                        role=Role.admin))
        if db.scalar(select(Product).limit(1)) is None:
            db.add_all(Product(name=n, category=c, price=p, stock=s) for n, c, p, s in PRODUCTS)
        if db.scalar(select(PromoCode).limit(1)) is None:
            db.add_all(_promo_rows(datetime.now(UTC)))
        db.commit()
        if settings.demo_reset:
            reset_demo(db)


def reset_demo(db: Session, now: datetime | None = None) -> None:
    """Вернуть витрину демо к исходному виду. Одна транзакция: сайт не увидит каталог наполовину сброшенным."""
    now = now or datetime.now(UTC)

    # Товары из списка — с исходными ценой, остатком и видимостью. Удалять строки нельзя: на товары
    # ссылаются позиции заказов. Поэтому всё лишнее (добавленное или переименованное посетителями) — скрывается
    keep: set[int] = set()
    for name, category, price, stock in PRODUCTS:
        query = select(Product).where(Product.name == name).order_by(Product.id).limit(1)
        product = db.scalar(query.where(Product.id.not_in(keep)) if keep else query)
        if product is None:
            product = Product(name=name)
            db.add(product)
        product.category, product.price, product.stock, product.is_active = category, price, stock, True
        db.flush()
        keep.add(product.id)
    db.execute(update(Product).where(Product.id.not_in(keep)).values(is_active=False))

    # Промокоды заказы хранят строкой, а не ссылкой — посторонние (например, «скидка 90 %») можно удалить
    db.execute(delete(PromoCode))
    db.add_all(_promo_rows(now))

    db.commit()


if __name__ == "__main__":
    seed()
    print("Демо-данные готовы" + (" и сброшены к исходному виду" if settings.demo_reset else ""))
