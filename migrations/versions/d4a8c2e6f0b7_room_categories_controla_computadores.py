"""room_categories: controla_computadores substitui a regra do codigo fixo

Revision ID: d4a8c2e6f0b7
Revises: f8b2d4e6a1c9
Create Date: 2026-09-10 09:40:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd4a8c2e6f0b7'
down_revision = 'f8b2d4e6a1c9'
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if 'room_categories' not in inspector.get_table_names():
        return
    columns = [c['name'] for c in inspector.get_columns('room_categories')]
    if 'controla_computadores' in columns:
        return
    with op.batch_alter_table('room_categories', schema=None) as batch_op:
        batch_op.add_column(sa.Column('controla_computadores', sa.Boolean(),
                                      nullable=False, server_default='0'))
    # Backfill: a categoria que sempre controlou computadores é a de código
    # fixo 'computer_lab' — o comportamento existente é preservado.
    op.execute("UPDATE room_categories SET controla_computadores = 1 "
               "WHERE code = 'computer_lab'")


def downgrade():
    inspector = sa.inspect(op.get_bind())
    if 'room_categories' not in inspector.get_table_names():
        return
    columns = [c['name'] for c in inspector.get_columns('room_categories')]
    if 'controla_computadores' not in columns:
        return
    with op.batch_alter_table('room_categories', schema=None) as batch_op:
        batch_op.drop_column('controla_computadores')
