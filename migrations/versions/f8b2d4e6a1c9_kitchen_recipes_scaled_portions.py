"""kitchen_recipes: scaled_portions para persistir o recalculo de quantidades

Revision ID: f8b2d4e6a1c9
Revises: a7c3e9f1b4d2
Create Date: 2026-09-09 14:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f8b2d4e6a1c9'
down_revision = 'a7c3e9f1b4d2'
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if 'kitchen_recipes' not in inspector.get_table_names():
        return
    columns = [c['name'] for c in inspector.get_columns('kitchen_recipes')]
    if 'scaled_portions' in columns:
        return
    with op.batch_alter_table('kitchen_recipes', schema=None) as batch_op:
        batch_op.add_column(sa.Column('scaled_portions', sa.Float(), nullable=True))


def downgrade():
    inspector = sa.inspect(op.get_bind())
    if 'kitchen_recipes' not in inspector.get_table_names():
        return
    columns = [c['name'] for c in inspector.get_columns('kitchen_recipes')]
    if 'scaled_portions' not in columns:
        return
    with op.batch_alter_table('kitchen_recipes', schema=None) as batch_op:
        batch_op.drop_column('scaled_portions')
