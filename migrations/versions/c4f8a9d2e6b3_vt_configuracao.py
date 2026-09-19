"""vt: configuracoes do pedido por unidade (vales base e fechamento)

Revision ID: c4f8a9d2e6b3
Revises: b3d7e2c8f5a1
Create Date: 2026-09-18 09:15:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c4f8a9d2e6b3'
down_revision = 'b3d7e2c8f5a1'
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if 'vt_configs' in inspector.get_table_names():
        return
    op.create_table('vt_configs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('unity_id', sa.Integer(), nullable=False),
    sa.Column('vales_somente_ida', sa.Integer(), nullable=True),
    sa.Column('vales_ida_e_volta', sa.Integer(), nullable=True),
    sa.Column('fecha_em', sa.Date(), nullable=True),
    sa.ForeignKeyConstraint(['unity_id'], ['unities.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_vt_configs_unity_id'), 'vt_configs',
                    ['unity_id'], unique=True)


def downgrade():
    inspector = sa.inspect(op.get_bind())
    if 'vt_configs' not in inspector.get_table_names():
        return
    op.drop_index(op.f('ix_vt_configs_unity_id'), table_name='vt_configs')
    op.drop_table('vt_configs')
