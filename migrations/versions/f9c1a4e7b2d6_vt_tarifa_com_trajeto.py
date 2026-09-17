"""vt: tarifa da empresa ganha trajeto (linhas trajeto+valor)

Revision ID: f9c1a4e7b2d6
Revises: e4b7c9d2a5f8
Create Date: 2026-09-17 20:05:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f9c1a4e7b2d6'
down_revision = 'e4b7c9d2a5f8'
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if 'vt_empresas_valores' not in inspector.get_table_names():
        return
    colunas = [c['name'] for c in inspector.get_columns('vt_empresas_valores')]
    if 'trajeto' in colunas:
        return
    # Tarifas antigas ficam com trajeto NULL e aparecem só com o valor.
    with op.batch_alter_table('vt_empresas_valores') as batch_op:
        batch_op.add_column(sa.Column('trajeto', sa.String(length=20), nullable=True))


def downgrade():
    inspector = sa.inspect(op.get_bind())
    if 'vt_empresas_valores' not in inspector.get_table_names():
        return
    colunas = [c['name'] for c in inspector.get_columns('vt_empresas_valores')]
    if 'trajeto' in colunas:
        with op.batch_alter_table('vt_empresas_valores') as batch_op:
            batch_op.drop_column('trajeto')
