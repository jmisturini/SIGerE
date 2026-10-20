"""vt: trajeto da tarifa vira identificacao (texto livre)

Revision ID: a6e8f3b1c7d4
Revises: f9c1a4e7b2d6
Create Date: 2026-09-17 21:20:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a6e8f3b1c7d4'
down_revision = 'f9c1a4e7b2d6'
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if 'vt_empresas_valores' not in inspector.get_table_names():
        return
    colunas = [c['name'] for c in inspector.get_columns('vt_empresas_valores')]
    if 'identificacao' in colunas:
        return
    with op.batch_alter_table('vt_empresas_valores') as batch_op:
        batch_op.alter_column('trajeto', new_column_name='identificacao',
                              existing_type=sa.String(length=20),
                              type_=sa.String(length=100))


def downgrade():
    inspector = sa.inspect(op.get_bind())
    if 'vt_empresas_valores' not in inspector.get_table_names():
        return
    colunas = [c['name'] for c in inspector.get_columns('vt_empresas_valores')]
    if 'trajeto' in colunas:
        return
    with op.batch_alter_table('vt_empresas_valores') as batch_op:
        batch_op.alter_column('identificacao', new_column_name='trajeto',
                              existing_type=sa.String(length=100),
                              type_=sa.String(length=20))
