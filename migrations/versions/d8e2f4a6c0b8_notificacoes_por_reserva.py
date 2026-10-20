"""notificações por reserva (opt-in na reserva, padrão desativado)

Revision ID: d8e2f4a6c0b8
Revises: b6e9c3a7d1f4
Create Date: 2026-09-28 10:00:00.000000

Adiciona reservations.notify_enabled: as notificações de atividade próxima
passam a depender da ativação na própria reserva (botão no detalhe) — o
padrão é desativado e a varredura notify-scan ignora reservas sem aviso.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd8e2f4a6c0b8'
down_revision = 'b6e9c3a7d1f4'
branch_labels = None
depends_on = None


def _tem_coluna(inspector, tabela, coluna):
    return coluna in (c['name'] for c in inspector.get_columns(tabela))


def upgrade():
    inspector = sa.inspect(op.get_bind())

    if not _tem_coluna(inspector, 'reservations', 'notify_enabled'):
        op.add_column('reservations',
                      sa.Column('notify_enabled', sa.Boolean(), nullable=False,
                                server_default='0'))


def downgrade():
    inspector = sa.inspect(op.get_bind())

    if _tem_coluna(inspector, 'reservations', 'notify_enabled'):
        op.drop_column('reservations', 'notify_enabled')
