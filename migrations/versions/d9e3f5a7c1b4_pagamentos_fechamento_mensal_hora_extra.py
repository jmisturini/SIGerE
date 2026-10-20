"""pagamentos: fechamento mensal da hora extra

Revision ID: d9e3f5a7c1b4
Revises: c7d4f1e9a2b8
Create Date: 2026-10-02 14:00:00.000000

"""
import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = 'd9e3f5a7c1b4'
down_revision = 'c7d4f1e9a2b8'
branch_labels = None
depends_on = None


def upgrade():
    # Botão "Fechar Mês" da Hora Extra: registra quando a unidade fechou os
    # lançamentos de um mês de referência — o mês fechado fica somente leitura
    # e substitui os antigos bloqueios de 30 dias e de mês anterior.
    op.create_table(
        'overtime_month_closures',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('unity_id', sa.Integer(), nullable=False),
        sa.Column('month_base', sa.String(length=7), nullable=False),
        sa.Column('closed_by_id', sa.Integer(), nullable=True),
        sa.Column('closed_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['unity_id'], ['unities.id']),
        sa.ForeignKeyConstraint(['closed_by_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('unity_id', 'month_base',
                            name='uq_overtime_closure_unity_month'),
    )
    op.create_index('ix_overtime_month_closures_unity_id',
                    'overtime_month_closures', ['unity_id'])


def downgrade():
    op.drop_index('ix_overtime_month_closures_unity_id',
                  table_name='overtime_month_closures')
    op.drop_table('overtime_month_closures')
