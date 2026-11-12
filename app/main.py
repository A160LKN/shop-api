from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import AppError, app_error_handler
from app.routers import auth, orders, products, promo

app = FastAPI(
    title="Shop API",
    version="1.0.0",
    description="Бэкенд интернет-магазина: каталог, заказы со складом, промокоды, оплата через внешний шлюз. "
                "Все суммы — в тиынах (1 ₸ = 100).",
)
app.add_exception_handler(AppError, app_error_handler)
for module in (auth, products, promo, orders):
    app.include_router(module.router)


@app.get("/health", tags=["Служебное"])
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok"}
