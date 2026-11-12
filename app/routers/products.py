from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import not_found
from app.models import Product
from app.schemas import MAX_ID, ProductIn, ProductOut, ProductPage, ProductPatch
from app.security import admin_user

router = APIRouter(prefix="/products", tags=["Каталог"])
ProductId = Annotated[int, Path(gt=0, le=MAX_ID, description='id от 1 до 2 147 483 647')]


@router.get("", response_model=ProductPage)
def list_products(
    db: Session = Depends(get_db),
    category: str | None = None,
    q: str | None = Query(None, max_length=100, description="Поиск по названию, без учёта регистра"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0, le=MAX_ID),
):
    query = select(Product).where(Product.is_active)
    if category:
        query = query.where(Product.category == category)
    if q:
        # Параметр передаётся отдельно от SQL — SQL-инъекция невозможна; % и _ экранируются
        pattern = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        query = query.where(Product.name.ilike(pattern, escape="\\"))
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    items = db.scalars(query.order_by(Product.id).limit(limit).offset(offset)).all()
    return ProductPage(items=items, total=total, limit=limit, offset=offset)


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
