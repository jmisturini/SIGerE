"""financeiro: tabela vt_requests (pedidos públicos de vale-transporte)

Revision ID: f3a9c8e2b7d6
Revises: e2c9a7d5f8b1
Create Date: 2026-09-17 10:20:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f3a9c8e2b7d6'
down_revision = 'e2c9a7d5f8b1'
branch_labels = None
depends_on = None


def upgrade():
    # Guarda idempotente (padrão das migrations anteriores): bancos criados
    # com o schema atual já têm a tabela.
    inspector = sa.inspect(op.get_bind())
    if 'vt_requests' in inspector.get_table_names():
        return
    op.create_table('vt_requests',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('full_name', sa.String(length=255), nullable=False),
    sa.Column('registration', sa.String(length=20), nullable=False),
    sa.Column('optant', sa.String(length=3), nullable=False),
    sa.Column('unity', sa.String(length=100), nullable=True),
    sa.Column('link', sa.String(length=50), nullable=True),
    sa.Column('company_count', sa.Integer(), nullable=True),
    sa.Column('company_a_name', sa.String(length=100), nullable=True),
    sa.Column('company_a_passes', sa.Integer(), nullable=True),
    sa.Column('company_a_route', sa.String(length=20), nullable=True),
    sa.Column('company_b_name', sa.String(length=100), nullable=True),
    sa.Column('company_b_passes', sa.Integer(), nullable=True),
    sa.Column('company_b_route', sa.String(length=20), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('vt_requests', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_vt_requests_email'), ['email'], unique=False)


def downgrade():
    inspector = sa.inspect(op.get_bind())
    if 'vt_requests' not in inspector.get_table_names():
        return
    with op.batch_alter_table('vt_requests', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_vt_requests_email'))
    op.drop_table('vt_requests')
