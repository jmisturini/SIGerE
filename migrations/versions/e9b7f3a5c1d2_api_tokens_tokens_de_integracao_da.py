"""api_tokens: tokens de integracao da API de reservas

Revision ID: e9b7f3a5c1d2
Revises: d4a8c2e6f0b7
Create Date: 2026-09-11 15:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e9b7f3a5c1d2'
down_revision = 'd4a8c2e6f0b7'
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if 'api_tokens' in inspector.get_table_names():
        return
    op.create_table(
        'api_tokens',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('prefix', sa.String(length=16), nullable=False),
        sa.Column('created_by_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('last_used_at', sa.DateTime(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='1'),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ondelete='CASCADE'),
    )
    with op.batch_alter_table('api_tokens') as batch_op:
        batch_op.create_index('ix_api_tokens_token_hash', ['token_hash'], unique=True)


def downgrade():
    inspector = sa.inspect(op.get_bind())
    if 'api_tokens' not in inspector.get_table_names():
        return
    op.drop_table('api_tokens')
