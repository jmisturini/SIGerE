"""adicional noturno professores

Revision ID: cd04617d1484
Revises: b2e7c4a9d1f6
Create Date: 2026-10-13 13:54:41.245939

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'cd04617d1484'
down_revision = 'b2e7c4a9d1f6'
branch_labels = None
depends_on = None


def upgrade():
    # Lançamentos do Adicional Noturno de Professores (RH) — espelha as
    # colunas da planilha "Adicional Noturno Professores" e alimenta a
    # exportação planilha_base_an.xlsx.
    op.create_table('teacher_night_shift_pay',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('unity_id', sa.Integer(), nullable=True),
    sa.Column('month_base', sa.String(length=7), nullable=False),
    sa.Column('registration', sa.String(length=20), nullable=False),
    sa.Column('full_name', sa.String(length=255), nullable=False),
    sa.Column('entitled', sa.Boolean(), nullable=False),
    sa.Column('class_hours', sa.Numeric(precision=7, scale=2), nullable=True),
    sa.Column('night_minutes', sa.Integer(), nullable=True),
    sa.Column('uo_code', sa.Integer(), nullable=True),
    sa.Column('created_by_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['unity_id'], ['unities.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('teacher_night_shift_pay', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_teacher_night_shift_pay_unity_id'),
                              ['unity_id'], unique=False)


def downgrade():
    with op.batch_alter_table('teacher_night_shift_pay', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_teacher_night_shift_pay_unity_id'))

    op.drop_table('teacher_night_shift_pay')
