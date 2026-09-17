"""vt: empresas e pedidos escopados por unidade

Revision ID: e4b7c9d2a5f8
Revises: c8d4a1e6f2b9
Create Date: 2026-09-17 18:10:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e4b7c9d2a5f8'
down_revision = 'c8d4a1e6f2b9'
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    tables = inspector.get_table_names()

    connection = op.get_bind()

    if 'vt_requests' in tables:
        colunas_pedido = [c['name'] for c in inspector.get_columns('vt_requests')]
        if 'unity_id' not in colunas_pedido:
            # SQLite não aceita ALTER de constraint: batch mode recria a
            # tabela (preservando os dados) com a FK nova.
            with op.batch_alter_table('vt_requests') as batch_op:
                batch_op.add_column(sa.Column('unity_id', sa.Integer(), nullable=True))
                batch_op.create_foreign_key('fk_vt_requests_unity_id', 'unities',
                                            ['unity_id'], ['id'])
            op.create_index(op.f('ix_vt_requests_unity_id'), 'vt_requests',
                            ['unity_id'], unique=False)
        # Pedidos anteriores ao multi-unidade pertencem à primeira unidade
        # ativa (instalações novas não têm linhas para migrar).
        if connection.execute(sa.text('SELECT COUNT(*) FROM vt_requests')).scalar() > 0:
            primeira = connection.execute(
                sa.text('SELECT id FROM unities WHERE is_active = 1 '
                        'ORDER BY name LIMIT 1')).scalar()
            if primeira is not None:
                connection.execute(
                    sa.text('UPDATE vt_requests SET unity_id = :uid '
                            'WHERE unity_id IS NULL'), {'uid': primeira})

    if 'vt_empresas' in tables:
        colunas_empresa = [c['name'] for c in inspector.get_columns('vt_empresas')]
        if 'unity_id' not in colunas_empresa:
            with op.batch_alter_table('vt_empresas') as batch_op:
                batch_op.add_column(sa.Column('unity_id', sa.Integer(), nullable=True))
                batch_op.create_foreign_key('fk_vt_empresas_unity_id', 'unities',
                                            ['unity_id'], ['id'])
            op.create_index(op.f('ix_vt_empresas_unity_id'), 'vt_empresas',
                            ['unity_id'], unique=False)
        # NULL = compartilhada por todas as unidades: as empresas semeadas
        # ficam visíveis para todas sem necessidade de reatribuição.


def downgrade():
    inspector = sa.inspect(op.get_bind())
    tables = inspector.get_table_names()
    if 'vt_empresas' in tables:
        colunas_empresa = [c['name'] for c in inspector.get_columns('vt_empresas')]
        if 'unity_id' in colunas_empresa:
            with op.batch_alter_table('vt_empresas') as batch_op:
                batch_op.drop_column('unity_id')
    if 'vt_requests' in tables:
        colunas_pedido = [c['name'] for c in inspector.get_columns('vt_requests')]
        if 'unity_id' in colunas_pedido:
            with op.batch_alter_table('vt_requests') as batch_op:
                batch_op.drop_column('unity_id')
