"""vt_records: original_name para auditoria da padronizacao de nomes

Revision ID: d9f31c8a6b24
Revises: c7e29a4b1f53
Create Date: 2026-09-08 14:10:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd9f31c8a6b24'
down_revision = 'c7e29a4b1f53'
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if 'vt_records' not in inspector.get_table_names():
        return
    columns = [c['name'] for c in inspector.get_columns('vt_records')]
    if 'original_name' in columns:
        return
    with op.batch_alter_table('vt_records', schema=None) as batch_op:
        batch_op.add_column(sa.Column('original_name', sa.String(length=255), nullable=True))


def downgrade():
    inspector = sa.inspect(op.get_bind())
    if 'vt_records' not in inspector.get_table_names():
        return
    columns = [c['name'] for c in inspector.get_columns('vt_records')]
    if 'original_name' not in columns:
        return
    with op.batch_alter_table('vt_records', schema=None) as batch_op:
        batch_op.drop_column('original_name')
