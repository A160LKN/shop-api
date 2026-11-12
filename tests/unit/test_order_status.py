"""Переходы статусов заказа: полная таблица «статус × действие».

Проверяются и разрешённые переходы, и все запрещённые — именно в запрещённых обычно и прячутся баги.
"""
import pytest

from app.domain.order_status import TRANSITIONS, TransitionError, next_status
from app.models import OrderStatus as S

pytestmark = pytest.mark.unit

ALLOWED = {
    (S.created, "pay"): S.paid,
    (S.created, "cancel"): S.cancelled,
    (S.paid, "cancel"): S.cancelled,
    (S.paid, "ship"): S.shipped,
    (S.shipped, "deliver"): S.delivered,
}
ALL_PAIRS = [(status, action) for status in S for action in TRANSITIONS]


@pytest.mark.parametrize(("status", "action"), list(ALLOWED), ids=lambda x: str(x))
def test_allowed_transition(status, action):
    assert next_status(status, action) == ALLOWED[(status, action)]


@pytest.mark.parametrize(("status", "action"), [p for p in ALL_PAIRS if p not in ALLOWED], ids=lambda x: str(x))
def test_forbidden_transition(status, action):
    with pytest.raises(TransitionError, match="Нельзя"):
        next_status(status, action)


def test_table_covers_every_pair():
    assert len(ALL_PAIRS) == len(S) * len(TRANSITIONS) == 20


@pytest.mark.parametrize("final", [S.delivered, S.cancelled])
def test_final_statuses_have_no_way_out(final):
    for action in TRANSITIONS:
        with pytest.raises(TransitionError):
            next_status(final, action)


def test_error_message_is_human_readable():
    with pytest.raises(TransitionError, match="Нельзя отправить заказ в статусе «создан»"):
        next_status(S.created, "ship")
