"""Клиент внешнего платёжного шлюза.

Шлюз — чужой сервис: он может отказать, ответить медленно или не ответить вовсе.
В тестах он заменяется моком (respx), поэтому каждый из этих случаев проверяется.
"""
from dataclasses import dataclass

import httpx

from app.config import settings


class PaymentUnavailable(Exception):
    """Шлюз не ответил или ответил ошибкой сервера — результат оплаты неизвестен."""


@dataclass(frozen=True)
class ChargeResult:
    approved: bool
    payment_id: str | None = None
    reason: str | None = None


class PaymentGateway:
    def __init__(self, base_url: str, timeout: float):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _post(self, path: str, json: dict, idempotency_key: str) -> httpx.Response:
        try:
            response = httpx.post(f"{self.base_url}{path}", json=json, timeout=self.timeout,
                                  headers={"Idempotency-Key": idempotency_key})
        except httpx.HTTPError as exc:  # таймаут, обрыв соединения, DNS
            raise PaymentUnavailable(str(exc)) from exc
        if response.status_code >= 500:
            raise PaymentUnavailable(f"шлюз ответил {response.status_code}")
        return response

    def charge(self, order_id: int, amount: int, card_token: str, attempt: int = 0) -> ChargeResult:
        # Idempotency-Key: повтор той же попытки (обрыв связи, таймаут) шлюз не спишет второй раз.
        # Номер попытки в ключе: после отказа новая попытка — новый ключ, иначе шлюз вернул бы старый отказ
        response = self._post("/payments", {"order_id": order_id, "amount": amount, "currency": "KZT",
                                            "card_token": card_token},
                              idempotency_key=f"order-{order_id}-charge-{attempt}")
        body = response.json()
        if response.status_code == 200 and body.get("status") == "approved":
            return ChargeResult(approved=True, payment_id=body["payment_id"])
        return ChargeResult(approved=False, reason=body.get("reason", "платёж отклонён"))

    def refund(self, payment_id: str, amount: int) -> None:
        response = self._post(f"/payments/{payment_id}/refund", {"amount": amount},
                              idempotency_key=f"{payment_id}-refund")
        if response.status_code != 200:
            raise PaymentUnavailable(f"возврат не выполнен: {response.status_code}")


def get_gateway() -> PaymentGateway:
    return PaymentGateway(settings.payment_gateway_url, settings.payment_timeout_seconds)
