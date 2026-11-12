from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.config import settings
from app.models import Role, User
from app.security import create_token, hash_password, verify_password

pytestmark = pytest.mark.unit


def test_password_is_not_stored_as_is():
    stored = hash_password("my-password")
    assert "my-password" not in stored
    assert stored.startswith("scrypt$")


def test_same_password_gives_different_hashes():
    """Соль: одинаковые пароли у разных людей не видны по одинаковым хешам."""
    assert hash_password("same-password") != hash_password("same-password")


def test_verify_password():
    stored = hash_password("correct-horse")
    assert verify_password("correct-horse", stored)
    assert not verify_password("correct-hors", stored)
    assert not verify_password("", stored)


def test_broken_hash_does_not_crash():
    assert not verify_password("anything", "not-a-hash")


def test_token_contains_user_and_role_and_expires():
    now = datetime(2026, 11, 12, tzinfo=UTC)
    token = create_token(User(id=7, email="a@b.kz", password_hash="x", role=Role.admin), now=now)
    payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"], options={"verify_exp": False})
    assert payload["sub"] == "7"
    assert payload["role"] == "admin"
    assert payload["exp"] - payload["iat"] == timedelta(minutes=settings.jwt_ttl_minutes).total_seconds()
