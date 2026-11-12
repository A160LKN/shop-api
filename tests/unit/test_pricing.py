"""Расчёт суммы заказа: классы эквивалентности и граничные значения."""
from datetime import UTC, datetime, timedelta

import pytest

from app.domain.pricing import Promo, PromoError, calculate, check_promo, subtotal

pytestmark = pytest.mark.unit

NOW = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)


def promo(**overrides) -> Promo:
    data = {"code": "SALE", "percent": 10, "min_order_total": 0, "max_uses": 10, "used_count": 0,
            "expires_at": NOW + timedelta(days=1)}
    return Promo(**{**data, **overrides})


def test_subtotal_is_sum_of_lines():
    assert subtotal([(10_000_00, 2), (500_00, 3)]) == 21_500_00


def test_without_promo_there_is_no_discount():
    totals = calculate([(10_000_00, 1)], None, NOW)
    assert (totals.subtotal, totals.discount, totals.total) == (10_000_00, 0, 10_000_00)


def test_percent_discount():
    assert calculate([(10_000_00, 2)], promo(percent=15), NOW).discount == 3_000_00


@pytest.mark.parametrize(
    ("amount", "expected_discount"),
    [
        (999_99, 99_00),     # 10 % = 99,999 ₸ → 99 ₸: копейки в скидку не идут
        (1_000_00, 100_00),  # ровно 100 ₸
        (9_99, 0),           # скидка меньше 1 ₸ — не даётся
    ],
)
def test_discount_is_rounded_down_to_whole_tenge(amount, expected_discount):
    assert calculate([(amount, 1)], promo(percent=10), NOW).discount == expected_discount


@pytest.mark.parametrize("percent", [1, 50, 90])
@pytest.mark.parametrize("amount", [1, 9_99, 12_345_67, 1_000_000_00])
def test_total_plus_discount_equals_subtotal_and_is_never_negative(amount, percent):
    totals = calculate([(amount, 3)], promo(percent=percent), NOW)
    assert totals.total + totals.discount == totals.subtotal
    assert totals.total > 0


# ---------- Минимальная сумма заказа: граница ----------

def test_min_order_total_reached_exactly():
    check_promo(promo(min_order_total=50_000_00), 50_000_00, NOW)


def test_min_order_total_one_tiyn_short():
    with pytest.raises(PromoError, match="от 50000 ₸"):
        check_promo(promo(min_order_total=50_000_00), 49_999_99, NOW)


# ---------- Срок действия: граница ----------

def test_promo_works_one_second_before_expiry():
    check_promo(promo(expires_at=NOW + timedelta(seconds=1)), 100, NOW)


@pytest.mark.parametrize("delta", [timedelta(0), timedelta(seconds=-1)], ids=["at-expiry", "after-expiry"])
def test_expired_promo(delta):
    with pytest.raises(PromoError, match="истёк"):
        check_promo(promo(expires_at=NOW + delta), 100, NOW)


# ---------- Лимит использований: граница ----------

def test_last_allowed_use():
    check_promo(promo(max_uses=5, used_count=4), 100, NOW)


def test_usage_limit_reached():
    with pytest.raises(PromoError, match="лимит"):
        check_promo(promo(max_uses=5, used_count=5), 100, NOW)


def test_all_checks_run_before_discount():
    with pytest.raises(PromoError):
        calculate([(100, 1)], promo(used_count=10, max_uses=10), NOW)
