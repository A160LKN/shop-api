from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Настройки из переменных окружения (или файла .env)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

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
    admin_email: str = "admin@shop.kz"
    admin_password: str = "admin12345"


settings = Settings()
