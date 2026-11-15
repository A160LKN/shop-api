"""Ограничение попыток: защита входа от подбора пароля и регистрации от спама.

Окно скользящее, счётчики в памяти процесса: на бесплатном Render работает один экземпляр API.
При нескольких экземплярах счётчики нужно вынести в общее хранилище (Redis или таблицу).
"""
import threading
import time
from collections import defaultdict, deque

from fastapi import Request

from app.config import settings
from app.errors import AppError


class SlidingWindow:
    def __init__(self, limit: int, seconds: int) -> None:
        self.limit, self.seconds = limit, seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> deque[float]:
        hits = self._hits[key]
        while hits and hits[0] <= now - self.seconds:
            hits.popleft()
        return hits

    def check(self, key: str) -> None:
        """429, если лимит исчерпан. Retry-After — через сколько секунд освободится попытка."""
        now = time.monotonic()
        with self._lock:
            hits = self._prune(key, now)
            if len(hits) >= self.limit:
                retry = int(hits[0] + self.seconds - now) + 1
                raise AppError(429, "too_many_attempts", "Слишком много попыток — повторите позже",
                               headers={"Retry-After": str(retry)})

    def hit(self, key: str) -> None:
        with self._lock:
            self._hits[key].append(time.monotonic())

    def reset(self, key: str | None = None) -> None:
        with self._lock:
            if key is None:
                self._hits.clear()
            else:
                self._hits.pop(key, None)


# 5 неудачных входов за 15 минут на пару «адрес + IP»; 10 регистраций в час с одного IP
failed_logins = SlidingWindow(limit=settings.login_attempts, seconds=15 * 60)
# Второй рубеж — по одной почте с любых адресов: подделка IP в X-Forwarded-For не даёт бесконечных попыток
failed_logins_per_email = SlidingWindow(limit=settings.login_attempts * 4, seconds=15 * 60)
registrations = SlidingWindow(limit=settings.registrations_per_hour, seconds=60 * 60)


def client_ip(request: Request) -> str:
    """За прокси Render настоящий адрес клиента — первый в X-Forwarded-For."""
    if settings.trust_proxy:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
