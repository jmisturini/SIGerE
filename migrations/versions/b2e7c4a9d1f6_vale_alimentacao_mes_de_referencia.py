"""rh: vale alimentação ganha mês de referência

Revision ID: b2e7c4a9d1f6
Revises: c5d9e2a7b4f3
Create Date: 2026-10-08 10:00:00.000000

"""
import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = 'b2e7c4a9d1f6'
down_revision = 'c5d9e2a7b4f3'
branch_labels = None
depends_on = None


def upgrade():
    # Mês de referência (YYYY-MM) do lançamento: permite lançar meses
    # diferentes sem limpar os anteriores. Nulo nos lançamentos anteriores
    # à coluna — continuam visíveis, exibidos como "—".
    op.add_column('teacher_meal_allowances',
                  sa.Column('month_base', sa.String(7), nullable=True))


def downgrade():
    op.drop_column('teacher_meal_allowances', 'month_base')
