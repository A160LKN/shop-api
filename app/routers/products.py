import enum
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import AppError, not_found
from app.models import Product
from app.schemas import MAX_ID, CategoryOut, ProductIn, ProductOut, ProductPage, ProductPatch
from app.security import admin_user

router = APIRouter(prefix="/products", tags=["Каталог"])
class ProductSort(enum.StrEnum):
    default = "default"        # как в каталоге — по порядку добавления
    newest = "newest"          # новинки — сначала добавленные последними
    price_asc = "price_asc"    # сначала дешевле
    price_desc = "price_desc"  # сначала дороже
    name = "name"              # по алфавиту


SORT_ORDER = {
    ProductSort.default: (Product.id,),
    ProductSort.newest: (Product.id.desc(),),
    ProductSort.price_asc: (Product.price, Product.id),
    ProductSort.price_desc: (Product.price.desc(), Product.id),
    ProductSort.name: (Product.name, Product.id),
}
Price = Annotated[int | None, Query(ge=0, le=100_000_000_000, description="В тиынах")]

ProductId = Annotated[int, Path(gt=0, le=MAX_ID, description='id от 1 до 2 147 483 647')]


@router.get("", response_model=ProductPage)
def list_products(
    db: Session = Depends(get_db),
    category: str | None = None,
    q: str | None = Query(None, max_length=100, description="Поиск по названию, без учёта регистра"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0, le=MAX_ID),
    sort: ProductSort = ProductSort.default,
    in_stock: bool = Query(False, description="Только товары в наличии"),
    min_price: Price = None,
    max_price: Price = None,
):
    if min_price is not None and max_price is not None and min_price > max_price:
        raise AppError(422, "invalid_price_range", "Цена «от» больше цены «до»")
    query = select(Product).where(Product.is_active)
    if category:
        query = query.where(Product.category == category)
    if in_stock:
        query = query.where(Product.stock > 0)
    if min_price is not None:
        query = query.where(Product.price >= min_price)
    if max_price is not None:
        query = query.where(Product.price <= max_price)
    if q:
        # Параметр передаётся отдельно от SQL — SQL-инъекция невозможна; % и _ экранируются
        pattern = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        query = query.where(Product.name.ilike(pattern, escape="\\"))
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    items = db.scalars(query.order_by(*SORT_ORDER[sort]).limit(limit).offset(offset)).all()
    return ProductPage(items=items, total=total, limit=limit, offset=offset)


@router.get("/categories", response_model=list[CategoryOut])
def list_categories(db: Session = Depends(get_db)):
    """Категории каталога с числом товаров — для фильтра на витрине."""
    rows = db.execute(select(Product.category, func.count()).where(Product.is_active)
                      .group_by(Product.category).order_by(Product.category)).all()
    return [CategoryOut(name=name, count=count) for name, count in rows]


@router.get("/{product_id}", response_model=ProductOut)
def get_product(product_id: ProductId, db: Session = Depends(get_db)):
    product = db.get(Product, product_id)
    if product is None or not product.is_active:
        raise not_found("Товар")
    return product


@router.post("", response_model=ProductOut, status_code=status.HTTP_201_CREATED, dependencies=[Depends(admin_user)])
def create_product(data: ProductIn, db: Session = Depends(get_db)):
    product = Product(**data.model_dump())
    db.add(product)
    db.commit()
    return product


@router.patch("/{product_id}", response_model=ProductOut, dependencies=[Depends(admin_user)])
def update_product(product_id: ProductId, data: ProductPatch, db: Session = Depends(get_db)):
    product = db.get(Product, product_id)
    if product is None or not product.is_active:
        raise not_found("Товар")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(product, field, value)
    db.commit()
    return product


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(admin_user)])
def delete_product(product_id: ProductId, db: Session = Depends(get_db)):
    """Мягкое удаление: товар скрывается из каталога, но остаётся в старых заказах."""
    product = db.get(Product, product_id)
    if product is None or not product.is_active:
        raise not_found("Товар")
    product.is_active = False
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
