import os
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def on_render() -> bool:
    """Render сам задаёт каждому сервису RENDER=true. По нему включаются настройки живого сайта:
    доверие к прокси Render и Cloudflare и запрет секретов по умолчанию. Явная переменная окружения
    по-прежнему важнее — значения по умолчанию лишь не дают забыть их в панели."""
    return os.environ.get("RENDER", "").lower() == "true"


class Settings(BaseSettings):
    """Настройки из переменных окружения (или файла .env)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # production — живой сайт: там значения по умолчанию из этого файла запрещены (см. no_dev_secrets_in_production)
    # На Render — production по умолчанию: живой сайт не должен зависеть от того, перенесли ли переменные
    # из render.yaml в панель (у сервиса, созданного не через Blueprint, они не применяются)
    environment: Literal["development", "test", "production"] = Field(
        default_factory=lambda: "production" if on_render() else "development")

    database_url: str = "postgresql+psycopg://shop:shop@localhost:5432/shop"
    # Пул соединений с БД. Сервер обрабатывает до 40 запросов одновременно (пул потоков FastAPI),
    # поэтому соединений должно хватать на всех. Найдено нагрузочным тестом: при 15 соединениях
    # запросы ждали 30 секунд и падали с 500
    db_pool_size: int = 20
    db_max_overflow: int = 20
    db_pool_timeout: float = 5.0  # дольше ждать нет смысла — лучше быстро ответить 503
    # Внимание: у каждого процесса сервера (WEB_CONCURRENCY) свой пул.
    # процессы × (db_pool_size + db_max_overflow) должно быть меньше max_connections в PostgreSQL (по умолчанию 100)
    jwt_secret: str = "dev-secret-change-me-in-production-32b"
    jwt_ttl_minutes: int = 60
    payment_gateway_url: str = "http://localhost:8001"
    payment_timeout_seconds: float = 5.0
    # Адреса фронтендов, которым браузер разрешит обращаться к API (CORS), через запятую
    cors_origins: str = "http://localhost:5173,http://localhost:4173"
    timezone: str = "Asia/Almaty"  # часовой пояс магазина — для «сегодня» в сводке
    # За прокси Render адрес клиента — в X-Forwarded-For. Локально заголовку не доверяем; на Render — доверяем
    trust_proxy: bool = Field(default_factory=on_render)
    # Сколько наших прокси дописывают адрес в конец X-Forwarded-For. На Render («…, клиент, Cloudflare») — 2
    proxy_hops: int = Field(default_factory=lambda: 2 if on_render() else 1)
    # Заголовок с адресом клиента от доверенного прокси. На Render — cf-connecting-ip: его ставит Cloudflare
    # на любом тарифе и перезаписывает, если клиент прислал свой.
    # Пусто — не используется: без такого прокси заголовок подделает кто угодно
    client_ip_header: str = Field(default_factory=lambda: "cf-connecting-ip" if on_render() else "")
    login_attempts: int = 5  # неудачных входов за 15 минут на пару «email + IP»
    registrations_per_hour: int = 10  # с одного IP
    admin_email: str = "admin@shop.kz"
    admin_password: str = "admin12345"
    # Демо на Render: при старте вернуть каталог и промокоды к исходному виду (см. app/seed.py).
    # Пароль администратора демо публичный — без сброса витрину мог бы испортить любой посетитель
    demo_reset: bool = False

    @model_validator(mode="after")
    def no_dev_secrets_in_production(self) -> "Settings":
        """Секрет по умолчанию опубликован в репозитории: с ним любой подпишет себе токен.
        Забыли задать JWT_SECRET на живом сайте — сервер не стартует, а не работает с известным ключом."""
        if self.environment == "production" and (self.jwt_secret.startswith("dev-") or len(self.jwt_secret) < 32):
            raise ValueError("JWT_SECRET по умолчанию или короче 32 символов нельзя использовать в production")
        return self

    @field_validator("database_url")
    @classmethod
    def use_psycopg_driver(cls, url: str) -> str:
        """Хостинги (Neon, Render, Heroku) выдают адрес вида postgresql:// или postgres://.
        SQLAlchemy по такому адресу ищет драйвер psycopg2, а в проекте psycopg 3 — указываем его явно."""
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url.removeprefix(prefix)
        return url


settings = Settings()
