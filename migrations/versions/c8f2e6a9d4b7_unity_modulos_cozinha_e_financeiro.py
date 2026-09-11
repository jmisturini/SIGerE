"""unity: modulos opcionais por unidade (cozinha e financeiro)

Revision ID: c8f2e6a9d4b7
Revises: e9b7f3a5c1d2
Create Date: 2026-09-11 18:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c8f2e6a9d4b7'
down_revision = 'e9b7f3a5c1d2'
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if 'unities' not in inspector.get_table_names():
        return
    columns = {c['name'] for c in inspector.get_columns('unities')}
    # server_default '1' = instalações antigas mantêm os módulos ligados.
    with op.batch_alter_table('unities') as batch_op:
        if 'kitchen_enabled' not in columns:
            batch_op.add_column(sa.Column('kitchen_enabled', sa.Boolean(),
                                          nullable=False, server_default='1'))
        if 'finance_enabled' not in columns:
            batch_op.add_column(sa.Column('finance_enabled', sa.Boolean(),
                                          nullable=False, server_default='1'))


def downgrade():
    inspector = sa.inspect(op.get_bind())
    if 'unities' not in inspector.get_table_names():
        return
    columns = {c['name'] for c in inspector.get_columns('unities')}
    with op.batch_alter_table('unities') as batch_op:
        if 'finance_enabled' in columns:
            batch_op.drop_column('finance_enabled')
        if 'kitchen_enabled' in columns:
            batch_op.drop_column('kitchen_enabled')
