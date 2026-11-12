"""Пароли и JWT-токены."""
import base64
import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.errors import AppError
from app.models import Role, User

# scrypt из стандартной библиотеки: медленный по задумке, с солью — подбор пароля дорогой
_SCRYPT = {"n": 2**14, "r": 8, "p": 1}


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    return f"scrypt${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt_b64, digest_b64 = stored.split("$")
    except ValueError:
        return False
    digest = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt_b64), **_SCRYPT)
    return hmac.compare_digest(digest, base64.b64decode(digest_b64))  # сравнение без утечки по времени


def create_token(user: User, now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    payload = {"sub": str(user.id), "role": user.role.value, "iat": now,
               "exp": now + timedelta(minutes=settings.jwt_ttl_minutes)}
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


_bearer = HTTPBearer(auto_error=False)
UNAUTHORIZED = AppError(401, "unauthorized",
                        "Нужна авторизация: передайте токен в заголовке Authorization: Bearer <token>")


def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
                 db: Session = Depends(get_db)) -> User:
    if credentials is None:
        raise UNAUTHORIZED
    try:
        # algorithms задан явно: токен с alg=none или другим алгоритмом не пройдёт
        payload = jwt.decode(credentials.credentials, settings.jwt_secret, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise AppError(401, "token_expired", "Срок действия токена истёк — войдите заново") from None
    except jwt.PyJWTError:
        raise AppError(401, "invalid_token", "Неверный токен") from None
    sub = payload.get("sub")
    user = db.get(User, int(sub)) if isinstance(sub, str) and sub.isdigit() and int(sub) <= 2_147_483_647 else None
    if user is None:
        raise AppError(401, "invalid_token", "Неверный токен")
    return user


def admin_user(user: User = Depends(current_user)) -> User:
    if user.role != Role.admin:
        raise AppError(403, "forbidden", "Действие доступно только администратору")
    return user
