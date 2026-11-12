from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import AppError
from app.models import User
from app.schemas import Credentials, TokenOut, UserOut
from app.security import create_token, current_user, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["Авторизация"])


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(data: Credentials, db: Session = Depends(get_db)):
    user = User(email=data.email, password_hash=hash_password(data.password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError:  # уникальность проверяет БД — без гонки «проверил, потом вставил»
        db.rollback()
        raise AppError(409, "email_taken", "Пользователь с таким email уже зарегистрирован") from None
    return user


@router.post("/login", response_model=TokenOut)
def login(data: Credentials, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == data.email))
    # Одинаковый ответ для «нет такого email» и «неверный пароль» — нельзя перебором узнать, кто зарегистрирован
    if user is None or not verify_password(data.password, user.password_hash):
        raise AppError(401, "bad_credentials", "Неверный email или пароль")
    return TokenOut(access_token=create_token(user))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user
