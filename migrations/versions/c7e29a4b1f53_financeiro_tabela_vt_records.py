"""financeiro: tabela vt_records para o modulo Vale Transporte

Revision ID: c7e29a4b1f53
Revises: b8c41d6f2e97
Create Date: 2026-09-08 11:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c7e29a4b1f53'
down_revision = 'b8c41d6f2e97'
branch_labels = None
depends_on = None


def upgrade():
    # Guarda idempotente (padrão das migrations anteriores): bancos criados
    # com o schema atual já têm a tabela.
    inspector = sa.inspect(op.get_bind())
    if 'vt_records' in inspector.get_table_names():
        return
    op.create_table('vt_records',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('unity_id', sa.Integer(), nullable=True),
    sa.Column('registration', sa.String(length=20), nullable=False),
    sa.Column('full_name', sa.String(length=255), nullable=False),
    sa.Column('optant', sa.String(length=3), nullable=False),
    sa.Column('link', sa.String(length=50), nullable=True),
    sa.Column('unity', sa.String(length=100), nullable=True),
    sa.Column('company_count', sa.Integer(), nullable=True),
    sa.Column('company_a_name', sa.String(length=100), nullable=True),
    sa.Column('company_a_value', sa.Numeric(precision=10, scale=2), nullable=True),
    sa.Column('company_a_passes', sa.Integer(), nullable=True),
    sa.Column('company_a_total', sa.Numeric(precision=10, scale=2), nullable=True),
    sa.Column('company_b_name', sa.String(length=100), nullable=True),
    sa.Column('company_b_value', sa.Numeric(precision=10, scale=2), nullable=True),
    sa.Column('company_b_passes', sa.Integer(), nullable=True),
    sa.Column('company_b_total', sa.Numeric(precision=10, scale=2), nullable=True),
    sa.Column('total_passes', sa.Integer(), nullable=True),
    sa.Column('total_value', sa.Numeric(precision=10, scale=2), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['unity_id'], ['unities.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('vt_records', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_vt_records_unity_id'), ['unity_id'], unique=False)


def downgrade():
    inspector = sa.inspect(op.get_bind())
    if 'vt_records' not in inspector.get_table_names():
        return
    with op.batch_alter_table('vt_records', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_vt_records_unity_id'))
    op.drop_table('vt_records')
