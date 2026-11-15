import pytest

from app import ratelimit

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
