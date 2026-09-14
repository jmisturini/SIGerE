"""user_roles: papeis adicionais (add-on) por usuario

Revision ID: b3d8f7a2c6e1
Revises: c8f2e6a9d4b7
Create Date: 2026-09-14 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b3d8f7a2c6e1'
down_revision = 'c8f2e6a9d4b7'
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if 'user_roles' in inspector.get_table_names():
        return
    # Papéis adicionais complementam o papel principal (users.role_id); a
    # permissão efetiva do usuário passa a ser a união dos dois conjuntos.
    op.create_table(
        'user_roles',
        sa.Column('user_id', sa.Integer(),
                  sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('role_id', sa.Integer(),
                  sa.ForeignKey('roles.id', ondelete='CASCADE'), primary_key=True),
    )


def downgrade():
    inspector = sa.inspect(op.get_bind())
    if 'user_roles' in inspector.get_table_names():
        op.drop_table('user_roles')
