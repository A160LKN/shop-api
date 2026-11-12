from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Настройки из переменных окружения (или файла .env)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://shop:shop@localhost:5432/shop"
    jwt_secret: str = "dev-secret-change-me-in-production-32b"
    jwt_ttl_minutes: int = 60
    payment_gateway_url: str = "http://localhost:8001"
    payment_timeout_seconds: float = 5.0
    admin_email: str = "admin@shop.kz"
    admin_password: str = "admin12345"


settings = Settings()
