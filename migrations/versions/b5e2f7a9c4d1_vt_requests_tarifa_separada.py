"""vt_requests: colunas de tarifa separadas da empresa

Revision ID: b5e2f7a9c4d1
Revises: f3a9c8e2b7d6
Create Date: 2026-09-17 14:45:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b5e2f7a9c4d1'
down_revision = 'f3a9c8e2b7d6'
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if 'vt_requests' not in inspector.get_table_names():
        return
    columns = [c['name'] for c in inspector.get_columns('vt_requests')]
    with op.batch_alter_table('vt_requests', schema=None) as batch_op:
        if 'company_a_value' not in columns:
            batch_op.add_column(sa.Column('company_a_value', sa.Numeric(10, 2), nullable=True))
        if 'company_b_value' not in columns:
            batch_op.add_column(sa.Column('company_b_value', sa.Numeric(10, 2), nullable=True))


def downgrade():
    inspector = sa.inspect(op.get_bind())
    if 'vt_requests' not in inspector.get_table_names():
        return
    columns = [c['name'] for c in inspector.get_columns('vt_requests')]
    with op.batch_alter_table('vt_requests', schema=None) as batch_op:
        if 'company_b_value' in columns:
            batch_op.drop_column('company_b_value')
        if 'company_a_value' in columns:
            batch_op.drop_column('company_a_value')
