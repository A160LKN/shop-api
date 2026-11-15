from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import ratelimit
from app.db import get_db
from app.errors import AppError
from app.models import User
from app.schemas import Credentials, TokenOut, UserOut
from app.security import create_token, current_user, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["Авторизация"])

# Самые частые пароли из утечек: их подбирают первыми
COMMON_PASSWORDS = {"12345678", "123456789", "1234567890", "password", "password1", "qwerty123", "qwertyuiop",
                    "11111111", "00000000", "iloveyou", "12341234", "87654321", "qwerty12", "1q2w3e4r", "abc12345"}


def check_password_strength(password: str, email: str) -> None:
    lowered = password.lower()
    if lowered in COMMON_PASSWORDS or len(set(password)) < 4 or lowered in (email, email.split("@")[0]):
        raise AppError(422, "weak_password", "Слишком простой пароль: возьмите длиннее и не из популярных")


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(data: Credentials, request: Request, db: Session = Depends(get_db)):
    ip = ratelimit.client_ip(request)
    ratelimit.registrations.check(ip)
    check_password_strength(data.password, data.email)
    ratelimit.registrations.hit(ip)
    user = User(email=data.email, password_hash=hash_password(data.password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError:  # уникальность проверяет БД — без гонки «проверил, потом вставил»
        db.rollback()
        raise AppError(409, "email_taken", "Пользователь с таким email уже зарегистрирован") from None
    return user


@router.post("/login", response_model=TokenOut)
def login(data: Credentials, request: Request, db: Session = Depends(get_db)):
    key = f"{data.email}|{ratelimit.client_ip(request)}"
    ratelimit.failed_logins.check(key)
    ratelimit.failed_logins_per_email.check(data.email)  # защита от подбора пароля
    user = db.scalar(select(User).where(User.email == data.email))
    # Одинаковый ответ для «нет такого email» и «неверный пароль» — нельзя перебором узнать, кто зарегистрирован
    if user is None or not verify_password(data.password, user.password_hash):
        ratelimit.failed_logins.hit(key)
        ratelimit.failed_logins_per_email.hit(data.email)
        raise AppError(401, "bad_credentials", "Неверный email или пароль")
    ratelimit.failed_logins.reset(key)
    return TokenOut(access_token=create_token(user))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user
