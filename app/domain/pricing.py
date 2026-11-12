"""Расчёт суммы заказа. Чистые функции без БД — проверяются юнит-тестами."""
from dataclasses import dataclass
from datetime import datetime


class PromoError(ValueError):
    """Промокод нельзя применить. Текст — для пользователя."""


@dataclass(frozen=True)
class Promo:
    code: str
    percent: int
    min_order_total: int
    max_uses: int
    used_count: int
    expires_at: datetime


@dataclass(frozen=True)
class Totals:
    subtotal: int
    discount: int
    total: int


def subtotal(lines: list[tuple[int, int]]) -> int:
    """Сумма строк заказа: [(цена в тиынах, количество), ...]."""
    return sum(price * quantity for price, quantity in lines)


def check_promo(promo: Promo, order_subtotal: int, now: datetime) -> None:
    if now >= promo.expires_at:
        raise PromoError("Срок действия промокода истёк")
    if promo.used_count >= promo.max_uses:
        raise PromoError("Промокод больше недействителен: лимит использований исчерпан")
    if order_subtotal < promo.min_order_total:
        raise PromoError(f"Промокод действует при заказе от {promo.min_order_total // 100} ₸")


def calculate(lines: list[tuple[int, int]], promo: Promo | None, now: datetime) -> Totals:
    """Итог заказа. Скидка округляется вниз до целого тенге — в пользу магазина, но без копеек в чеке."""
    amount = subtotal(lines)
    discount = 0
    if promo is not None:
        check_promo(promo, amount, now)
        discount = amount * promo.percent // 100 // 100 * 100
    return Totals(subtotal=amount, discount=discount, total=amount - discount)
