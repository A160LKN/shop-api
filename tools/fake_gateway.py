"""Имитация платёжного шлюза для локального запуска и нагрузочных тестов.

Поведение зависит от токена карты:
- tok_declined — отказ «недостаточно средств»;
- tok_timeout  — шлюз «зависает» на 10 секунд (приложение ждёт 5 и сдаётся);
- любой другой — оплата проходит.
"""
import time
import uuid

from fastapi import FastAPI, Header

app = FastAPI(title="Fake payment gateway")
_payments: dict[str, dict] = {}  # Idempotency-Key → ответ: повтор не создаёт второй платёж


@app.post("/payments")
def charge(body: dict, idempotency_key: str = Header()):
    if idempotency_key in _payments:
        return _payments[idempotency_key]
    token = body.get("card_token")
    if token == "tok_timeout":
        time.sleep(10)
    if token == "tok_declined":
        result = {"status": "declined", "reason": "недостаточно средств"}
    else:
        result = {"status": "approved", "payment_id": f"pay_{uuid.uuid4().hex[:12]}"}
        _payments[idempotency_key] = result
    return result


@app.post("/payments/{payment_id}/refund")
def refund(payment_id: str, body: dict):
    return {"status": "ok", "payment_id": payment_id, "amount": body.get("amount")}
