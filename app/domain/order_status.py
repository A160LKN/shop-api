"""Жизненный цикл заказа — конечный автомат.

created ──pay──► paid ──ship──► shipped ──deliver──► delivered
   │               │
   └──cancel──► cancelled ◄──cancel (с возвратом денег)
"""
from app.models import OrderStatus

TRANSITIONS: dict[str, dict[OrderStatus, OrderStatus]] = {
    "pay": {OrderStatus.created: OrderStatus.paid},
    "cancel": {OrderStatus.created: OrderStatus.cancelled, OrderStatus.paid: OrderStatus.cancelled},
    "ship": {OrderStatus.paid: OrderStatus.shipped},
    "deliver": {OrderStatus.shipped: OrderStatus.delivered},
}

ACTION_NAMES = {"pay": "оплатить", "cancel": "отменить", "ship": "отправить", "deliver": "отметить доставленным"}
STATUS_NAMES = {
    OrderStatus.created: "создан", OrderStatus.paid: "оплачен", OrderStatus.shipped: "отправлен",
    OrderStatus.delivered: "доставлен", OrderStatus.cancelled: "отменён",
}


class TransitionError(ValueError):
    pass


def next_status(current: OrderStatus, action: str) -> OrderStatus:
    allowed = TRANSITIONS[action]
    if current not in allowed:
        raise TransitionError(f"Нельзя {ACTION_NAMES[action]} заказ в статусе «{STATUS_NAMES[current]}»")
    return allowed[current]
