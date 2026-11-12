"""Схемы запросов и ответов API. Они же — документация в /docs."""
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models import OrderStatus, Role

Email = Annotated[str, Field(max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", examples=["aibol@mail.kz"])]
Money = Annotated[int, Field(gt=0, le=100_000_000_000, description="Сумма в тиынах: 1 ₸ = 100")]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")  # неизвестное поле в запросе — ошибка 422, а не тихий игнор


class Credentials(Strict):
    email: Email
    password: str = Field(min_length=8, max_length=128)

    @field_validator("email", mode="before")  # before: пробелы убираются до проверки формата
    @classmethod
    def normalize_email(cls, v: object) -> object:
        return v.strip().lower() if isinstance(v, str) else v


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: str
    role: Role


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 — это тип токена, а не пароль


class ProductIn(Strict):
    name: str = Field(min_length=1, max_length=200)
    category: str = Field(min_length=1, max_length=50)
    price: Money
    stock: int = Field(ge=0, le=1_000_000)


class ProductPatch(Strict):
    name: str | None = Field(None, min_length=1, max_length=200)
    category: str | None = Field(None, min_length=1, max_length=50)
    price: Money | None = None
    stock: int | None = Field(None, ge=0, le=1_000_000)


class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    category: str
    price: int
    stock: int


class ProductPage(BaseModel):
    items: list[ProductOut]
    total: int
    limit: int
    offset: int


class PromoIn(Strict):
    code: str = Field(min_length=3, max_length=32, pattern=r"^[A-Z0-9_-]+$")
    percent: int = Field(ge=1, le=90)
    min_order_total: int = Field(0, ge=0)
    max_uses: int = Field(ge=1)
    expires_at: datetime


class PromoOut(PromoIn):
    model_config = ConfigDict(from_attributes=True, extra="ignore")
    id: int
    used_count: int


class OrderLineIn(Strict):
    product_id: int = Field(gt=0)
    quantity: int = Field(ge=1, le=100)


class OrderIn(Strict):
    items: list[OrderLineIn] = Field(min_length=1, max_length=50)
    promo_code: str | None = Field(None, max_length=32)

    @field_validator("items")
    @classmethod
    def unique_products(cls, items: list[OrderLineIn]) -> list[OrderLineIn]:
        ids = [i.product_id for i in items]
        if len(ids) != len(set(ids)):
            raise ValueError("товар повторяется — укажите его один раз с нужным количеством")
        return items

    @field_validator("promo_code")
    @classmethod
    def normalize_code(cls, v: str | None) -> str | None:
        return v.strip().upper() or None if v else None


class OrderLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    product_id: int
    quantity: int
    price: int


class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    status: OrderStatus
    items: list[OrderLineOut]
    subtotal: int
    discount: int
    total: int
    promo_code: str | None
    created_at: datetime


class PaymentIn(Strict):
    card_token: str = Field(min_length=3, max_length=64, description="Токен карты от платёжной формы, не номер карты",
                            examples=["tok_visa"])
