import pytest
import respx
from fastapi.testclient import TestClient

from app import ratelimit
from app.config import settings
from app.main import app


@pytest.fixture
def client(clean_db):
    # Счётчики попыток живут в памяти процесса — между тестами их сбрасываем
    ratelimit.failed_logins.reset()
    ratelimit.registrations.reset()
    ratelimit.failed_logins_per_email.reset()
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def gateway():
    """Мок платёжного шлюза. Неописанный запрос к шлюзу — ошибка теста, а не поход в реальную сеть."""
    with respx.mock(base_url=settings.payment_gateway_url, assert_all_called=False) as mock:
        yield mock
