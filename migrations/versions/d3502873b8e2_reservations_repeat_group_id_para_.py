"""reservations: repeat_group_id para gerenciar series de repeticao

Revision ID: d3502873b8e2
Revises: 9673dec865ca
Create Date: 2026-09-06 14:45:43.717684

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd3502873b8e2'
down_revision = '9673dec865ca'
branch_labels = None
depends_on = None


def upgrade():
    # Nome explícito: batch_alter_table (SQLite) reconstrói a tabela e exige
    # constraints nomeadas. Gera só quando a coluna ainda não existe — bancos
    # já com o esquema do modelo atual não precisam do rebuild.
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if 'repeat_group_id' in [c['name'] for c in inspector.get_columns('reservations')]:
        return
    with op.batch_alter_table('reservations', schema=None) as batch_op:
        batch_op.add_column(sa.Column('repeat_group_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_reservations_repeat_group_id'), ['repeat_group_id'], unique=False)
        batch_op.create_foreign_key('fk_reservations_repeat_group', 'reservations',
                                    ['repeat_group_id'], ['id'])


def downgrade():
    with op.batch_alter_table('reservations', schema=None) as batch_op:
        batch_op.drop_constraint('fk_reservations_repeat_group', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_reservations_repeat_group_id'))
        batch_op.drop_column('repeat_group_id')

    # ### end Alembic commands ###
