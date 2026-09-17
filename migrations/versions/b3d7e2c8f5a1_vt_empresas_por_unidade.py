"""vt: empresas de onibus deixam de ser compartilhadas entre unidades

Revision ID: b3d7e2c8f5a1
Revises: a6e8f3b1c7d4
Create Date: 2026-09-17 22:40:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b3d7e2c8f5a1'
down_revision = 'a6e8f3b1c7d4'
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if 'vt_empresas' not in inspector.get_table_names():
        return
    colunas = [c['name'] for c in inspector.get_columns('vt_empresas')]
    if 'unity_id' not in colunas:
        return

    connection = op.get_bind()
    # Empresas sem unidade (as semeadas como "compartilhadas") passam a
    # pertencer à primeira unidade ativa; sem unidades no banco, não têm
    # dono e são removidas com as tarifas.
    primeira = connection.execute(
        sa.text('SELECT id FROM unities WHERE is_active = 1 '
                'ORDER BY name LIMIT 1')).scalar()
    if primeira is not None:
        connection.execute(
            sa.text('UPDATE vt_empresas SET unity_id = :uid '
                    'WHERE unity_id IS NULL'), {'uid': primeira})
    else:
        connection.execute(
            sa.text('DELETE FROM vt_empresas WHERE unity_id IS NULL'))

    with op.batch_alter_table('vt_empresas') as batch_op:
        batch_op.alter_column('unity_id', existing_type=sa.Integer(),
                              nullable=False)


def downgrade():
    inspector = sa.inspect(op.get_bind())
    if 'vt_empresas' not in inspector.get_table_names():
        return
    colunas = [c['name'] for c in inspector.get_columns('vt_empresas')]
    if 'unity_id' not in colunas:
        return
    with op.batch_alter_table('vt_empresas') as batch_op:
        batch_op.alter_column('unity_id', existing_type=sa.Integer(),
                              nullable=True)
