"""Ограничение попыток: защита входа от подбора пароля и регистрации от спама.

Окно скользящее, счётчики в памяти процесса: на бесплатном Render работает один экземпляр API.
При нескольких экземплярах счётчики нужно вынести в общее хранилище (Redis или таблицу).
"""
import ipaddress
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
        """Старые попытки — прочь. Пустой ключ удаляется: иначе каждый новый email или IP
        оставался бы в памяти навсегда, и поток случайных адресов съел бы память процесса."""
        hits = self._hits.get(key)
        if hits is None:
            return deque()
        while hits and hits[0] <= now - self.seconds:
            hits.popleft()
        if not hits:
            del self._hits[key]
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
            now = time.monotonic()
            self._prune(key, now)
            self._hits[key].append(now)

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


def _valid_ip(value: str) -> str | None:
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return None


def client_ip(request: Request) -> str:
    """Адрес клиента для лимитов.

    Левый адрес в X-Forwarded-For присылает сам клиент — ему верить нельзя: подставив новый адрес,
    можно обойти любой лимит. Поэтому по порядку:
    1. client_ip_header (на Render — CF-Connecting-IP): его ставит Cloudflare и перезаписывает присланный клиентом;
    2. адрес на позиции proxy_hops справа в X-Forwarded-For: каждый прокси дописывает адрес в конец,
       и только эти записи — от наших прокси (на Render: «…, клиент, Cloudflare» — значит, 2);
    3. адрес TCP-соединения.
    """
    if settings.client_ip_header:
        ip = _valid_ip(request.headers.get(settings.client_ip_header, ""))
        if ip:
            return ip
    if settings.trust_proxy and settings.proxy_hops > 0:
        hops = [h for h in request.headers.get("x-forwarded-for", "").split(",") if h.strip()]
        if len(hops) >= settings.proxy_hops:
            ip = _valid_ip(hops[-settings.proxy_hops])
            if ip:
                return ip
    return request.client.host if request.client else "unknown"
