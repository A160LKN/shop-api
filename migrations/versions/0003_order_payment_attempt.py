"""order payment attempt and in-progress mark

Оплата больше не держит блокировку строки заказа на время запроса к шлюзу:
отметка payment_started_at не даёт оплатить или отменить заказ, пока шлюз отвечает,
а payment_attempt входит в ключ идемпотентности — после отказа банка новая попытка получает новый ключ.

Revision ID: c3a1f0d2e4b5
Revises: b0aae3eff959
Create Date: 2026-11-20 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3a1f0d2e4b5'
down_revision: Union[str, Sequence[str], None] = 'b0aae3eff959'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('orders', sa.Column('payment_attempt', sa.Integer(), server_default='0', nullable=False))
    op.add_column('orders', sa.Column('payment_started_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('orders', 'payment_started_at')
    op.drop_column('orders', 'payment_attempt')
