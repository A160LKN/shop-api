import pytest
from starlette.requests import Request

from app import ratelimit
from app.config import settings

pytestmark = pytest.mark.unit


def test_sliding_window_frees_attempts_as_time_passes(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(ratelimit.time, "monotonic", lambda: now[0])
    window = ratelimit.SlidingWindow(limit=2, seconds=60)
    window.hit("k")
    now[0] += 30
    window.hit("k")
    with pytest.raises(Exception) as exc:
        window.check("k")
    assert exc.value.headers["Retry-After"] == "31"  # первая попытка освободится через 30 с (+1 на округление)
    now[0] += 31
    window.check("k")  # первая попытка устарела — можно снова
    window.reset("k")
    window.check("k")


def test_window_forgets_keys_without_recent_attempts(monkeypatch):
    """Ключи без свежих попыток удаляются: поток случайных email и IP не съест память процесса."""
    now = [1000.0]
    monkeypatch.setattr(ratelimit.time, "monotonic", lambda: now[0])
    window = ratelimit.SlidingWindow(limit=5, seconds=60)
    for n in range(1000):
        window.check(f"never-hit-{n}")
    assert window._hits == {}, "проверка без попытки ничего не хранит"
    window.hit("old")
    now[0] += 61
    window.check("old")
    assert "old" not in window._hits, "устаревший ключ удалён"


def _request(headers: dict[str, str], peer: str = "10.21.157.68") -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    return Request({"type": "http", "headers": raw, "client": (peer, 1234)})


@pytest.fixture
def render(monkeypatch):
    """Настройки как на Render: за Cloudflare и балансировщиком."""
    monkeypatch.setattr(settings, "trust_proxy", True)
    monkeypatch.setattr(settings, "proxy_hops", 2)
    monkeypatch.setattr(settings, "client_ip_header", "true-client-ip")


def test_client_ip_ignores_spoofed_leftmost_forwarded_for(render):
    # Клиент сам прислал «6.6.6.6», Render дописал настоящий адрес и адрес Cloudflare
    request = _request({"X-Forwarded-For": "6.6.6.6, 99.61.165.29, 104.22.17.40"})
    assert ratelimit.client_ip(request) == "99.61.165.29"


def test_client_ip_prefers_header_from_cloudflare(render):
    request = _request({"True-Client-IP": "99.61.165.29", "X-Forwarded-For": "6.6.6.6, 5.5.5.5, 104.22.17.40"})
    assert ratelimit.client_ip(request) == "99.61.165.29"


def test_client_ip_falls_back_to_peer_on_garbage(render):
    request = _request({"True-Client-IP": "не адрес", "X-Forwarded-For": "1.1.1.1"})  # короче, чем proxy_hops
    assert ratelimit.client_ip(request) == "10.21.157.68"


def test_client_ip_ignores_headers_without_trust(monkeypatch):
    monkeypatch.setattr(settings, "trust_proxy", False)
    monkeypatch.setattr(settings, "client_ip_header", "")
    request = _request({"True-Client-IP": "1.2.3.4", "X-Forwarded-For": "1.2.3.4"})
    assert ratelimit.client_ip(request) == "10.21.157.68"
