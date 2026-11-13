from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.errors import AppError, PoolTimeout, app_error_handler, overload_handler
from app.routers import auth, orders, products, promo, stats

app = FastAPI(
    title="Shop API",
    version="1.0.0",
    description="Бэкенд интернет-магазина: каталог, заказы со складом, промокоды, оплата через внешний шлюз. "
                "Все суммы — в тиынах (1 ₸ = 100).",
)
# Браузер пускает фронтенд с другого адреса к API только с этими заголовками.
# Список адресов — явный: «*» вместе с авторизацией открыл бы API любому сайту
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
    max_age=600,
)
app.add_exception_handler(AppError, app_error_handler)
app.add_exception_handler(PoolTimeout, overload_handler)
for module in (auth, products, promo, orders, stats):
    app.include_router(module.router)


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    """Адрес API без пути открывает документацию — по ссылке из резюме сразу видно, что умеет API."""
    return RedirectResponse("/docs")


@app.get("/health", tags=["Служебное"])
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok"}
