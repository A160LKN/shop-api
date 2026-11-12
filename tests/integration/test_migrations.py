"""Миграции совпадают с моделями: никто не поменял модель, забыв про миграцию."""
import pytest
from alembic import command
from alembic.config import Config

pytestmark = pytest.mark.integration


def test_models_match_migrations(database):
    command.check(Config("alembic.ini"))  # падает, если модели и схема БД разошлись


def test_migrations_can_be_rolled_back_and_reapplied(database):
    config = Config("alembic.ini")
    command.downgrade(config, "base")
    command.upgrade(config, "head")
